"""Generate deterministic vertical cover art from an approved final video."""

from __future__ import annotations

import json
import math
import subprocess
from pathlib import Path


class CoverGenerationError(ValueError):
    """Raised when a readable video cannot produce a cover frame."""


def generate_cover(
    video_path: str | Path,
    output_path: str | Path,
    *,
    width: int = 768,
    height: int = 1344,
) -> dict:
    source = Path(video_path)
    output = Path(output_path)
    if not source.is_file():
        raise CoverGenerationError(f"Final video is missing: {source}")
    if width <= 0 or height <= 0:
        raise CoverGenerationError("Cover dimensions must be positive")
    duration = _duration(source)
    if duration <= 0:
        return {"status": "unavailable", "reason": "video duration is unreadable"}
    timestamp = min(max(duration * 0.18, 0.1), max(duration - 0.1, 0.0))
    output.parent.mkdir(parents=True, exist_ok=True)
    command = [
        "ffmpeg", "-ss", f"{timestamp:.6f}", "-i", str(source),
        "-frames:v", "1",
        "-vf", f"scale={width}:{height}:force_original_aspect_ratio=increase,crop={width}:{height}",
        "-q:v", "2", "-y", str(output),
    ]
    try:
        subprocess.run(command, capture_output=True, text=True, check=True, timeout=60)
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
        raise CoverGenerationError(f"Cover extraction failed: {exc}") from exc
    if not output.is_file() or output.stat().st_size <= 0:
        raise CoverGenerationError("FFmpeg produced an empty cover")
    return {
        "status": "ready",
        "path": str(output),
        "source": str(source),
        "timestamp_seconds": round(timestamp, 6),
        "width": width,
        "height": height,
        "selection": "hook_18_percent",
    }


def _duration(path: Path) -> float:
    try:
        result = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", str(path)],
            capture_output=True, text=True, check=True, timeout=30,
        )
        value = float(result.stdout.strip())
        return value if math.isfinite(value) and value > 0 else 0.0
    except (OSError, ValueError, subprocess.SubprocessError):
        return 0.0
