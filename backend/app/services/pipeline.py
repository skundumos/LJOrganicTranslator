"""Per-job orchestration. The pipeline is split into discrete async steps; the upload route
chains the prep steps (audio extract → transcribe → translate script → frame extract → OCR →
translate overlay → voiceover gen) so by the time the user opens the review screen everything
is ready.

Each step updates the VideoJob row + status.
"""
from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path

from sqlmodel import Session

from app.config import settings
from app.db import session_scope
from app.models import JobStatus, VideoJob
from app.services import ocr_fallback, ocr_vision, stt_whisper, translator, tts_sarvam as tts
from app.services.ffmpeg_ops import (
    FFmpegError,
    build_blurred_background_frame,
    extract_audio,
    extract_frame,
    probe,
    probe_audio_duration,
    render_final,
)
from app.services.storage import storage
from app.services.text_renderer import render_text_png

log = logging.getLogger("ad_localizer.pipeline")


# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------

def _load(session: Session, job_id: int) -> VideoJob:
    job = session.get(VideoJob, job_id)
    if not job:
        raise RuntimeError(f"Job {job_id} not found")
    return job


def _update(session: Session, job: VideoJob, **fields) -> VideoJob:
    for k, v in fields.items():
        setattr(job, k, v)
    job.updated_at = datetime.utcnow()
    session.add(job)
    session.commit()
    session.refresh(job)
    return job


def _fail(session: Session, job: VideoJob, msg: str) -> None:
    log.exception("Job %s failed: %s", job.id, msg)
    _update(session, job, status=JobStatus.FAILED, error_message=msg[:1000])


# ---------------------------------------------------------------------------
# Step 1: prep (audio + frame + initial OCR/transcribe + initial translations)
# ---------------------------------------------------------------------------

