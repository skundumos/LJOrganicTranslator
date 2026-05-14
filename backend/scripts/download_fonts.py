"""Download all required Noto Sans fonts into backend/app/fonts/.

These are Google's official variable fonts (wdth + wght axes in a single TTF).
We save them with -Bold.ttf suffix to match the filenames in voice_catalog.py;
the text_renderer locks the wght axis to 700 at load time, giving the Bold weight.

Run from anywhere:
    python backend/scripts/download_fonts.py
"""
from __future__ import annotations

import sys
import urllib.parse
import urllib.request
from pathlib import Path

FONTS_DIR = Path(__file__).resolve().parent.parent / "app" / "fonts"

# (folder_in_google_fonts_repo, FontFamilyName, target_filename_in_app)
FONTS: list[tuple[str, str, str]] = [
    ("notosans",            "NotoSans",            "NotoSans-Bold.ttf"),
    ("notosansdevanagari",  "NotoSansDevanagari",  "NotoSansDevanagari-Bold.ttf"),
    ("notosanstamil",       "NotoSansTamil",       "NotoSansTamil-Bold.ttf"),
    ("notosanstelugu",      "NotoSansTelugu",      "NotoSansTelugu-Bold.ttf"),
    ("notosanskannada",     "NotoSansKannada",     "NotoSansKannada-Bold.ttf"),
    ("notosansmalayalam",   "NotoSansMalayalam",   "NotoSansMalayalam-Bold.ttf"),
    ("notosansbengali",     "NotoSansBengali",     "NotoSansBengali-Bold.ttf"),
    ("notosansgujarati",    "NotoSansGujarati",    "NotoSansGujarati-Bold.ttf"),
    ("notosansgurmukhi",    "NotoSansGurmukhi",    "NotoSansGurmukhi-Bold.ttf"),
]


def url_for(folder: str, family: str) -> str:
    # Variable font filename in google/fonts is FamilyName[wdth,wght].ttf
    filename = f"{family}[wdth,wght].ttf"
    encoded = urllib.parse.quote(filename)
    return f"https://github.com/google/fonts/raw/main/ofl/{folder}/{encoded}"


def download(url: str, dest: Path) -> bool:
    if dest.exists() and dest.stat().st_size > 10_000:
        print(f"[skip] {dest.name} ({dest.stat().st_size // 1024} KB, already present)")
        return True
    req = urllib.request.Request(url, headers={"User-Agent": "ad-localizer-font-fetch"})
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            data = r.read()
    except Exception as e:
        print(f"[FAIL] {dest.name}: {e}")
        return False
    if len(data) < 10_000:
        print(f"[FAIL] {dest.name}: only {len(data)} bytes (likely a 404 page)")
        return False
    dest.write_bytes(data)
    print(f"[ok]   {dest.name} ({len(data) // 1024} KB)")
    return True


def main() -> int:
    FONTS_DIR.mkdir(parents=True, exist_ok=True)
    print(f"Target: {FONTS_DIR}")
    failures = 0
    for folder, family, target in FONTS:
        if not download(url_for(folder, family), FONTS_DIR / target):
            failures += 1
    if failures:
        print(f"\n{failures} font(s) failed. Re-run; or download manually from "
              "https://fonts.google.com/noto and drop the variable TTFs into the fonts dir.")
        return 1
    print(f"\nAll {len(FONTS)} fonts ready.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
