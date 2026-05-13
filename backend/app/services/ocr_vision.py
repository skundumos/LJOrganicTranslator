"""Google Vision DOCUMENT_TEXT_DETECTION with bbox-merging heuristic for static centered overlay.

Returns a single bbox + the concatenated text. Falls back to OCR.space if Vision yields nothing.

Pre-processing:
- CLAHE on grayscale to rescue low-contrast white-on-light text.
- If frame is mostly white, also try an inverted copy and union results.
"""
from __future__ import annotations

import base64
import logging
from dataclasses import dataclass
from pathlib import Path

import cv2
import httpx
import numpy as np
from tenacity import retry, stop_after_attempt, wait_exponential

from app.config import settings

log = logging.getLogger("ad_localizer.ocr")


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


def _merge_paragraphs(annotation: dict, img_w: int, img_h: int) -> OcrResult | None:
    pages = annotation.get("pages", [])
    if not pages:
        return None

    paragraphs: list[dict] = []
    for page in pages:
        for block in page.get("blocks", []):
            for para in block.get("paragraphs", []):
                conf = para.get("confidence", 0.0)
                if conf < 0.6:
                    continue
                verts = _verts(para.get("boundingBox", {}))
                if len(verts) < 4:
                    continue
                x, y, w, h = _bbox_of_verts(verts)
                cx = x + w / 2
                # Keep only paragraphs whose center is in the central 60% horizontal band
                if cx < img_w * 0.2 or cx > img_w * 0.8:
                    continue
                # Concatenate words inside the paragraph
                words: list[str] = []
                for word in para.get("words", []):
                    sym = "".join(s.get("text", "") for s in word.get("symbols", []))
                    words.append(sym)
                paragraphs.append({
                    "text": " ".join(words).strip(),
                    "x": x, "y": y, "w": w, "h": h, "conf": conf,
                })

    if not paragraphs:
        return None

    # Vertically cluster paragraphs with gaps < 1.5 * median line height
    paragraphs.sort(key=lambda p: p["y"])
    heights = sorted(p["h"] for p in paragraphs)
    median_h = heights[len(heights) // 2]
    gap_threshold = 1.5 * median_h

    clusters: list[list[dict]] = [[paragraphs[0]]]
    for p in paragraphs[1:]:
        prev = clusters[-1][-1]
        gap = p["y"] - (prev["y"] + prev["h"])
        if gap < gap_threshold:
            clusters[-1].append(p)
        else:
            clusters.append([p])

    # Pick the largest cluster by total area (the overlay)
    def cluster_area(c: list[dict]) -> int:
        return sum(p["w"] * p["h"] for p in c)

    best = max(clusters, key=cluster_area)

    x0 = min(p["x"] for p in best)
    y0 = min(p["y"] for p in best)
    x1 = max(p["x"] + p["w"] for p in best)
    y1 = max(p["y"] + p["h"] for p in best)

    # Expand: 8% horizontal, 12% vertical
    w = x1 - x0
    h = y1 - y0
    dx = int(w * 0.08)
    dy = int(h * 0.12)
    x0 = max(0, x0 - dx)
    y0 = max(0, y0 - dy)
    x1 = min(img_w, x1 + dx)
    y1 = min(img_h, y1 + dy)

    text = "\n".join(p["text"] for p in best if p["text"]).strip()
    confidence = sum(p["conf"] for p in best) / len(best)
    font_hint = max(24, int(median_h * 0.95))

    return OcrResult(
        text=text,
        bbox=(int(x0), int(y0), int(x1 - x0), int(y1 - y0)),
        font_size_hint=font_hint,
        confidence=confidence,
    )


async def detect_overlay(frame_path: Path) -> OcrResult | None:
    img = cv2.imread(str(frame_path))
    if img is None:
        raise RuntimeError(f"Could not read frame: {frame_path}")
    h, w = img.shape[:2]

    best: OcrResult | None = None
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
        merged = _merge_paragraphs(annotation, w, h)
        if merged and (best is None or merged.confidence > best.confidence):
            best = merged
    if best:
        log.info("OCR detected text=%r bbox=%s conf=%.2f",
                 best.text[:80], best.bbox, best.confidence)
    else:
        log.warning("OCR failed to detect overlay text on %s", frame_path)
    return best
