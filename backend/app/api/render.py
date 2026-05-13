"""Render endpoints.

POST /api/render-preview/{job_id}
    - Composites the user's current overlay text onto the cached pre-blurred frame.
    - Returns a PNG (small, fast). Used for live preview on text edits.

POST /api/render-final/{job_id}
    - Triggers the full FFmpeg render in the background.
"""
from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from fastapi.responses import FileResponse
from sqlmodel import Session

from app.db import get_session
from app.models import VideoJob
from app.schemas import RenderPreviewIn
from app.services.ffmpeg_ops import composite_still
from app.services.pipeline import render_final_video
from app.services.runner import runner
from app.services.storage import storage
from app.services.text_renderer import render_text_png

router = APIRouter()


@router.post("/render-preview/{job_id}")
def render_preview(
    job_id: int,
    body: RenderPreviewIn,
    session: Session = Depends(get_session),
) -> FileResponse:
    job = session.get(VideoJob, job_id)
    if not job:
        raise HTTPException(404, "Job not found")
    if not (job.background_frame_path and job.bbox_width and job.bbox_height):
        raise HTTPException(400, "No background frame / bbox available")

    bbox = (job.bbox_x or 0, job.bbox_y or 0, job.bbox_width, job.bbox_height)
    job_dir = storage.job_dir(job_id)
    text_png = job_dir / "preview_text.png"
    out_png = job_dir / "preview_composite.png"
    render_text_png(
        body.text, job.target_language,
        bbox[2], bbox[3], job.font_size_hint or 60,
        text_png,
    )
    composite_still(Path(job.background_frame_path), text_png, bbox, out_png)
    return FileResponse(out_png, media_type="image/png", headers={"Cache-Control": "no-store"})


@router.post("/render-final/{job_id}")
def render_final_route(
    job_id: int,
    background_tasks: BackgroundTasks,
    session: Session = Depends(get_session),
) -> dict:
    job = session.get(VideoJob, job_id)
    if not job:
        raise HTTPException(404, "Job not found")
    background_tasks.add_task(lambda: runner.submit(lambda: render_final_video(job_id)))
    return {"ok": True, "job_id": job_id}
