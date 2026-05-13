"""POST /api/upload — accept an MP4 + target language, create a VideoJob,
kick off the prep pipeline in the background.
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime
from pathlib import Path

import aiofiles
from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, UploadFile
from sqlmodel import Session

from app.api._common import to_job_out
from app.config import settings
from app.db import get_session
from app.models import JobStatus, VideoJob
from app.schemas import JobOut
from app.services.pipeline import run_prep_pipeline
from app.services.runner import runner
from app.services.storage import storage
from app.services.voice_catalog import language_codes

log = logging.getLogger("ad_localizer.upload")
router = APIRouter()

ALLOWED_CTYPES = {"video/mp4", "video/quicktime", "video/x-m4v", "application/octet-stream"}
MAX_BYTES_DEFAULT = 200 * 1024 * 1024


@router.post("/upload", response_model=JobOut)
async def upload(
    background_tasks: BackgroundTasks,
    video: UploadFile = File(...),
    target_language: str = Form(...),
    session: Session = Depends(get_session),
) -> JobOut:
    if target_language not in language_codes():
        raise HTTPException(400, f"Unsupported language: {target_language}")
    if video.content_type and video.content_type not in ALLOWED_CTYPES:
        log.warning("Unexpected content-type: %s", video.content_type)

    max_bytes = settings.MAX_UPLOAD_MB * 1024 * 1024

    # Stage to a temp path under storage, then create the DB row, then move it under the job dir.
    tmp_name = f"upload_{uuid.uuid4().hex}.mp4"
    tmp_path = storage.absolute(tmp_name)
    written = 0
    async with aiofiles.open(tmp_path, "wb") as f:
        while True:
            chunk = await video.read(1024 * 1024)
            if not chunk:
                break
            written += len(chunk)
            if written > max_bytes:
                await f.close()
                tmp_path.unlink(missing_ok=True)
                raise HTTPException(413, f"Upload exceeds {settings.MAX_UPLOAD_MB}MB")
            await f.write(chunk)

    if written < 1024:
        tmp_path.unlink(missing_ok=True)
        raise HTTPException(400, "Uploaded file is too small")

    job = VideoJob(
        original_video_path=str(tmp_path),
        target_language=target_language,
        status=JobStatus.CREATED,
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
    )
    session.add(job)
    session.commit()
    session.refresh(job)

    # Move file into the job dir, update DB
    job_dir = storage.job_dir(job.id or 0)
    final_path = job_dir / "input.mp4"
    Path(tmp_path).rename(final_path)
    job.original_video_path = str(final_path)
    session.add(job)
    session.commit()
    session.refresh(job)

    # Kick off the prep chain in the background. BackgroundTasks uses a coroutine wrapper.
    job_id = job.id or 0
    background_tasks.add_task(_launch_prep, job_id)
    return to_job_out(job)


def _launch_prep(job_id: int) -> None:
    # FastAPI BackgroundTasks runs sync functions in a threadpool; schedule the coroutine.
    runner.submit(lambda: run_prep_pipeline(job_id))
