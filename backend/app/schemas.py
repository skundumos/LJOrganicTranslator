from datetime import datetime
from pydantic import BaseModel
from app.models import JobStatus


class BoundingBoxOut(BaseModel):
    x: int
    y: int
    width: int
    height: int
    font_size_hint: int


class JobOut(BaseModel):
    id: int
    status: JobStatus
    target_language: str
    original_duration_s: float | None
    original_transcript: str | None
    translated_script: str | None
    translated_script_natural: str | None
    translated_script_compact: str | None
    detected_overlay_text: str | None
    translated_overlay_text: str | None
    bbox: BoundingBoxOut | None
    has_preview_frame: bool
    has_voiceover: bool
    has_final_video: bool
    error_message: str | None
    created_at: datetime
    updated_at: datetime


class TranslateScriptIn(BaseModel):
    regenerate: bool = False


class UpdateOverlayIn(BaseModel):
    text: str


class UpdateScriptIn(BaseModel):
    text: str


class RenderPreviewIn(BaseModel):
    text: str


class RegenerateVoiceoverIn(BaseModel):
    text: str | None = None
