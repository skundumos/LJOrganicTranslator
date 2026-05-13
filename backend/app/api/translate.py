"""POST /api/translate-script, /api/translate-overlay — re-translate (regenerate)
or update user-edited text.
"""
from __future__ import annotations

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from sqlmodel import Session

from app.db import get_session
from app.models import JobStatus, VideoJob
from app.schemas import UpdateOverlayIn, UpdateScriptIn
from app.services.pipeline import regenerate_overlay
from app.services.runner import runner
from app.services.translator import translate_script

router = APIRouter()


@router.post("/translate-script/{job_id}")
async def regenerate_script(
    job_id: int,
    session: Session = Depends(get_session),
) -> dict:
    job = session.get(VideoJob, job_id)
    if not job:
        raise HTTPException(404, "Job not found")
    if not job.original_transcript:
        raise HTTPException(400, "No transcript available yet")
    scripts = await translate_script(
        job.original_transcript, job.target_language, job.original_duration_s or 30.0
    )
    job.translated_script_natural = scripts["natural"]
    job.translated_script_compact = scripts["compact"]
    job.translated_script = scripts["natural"]
    session.add(job)
    session.commit()
    return {"ok": True, "translated_script": job.translated_script,
            "natural": scripts["natural"], "compact": scripts["compact"]}


@router.put("/translate-script/{job_id}")
def update_script(
    job_id: int,
    body: UpdateScriptIn,
    session: Session = Depends(get_session),
) -> dict:
    job = session.get(VideoJob, job_id)
    if not job:
        raise HTTPException(404, "Job not found")
    job.translated_script = body.text
    session.add(job)
    session.commit()
    return {"ok": True, "translated_script": job.translated_script}


@router.post("/translate-overlay/{job_id}")
def regenerate_overlay_route(
    job_id: int,
    background_tasks: BackgroundTasks,
    session: Session = Depends(get_session),
) -> dict:
    job = session.get(VideoJob, job_id)
    if not job:
        raise HTTPException(404, "Job not found")
    if not job.detected_overlay_text:
        raise HTTPException(400, "No detected overlay text")
    background_tasks.add_task(lambda: runner.submit(lambda: regenerate_overlay(job_id)))
    return {"ok": True}


@router.put("/translate-overlay/{job_id}")
def update_overlay(
    job_id: int,
    body: UpdateOverlayIn,
    session: Session = Depends(get_session),
) -> dict:
    job = session.get(VideoJob, job_id)
    if not job:
        raise HTTPException(404, "Job not found")
    job.translated_overlay_text = body.text
    session.add(job)
    session.commit()
    return {"ok": True, "translated_overlay_text": job.translated_overlay_text}
