"""POST /api/generate-voiceover/{job_id} — regenerate ElevenLabs voiceover from current script."""
from __future__ import annotations

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from sqlmodel import Session

from app.db import get_session
from app.models import VideoJob
from app.schemas import RegenerateVoiceoverIn
from app.services.pipeline import regenerate_voiceover
from app.services.runner import runner

router = APIRouter()


@router.post("/generate-voiceover/{job_id}")
def regenerate_voice(
    job_id: int,
    body: RegenerateVoiceoverIn,
    background_tasks: BackgroundTasks,
    session: Session = Depends(get_session),
) -> dict:
    job = session.get(VideoJob, job_id)
    if not job:
        raise HTTPException(404, "Job not found")
    if not (body.text or job.translated_script):
        raise HTTPException(400, "No script available")
    background_tasks.add_task(
        lambda: runner.submit(lambda: regenerate_voiceover(job_id, body.text))
    )
    return {"ok": True}
