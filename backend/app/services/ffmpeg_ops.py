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
    overlays: list[tuple[Path, tuple[int, int, int, int]]],
    out_mp4: Path,
) -> Path:
    """Single-pass render: blur original-text region(s), overlay translated PNG(s), replace
    audio with the localized voiceover.

    Audio: original video audio is dropped entirely. The translated voiceover is the only
    audio source — coerced to stereo 48 kHz and passed through `loudnorm` to land at -16
    LUFS / -1.5 dBTP (Meta/YouTube streaming spec). Encoded AAC stereo @ 48 kHz. This is
    the right default for ads whose source is voiceover-only with no music bed; if a future
    input has a music/SFX bed worth preserving, that's a separate code path (sidechain duck).

    `overlays` is a list of (text_png_path, (x, y, w, h)) pairs. When empty, no video filter
    graph is built and the original video stream is copied through.
    """
    out_mp4.parent.mkdir(parents=True, exist_ok=True)

    cmd: list[str] = [settings.FFMPEG_BIN, "-y", "-i", str(video_in), "-i", str(audio_in)]
    # Input indexing: [0]=video, [1]=audio, [2..]=overlay PNGs in order
    for png, _ in overlays:
        cmd += ["-i", str(png)]

    steps: list[str] = []

    # ── Video graph ───────────────────────────────────────────────────────
    if overlays:
        prev_label = "base"
        steps.append(f"[0:v]copy[{prev_label}]")
        for i, (_png, (x, y, w, h)) in enumerate(overlays):
            sigma = max(15, h // 8)
            blurred = f"blurred{i}"
            covered = f"covered{i}"
            steps.append(f"[0:v]crop={w}:{h}:{x}:{y},gblur=sigma={sigma}[{blurred}]")
            steps.append(f"[{prev_label}][{blurred}]overlay={x}:{y}[{covered}]")
            png_idx = i + 2
            withtext = f"withtext{i}"
            steps.append(
                f"[{covered}][{png_idx}:v]overlay="
                f"x={x}+({w}-overlay_w)/2:y={y}+({h}-overlay_h)/2:format=auto[{withtext}]"
            )
            prev_label = withtext
        video_map = f"[{prev_label}]"
    else:
        video_map = "0:v"

    # ── Audio graph ───────────────────────────────────────────────────────
    # Voiceover-only output (original audio dropped). Coerce to stereo 48k and run a single
    # `loudnorm` pass so loudness is consistent across jobs at the Meta/YouTube spec.
    fmt = "aformat=sample_fmts=fltp:sample_rates=48000:channel_layouts=stereo"
    steps.append(f"[1:a]{fmt},loudnorm=I=-16:TP=-1.5:LRA=11[aout]")

    cmd += [
        "-filter_complex", ";".join(steps),
        "-map", video_map, "-map", "[aout]",
        "-c:v", "libx264", "-preset", "medium", "-crf", "20",
        "-pix_fmt", "yuv420p", "-profile:v", "high", "-level", "4.1",
        "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-ac", "2",
        "-movflags", "+faststart",
        str(out_mp4),
    ]
    _run(cmd, timeout=900)

    # Validate that the output duration covers the source video length — `-shortest` is gone,
    # so a silent truncation by some upstream length mismatch is now a hard failure.
    expected_min = probe(video_in).duration_s - 0.3
    validate_video_output(out_mp4, expected_min_duration=expected_min)
    return out_mp4


def validate_video_output(path: Path, expected_min_duration: float | None = None) -> None:
    """Gate: FFmpeg can silently produce a container with no video stream. Reject those.

    When `expected_min_duration` is set, also reject outputs shorter than that — useful for
    catching cases where a length mismatch between inputs would have caused `-shortest` (or an
    amix=duration=shortest) to clip the result.
    """
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
    if expected_min_duration is not None and duration < expected_min_duration:
        raise FFmpegError(
            f"Output duration {duration:.2f}s is below expected minimum "
            f"{expected_min_duration:.2f}s — output was truncated: {path}"
        )


def replace_audio_only(video_in: Path, audio_in: Path, out_mp4: Path) -> Path:
    """Phase-1 fallback: replace audio without text overlay, used for CLI smoke tests."""
    return render_final(video_in, audio_in, [], out_mp4)


def composite_still(
    background_png: Path,
    overlays: list[tuple[Path, tuple[int, int, int, int]]],
    out_png: Path,
) -> Path:
    """Compose one or more translated-text PNGs onto an already-blurred background frame.

    Each entry is (png, (x, y, w, h)) — the PNG is centered inside the bbox.
    """
    out_png.parent.mkdir(parents=True, exist_ok=True)
    cmd: list[str] = [settings.FFMPEG_BIN, "-y", "-i", str(background_png)]
    for png, _ in overlays:
        cmd += ["-i", str(png)]

    if not overlays:
        cmd += ["-map", "0:v", "-frames:v", "1", str(out_png)]
        _run(cmd, timeout=30)
        return out_png

    steps: list[str] = []
    prev_label = "base"
    steps.append(f"[0:v]copy[{prev_label}]")
    for i, (_png, (x, y, w, h)) in enumerate(overlays):
        png_idx = i + 1
        out_label = f"o{i}"
        steps.append(
            f"[{prev_label}][{png_idx}:v]overlay="
            f"x={x}+({w}-overlay_w)/2:y={y}+({h}-overlay_h)/2:format=auto[{out_label}]"
        )
        prev_label = out_label

    cmd += [
        "-filter_complex", ";".join(steps),
        "-map", f"[{prev_label}]",
        "-frames:v", "1", str(out_png),
    ]
    _run(cmd, timeout=30)
    return out_png


def build_blurred_background_frame(
    frame_png: Path,
    bboxes: list[tuple[int, int, int, int]],
    out_png: Path,
) -> Path:
    """Pre-blur one or more bbox regions of a still frame and save it. Cached per-job."""
    out_png.parent.mkdir(parents=True, exist_ok=True)
    if not bboxes:
        # Nothing to blur — just copy the frame so callers can rely on out_png existing.
        cmd = [
            settings.FFMPEG_BIN, "-y", "-i", str(frame_png),
            "-frames:v", "1", str(out_png),
        ]
        _run(cmd, timeout=30)
        return out_png

    steps: list[str] = []
    prev_label = "base"
    steps.append(f"[0:v]copy[{prev_label}]")
    for i, (x, y, w, h) in enumerate(bboxes):
        sigma = max(15, h // 8)
        blurred = f"blurred{i}"
        covered = f"covered{i}"
        steps.append(f"[0:v]crop={w}:{h}:{x}:{y},gblur=sigma={sigma}[{blurred}]")
        steps.append(f"[{prev_label}][{blurred}]overlay={x}:{y}[{covered}]")
        prev_label = covered

    cmd = [
        settings.FFMPEG_BIN, "-y", "-i", str(frame_png),
        "-filter_complex", ";".join(steps),
        "-map", f"[{prev_label}]",
        "-frames:v", "1", str(out_png),
    ]
    _run(cmd, timeout=30)
    return out_png
