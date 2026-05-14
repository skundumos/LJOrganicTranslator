"""Whisper STT client. Priority chain: Groq → OpenAI.

- Groq hosts `whisper-large-v3` on a free tier (20 RPM) via the OpenAI-compatible endpoint.
- OpenAI uses the standard `whisper-1` API.

Both branches force `language="en"` (auto-detect hallucinates Hindi on accented Indian English)
and add an Indian-ad bias prompt. We request `verbose_json` so we can strip phantom-tail
segments whose `no_speech_prob > 0.6`.
"""
from __future__ import annotations

import logging
from pathlib import Path

from tenacity import retry, stop_after_attempt, wait_exponential

from app.config import settings

log = logging.getLogger("ad_localizer.whisper")

_WHISPER_PROMPT = "Indian English advertisement voiceover. Conversational, persuasive."

GROQ_BASE_URL = "https://api.groq.com/openai/v1"
GROQ_MODEL = "whisper-large-v3"
OPENAI_MODEL = "whisper-1"


@retry(reraise=True, stop=stop_after_attempt(3), wait=wait_exponential(min=1, max=8))
async def transcribe(audio_path: Path) -> str:
    from openai import AsyncOpenAI

    if settings.GROQ_API_KEY:
        log.info("STT provider: Groq (%s)", GROQ_MODEL)
        client = AsyncOpenAI(api_key=settings.GROQ_API_KEY, base_url=GROQ_BASE_URL)
        model = GROQ_MODEL
    elif settings.OPENAI_API_KEY:
        log.info("STT provider: OpenAI (%s)", OPENAI_MODEL)
        client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)
        model = OPENAI_MODEL
    else:
        raise RuntimeError("No STT API key set (need GROQ_API_KEY or OPENAI_API_KEY)")

    with audio_path.open("rb") as f:
        resp = await client.audio.transcriptions.create(
            model=model,
            file=(audio_path.name, f, "audio/wav"),
            language="en",
            temperature=0.0,
            prompt=_WHISPER_PROMPT,
            response_format="verbose_json",
        )
    # verbose_json gives us segments with no_speech_prob — strip phantom tails.
    segments = getattr(resp, "segments", None) or []
    if segments:
        kept = []
        for s in segments:
            # Groq returns dicts; OpenAI returns objects. Handle both.
            nsp = s.get("no_speech_prob", 0.0) if isinstance(s, dict) else getattr(s, "no_speech_prob", 0.0)
            txt = s.get("text", "") if isinstance(s, dict) else getattr(s, "text", "")
            if nsp < 0.6 and txt.strip():
                kept.append(txt.strip())
        text = " ".join(kept)
        if text:
            return text.strip()
    return (getattr(resp, "text", None) or "").strip()
