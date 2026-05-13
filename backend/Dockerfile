FROM python:3.11-slim

# FFmpeg with libx264 + librubberband + libfreetype is required for full quality renders.
# Debian's ffmpeg ships libx264 + libfreetype; rubberband requires the contrib build.
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    libgl1 \
    libglib2.0-0 \
    libraqm0 \
    fontconfig \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY pyproject.toml ./
RUN pip install --no-cache-dir \
    "fastapi>=0.115.0" "uvicorn[standard]>=0.32.0" "python-multipart>=0.0.12" \
    "sqlmodel>=0.0.22" "pydantic>=2.9.0" "pydantic-settings>=2.5.0" \
    "httpx>=0.27.0" "openai>=1.54.0" "anthropic>=0.39.0" \
    "pillow>=10.4.0" "numpy>=1.26.0" "opencv-python-headless>=4.10.0" \
    "python-dotenv>=1.0.1" "tenacity>=9.0.0" "aiofiles>=24.1.0"

COPY app ./app

ENV STORAGE_DIR=/data/storage \
    DB_URL=sqlite:////data/adlocalizer.db \
    CORS_ORIGINS=http://localhost:3000

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
