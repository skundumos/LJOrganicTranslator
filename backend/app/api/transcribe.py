"""POST /api/transcribe/{job_id} — manual re-trigger of Whisper transcription. Useful if the
initial run failed or the user wants to retry. Not normally called: upload auto-chains it.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session

from app.db import get_session
from app.models import VideoJob
from app.services.pipeline import run_prep_pipeline
from app.services.runner import runner

router = APIRouter()


@router.post("/transcribe/{job_id}")
def retranscribe(job_id: int, session: Session = Depends(get_session)) -> dict:
    job = session.get(VideoJob, job_id)
    if not job:
        raise HTTPException(404, "Job not found")
    # Re-run the full prep chain (idempotent). Sync route -> runner spawns a worker thread.
    runner.submit(lambda: run_prep_pipeline(job_id))
    return {"ok": True, "job_id": job_id}
