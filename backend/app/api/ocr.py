"""POST /api/detect-text/{job_id} — re-run OCR on the cached frame. Idempotent."""
from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session

from app.db import get_session
from app.models import VideoJob
from app.services import ocr_vision
from app.services.ffmpeg_ops import build_blurred_background_frame
from app.services.storage import storage

router = APIRouter()


@router.post("/detect-text/{job_id}")
async def detect_text(job_id: int, session: Session = Depends(get_session)) -> dict:
    job = session.get(VideoJob, job_id)
    if not job:
        raise HTTPException(404, "Job not found")
    if not job.preview_frame_path:
        raise HTTPException(400, "No frame extracted yet")

    regions = await ocr_vision.detect_overlay_regions(Path(job.preview_frame_path))
    if not regions:
        raise HTTPException(422, "OCR found no overlay text")

    # Don't overwrite existing translations — preserve them on a per-region basis when the
    # detected English matches what we already had. If detected text changed, translation
    # is dropped for that region (caller can hit /translate-overlay to retranslate).
    prior = list(job.regions) if job.regions else []
    prior_by_detected = {(r.get("detected") or "").strip(): r.get("translated")
                          for r in prior}

    regions_payload = []
    for r in regions:
        translated = prior_by_detected.get(r.text.strip())
        regions_payload.append({
            "detected": r.text,
            "translated": translated,
            "bbox": {"x": r.bbox[0], "y": r.bbox[1], "w": r.bbox[2], "h": r.bbox[3]},
            "font_size_hint": r.font_size_hint,
        })

    job.regions = regions_payload
    first = regions[0]
    x, y, w, h = first.bbox
    job.detected_overlay_text = "\n---\n".join(r.text for r in regions)
    job.translated_overlay_text = "\n---\n".join(
        (r["translated"] or "") for r in regions_payload
    )
    job.bbox_x, job.bbox_y, job.bbox_width, job.bbox_height = x, y, w, h
    job.font_size_hint = first.font_size_hint

    bg = storage.job_dir(job_id) / "background_blurred.png"
    build_blurred_background_frame(
        Path(job.preview_frame_path), [r.bbox for r in regions], bg
    )
    job.background_frame_path = str(bg)

    session.add(job)
    session.commit()
    return {
        "ok": True,
        "regions": regions_payload,
    }
