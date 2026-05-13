from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    OPENAI_API_KEY: str = ""
    CLAUDE_API_KEY: str = ""
    ELEVENLABS_API_KEY: str = ""
    GOOGLE_VISION_API_KEY: str = ""
    OCR_SPACE_API_KEY: str = ""

    STORAGE_DIR: str = "./storage"
    DB_URL: str = "sqlite:///./adlocalizer.db"
    MAX_UPLOAD_MB: int = 200
    MAX_VIDEO_DURATION_S: int = 60
    CORS_ORIGINS: str = "http://localhost:3000"

    FFMPEG_BIN: str = "ffmpeg"
    FFPROBE_BIN: str = "ffprobe"

    @property
    def storage_root(self) -> Path:
        p = Path(self.STORAGE_DIR).resolve()
        p.mkdir(parents=True, exist_ok=True)
        return p

    @property
    def cors_origins_list(self) -> list[str]:
        return [o.strip() for o in self.CORS_ORIGINS.split(",") if o.strip()]


settings = Settings()
