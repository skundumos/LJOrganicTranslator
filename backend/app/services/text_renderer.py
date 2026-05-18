"""Render translated text to a transparent RGBA PNG using Pillow.

Pillow ≥10 with libraqm linked shapes Indic scripts via HarfBuzz — FFmpeg drawtext does NOT,
which is why we render to PNG and overlay rather than using drawtext directly.

Auto-fit:
- Binary-search font size in [24, max(font_size_hint*1.2, 48)] so rendered text width
  <= bbox_width * 0.95 and height fits.
- If still overflows at min size, word-wrap; if still overflows, tighten line-height to 1.05
  before reducing font further.
- Render at 4x supersample, Lanczos downsample (kills aliasing on Tamil/Telugu diagonals).

Sanity check: assert non-transparent pixel count > min — sparse PNG = font load failed silently.
"""
from __future__ import annotations

import logging
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from app.services.voice_catalog import get_language

log = logging.getLogger("ad_localizer.text_renderer")

FONTS_DIR = Path(__file__).resolve().parent.parent / "fonts"
SUPERSAMPLE = 4


def _font_path(language_code: str) -> Path:
    lang = get_language(language_code)
    f = FONTS_DIR / lang["noto_font"]
    if f.exists():
        return f
    fallback = FONTS_DIR / "NotoSans-Bold.ttf"
    if fallback.exists():
        log.warning("Font %s missing; falling back to NotoSans-Bold.ttf", lang["noto_font"])
        return fallback
    raise FileNotFoundError(
        f"No font found at {f}. Run `python backend/scripts/download_fonts.py` to fetch the Noto fonts."
    )


def _load_bold(font_file: Path, size: int) -> ImageFont.FreeTypeFont:
    """Load a Noto font and lock the weight axis to Bold (700).

    Our bundled files are variable fonts (wdth+wght axes) saved as *-Bold.ttf for
    naming clarity. If the file is a non-variable static, set_variation_by_axes
    raises OSError — we just fall through and use the file as-is.
    """
    font = ImageFont.truetype(str(font_file), size)
    try:
        font.set_variation_by_axes([100.0, 700.0])  # wdth=100 (normal), wght=700 (Bold)
    except (OSError, AttributeError, ValueError):
        pass  # static font — already the right weight (or not a variable font)
    return font


def _wrap(text: str, font: ImageFont.FreeTypeFont, max_width: int, draw: ImageDraw.ImageDraw) -> list[str]:
    words = text.split()
    lines: list[str] = []
    cur = ""
    for w in words:
        candidate = (cur + " " + w).strip()
        bbox = draw.textbbox((0, 0), candidate, font=font)
        if (bbox[2] - bbox[0]) <= max_width:
            cur = candidate
        else:
            if cur:
                lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    return lines


def _measure(lines: list[str], font: ImageFont.FreeTypeFont, draw: ImageDraw.ImageDraw,
             line_height_mult: float) -> tuple[int, int]:
    if not lines:
        return 0, 0
    widths = []
    line_h = 0
    for line in lines:
        bbox = draw.textbbox((0, 0), line, font=font)
        widths.append(bbox[2] - bbox[0])
        line_h = max(line_h, bbox[3] - bbox[1])
    total_h = int(line_h * line_height_mult * len(lines))
    return max(widths), total_h


def render_text_png(
    text: str,
    language_code: str,
    bbox_w: int,
    bbox_h: int,
    font_size_hint: int,
    out_png: Path,
) -> tuple[Path, int]:
    """Render `text` for `language_code` to a transparent PNG sized to fit within bbox.

    Returns (out_png, chosen_font_px) — the second element is the actual font size used
    after the auto-fit binary search, in screen pixels (already de-supersampled). Callers
    can use it to detect overflow (when the search pinned at the 24px floor) and retry
    the upstream translation with a tighter character budget.
    """
    out_png.parent.mkdir(parents=True, exist_ok=True)
    lang = get_language(language_code)
    bcp47 = lang["bcp47"]
    font_file = _font_path(language_code)

    canvas_w = bbox_w * SUPERSAMPLE
    canvas_h = bbox_h * SUPERSAMPLE
    target_w = int(canvas_w * 0.95)
    target_h = int(canvas_h * 0.95)

    measure_img = Image.new("RGBA", (canvas_w, canvas_h), (0, 0, 0, 0))
    measure_draw = ImageDraw.Draw(measure_img)

    lo, hi = 24 * SUPERSAMPLE, max(font_size_hint, 48) * SUPERSAMPLE
    chosen_size = lo
    chosen_lines: list[str] = [text]
    line_height_mult = 1.15

    # Binary search for largest font size that fits
    while lo <= hi:
        mid = (lo + hi) // 2
        font = _load_bold(font_file, mid)
        lines = _wrap(text, font, target_w, measure_draw)
        w, h = _measure(lines, font, measure_draw, line_height_mult)
        if w <= target_w and h <= target_h:
            chosen_size = mid
            chosen_lines = lines
            lo = mid + 4
        else:
            hi = mid - 4

    # If still overflowing at min size, tighten line height before giving up
    font = _load_bold(font_file, chosen_size)
    lines = _wrap(text, font, target_w, measure_draw)
    w, h = _measure(lines, font, measure_draw, line_height_mult)
    if h > target_h and line_height_mult > 1.05:
        line_height_mult = 1.05
        w, h = _measure(lines, font, measure_draw, line_height_mult)

    img = Image.new("RGBA", (canvas_w, canvas_h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    # Compute total text height for vertical centering
    total_h = h
    y_cursor = (canvas_h - total_h) // 2

    stroke = max(2 * SUPERSAMPLE, chosen_size // 18)

    for line in lines:
        bbox = draw.textbbox((0, 0), line, font=font)
        line_w = bbox[2] - bbox[0]
        line_h = bbox[3] - bbox[1]
        x = (canvas_w - line_w) // 2
        try:
            draw.text(
                (x, y_cursor),
                line,
                font=font,
                fill=(255, 255, 255, 255),
                stroke_width=stroke,
                stroke_fill=(0, 0, 0, 220),
                language=bcp47,
                features=["liga", "calt"],
            )
        except (TypeError, KeyError):
            # Pillow without libraqm (typical on Windows): no HarfBuzz shaping. Indic conjuncts
            # may not form correctly. For production-quality Indic rendering, run the backend in
            # a Linux container with libraqm0 installed.
            draw.text(
                (x, y_cursor),
                line,
                font=font,
                fill=(255, 255, 255, 255),
                stroke_width=stroke,
                stroke_fill=(0, 0, 0, 220),
            )
        y_cursor += int(line_h * line_height_mult)

    # Downsample with Lanczos
    final = img.resize((bbox_w, bbox_h), Image.LANCZOS)

    # Sanity check
    alpha = final.split()[3]
    nonzero = sum(1 for px in alpha.getdata() if px > 0)
    if nonzero < bbox_w * bbox_h * 0.001:
        raise RuntimeError(
            f"Rendered PNG is suspiciously sparse ({nonzero} px). Likely font load failure: {font_file}"
        )

    final.save(out_png, "PNG")
    chosen_px = chosen_size // SUPERSAMPLE
    log.info("Rendered text PNG %s size=(%d,%d) font_px=%d lines=%d",
             out_png.name, bbox_w, bbox_h, chosen_px, len(lines))
    return out_png, chosen_px
