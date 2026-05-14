"""Sarvam Bulbul TTS — native Indian-language voiceover.

Mirrors the public interface of tts_elevenlabs.generate_voiceover so the rest of the
pipeline (chunking concat, duration matching, FFmpeg render) is unchanged.

Sarvam returns base64-encoded 22.05kHz WAV. We:
  1. Split text at sentence boundaries (Sarvam's per-request soft cap is ~500 chars)
  2. Call POST /text-to-speech for each chunk, decode base64 -> WAV
  3. Convert each WAV -> MP3 via FFmpeg (so the rest of the pipeline stays MP3-based)
  4. Concatenate MP3 chunks with 80ms crossfade
  5. Strip leading/trailing silence
  6. Adjust tempo with rubberband/atempo to land within [0.85, 1.18] of original duration
"""
from __future__ import annotations

import base64
import logging
import re
import shutil
import tempfile
from pathlib import Path

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential

from app.config import settings
from app.services.ffmpeg_ops import (
    FFmpegError,
    _run,
    probe_audio_duration,
    probe_ffmpeg_features,
    time_stretch,
)
from app.services.voice_catalog import get_language

log = logging.getLogger("ad_localizer.tts_sarvam")

_API = "https://api.sarvam.ai/text-to-speech"
_MODEL = "bulbul:v2"
_MAX_CHUNK_CHARS = 450  # safe under Sarvam's per-request soft cap of ~500

_ATEMPO_BAND = (0.93, 1.08)
_RUBBERBAND_BAND = (0.82, 1.22)


def _split_sentences(text: str) -> list[str]:
    """Sentence-ish split. Handles common Indic + English punctuation."""
    parts = re.split(r"(?<=[\.!\?।])\s+", text.strip())
    chunks: list[str] = []
    for part in parts:
        part = part.strip()
        if not part:
            continue
        if len(part) <= _MAX_CHUNK_CHARS:
            chunks.append(part)
        else:
            words = part.split()
            cur = ""
            for w in words:
                if len(cur) + len(w) + 1 > _MAX_CHUNK_CHARS:
                    chunks.append(cur.strip())
                    cur = w
                else:
                    cur = f"{cur} {w}".strip()
            if cur:
                chunks.append(cur.strip())
    return chunks


@retry(reraise=True, stop=stop_after_attempt(3), wait=wait_exponential(min=2, max=10))
async def _tts_chunk(text: str, language_code: str, speaker: str, out_mp3: Path) -> Path:
    if not settings.SARVAM_API_KEY:
        raise RuntimeError("SARVAM_API_KEY required for Sarvam TTS")
    lang = get_language(language_code)
    target_lang_code = lang["bcp47"]  # e.g., hi-IN, ta-IN

    payload = {
        "inputs": [text],
        "target_language_code": target_lang_code,
        "speaker": speaker,
        "model": _MODEL,
        "speech_sample_rate": 22050,
        "enable_preprocessing": True,
        "pitch": 0,
        "pace": 1.0,
        "loudness": 1.5,
    }
    headers = {
        "api-subscription-key": settings.SARVAM_API_KEY,
        "Content-Type": "application/json",
    }
    async with httpx.AsyncClient(timeout=120) as client:
        resp = await client.post(_API, json=payload, headers=headers)
    if resp.status_code != 200:
        raise RuntimeError(f"Sarvam {resp.status_code}: {resp.text[:400]}")

    body = resp.json()
    audios = body.get("audios") or []
    if not audios:
        raise RuntimeError(f"Sarvam returned no audio: {body}")
    wav_bytes = base64.b64decode(audios[0])

    out_mp3.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
        tmp.write(wav_bytes)
        tmp_path = Path(tmp.name)
    try:
        # WAV -> MP3 via FFmpeg, so downstream pipeline stays MP3
        _run([
            settings.FFMPEG_BIN, "-y", "-i", str(tmp_path),
            "-c:a", "libmp3lame", "-b:a", "192k",
            str(out_mp3),
        ], timeout=60)
    finally:
        tmp_path.unlink(missing_ok=True)

    if out_mp3.stat().st_size < 1024:
        raise RuntimeError(f"Sarvam->MP3 produced tiny file ({out_mp3.stat().st_size}b)")
    return out_mp3


def _expected_duration(text: str) -> float:
    """Heuristic: ~14 chars/sec average for natural ad reads."""
    return max(0.5, len(text) / 14.0)


