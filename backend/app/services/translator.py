"""LLM adapter. Uses Claude (Sonnet 4.6) if CLAUDE_API_KEY is set, otherwise OpenAI GPT-4o.

Both providers are invoked through a thin async wrapper that enforces JSON output.
"""
from __future__ import annotations

import json
import logging
import re
from typing import Any

from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from app.config import settings
from app.services.prompts import build_overlay_messages, build_script_messages
from app.services.voice_catalog import get_language

log = logging.getLogger("ad_localizer.translator")


class TranslationError(RuntimeError):
    pass


def _strip_code_fences(s: str) -> str:
    s = s.strip()
    s = re.sub(r"^```(?:json)?\s*", "", s)
    s = re.sub(r"\s*```$", "", s)
    return s.strip()


def _parse_json(raw: str) -> dict[str, Any]:
    raw = _strip_code_fences(raw)
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        # Try to grab the first {...} block
        m = re.search(r"\{.*\}", raw, re.DOTALL)
        if not m:
            raise TranslationError(f"Could not parse JSON from LLM output: {raw[:200]}")
        return json.loads(m.group(0))


async def _call_claude(messages: list[dict], max_tokens: int = 1024) -> str:
    from anthropic import AsyncAnthropic

    client = AsyncAnthropic(api_key=settings.CLAUDE_API_KEY)
    system = next((m["content"] for m in messages if m["role"] == "system"), "")
    user_msgs = [{"role": "user", "content": m["content"]} for m in messages if m["role"] == "user"]
    resp = await client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=max_tokens,
        system=system,
        messages=user_msgs,
    )
    return "".join(block.text for block in resp.content if hasattr(block, "text"))


async def _call_openai(messages: list[dict], max_tokens: int = 1024) -> str:
    from openai import AsyncOpenAI

    client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)
    resp = await client.chat.completions.create(
        model="gpt-4o",
        messages=messages,
        max_tokens=max_tokens,
        temperature=0.4,
        response_format={"type": "json_object"},
    )
    return resp.choices[0].message.content or ""


@retry(
    reraise=True,
    stop=stop_after_attempt(3),
    wait=wait_exponential(min=1, max=8),
    retry=retry_if_exception_type((TranslationError,)),
)
async def _call_llm(messages: list[dict], max_tokens: int = 1024) -> dict:
    if settings.CLAUDE_API_KEY:
        raw = await _call_claude(messages, max_tokens=max_tokens)
    elif settings.OPENAI_API_KEY:
        raw = await _call_openai(messages, max_tokens=max_tokens)
    else:
        raise TranslationError("No LLM API key set (CLAUDE_API_KEY or OPENAI_API_KEY)")
    return _parse_json(raw)


_DEVANAGARI_DIGITS = "०१२३४५६७८९"


def _lint_overlay(text: str, original: str) -> str:
    # Reject Devanagari numerals in price-like contexts; translator was instructed to use Western.
    if any(d in text for d in _DEVANAGARI_DIGITS):
        # Map back to ASCII digits as a best-effort recovery rather than rejecting outright.
        trans_table = str.maketrans({d: str(i) for i, d in enumerate(_DEVANAGARI_DIGITS)})
        text = text.translate(trans_table)
    if len(text) > max(60, len(original) * 3):
        log.warning("Overlay translation suspiciously long (%d chars from %d)", len(text), len(original))
    return text.strip()


async def translate_overlay(text: str, language_code: str) -> str:
    lang = get_language(language_code)
    messages = build_overlay_messages(text, lang["display_name"])
    data = await _call_llm(messages, max_tokens=400)
    out = data.get("text") or data.get("translation") or ""
    if not out:
        raise TranslationError(f"Empty overlay translation: {data}")
    return _lint_overlay(str(out), text)


async def translate_script(text: str, language_code: str, target_seconds: float) -> dict[str, str]:
    """Returns {'natural': ..., 'compact': ...}."""
    lang = get_language(language_code)
    messages = build_script_messages(text, lang["display_name"], target_seconds)
    data = await _call_llm(messages, max_tokens=1500)
    natural = str(data.get("natural") or data.get("text") or "").strip()
    compact = str(data.get("compact") or "").strip()
    if not natural:
        raise TranslationError(f"Empty script translation: {data}")
    if not compact:
        compact = natural  # graceful fallback
    return {"natural": natural, "compact": compact}
