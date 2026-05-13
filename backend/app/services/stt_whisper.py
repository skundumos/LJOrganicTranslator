"""OpenAI Whisper API client. Forces language=en and adds an Indian-ad bias prompt so the
transcriber doesn't hallucinate Hindi words from accented English.
"""
from __future__ import annotations

import logging
from pathlib import Path

from tenacity import retry, stop_after_attempt, wait_exponential

from app.config import settings

log = logging.getLogger("ad_localizer.whisper")

_WHISPER_PROMPT = "Indian English advertisement voiceover. Conversational, persuasive."


@retry(reraise=True, stop=stop_after_attempt(3), wait=wait_exponential(min=1, max=8))
async def transcribe(audio_path: Path) -> str:
    if not settings.OPENAI_API_KEY:
        raise RuntimeError("OPENAI_API_KEY required for Whisper STT")
    from openai import AsyncOpenAI

    client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)
    with audio_path.open("rb") as f:
        resp = await client.audio.transcriptions.create(
            model="whisper-1",
            file=(audio_path.name, f, "audio/wav"),
            language="en",
            temperature=0.0,
            prompt=_WHISPER_PROMPT,
            response_format="verbose_json",
        )
    # verbose_json gives us segments with no_speech_prob — strip phantom tails.
    segments = getattr(resp, "segments", None) or []
    if segments:
        kept = [s for s in segments if getattr(s, "no_speech_prob", 0.0) < 0.6]
        text = " ".join(s.text.strip() for s in kept if s.text.strip())
        if text:
            return text.strip()
    return (resp.text or "").strip()
