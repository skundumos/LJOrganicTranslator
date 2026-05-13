"""FFmpeg / ffprobe operations. All commands are subprocess.run wrappers with structured logging
and explicit output validation (FFmpeg can produce a valid container with no video stream on
silent failures, so every render is gated by ffprobe).
"""
from __future__ import annotations

import json
import logging
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from app.config import settings

log = logging.getLogger("ad_localizer.ffmpeg")


class FFmpegError(RuntimeError):
    pass


@dataclass(frozen=True)
class VideoMeta:
    duration_s: float
    width: int
    height: int
    fps: float


def _run(cmd: list[str], timeout: int = 600) -> subprocess.CompletedProcess:
    log.info("RUN: %s", " ".join(cmd))
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    if proc.returncode != 0:
        log.error("FFmpeg failed (rc=%s): %s", proc.returncode, proc.stderr[-2000:])
        raise FFmpegError(f"ffmpeg returned {proc.returncode}: {proc.stderr[-500:]}")
    return proc


def probe_ffmpeg_features() -> dict:
    bin_path = shutil.which(settings.FFMPEG_BIN) or settings.FFMPEG_BIN
    try:
        proc = subprocess.run([bin_path, "-hide_banner", "-buildconf"], capture_output=True, text=True)
        out = (proc.stdout + proc.stderr).lower()
        return {
            "ffmpeg_path": bin_path,
            "libx264": "libx264" in out or "--enable-libx264" in out,
            "librubberband": "librubberband" in out or "--enable-librubberband" in out,
            "libfreetype": "libfreetype" in out or "--enable-libfreetype" in out,
            "version_line": out.splitlines()[0] if out else "",
        }
    except FileNotFoundError:
        return {"ffmpeg_path": None, "libx264": False, "librubberband": False, "libfreetype": False}


def probe(path: Path) -> VideoMeta:
    cmd = [
        settings.FFPROBE_BIN, "-v", "error",
        "-select_streams", "v:0",
        "-show_entries", "stream=width,height,r_frame_rate:format=duration",
        "-of", "json",
        str(path),
    ]
    proc = _run(cmd, timeout=30)
    data = json.loads(proc.stdout)
    stream = data["streams"][0]
    num, den = stream["r_frame_rate"].split("/")
    fps = float(num) / float(den) if float(den) else 30.0
    duration = float(data["format"]["duration"])
    return VideoMeta(duration_s=duration, width=int(stream["width"]), height=int(stream["height"]), fps=fps)


def probe_audio_duration(path: Path) -> float:
    cmd = [
        settings.FFPROBE_BIN, "-v", "error",
        "-show_entries", "format=duration", "-of", "json", str(path),
    ]
    proc = _run(cmd, timeout=30)
    return float(json.loads(proc.stdout)["format"]["duration"])


def extract_audio(video_path: Path, out_wav: Path) -> Path:
    out_wav.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        settings.FFMPEG_BIN, "-y", "-i", str(video_path),
        "-vn", "-acodec", "pcm_s16le", "-ar", "16000", "-ac", "1",
        str(out_wav),
    ]
    _run(cmd, timeout=300)
    return out_wav


def extract_frame(video_path: Path, t_seconds: float, out_png: Path) -> Path:
    out_png.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        settings.FFMPEG_BIN, "-y", "-ss", f"{t_seconds:.3f}", "-i", str(video_path),
        "-frames:v", "1", "-q:v", "2",
        str(out_png),
    ]
    _run(cmd, timeout=60)
    if not out_png.exists() or out_png.stat().st_size < 1024:
        raise FFmpegError(f"Frame extraction produced empty file: {out_png}")
    return out_png


def time_stretch(
    in_audio: Path, out_audio: Path, tempo: float, has_rubberband: bool
) -> Path:
    """Stretch/compress audio. tempo > 1 = faster, < 1 = slower."""
    out_audio.parent.mkdir(parents=True, exist_ok=True)
    if abs(tempo - 1.0) < 0.01:
        shutil.copyfile(in_audio, out_audio)
        return out_audio
    if has_rubberband and (tempo < 0.93 or tempo > 1.08):
        af = f"rubberband=tempo={tempo:.4f}:pitchq=quality"
    else:
        # atempo is clamped per filter to [0.5, 2.0]; chain if outside range.
        t = max(0.5, min(2.0, tempo))
        af = f"atempo={t:.4f}"
    cmd = [
        settings.FFMPEG_BIN, "-y", "-i", str(in_audio),
        "-af", af, "-acodec", "libmp3lame", "-b:a", "192k",
        str(out_audio),
    ]
    _run(cmd, timeout=120)
    return out_audio


