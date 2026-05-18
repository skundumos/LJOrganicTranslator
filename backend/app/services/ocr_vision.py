"""Google Vision DOCUMENT_TEXT_DETECTION with bbox-merging heuristic for static centered overlay.

Returns a single bbox + the concatenated text. Falls back to OCR.space if Vision yields nothing.

Pre-processing:
- CLAHE on grayscale to rescue low-contrast white-on-light text.
- If frame is mostly white, also try an inverted copy and union results.
"""
from __future__ import annotations

import base64
import logging
import unicodedata
from dataclasses import dataclass
from pathlib import Path

import cv2
import httpx
import numpy as np
from tenacity import retry, stop_after_attempt, wait_exponential

from app.config import settings

log = logging.getLogger("ad_localizer.ocr")


def _is_textual_word(text: str) -> bool:
    """True if `text` contains at least one letter or digit codepoint.

    Used to drop emoji/pictograph-only "words" from a paragraph before we union word
    bboxes — otherwise the blur rectangle we draw on top of the detected text region
    would enclose any adjacent emojis, which looks unnatural.
    """
    if not text:
        return False
    for ch in text:
        if ch.isalnum():
            return True
        cat = unicodedata.category(ch)
        # L* = Letter, N* = Number — keep punctuation out of the "is textual" decision
        # because a punctuation-only word (e.g. "—") is rarely a translatable overlay on
        # its own, and we'd rather drop it than blur an emoji next to it.
        if cat.startswith("L") or cat.startswith("N"):
            return True
    return False


@dataclass
class OcrResult:
    text: str
    bbox: tuple[int, int, int, int]  # x, y, w, h
    font_size_hint: int
    confidence: float


def _preprocess(img: np.ndarray) -> list[np.ndarray]:
    """Return a list of candidate images to OCR (original + CLAHE + optionally inverted)."""
    candidates = [img]
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    clahe = cv2.createCLAHE(clipLimit=2.5, tileGridSize=(8, 8))
    enhanced = clahe.apply(gray)
    candidates.append(cv2.cvtColor(enhanced, cv2.COLOR_GRAY2BGR))
    # If frame is bright/white-heavy, also send an inverted copy
    if gray.mean() > 180:
        candidates.append(cv2.bitwise_not(img))
    return candidates


@retry(reraise=True, stop=stop_after_attempt(3), wait=wait_exponential(min=1, max=8))
async def _vision_call(image_bytes: bytes) -> dict:
    if not settings.GOOGLE_VISION_API_KEY:
        raise RuntimeError("GOOGLE_VISION_API_KEY required for OCR")
    url = f"https://vision.googleapis.com/v1/images:annotate?key={settings.GOOGLE_VISION_API_KEY}"
    payload = {
        "requests": [{
            "image": {"content": base64.b64encode(image_bytes).decode()},
            "features": [{"type": "DOCUMENT_TEXT_DETECTION"}],
            "imageContext": {"languageHints": ["en"]},
        }]
    }
    async with httpx.AsyncClient(timeout=60) as client:
        resp = await client.post(url, json=payload)
    resp.raise_for_status()
    return resp.json()["responses"][0]


def _verts(box: dict) -> list[tuple[int, int]]:
    return [(v.get("x", 0), v.get("y", 0)) for v in box.get("vertices", [])]


def _bbox_of_verts(verts: list[tuple[int, int]]) -> tuple[int, int, int, int]:
    xs = [v[0] for v in verts]
    ys = [v[1] for v in verts]
    x0, y0, x1, y1 = min(xs), min(ys), max(xs), max(ys)
    return x0, y0, x1 - x0, y1 - y0


