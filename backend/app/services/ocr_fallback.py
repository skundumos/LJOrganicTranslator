"""OCR.space — used when GOOGLE_VISION_API_KEY isn't set.

Engine 2 returns per-word pixel coordinates when `isOverlayRequired=true`. We use those
to do real bbox detection rather than centered estimation. For Instagram-style ads, the
overlay text is at the top or bottom of the frame, NOT in the visual middle (which is
usually the product). The clustering heuristic here filters out the central product band
and picks the densest top-or-bottom cluster as the overlay region.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

import httpx

from app.config import settings
from app.services.ocr_vision import _is_textual_word

log = logging.getLogger("ad_localizer.ocr_fallback")


@dataclass
class Word:
    text: str
    x: int
    y: int
    width: int
    height: int

    @property
    def cx(self) -> float:
        return self.x + self.width / 2

    @property
    def cy(self) -> float:
        return self.y + self.height / 2


@dataclass
class OcrSpaceResult:
    text: str
    bbox: tuple[int, int, int, int]   # x, y, w, h
    font_size_hint: int


async def _ocrspace_raw(image_path: Path) -> dict | None:
    """Returns the raw OCR.space response (Engine 2 with word overlays), or None on failure."""
    if not settings.OCR_SPACE_API_KEY:
        return None
    url = "https://api.ocr.space/parse/image"
    headers = {"apikey": settings.OCR_SPACE_API_KEY}
    with image_path.open("rb") as f:
        files = {"file": (image_path.name, f, "image/png")}
        data = {
            "language": "eng",
            "OCREngine": "2",
            "scale": "true",
            "detectOrientation": "true",
            "isOverlayRequired": "true",
        }
        async with httpx.AsyncClient(timeout=60) as client:
            resp = await client.post(url, headers=headers, data=data, files=files)
    if resp.status_code != 200:
        log.warning("OCR.space %s: %s", resp.status_code, resp.text[:200])
        return None
    body = resp.json()
    parsed = body.get("ParsedResults") or []
    if not parsed:
        return None
    return parsed[0]


def _words_from_response(parsed: dict) -> list[Word]:
    """Parse word records, skipping any that are emoji/pictograph-only.

    Mirrors the filter in ocr_vision so the blur rectangle hugs the textual region and
    doesn't enclose adjacent emojis (which look unnatural when blurred and overwritten).
    """
    overlay = parsed.get("TextOverlay") or {}
    lines = overlay.get("Lines") or []
    out: list[Word] = []
    for line in lines:
        for w in line.get("Words") or []:
            try:
                text = str(w.get("WordText", ""))
                if not _is_textual_word(text):
                    continue
                out.append(Word(
                    text=text,
                    x=int(w.get("Left", 0)),
                    y=int(w.get("Top", 0)),
                    width=int(w.get("Width", 0)),
                    height=int(w.get("Height", 0)),
                ))
            except (TypeError, ValueError):
                continue
    return out


def _build_cluster_result(cluster: list[Word], img_w: int, img_h: int) -> OcrSpaceResult:
    x0 = min(w.x for w in cluster)
    y0 = min(w.y for w in cluster)
    x1 = max(w.x + w.width for w in cluster)
    y1 = max(w.y + w.height for w in cluster)

    bw = x1 - x0
    bh = y1 - y0
    # Tighter than before (5%/10%, was 8%/20%). Words are already emoji-filtered upstream,
    # so a smaller pad keeps the blur rectangle off any emojis sitting right next to text.
    pad_x = int(bw * 0.05)
    pad_y = int(bh * 0.10)
    x0 = max(0, x0 - pad_x)
    y0 = max(0, y0 - pad_y)
    x1 = min(img_w, x1 + pad_x)
    y1 = min(img_h, y1 + pad_y)

    # Reconstruct text by line for readability
    lines: list[str] = []
    cur_line: list[Word] = []
    line_y: int | None = None
    for w in sorted(cluster, key=lambda w: (w.y, w.x)):
        if line_y is None or abs(w.y - line_y) < w.height * 0.6:
            cur_line.append(w)
            line_y = w.y if line_y is None else line_y
        else:
            lines.append(" ".join(t.text for t in sorted(cur_line, key=lambda x: x.x)))
            cur_line = [w]
            line_y = w.y
    if cur_line:
        lines.append(" ".join(t.text for t in sorted(cur_line, key=lambda x: x.x)))
    text = "\n".join(s for s in lines if s.strip())

    heights = sorted(w.height for w in cluster)
    median_h = heights[len(heights) // 2]
    font_hint = max(24, int(median_h * 0.95))

    return OcrSpaceResult(
        text=text.strip(),
        bbox=(int(x0), int(y0), int(x1 - x0), int(y1 - y0)),
        font_size_hint=font_hint,
    )


def _vert_clusters(group: list[Word]) -> list[list[Word]]:
    if not group:
        return []
    group = sorted(group, key=lambda w: w.y)
    heights = sorted(w.height for w in group)
    median_h = heights[len(heights) // 2] or 20
    gap_threshold = 1.5 * median_h
    clusters: list[list[Word]] = [[group[0]]]
    for w in group[1:]:
        prev = clusters[-1][-1]
        if w.y - (prev.y + prev.height) < gap_threshold:
            clusters[-1].append(w)
        else:
            clusters.append([w])
    return clusters


def _cluster_regions(words: list[Word], img_w: int, img_h: int) -> list[OcrSpaceResult]:
    """Return up to two OcrSpaceResults — best cluster in the top band and in the bottom band.

    Each band is processed independently so an ad with text both above and below the product
    yields two regions (top first, bottom second).
    """
    if not words:
        return []

    # Loosened from 0.35/0.65 to 0.45/0.55 — only the central 10% stays excluded as the
    # "product" zone. Matches the band split in ocr_vision so both providers agree on
    # which slice of the frame is a candidate overlay.
    TOP_BAND = img_h * 0.45
    BOTTOM_BAND_START = img_h * 0.55

    top_words = [w for w in words if w.cy <= TOP_BAND]
    bottom_words = [w for w in words if w.cy >= BOTTOM_BAND_START]

    def best_in_band(group: list[Word]) -> list[Word] | None:
        clusters = _vert_clusters(group)
        if not clusters:
            return None
        return max(clusters, key=lambda c: sum(w.width * w.height for w in c))

    out: list[OcrSpaceResult] = []
    top_best = best_in_band(top_words)
    if top_best:
        out.append(_build_cluster_result(top_best, img_w, img_h))
    bot_best = best_in_band(bottom_words)
    if bot_best:
        out.append(_build_cluster_result(bot_best, img_w, img_h))
    return out


async def detect_overlay_regions(
    image_path: Path, img_w: int, img_h: int
) -> list[OcrSpaceResult]:
    """Full OCR.space pipeline: API call + word parse + per-band clustering."""
    parsed = await _ocrspace_raw(image_path)
    if not parsed:
        return []
    words = _words_from_response(parsed)
    if not words:
        # No word overlay info — fall back to whole-page text only (no bbox)
        text = (parsed.get("ParsedText") or "").strip()
        if not text:
            return []
        log.info("OCR.space returned text without word coords; using centered estimate.")
        bw = int(img_w * 0.8)
        bh = int(img_h * 0.18)
        bx = (img_w - bw) // 2
        by = int(img_h * 0.08)  # top placement default (Instagram style)
        return [OcrSpaceResult(
            text=text, bbox=(bx, by, bw, bh),
            font_size_hint=max(48, bh // 3),
        )]
    return _cluster_regions(words, img_w, img_h)


async def detect_overlay_smart(
    image_path: Path, img_w: int, img_h: int
) -> OcrSpaceResult | None:
    """Back-compat single-region entrypoint. Returns the first region only."""
    regions = await detect_overlay_regions(image_path, img_w, img_h)
    return regions[0] if regions else None


async def ocrspace_text(image_path: Path) -> str | None:
    """Legacy text-only entrypoint kept for back-compat."""
    parsed = await _ocrspace_raw(image_path)
    if not parsed:
        return None
    return (parsed.get("ParsedText") or "").strip() or None
