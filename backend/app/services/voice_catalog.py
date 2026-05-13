"""Curated ElevenLabs voice IDs per supported language.

These voice IDs are picked from the ElevenLabs library for natural Indian-ad delivery
on the eleven_multilingual_v2 model. ElevenLabs occasionally deprecates voices silently;
the startup probe in pipeline.py verifies each ID still resolves.

Language codes are kept short and stable (used in DB rows + frontend URL params).
"""
from __future__ import annotations

from typing import TypedDict


class LanguageMeta(TypedDict):
    code: str
    display_name: str
    native_name: str
    voice_id: str
    voice_gender: str
    expansion_factor: float          # avg char-length expansion vs English
    bcp47: str                        # for Pillow text shaping
    noto_font: str                    # filename in backend/app/fonts/


# Default voice = "Rachel" tuned multilingual. Swap voice_ids per project preference.
# These are real, public ElevenLabs voice IDs that support multilingual_v2.
_DEFAULT_FEMALE = "21m00Tcm4TlvDq8ikWAM"   # Rachel (multilingual, warm)
_DEFAULT_MALE = "TxGEqnHWrfWFTfGW9XjX"     # Josh (multilingual, energetic)

LANGUAGES: list[LanguageMeta] = [
    {
        "code": "hi", "display_name": "Hindi", "native_name": "हिन्दी",
        "voice_id": _DEFAULT_FEMALE, "voice_gender": "female",
        "expansion_factor": 1.15, "bcp47": "hi-IN", "noto_font": "NotoSansDevanagari-Bold.ttf",
    },
    {
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
