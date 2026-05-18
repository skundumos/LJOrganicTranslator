"""LLM adapter. Priority chain: Groq → Claude → OpenAI.

- Groq uses `llama-3.3-70b-versatile` via the OpenAI-compatible endpoint at api.groq.com.
- Claude uses Sonnet 4.6.
- OpenAI uses GPT-4o.

All providers are invoked through a thin async wrapper that enforces JSON output.
"""
from __future__ import annotations

import json
import logging
import re
import tempfile
from pathlib import Path
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


GROQ_BASE_URL = "https://api.groq.com/openai/v1"
GROQ_MODEL = "llama-3.3-70b-versatile"
OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"


async def _call_groq(messages: list[dict], max_tokens: int = 1024) -> str:
    from openai import AsyncOpenAI

    client = AsyncOpenAI(api_key=settings.GROQ_API_KEY, base_url=GROQ_BASE_URL)
    resp = await client.chat.completions.create(
        model=GROQ_MODEL,
        messages=messages,
        max_tokens=max_tokens,
        temperature=0.4,
        response_format={"type": "json_object"},
    )
    return resp.choices[0].message.content or ""


async def _call_openrouter(messages: list[dict], max_tokens: int = 1024) -> str:
    from openai import AsyncOpenAI

    client = AsyncOpenAI(
        api_key=settings.OPENROUTER_API_KEY,
        base_url=OPENROUTER_BASE_URL,
    )
    resp = await client.chat.completions.create(
        model=settings.OPENROUTER_MODEL,
        messages=messages,
        max_tokens=max_tokens,
        temperature=0.4,
        response_format={"type": "json_object"},
    )
    return resp.choices[0].message.content or ""


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
    # Priority: OpenRouter (routes to Claude/etc per OPENROUTER_MODEL) → native Anthropic
    # Claude → Groq Llama → OpenAI GPT-4o. Claude is preferred over Groq for ad-copy
    # localization because it handles South-Indian + Bengali expansion noticeably better
    # (see README "Engineering trade-offs").
    if settings.OPENROUTER_API_KEY:
        log.info("LLM provider: OpenRouter (%s)", settings.OPENROUTER_MODEL)
        raw = await _call_openrouter(messages, max_tokens=max_tokens)
    elif settings.CLAUDE_API_KEY:
        log.info("LLM provider: Claude (claude-sonnet-4-6)")
        raw = await _call_claude(messages, max_tokens=max_tokens)
    elif settings.GROQ_API_KEY:
        log.info("LLM provider: Groq (%s)", GROQ_MODEL)
        raw = await _call_groq(messages, max_tokens=max_tokens)
    elif settings.OPENAI_API_KEY:
        log.info("LLM provider: OpenAI (gpt-4o)")
        raw = await _call_openai(messages, max_tokens=max_tokens)
    else:
        raise TranslationError(
            "No LLM API key set (need OPENROUTER_API_KEY, CLAUDE_API_KEY, GROQ_API_KEY, or OPENAI_API_KEY)"
        )
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


async def translate_overlay(
    text: str,
    language_code: str,
    bbox_w: int | None = None,
    bbox_h: int | None = None,
    font_size_hint: int | None = None,
) -> str:
    """Translate one overlay string.

    When `bbox_w`/`bbox_h`/`font_size_hint` are supplied, the result is probe-rendered and
    the LLM is retried (up to 2x) with a tighter character budget if the auto-fit pinned
    the font near the 24px legibility floor. Without bbox info, behaves as before — single
    LLM call, no fit check.
    """
    lang = get_language(language_code)
    initial_max_chars = max(30, min(200, int(len(text) * 1.2)))
    messages = build_overlay_messages(text, lang["display_name"], initial_max_chars)
    data = await _call_llm(messages, max_tokens=400)
    out = data.get("text") or data.get("translation") or ""
    if not out:
        raise TranslationError(f"Empty overlay translation: {data}")
    candidate = _lint_overlay(str(out), text)

    if bbox_w and bbox_h and font_size_hint:
        candidate = await _refine_for_fit(
            candidate, text, lang["display_name"], initial_max_chars,
            language_code, bbox_w, bbox_h, font_size_hint,
        )
    return candidate


async def _refine_for_fit(
    candidate: str,
    original_english: str,
    language_name: str,
    initial_max_chars: int,
    language_code: str,
    bbox_w: int,
    bbox_h: int,
    font_size_hint: int,
) -> str:
    """Probe-render and retry-translate until the rendered font px clears the legibility
    floor or 2 retries are exhausted. Always returns the variant with the highest font px
    observed across attempts.
    """
    from app.services.text_renderer import render_text_png

    fit_threshold = max(28, int(font_size_hint * 0.6))
    best_text = candidate
    best_px = 0
    current = candidate

    with tempfile.TemporaryDirectory() as td:
        for attempt in range(3):  # 1 initial probe + up to 2 retries
            probe_png = Path(td) / f"probe_{attempt}.png"
            try:
                _, font_px = render_text_png(
                    current, language_code, bbox_w, bbox_h, font_size_hint, probe_png,
                )
            except Exception:
                log.exception("Length-fit probe %d failed; using best so far.", attempt)
                break

            if font_px > best_px:
                best_text, best_px = current, font_px

            if font_px >= fit_threshold:
                log.info("Length-fit OK at attempt %d (font_px=%d >= floor %d).",
                         attempt, font_px, fit_threshold)
                return best_text

            if attempt == 2:
                log.info("Length-fit exhausted; using best variant (font_px=%d).", best_px)
                break

            tighter_chars = max(20, int(initial_max_chars * (0.7 ** (attempt + 1))))
            log.info("Length-fit retry %d at <= %d chars (current font_px=%d < floor %d).",
                     attempt + 1, tighter_chars, font_px, fit_threshold)
            retry_messages = build_overlay_messages(
                original_english, language_name, tighter_chars,
            ) + [
                {"role": "assistant", "content": json.dumps({"text": current})},
                {"role": "user", "content": (
                    f"That was still too long — the rendered font shrank to {font_px}px "
                    f"below the {fit_threshold}px legibility floor. Return a tighter "
                    f"version with at most {tighter_chars} characters. Abbreviate "
                    f'aggressively. JSON only: {{"text": "..."}}'
                )},
            ]
            try:
                data = await _call_llm(retry_messages, max_tokens=300)
                retry_out = data.get("text") or data.get("translation") or ""
                if not retry_out:
                    log.warning("Length-fit retry %d returned empty; stopping.", attempt + 1)
                    break
                current = _lint_overlay(str(retry_out), original_english)
            except Exception:
                log.exception("Length-fit retry %d failed; keeping best so far.", attempt + 1)
                break

    return best_text


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