async def run_prep_pipeline(job_id: int) -> None:
    """Run the full prep chain. Status lands in AWAITING_REVIEW (or FAILED)."""
    with session_scope() as session:
        try:
            job = _load(session, job_id)
            job_dir = storage.job_dir(job_id)

            # Probe original video for duration etc.
            meta = probe(Path(job.original_video_path))
            _update(session, job, original_duration_s=meta.duration_s,
                    status=JobStatus.EXTRACTING_AUDIO)

            # Extract audio
            audio_path = extract_audio(Path(job.original_video_path), job_dir / "audio_en.wav")
            _update(session, job, extracted_audio_path=str(audio_path),
                    status=JobStatus.TRANSCRIBING)

            # Whisper transcription
            transcript = await stt_whisper.transcribe(audio_path)
            _update(session, job, original_transcript=transcript,
                    status=JobStatus.TRANSLATING_SCRIPT)

            # Translate script (returns natural + compact)
            scripts = await translator.translate_script(
                transcript, job.target_language, meta.duration_s
            )
            _update(
                session, job,
                translated_script_natural=scripts["natural"],
                translated_script_compact=scripts["compact"],
                translated_script=scripts["natural"],
                status=JobStatus.GENERATING_VOICEOVER,
            )

            # Voiceover generation (duration-matched)
            voice_path = job_dir / "voiceover.mp3"
            voice_path, voice_dur = await tts.generate_voiceover(
                scripts["natural"], job.target_language, meta.duration_s,
                voice_path, compact_text=scripts["compact"],
            )
            _update(
                session, job,
                generated_voiceover_path=str(voice_path),
                generated_voiceover_duration_s=voice_dur,
                status=JobStatus.EXTRACTING_FRAME,
            )

            # Extract THREE frames across the clip, not one. A single frame at t=1s misses
            # overlays that appear later, or any frame that landed on a motion-blur. We OCR
            # each, then keep the highest-confidence region per band (top/bottom) across the
            # whole sample set.
            min_t = 0.3
            max_t = max(min_t + 0.1, meta.duration_s - 0.3)
            sample_offsets = [0.15, 0.50, 0.85]
            sample_ts = sorted({
                round(max(min_t, min(max_t, meta.duration_s * f)), 2)
                for f in sample_offsets
            })
            sample_frames: list[Path] = []
            for i, t in enumerate(sample_ts):
                fp = job_dir / f"frame_{i}.png"
                extract_frame(Path(job.original_video_path), t, fp)
                sample_frames.append(fp)
            # Default preview frame: the middle sample. Updated below to the frame that
            # sourced our chosen regions, so what the user sees in the editor matches what
            # the final render will look like.
            preview_path = sample_frames[len(sample_frames) // 2]
            _update(session, job, preview_frame_path=str(preview_path),
                    status=JobStatus.DETECTING_TEXT)

            # OCR. Priority chain: Google Vision (precise bbox) → OCR.space (text only + estimated bbox).
            # Both return a LIST of regions (top + bottom) when present, so ads with text above
            # AND below the product get both replaced.
            img_h = meta.height
            best_by_band: dict[str, tuple[ocr_vision.OcrResult, Path]] = {}

            for fp in sample_frames:
                regions_i: list = []
                if settings.GOOGLE_VISION_API_KEY:
                    log.info("OCR provider: Google Vision on %s", fp.name)
                    regions_i = await ocr_vision.detect_overlay_regions(fp)
                if not regions_i and settings.OCR_SPACE_API_KEY:
                    log.info("OCR provider: OCR.space on %s", fp.name)
                    space_regions = await ocr_fallback.detect_overlay_regions(
                        fp, meta.width, meta.height
                    )
                    regions_i = [
                        ocr_vision.OcrResult(
                            text=r.text, bbox=r.bbox,
                            font_size_hint=r.font_size_hint, confidence=0.5,
                        )
                        for r in space_regions
                    ]
                for r in regions_i:
                    cy = r.bbox[1] + r.bbox[3] / 2
                    band = "top" if cy < img_h * 0.5 else "bot"
                    existing = best_by_band.get(band)
                    if existing is None or r.confidence > existing[0].confidence:
                        best_by_band[band] = (r, fp)

            regions: list = sorted(
                (entry[0] for entry in best_by_band.values()),
                key=lambda r: r.bbox[1],
            )

            # Re-pick the preview frame: the sample that sourced our highest-confidence
            # region. The blur happens dynamically per video frame in render_final, but the
            # editor preview composites on a still — match the still to the OCR source so
            # the user sees the bbox over its actual text.
            if best_by_band:
                chosen_source = max(
                    best_by_band.values(), key=lambda v: v[0].confidence,
                )[1]
                if chosen_source != preview_path:
                    preview_path = chosen_source
                    _update(session, job, preview_frame_path=str(preview_path))

            if regions:
                bboxes = [r.bbox for r in regions]

                # Pre-build the background frame with ALL detected regions blurred
                bg = job_dir / "background_blurred.png"
                build_blurred_background_frame(preview_path, bboxes, bg)
                _update(session, job, background_frame_path=str(bg))

                # Translate each region's text independently. Pass bbox + font hint so the
                # translator can probe-render and retry with a tighter budget when the
                # auto-fit would otherwise shrink text below the legibility floor.
                translated_per_region: list[str] = []
                for r in regions:
                    t = await translator.translate_overlay(
                        r.text, job.target_language,
                        bbox_w=r.bbox[2], bbox_h=r.bbox[3],
                        font_size_hint=r.font_size_hint,
                    )
                    translated_per_region.append(t)

                # Persist regions list + mirror first region to legacy fields
                regions_payload = [
                    {
                        "detected": r.text,
                        "translated": translated_per_region[i],
                        "bbox": {"x": r.bbox[0], "y": r.bbox[1],
                                 "w": r.bbox[2], "h": r.bbox[3]},
                        "font_size_hint": r.font_size_hint,
                        "confidence": r.confidence,
                    }
                    for i, r in enumerate(regions)
                ]
                first = regions[0]
                x, y, w, h = first.bbox
                _update(
                    session, job,
                    regions=regions_payload,
                    detected_overlay_text="\n---\n".join(r.text for r in regions),
                    translated_overlay_text="\n---\n".join(translated_per_region),
                    bbox_x=x, bbox_y=y, bbox_width=w, bbox_height=h,
                    font_size_hint=first.font_size_hint,
                    status=JobStatus.TRANSLATING_OVERLAY,
                )
            else:
                log.warning("Job %s: no overlay text detected — proceeding without overlay step.", job_id)
                _update(session, job, status=JobStatus.TRANSLATING_OVERLAY)

            _update(session, job, status=JobStatus.AWAITING_REVIEW)

        except Exception as e:
            _fail(session, _load(session, job_id), str(e))


# ---------------------------------------------------------------------------
# Step 2: regenerate voiceover (called when user edits the script and clicks "regenerate")
# ---------------------------------------------------------------------------

async def regenerate_voiceover(job_id: int, script_override: str | None = None) -> None:
    with session_scope() as session:
        try:
            job = _load(session, job_id)
            _update(session, job, status=JobStatus.GENERATING_VOICEOVER)
            text = script_override or job.translated_script or job.translated_script_natural
            if not text:
                raise RuntimeError("No script available to regenerate voiceover")
            compact = job.translated_script_compact
            job_dir = storage.job_dir(job_id)
            voice_path = job_dir / "voiceover.mp3"
            voice_path, voice_dur = await tts.generate_voiceover(
                text, job.target_language, job.original_duration_s or 30.0,
                voice_path, compact_text=compact,
            )
            _update(
                session, job,
                generated_voiceover_path=str(voice_path),
                generated_voiceover_duration_s=voice_dur,
                translated_script=text,
                status=JobStatus.AWAITING_REVIEW,
            )
        except Exception as e:
            _fail(session, _load(session, job_id), str(e))


# ---------------------------------------------------------------------------
# Step 3: regenerate overlay translation (LLM only)
# ---------------------------------------------------------------------------

async def regenerate_overlay(job_id: int, region_index: int | None = None) -> None:
    """Re-translate overlay region(s).

    If region_index is None, re-translate every region in `regions`.
    If an index is given, re-translate just that region.
    Falls back to the legacy single-string field when `regions` is absent.
    """
    with session_scope() as session:
        try:
            job = _load(session, job_id)
            regions = list(job.regions) if job.regions else []

            if regions:
                indices = [region_index] if region_index is not None else range(len(regions))
                for idx in indices:
                    if idx < 0 or idx >= len(regions):
                        continue
                    detected = regions[idx].get("detected") or ""
                    if not detected:
                        continue
                    bb = regions[idx].get("bbox") or {}
                    bw = int(bb.get("w") or 0)
                    bh = int(bb.get("h") or 0)
                    fsh = int(regions[idx].get("font_size_hint") or 0)
                    regions[idx] = {
                        **regions[idx],
                        "translated": await translator.translate_overlay(
                            detected, job.target_language,
                            bbox_w=bw or None, bbox_h=bh or None,
                            font_size_hint=fsh or None,
                        ),
                    }
                _update(
                    session, job,
                    regions=regions,
                    translated_overlay_text="\n---\n".join(
                        r.get("translated") or "" for r in regions
                    ),
                    status=JobStatus.AWAITING_REVIEW,
                )
            else:
                if not job.detected_overlay_text:
                    raise RuntimeError("No detected overlay text to translate")
                translated = await translator.translate_overlay(
                    job.detected_overlay_text, job.target_language,
                    bbox_w=job.bbox_width, bbox_h=job.bbox_height,
                    font_size_hint=job.font_size_hint,
                )
                _update(session, job, translated_overlay_text=translated,
                        status=JobStatus.AWAITING_REVIEW)
        except Exception as e:
            _fail(session, _load(session, job_id), str(e))


# ---------------------------------------------------------------------------
# Step 4: final render
# ---------------------------------------------------------------------------

async def render_final_video(job_id: int) -> None:
    with session_scope() as session:
        try:
            job = _load(session, job_id)
            _update(session, job, status=JobStatus.RENDERING_FINAL)

            if not job.generated_voiceover_path:
                raise RuntimeError("No voiceover available — cannot render")

            job_dir = storage.job_dir(job_id)
            out_mp4 = job_dir / "final.mp4"
            overlays: list[tuple[Path, tuple[int, int, int, int]]] = []

            regions = list(job.regions) if job.regions else []
            if regions:
                for i, r in enumerate(regions):
                    translated = (r.get("translated") or "").strip()
                    bb = r.get("bbox") or {}
                    bw, bh = int(bb.get("w") or 0), int(bb.get("h") or 0)
                    if not translated or bw <= 0 or bh <= 0:
                        continue
                    bbox = (int(bb.get("x") or 0), int(bb.get("y") or 0), bw, bh)
                    png = job_dir / f"overlay_{i}.png"
                    render_text_png(
                        translated, job.target_language,
                        bbox[2], bbox[3],
                        int(r.get("font_size_hint") or 60),
                        png,
                    )
                    overlays.append((png, bbox))
            elif job.translated_overlay_text and job.bbox_width and job.bbox_height:
                # Back-compat: pre-multi-region job. Single overlay from legacy fields.
                bbox = (job.bbox_x or 0, job.bbox_y or 0, job.bbox_width, job.bbox_height)
                png = job_dir / "overlay.png"
                render_text_png(
                    job.translated_overlay_text, job.target_language,
                    bbox[2], bbox[3],
                    job.font_size_hint or 60,
                    png,
                )
                overlays.append((png, bbox))

            # Sync sanity check: video and (padded) voiceover should be within 200ms. If they
                # aren't, the new mix path (sidechain duck + amix=longest, no -shortest) will
                # still produce a full-length output, but the gap likely points at an earlier
                # bug in time-stretch or padding.
            video_dur = probe(Path(job.original_video_path)).duration_s
            voice_dur = probe_audio_duration(Path(job.generated_voiceover_path))
            gap = voice_dur - video_dur
            if abs(gap) > 0.2:
                log.warning(
                    "Pre-render duration gap: voiceover=%.2fs video=%.2fs (gap=%+.2fs). "
                    "Continuing — amix=longest will hold the longer stream.",
                    voice_dur, video_dur, gap,
                )

            render_final(
                Path(job.original_video_path),
                Path(job.generated_voiceover_path),
                overlays, out_mp4,
            )

            _update(session, job, final_video_path=str(out_mp4),
                    status=JobStatus.COMPLETED)
        except FFmpegError as e:
            _fail(session, _load(session, job_id), f"FFmpeg error: {e}")
        except Exception as e:
            _fail(session, _load(session, job_id), str(e))
