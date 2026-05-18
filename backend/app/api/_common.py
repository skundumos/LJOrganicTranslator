"""Shared helpers across API routers."""
from __future__ import annotations

from pathlib import Path

from app.models import VideoJob
from app.schemas import BoundingBoxOut, JobOut, RegionOut
from app.services.storage import storage


def _regions_out(job: VideoJob) -> list[RegionOut]:
    """Build the per-region list for the API response.

    Prefer the `regions` JSON column. Fall back to constructing a single region from the
    legacy bbox_* + *_overlay_text fields so pre-multi-region jobs still render in the UI.
    """
    out: list[RegionOut] = []
    if job.regions:
        for r in job.regions:
            bb = r.get("bbox") or {}
            if not (bb.get("w") and bb.get("h")):
                continue
            conf = r.get("confidence")
            out.append(RegionOut(
                detected=r.get("detected") or "",
                translated=r.get("translated"),
                bbox=BoundingBoxOut(
                    x=int(bb.get("x") or 0), y=int(bb.get("y") or 0),
                    width=int(bb["w"]), height=int(bb["h"]),
                    font_size_hint=int(r.get("font_size_hint") or 60),
                ),
                confidence=float(conf) if conf is not None else None,
            ))
        return out
    if job.bbox_width and job.bbox_height:
        out.append(RegionOut(
            detected=job.detected_overlay_text or "",
            translated=job.translated_overlay_text,
            bbox=BoundingBoxOut(
                x=job.bbox_x or 0, y=job.bbox_y or 0,
                width=job.bbox_width, height=job.bbox_height,
                font_size_hint=job.font_size_hint or 60,
            ),
        ))
    return out


def to_job_out(job: VideoJob) -> JobOut:
    bbox = None
    if job.bbox_width and job.bbox_height:
        bbox = BoundingBoxOut(
            x=job.bbox_x or 0, y=job.bbox_y or 0,
            width=job.bbox_width, height=job.bbox_height,
            font_size_hint=job.font_size_hint or 60,
        )
    return JobOut(
        id=job.id or 0,
        status=job.status,
        target_language=job.target_language,
        original_duration_s=job.original_duration_s,
        original_transcript=job.original_transcript,
        translated_script=job.translated_script,
        translated_script_natural=job.translated_script_natural,
        translated_script_compact=job.translated_script_compact,
        detected_overlay_text=job.detected_overlay_text,
        translated_overlay_text=job.translated_overlay_text,
        bbox=bbox,
        regions=_regions_out(job),
        has_preview_frame=bool(job.preview_frame_path and Path(job.preview_frame_path).exists()),
        has_voiceover=bool(job.generated_voiceover_path and Path(job.generated_voiceover_path).exists()),
        has_final_video=bool(job.final_video_path and Path(job.final_video_path).exists()),
        error_message=job.error_message,
        created_at=job.created_at,
        updated_at=job.updated_at,
    )


def relpath(absolute: str | Path) -> str:
    p = Path(absolute).resolve()
    try:
        return str(p.relative_to(storage.absolute("").resolve())).replace("\\", "/")
    except ValueError:
        return str(p).replace("\\", "/")


def file_url(absolute: str | None) -> str | None:
    if not absolute:
        return None
    return storage.url(relpath(absolute))
