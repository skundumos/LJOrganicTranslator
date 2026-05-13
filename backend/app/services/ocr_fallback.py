"""OCR.space fallback. Used only when Google Vision returns nothing.

Its bbox data is unreliable, so we only use it for text extraction; geometry stays from Vision
or, if Vision found nothing at all, we estimate a centered bbox.
"""
from __future__ import annotations

import logging
from pathlib import Path

import httpx

from app.config import settings

log = logging.getLogger("ad_localizer.ocr_fallback")


async def ocrspace_text(image_path: Path) -> str | None:
    if not settings.OCR_SPACE_API_KEY:
        return None
    url = "https://api.ocr.space/parse/image"
    headers = {"apikey": settings.OCR_SPACE_API_KEY}
    with image_path.open("rb") as f:
        files = {"file": (image_path.name, f, "image/png")}
        data = {"language": "eng", "OCREngine": "2", "scale": "true", "detectOrientation": "true"}
        async with httpx.AsyncClient(timeout=60) as client:
            resp = await client.post(url, headers=headers, data=data, files=files)
    if resp.status_code != 200:
        log.warning("OCR.space %s: %s", resp.status_code, resp.text[:200])
        return None
    body = resp.json()
    parsed = body.get("ParsedResults") or []
    if not parsed:
        return None
    return (parsed[0].get("ParsedText") or "").strip() or None