def render_final(
    video_in: Path,
    audio_in: Path,
    text_png: Path | None,
    bbox: tuple[int, int, int, int] | None,
    out_mp4: Path,
) -> Path:
    """Single-pass render: blur original-text region, overlay translated PNG, replace audio.

    If bbox or text_png is None, skips the blur+overlay and just replaces audio.
    """
    out_mp4.parent.mkdir(parents=True, exist_ok=True)

    cmd: list[str] = [settings.FFMPEG_BIN, "-y", "-i", str(video_in), "-i", str(audio_in)]
    if text_png is not None and bbox is not None:
        x, y, w, h = bbox
        sigma = max(15, h // 8)
        cmd += ["-i", str(text_png)]
        filter_complex = (
            f"[0:v]split=2[base][region];"
            f"[region]crop={w}:{h}:{x}:{y},gblur=sigma={sigma}[blurred];"
            f"[base][blurred]overlay={x}:{y}[covered];"
            f"[covered][2:v]overlay=x={x}+({w}-overlay_w)/2:y={y}+({h}-overlay_h)/2:format=auto[outv]"
        )
        cmd += [
            "-filter_complex", filter_complex,
            "-map", "[outv]", "-map", "1:a",
        ]
    else:
        cmd += ["-map", "0:v", "-map", "1:a"]

    cmd += [
        "-c:v", "libx264", "-preset", "medium", "-crf", "20",
        "-pix_fmt", "yuv420p", "-profile:v", "high", "-level", "4.1",
        "-c:a", "aac", "-b:a", "192k",
        "-movflags", "+faststart", "-shortest",
        str(out_mp4),
    ]
    _run(cmd, timeout=900)
    validate_video_output(out_mp4)
    return out_mp4


def validate_video_output(path: Path) -> None:
    """Gate: FFmpeg can silently produce a container with no video stream. Reject those."""
    if not path.exists() or path.stat().st_size < 4096:
        raise FFmpegError(f"Output too small or missing: {path}")
    cmd = [
        settings.FFPROBE_BIN, "-v", "error",
        "-select_streams", "v:0",
        "-show_entries", "stream=codec_name,nb_frames:format=duration",
        "-of", "json", str(path),
    ]
    proc = _run(cmd, timeout=30)
    data = json.loads(proc.stdout)
    if not data.get("streams"):
        raise FFmpegError(f"Output has no video stream: {path}")
    duration = float(data.get("format", {}).get("duration", 0))
    if duration < 0.5:
        raise FFmpegError(f"Output duration suspiciously short ({duration:.2f}s): {path}")


def replace_audio_only(video_in: Path, audio_in: Path, out_mp4: Path) -> Path:
    """Phase-1 fallback: replace audio without text overlay, used for CLI smoke tests."""
    return render_final(video_in, audio_in, None, None, out_mp4)


def composite_still(
    background_png: Path, text_png: Path, bbox: tuple[int, int, int, int], out_png: Path
) -> Path:
    """Compose translated text onto an already-blurred background frame. Used for live preview."""
    out_png.parent.mkdir(parents=True, exist_ok=True)
    x, y, w, h = bbox
    filter_complex = (
        f"[0:v][1:v]overlay=x={x}+({w}-overlay_w)/2:y={y}+({h}-overlay_h)/2:format=auto[outv]"
    )
    cmd = [
        settings.FFMPEG_BIN, "-y", "-i", str(background_png), "-i", str(text_png),
        "-filter_complex", filter_complex, "-map", "[outv]",
        "-frames:v", "1", str(out_png),
    ]
    _run(cmd, timeout=30)
    return out_png


def build_blurred_background_frame(
    frame_png: Path, bbox: tuple[int, int, int, int], out_png: Path
) -> Path:
    """Pre-blur the bbox region of a still frame and save it. Cached per-job for fast previews."""
    out_png.parent.mkdir(parents=True, exist_ok=True)
    x, y, w, h = bbox
    sigma = max(15, h // 8)
    filter_complex = (
        f"[0:v]split=2[base][region];"
        f"[region]crop={w}:{h}:{x}:{y},gblur=sigma={sigma}[blurred];"
        f"[base][blurred]overlay={x}:{y}[outv]"
    )
    cmd = [
        settings.FFMPEG_BIN, "-y", "-i", str(frame_png),
        "-filter_complex", filter_complex, "-map", "[outv]",
        "-frames:v", "1", str(out_png),
    ]
    _run(cmd, timeout=30)
    return out_png
