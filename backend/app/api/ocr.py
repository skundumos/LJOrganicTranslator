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
    ocr = await ocr_vision.detect_overlay(Path(job.preview_frame_path))
    if not ocr:
        raise HTTPException(422, "OCR found no overlay text")
    x, y, w, h = ocr.bbox
    job.detected_overlay_text = ocr.text
    job.bbox_x, job.bbox_y, job.bbox_width, job.bbox_height = x, y, w, h
    job.font_size_hint = ocr.font_size_hint

    bg = storage.job_dir(job_id) / "background_blurred.png"
    build_blurred_background_frame(Path(job.preview_frame_path), (x, y, w, h), bg)
    job.background_frame_path = str(bg)

    session.add(job)
    session.commit()
    return {
        "ok": True,
        "detected_overlay_text": ocr.text,
        "bbox": {"x": x, "y": y, "width": w, "height": h, "font_size_hint": ocr.font_size_hint},
    }
