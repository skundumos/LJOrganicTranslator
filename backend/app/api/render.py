"""Render endpoints.

POST /api/render-preview/{job_id}
    - Composites the user's current overlay text onto the cached pre-blurred frame.
    - Returns a PNG (small, fast). Used for live preview on text edits.

POST /api/render-final/{job_id}
    - Triggers the full FFmpeg render in the background.
"""
from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
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
    if not job.background_frame_path:
        raise HTTPException(400, "No background frame available")

    job_dir = storage.job_dir(job_id)
    out_png = job_dir / "preview_composite.png"

    # Resolve the editable region. With multiple regions, the caller passes region_index;
    # for every other region we composite the already-saved translated text so the user
    # sees the full frame state as they edit one slot.
    regions = list(job.regions) if job.regions else []
    overlays: list[tuple[Path, tuple[int, int, int, int]]] = []

    if regions:
        idx = body.region_index if body.region_index is not None else 0
        if idx < 0 or idx >= len(regions):
            raise HTTPException(400, f"region_index {idx} out of range")
        for i, r in enumerate(regions):
            bb = r.get("bbox") or {}
            bw, bh = int(bb.get("w") or 0), int(bb.get("h") or 0)
            if bw <= 0 or bh <= 0:
                continue
            bbox = (int(bb.get("x") or 0), int(bb.get("y") or 0), bw, bh)
            txt = body.text if i == idx else (r.get("translated") or "")
            if not txt:
                continue
            png = job_dir / f"preview_text_{i}.png"
            render_text_png(
                txt, job.target_language,
                bbox[2], bbox[3],
                int(r.get("font_size_hint") or 60),
                png,
            )
            overlays.append((png, bbox))
    elif job.bbox_width and job.bbox_height:
        # Back-compat: legacy single-region path
        bbox = (job.bbox_x or 0, job.bbox_y or 0, job.bbox_width, job.bbox_height)
        png = job_dir / "preview_text.png"
        render_text_png(
            body.text, job.target_language,
            bbox[2], bbox[3], job.font_size_hint or 60,
            png,
        )
        overlays.append((png, bbox))
    else:
        raise HTTPException(400, "No bbox available")

    composite_still(Path(job.background_frame_path), overlays, out_png)
    return FileResponse(out_png, media_type="image/png", headers={"Cache-Control": "no-store"})


@router.post("/render-final/{job_id}")
def render_final_route(job_id: int, session: Session = Depends(get_session)) -> dict:
    job = session.get(VideoJob, job_id)
    if not job:
        raise HTTPException(404, "Job not found")
    runner.submit(lambda: render_final_video(job_id))
    return {"ok": True, "job_id": job_id}