def _cluster_to_result(cluster: list[dict], img_w: int, img_h: int) -> OcrResult:
    x0 = min(p["x"] for p in cluster)
    y0 = min(p["y"] for p in cluster)
    x1 = max(p["x"] + p["w"] for p in cluster)
    y1 = max(p["y"] + p["h"] for p in cluster)

    # Tighter padding than before (5% horizontal, 10% vertical, was 8%/12%). The bbox is
    # now built from word-level boxes that already exclude emoji-only words; a smaller
    # pad keeps adjacent emojis outside the blur rectangle. Vertical pad is larger than
    # horizontal because descenders + stroke outline often extend below the word bbox.
    w = x1 - x0
    h = y1 - y0
    dx = int(w * 0.05)
    dy = int(h * 0.10)
    x0 = max(0, x0 - dx)
    y0 = max(0, y0 - dy)
    x1 = min(img_w, x1 + dx)
    y1 = min(img_h, y1 + dy)

    text = "\n".join(p["text"] for p in cluster if p["text"]).strip()
    confidence = sum(p["conf"] for p in cluster) / len(cluster)
    # Use word-level heights (collected during paragraph parsing) rather than the
    # paragraph block height — the paragraph block grows with line-spacing and would
    # overestimate font size, especially for multi-line overlays.
    word_heights = [wh for p in cluster for wh in p.get("word_heights", [])]
    if word_heights:
        word_heights.sort()
        median_word_h = word_heights[len(word_heights) // 2]
    else:
        heights = sorted(p["h"] for p in cluster)
        median_word_h = heights[len(heights) // 2]
    font_hint = max(24, int(median_word_h * 0.95))

    return OcrResult(
        text=text,
        bbox=(int(x0), int(y0), int(x1 - x0), int(y1 - y0)),
        font_size_hint=font_hint,
        confidence=confidence,
    )


def _best_cluster(paragraphs: list[dict]) -> list[dict] | None:
    """Vertical-cluster the given paragraphs and return the largest cluster by area."""
    if not paragraphs:
        return None
    paragraphs = sorted(paragraphs, key=lambda p: p["y"])
    heights = sorted(p["h"] for p in paragraphs)
    median_h = heights[len(heights) // 2] or 20
    gap_threshold = 1.5 * median_h

    clusters: list[list[dict]] = [[paragraphs[0]]]
    for p in paragraphs[1:]:
        prev = clusters[-1][-1]
        if p["y"] - (prev["y"] + prev["h"]) < gap_threshold:
            clusters[-1].append(p)
        else:
            clusters.append([p])
    return max(clusters, key=lambda c: sum(p["w"] * p["h"] for p in c))


def _merge_paragraphs(annotation: dict, img_w: int, img_h: int) -> list[OcrResult]:
    """Return up to two OcrResults — the best cluster in the top band AND in the bottom band.

    Returning both lets the pipeline blur+overlay each independently, so ads with text
    above AND below the product (typical Instagram format) get fully localized.

    The paragraph bbox is computed as the UNION OF TEXTUAL-WORD BBOXES, not the paragraph
    bbox Vision returns. Emoji and pictograph-only words are dropped, so the rectangle
    we'll blur excludes any adjacent emojis. Words also feed `font_size_hint`.
    """
    pages = annotation.get("pages", [])
    if not pages:
        return []

    top_paras: list[dict] = []
    bot_paras: list[dict] = []
    for page in pages:
        for block in page.get("blocks", []):
            for para in block.get("paragraphs", []):
                conf = para.get("confidence", 0.0)
                if conf < 0.5:  # relaxed from 0.6 — word-level filter below offsets the risk
                    continue

                # Collect word-level bboxes, dropping any "word" that's only emoji/symbols.
                textual_words: list[dict] = []
                for word in para.get("words", []):
                    sym = "".join(s.get("text", "") for s in word.get("symbols", []))
                    if not _is_textual_word(sym):
                        continue
                    wverts = _verts(word.get("boundingBox", {}))
                    if len(wverts) < 4:
                        continue
                    wx, wy, ww, wh = _bbox_of_verts(wverts)
                    if ww <= 0 or wh <= 0:
                        continue
                    textual_words.append({
                        "text": sym, "x": wx, "y": wy, "w": ww, "h": wh,
                    })

                if not textual_words:
                    continue  # paragraph was entirely emoji/symbol — skip

                # Bbox = union of filtered word boxes (tighter than paragraph bbox).
                x0 = min(w["x"] for w in textual_words)
                y0 = min(w["y"] for w in textual_words)
                x1 = max(w["x"] + w["w"] for w in textual_words)
                y1 = max(w["y"] + w["h"] for w in textual_words)
                x, y, w, h = x0, y0, x1 - x0, y1 - y0
                cx = x + w / 2
                cy = y + h / 2

                # Horizontal band: relaxed from [0.2, 0.8] to [0.1, 0.9] so off-center
                # captions and lower-third graphics aren't rejected.
                if cx < img_w * 0.1 or cx > img_w * 0.9:
                    continue

                p_record = {
                    "text": " ".join(w["text"] for w in textual_words).strip(),
                    "x": x, "y": y, "w": w, "h": h, "conf": conf,
                    "word_heights": [w["h"] for w in textual_words],
                }
                # Vertical bands: top 45% / bottom 45% (was 35% / 65%) — only the central
                # 10% strip stays excluded as the "product" zone.
                if cy <= img_h * 0.45:
                    top_paras.append(p_record)
                elif cy >= img_h * 0.55:
                    bot_paras.append(p_record)

    results: list[OcrResult] = []
    top_cluster = _best_cluster(top_paras)
    if top_cluster:
        results.append(_cluster_to_result(top_cluster, img_w, img_h))
    bot_cluster = _best_cluster(bot_paras)
    if bot_cluster:
        results.append(_cluster_to_result(bot_cluster, img_w, img_h))
    return results


async def detect_overlay_regions(frame_path: Path) -> list[OcrResult]:
    """Run Vision OCR across preprocessed variants and return up to one region per band.

    For each band (top, bottom) keep the result with the highest confidence across variants —
    different preprocessing (CLAHE, inversion) can rescue text the original missed.
    """
    img = cv2.imread(str(frame_path))
    if img is None:
        raise RuntimeError(f"Could not read frame: {frame_path}")
    h, w = img.shape[:2]

    best_top: OcrResult | None = None
    best_bot: OcrResult | None = None
    for variant in _preprocess(img):
        ok, buf = cv2.imencode(".png", variant)
        if not ok:
            continue
        try:
            resp = await _vision_call(buf.tobytes())
        except Exception:
            log.exception("Google Vision call failed; trying next variant")
            continue
        annotation = resp.get("fullTextAnnotation")
        if not annotation:
            continue
        for region in _merge_paragraphs(annotation, w, h):
            cy = region.bbox[1] + region.bbox[3] / 2
            if cy <= h * 0.5:
                if best_top is None or region.confidence > best_top.confidence:
                    best_top = region
            else:
                if best_bot is None or region.confidence > best_bot.confidence:
                    best_bot = region

    out: list[OcrResult] = []
    if best_top:
        out.append(best_top)
    if best_bot:
        out.append(best_bot)
    if out:
        for r in out:
            log.info("OCR region text=%r bbox=%s conf=%.2f",
                     r.text[:80], r.bbox, r.confidence)
    else:
        log.warning("OCR failed to detect overlay text on %s", frame_path)
    return out


async def detect_overlay(frame_path: Path) -> OcrResult | None:
    """Back-compat single-region entrypoint. Prefer detect_overlay_regions for new callers."""
    regions = await detect_overlay_regions(frame_path)
    return regions[0] if regions else None
