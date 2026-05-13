import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.config import settings
from app.db import init_db
from app.api import upload, jobs, render, translate, voiceover, ocr, transcribe
from app.services.ffmpeg_ops import probe_ffmpeg_features

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s :: %(message)s",
)
log = logging.getLogger("ad_localizer")


@asynccontextmanager
async def lifespan(_: FastAPI):
    init_db()
    features = probe_ffmpeg_features()
    log.info("FFmpeg features: %s", features)
    if not features.get("libx264"):
        log.warning("FFmpeg lacks libx264 — final renders will fail. Install a full FFmpeg build.")
    if not features.get("librubberband"):
        log.warning(
            "FFmpeg lacks librubberband — falling back to atempo with reduced quality for extreme stretches."
        )
    yield


app = FastAPI(title="Ad Localizer", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(upload.router, prefix="/api", tags=["upload"])
app.include_router(jobs.router, prefix="/api", tags=["jobs"])
app.include_router(transcribe.router, prefix="/api", tags=["transcribe"])
app.include_router(translate.router, prefix="/api", tags=["translate"])
app.include_router(voiceover.router, prefix="/api", tags=["voiceover"])
app.include_router(ocr.router, prefix="/api", tags=["ocr"])
app.include_router(render.router, prefix="/api", tags=["render"])

app.mount("/files", StaticFiles(directory=str(settings.storage_root)), name="files")


@app.get("/api/health")
def health() -> dict:
    return {"ok": True, "ffmpeg": probe_ffmpeg_features()}


@app.get("/api/languages")
def languages() -> list[dict]:
    from app.services.voice_catalog import LANGUAGES
    return LANGUAGES
