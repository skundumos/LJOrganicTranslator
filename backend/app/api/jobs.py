"""GET /api/job/{id} — poll job status. Returns artifact URLs (served by StaticFiles)."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session

from app.api._common import file_url, to_job_out
from app.db import get_session
from app.models import VideoJob
from app.schemas import JobOut

router = APIRouter()


@router.get("/job/{job_id}", response_model=dict)
def get_job(job_id: int, session: Session = Depends(get_session)) -> dict:
    job = session.get(VideoJob, job_id)
    if not job:
        raise HTTPException(404, "Job not found")
    out: JobOut = to_job_out(job)
    return {
        **out.model_dump(),
        "urls": {
            "input_video": file_url(job.original_video_path),
            "voiceover": file_url(job.generated_voiceover_path),
            "preview_frame": file_url(job.preview_frame_path),
            "background_frame": file_url(job.background_frame_path),
            "final_video": file_url(job.final_video_path),
        },
    }
