"""Curated Sarvam Bulbul speakers per supported language.

Sarvam Bulbul v2 ships native Indian voices that work across all supported Indian
languages on the bulbul:v2 model. Anushka is a warm female voice well-suited to
Instagram-style direct-to-camera ad delivery. Swap per language as preference dictates.

Bulbul v2 speakers (as of 2026):
  Female: anushka, manisha, vidya, arya
  Male:   abhilash, karun, hitesh

The `voice_id` field stores the Sarvam speaker name (not an ElevenLabs UUID anymore).
The `bcp47` code is the `target_language_code` parameter passed to Sarvam's API.
"""
from __future__ import annotations

from typing import TypedDict


class LanguageMeta(TypedDict):
    code: str
    display_name: str
    native_name: str
    voice_id: str                     # Sarvam speaker name (e.g., "anushka")
    voice_gender: str
    expansion_factor: float           # avg char-length expansion vs English
    bcp47: str                        # target_language_code for Sarvam API + Pillow shaping
    noto_font: str                    # filename in backend/app/fonts/


_DEFAULT_FEMALE = "anushka"  # warm conversational, ad-style
_DEFAULT_MALE = "abhilash"

LANGUAGES: list[LanguageMeta] = [
    {
        "code": "hi", "display_name": "Hindi", "native_name": "हिन्दी",
        "voice_id": _DEFAULT_FEMALE, "voice_gender": "female",
        "expansion_factor": 1.15, "bcp47": "hi-IN", "noto_font": "NotoSansDevanagari-Bold.ttf",
    },
    {
        # Hinglish: Sarvam doesn't have a dedicated code-mixed code. en-IN handles English
        # words with Indian accent and tolerates Romanized Hindi inserts reasonably.
        "code": "hinglish", "display_name": "Hinglish", "native_name": "Hinglish",
        "voice_id": _DEFAULT_FEMALE, "voice_gender": "female",
        "expansion_factor": 1.05, "bcp47": "en-IN", "noto_font": "NotoSans-Bold.ttf",
    },
    {
        "code": "ta", "display_name": "Tamil", "native_name": "தமிழ்",
        "voice_id": _DEFAULT_FEMALE, "voice_gender": "female",
        "expansion_factor": 1.30, "bcp47": "ta-IN", "noto_font": "NotoSansTamil-Bold.ttf",
    },
    {
        "code": "te", "display_name": "Telugu", "native_name": "తెలుగు",
        "voice_id": _DEFAULT_FEMALE, "voice_gender": "female",
        "expansion_factor": 1.25, "bcp47": "te-IN", "noto_font": "NotoSansTelugu-Bold.ttf",
    },
    {
        "code": "kn", "display_name": "Kannada", "native_name": "ಕನ್ನಡ",
        "voice_id": _DEFAULT_FEMALE, "voice_gender": "female",
        "expansion_factor": 1.25, "bcp47": "kn-IN", "noto_font": "NotoSansKannada-Bold.ttf",
    },
    {
        "code": "ml", "display_name": "Malayalam", "native_name": "മലയാളം",
        "voice_id": _DEFAULT_FEMALE, "voice_gender": "female",
        "expansion_factor": 1.35, "bcp47": "ml-IN", "noto_font": "NotoSansMalayalam-Bold.ttf",
    },
    {
        "code": "mr", "display_name": "Marathi", "native_name": "मराठी",
        "voice_id": _DEFAULT_FEMALE, "voice_gender": "female",
        "expansion_factor": 1.18, "bcp47": "mr-IN", "noto_font": "NotoSansDevanagari-Bold.ttf",
    },
    {
        "code": "bn", "display_name": "Bengali", "native_name": "বাংলা",
        "voice_id": _DEFAULT_FEMALE, "voice_gender": "female",
        "expansion_factor": 1.20, "bcp47": "bn-IN", "noto_font": "NotoSansBengali-Bold.ttf",
    },
    {
        "code": "gu", "display_name": "Gujarati", "native_name": "ગુજરાતી",
        "voice_id": _DEFAULT_FEMALE, "voice_gender": "female",
        "expansion_factor": 1.18, "bcp47": "gu-IN", "noto_font": "NotoSansGujarati-Bold.ttf",
    },
    {
        "code": "pa", "display_name": "Punjabi", "native_name": "ਪੰਜਾਬੀ",
        "voice_id": _DEFAULT_FEMALE, "voice_gender": "female",
        "expansion_factor": 1.15, "bcp47": "pa-IN", "noto_font": "NotoSansGurmukhi-Bold.ttf",
    },
]


def get_language(code: str) -> LanguageMeta:
    for lang in LANGUAGES:
        if lang["code"] == code:
            return lang
    raise ValueError(f"Unsupported language: {code}")


def language_codes() -> list[str]:
    return [lang["code"] for lang in LANGUAGES]
