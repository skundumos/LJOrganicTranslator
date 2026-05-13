from datetime import datetime
from enum import Enum
from sqlmodel import Field, SQLModel


class JobStatus(str, Enum):
    CREATED = "created"
    EXTRACTING_AUDIO = "extracting_audio"
    TRANSCRIBING = "transcribing"
    TRANSLATING_SCRIPT = "translating_script"
    GENERATING_VOICEOVER = "generating_voiceover"
    EXTRACTING_FRAME = "extracting_frame"
    DETECTING_TEXT = "detecting_text"
    TRANSLATING_OVERLAY = "translating_overlay"
    AWAITING_REVIEW = "awaiting_review"
    RENDERING_FINAL = "rendering_final"
    COMPLETED = "completed"
    FAILED = "failed"


class VideoJob(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)

    original_video_path: str
    target_language: str
    original_duration_s: float | None = None

    extracted_audio_path: str | None = None
    original_transcript: str | None = None

    translated_script_natural: str | None = None
    translated_script_compact: str | None = None
    translated_script: str | None = None
    generated_voiceover_path: str | None = None
    generated_voiceover_duration_s: float | None = None

    preview_frame_path: str | None = None
    background_frame_path: str | None = None

    detected_overlay_text: str | None = None
    translated_overlay_text: str | None = None

    bbox_x: int | None = None
    bbox_y: int | None = None
    bbox_width: int | None = None
    bbox_height: int | None = None
    font_size_hint: int | None = None

    final_video_path: str | None = None
    status: JobStatus = Field(default=JobStatus.CREATED)
    error_message: str | None = None

    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