def _concat_with_crossfade(chunks: list[Path], out_mp3: Path) -> Path:
    if len(chunks) == 1:
        shutil.copyfile(chunks[0], out_mp3)
        return out_mp3
    inputs: list[str] = []
    for c in chunks:
        inputs += ["-i", str(c)]
    n = len(chunks)
    parts: list[str] = []
    prev = "[0:a]"
    for i in range(1, n):
        out = f"[a{i}]"
        parts.append(f"{prev}[{i}:a]acrossfade=d=0.08:c1=tri:c2=tri{out}")
        prev = out
    filter_complex = ";".join(parts)
    cmd = [
        settings.FFMPEG_BIN, "-y", *inputs,
        "-filter_complex", filter_complex,
        "-map", prev,
        "-c:a", "libmp3lame", "-b:a", "192k",
        str(out_mp3),
    ]
    _run(cmd, timeout=120)
    return out_mp3


def _trim_silence(in_mp3: Path, out_mp3: Path) -> Path:
    cmd = [
        settings.FFMPEG_BIN, "-y", "-i", str(in_mp3),
        "-af",
        "silenceremove=start_periods=1:start_silence=0.2:start_threshold=-45dB:"
        "stop_periods=-1:stop_silence=0.2:stop_threshold=-45dB",
        "-c:a", "libmp3lame", "-b:a", "192k",
        str(out_mp3),
    ]
    _run(cmd, timeout=60)
    return out_mp3


async def generate_voiceover(
    text: str,
    language_code: str,
    target_seconds: float,
    out_mp3: Path,
    compact_text: str | None = None,
) -> tuple[Path, float]:
    """Generate localized voiceover, duration-matched to target_seconds within tolerance.

    Returns (final_mp3_path, final_duration_seconds).
    """
    lang = get_language(language_code)
    speaker = lang["voice_id"]  # voice_catalog stores the Sarvam speaker name here
    out_mp3.parent.mkdir(parents=True, exist_ok=True)

    features = probe_ffmpeg_features()
    has_rubberband = bool(features.get("librubberband"))

    async def _generate(script_text: str, tag: str) -> tuple[Path, float]:
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            chunks = _split_sentences(script_text)
            chunk_paths: list[Path] = []
            for i, chunk in enumerate(chunks):
                cp = tmp / f"chunk_{i:03d}.mp3"
                await _tts_chunk(chunk, language_code, speaker, cp)
                expected = _expected_duration(chunk)
                actual = probe_audio_duration(cp)
                if actual < expected * 0.5 or actual > expected * 3.0:
                    log.warning(
                        "[%s] chunk %d duration out of band (%.2fs vs ~%.2fs). Retrying.",
                        tag, i, actual, expected,
                    )
                    cp.unlink(missing_ok=True)
                    await _tts_chunk(chunk, language_code, speaker, cp)
                chunk_paths.append(cp)
            concatenated = tmp / "concat.mp3"
            _concat_with_crossfade(chunk_paths, concatenated)
            trimmed = tmp / "trimmed.mp3"
            _trim_silence(concatenated, trimmed)
            dur = probe_audio_duration(trimmed)
            final = out_mp3.with_name(out_mp3.stem + f"_{tag}.mp3")
            shutil.copyfile(trimmed, final)
            return final, dur

    natural_path, natural_dur = await _generate(text, "natural")
    ratio = natural_dur / target_seconds
    log.info("Sarvam natural duration ratio=%.3f (got %.2fs / target %.2fs)",
             ratio, natural_dur, target_seconds)

    chosen_path, chosen_dur = natural_path, natural_dur

    if (ratio < _RUBBERBAND_BAND[0] or ratio > _RUBBERBAND_BAND[1]) and compact_text:
        log.info("Ratio outside [%.2f,%.2f]; regenerating from compact variant.",
                 *_RUBBERBAND_BAND)
        compact_path, compact_dur = await _generate(compact_text, "compact")
        if abs(compact_dur - target_seconds) < abs(natural_dur - target_seconds):
            chosen_path, chosen_dur = compact_path, compact_dur

    final_ratio = chosen_dur / target_seconds
    if final_ratio < _ATEMPO_BAND[0] or final_ratio > _ATEMPO_BAND[1]:
        tempo = chosen_dur / target_seconds
        tempo = max(_RUBBERBAND_BAND[0], min(_RUBBERBAND_BAND[1], tempo))
        log.info("Applying time-stretch tempo=%.3f (rubberband=%s)", tempo, has_rubberband)
        try:
            time_stretch(chosen_path, out_mp3, tempo, has_rubberband)
        except FFmpegError:
            log.exception("time_stretch failed; using untouched audio")
            shutil.copyfile(chosen_path, out_mp3)
    else:
        shutil.copyfile(chosen_path, out_mp3)

    final_dur = probe_audio_duration(out_mp3)
    log.info("Final Sarvam voiceover: %.2fs (target %.2fs, ratio %.3f)",
             final_dur, target_seconds, final_dur / target_seconds)
    return out_mp3, final_dur
