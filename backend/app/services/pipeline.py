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

from app.db import session_scope
from app.models import JobStatus, VideoJob
from app.services import ocr_fallback, ocr_vision, stt_whisper, translator, tts_elevenlabs
from app.services.ffmpeg_ops import (
    FFmpegError,
    build_blurred_background_frame,
    extract_audio,
    extract_frame,
    probe,
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
            voice_path, voice_dur = await tts_elevenlabs.generate_voiceover(
                scripts["natural"], job.target_language, meta.duration_s,
                voice_path, compact_text=scripts["compact"],
            )
            _update(
                session, job,
                generated_voiceover_path=str(voice_path),
                generated_voiceover_duration_s=voice_dur,
                status=JobStatus.EXTRACTING_FRAME,
            )

            # Extract a representative frame at t=1s (or earlier if clip is short)
            t = min(1.0, max(0.3, meta.duration_s * 0.1))
            frame_path = extract_frame(Path(job.original_video_path), t, job_dir / "frame.png")
            _update(session, job, preview_frame_path=str(frame_path),
                    status=JobStatus.DETECTING_TEXT)

            # OCR (Vision + bbox merge, OCR.space fallback for text only)
            ocr = await ocr_vision.detect_overlay(frame_path)
            if not ocr or not ocr.text:
                fallback_text = await ocr_fallback.ocrspace_text(frame_path)
                if fallback_text:
                    log.info("OCR.space fallback supplied text only; geometry will be estimated.")
                    # Estimate a centered bbox covering the central 80% width, 25% height.
                    bw = int(meta.width * 0.8)
                    bh = int(meta.height * 0.25)
                    bx = (meta.width - bw) // 2
                    by = int(meta.height * 0.45)
                    ocr = ocr_vision.OcrResult(
                        text=fallback_text, bbox=(bx, by, bw, bh),
                        font_size_hint=max(48, bh // 4), confidence=0.4,
                    )

            if ocr:
                x, y, w, h = ocr.bbox
                _update(
                    session, job,
                    detected_overlay_text=ocr.text,
                    bbox_x=x, bbox_y=y, bbox_width=w, bbox_height=h,
                    font_size_hint=ocr.font_size_hint,
                    status=JobStatus.TRANSLATING_OVERLAY,
                )

                # Pre-build the blurred background frame (used by live preview)
                bg = job_dir / "background_blurred.png"
                build_blurred_background_frame(frame_path, (x, y, w, h), bg)
                _update(session, job, background_frame_path=str(bg))

                # Translate overlay
                translated_overlay = await translator.translate_overlay(
                    ocr.text, job.target_language
                )
                _update(session, job, translated_overlay_text=translated_overlay)
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
            voice_path, voice_dur = await tts_elevenlabs.generate_voiceover(
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

async def regenerate_overlay(job_id: int) -> None:
    with session_scope() as session:
        try:
            job = _load(session, job_id)
            if not job.detected_overlay_text:
                raise RuntimeError("No detected overlay text to translate")
            translated = await translator.translate_overlay(
                job.detected_overlay_text, job.target_language
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
            text_png: Path | None = None
            bbox: tuple[int, int, int, int] | None = None

            if job.translated_overlay_text and job.bbox_width and job.bbox_height:
                bbox = (job.bbox_x or 0, job.bbox_y or 0, job.bbox_width, job.bbox_height)
                text_png = job_dir / "overlay.png"
                render_text_png(
                    job.translated_overlay_text,
                    job.target_language,
                    bbox[2], bbox[3],
                    job.font_size_hint or 60,
                    text_png,
                )

            render_final(
                Path(job.original_video_path),
                Path(job.generated_voiceover_path),
                text_png, bbox, out_mp4,
            )

            _update(session, job, final_video_path=str(out_mp4),
                    status=JobStatus.COMPLETED)
        except FFmpegError as e:
            _fail(session, _load(session, job_id), f"FFmpeg error: {e}")
        except Exception as e:
            _fail(session, _load(session, job_id), str(e))
