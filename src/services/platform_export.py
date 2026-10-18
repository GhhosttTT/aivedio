"""Quality-gated, reproducible platform export presets."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from src.services.video_quality_metrics import video_candidate_metrics


PLATFORM_EXPORT_PRESETS = {
    "douyin": {"label": "抖音竖屏", "width": 1080, "height": 1920, "fps": 30},
    "shorts": {"label": "YouTube Shorts / Reels", "width": 1080, "height": 1920, "fps": 30},
    "landscape": {"label": "横屏 16:9", "width": 1920, "height": 1080, "fps": 30},
    "square": {"label": "方形 1:1", "width": 1080, "height": 1080, "fps": 30},
}


class PlatformExportError(ValueError):
    """Raised when a platform export cannot be produced."""


def _signature(path: Path) -> str | None:
    try:
        stat = path.stat()
    except OSError:
        return None
    return f"{path.resolve()}:{stat.st_size}:{stat.st_mtime_ns}"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(payload, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
        os.replace(temp_name, path)
    finally:
        if os.path.exists(temp_name):
            os.unlink(temp_name)


def export_platform_video(final_video_path: str | Path, project_root: str | Path, preset: str) -> dict:
    """Export a final video with a fixed geometry/audio contract.

    The source is never modified. A manifest makes repeated requests idempotent
    and invalidates an export automatically when the final video changes.
    """
    config = PLATFORM_EXPORT_PRESETS.get(str(preset).strip().lower())
    if config is None:
        raise PlatformExportError(f"Unknown platform export preset: {preset}")
    source = Path(final_video_path)
    if not source.is_file() or source.stat().st_size <= 0:
        raise PlatformExportError("Final video is missing or empty")
    root = Path(project_root).resolve()
    export_dir = root / "exports"
    output = export_dir / f"{str(preset).strip().lower()}.mp4"
    manifest_path = export_dir / f"{str(preset).strip().lower()}.json"
    source_version = _signature(source)
    source_sha256 = _sha256(source)

    if output.is_file() and manifest_path.is_file():
        try:
            cached = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            cached = {}
        if (
            isinstance(cached, dict)
            and cached.get("source_signature") == source_version
            and cached.get("source_sha256") == source_sha256
            and cached.get("output_signature") == _signature(output)
            and cached.get("output_sha256") == _sha256(output)
            and isinstance(cached.get("technical_metrics"), dict)
            and cached["technical_metrics"].get("status") == "available"
        ):
            return cached

    export_dir.mkdir(parents=True, exist_ok=True)
    temporary = export_dir / f".{output.stem}.tmp.mp4"
    width, height, fps = config["width"], config["height"], config["fps"]
    vf = (
        f"scale={width}:{height}:force_original_aspect_ratio=increase,"
        f"crop={width}:{height}:(iw-ow)/2:(ih-oh)/2,setsar=1,fps={fps},format=yuv420p"
    )
    command = [
        "ffmpeg", "-v", "error", "-y", "-i", str(source),
        "-map", "0:v:0", "-map", "0:a?", "-vf", vf,
        "-c:v", "libx264", "-preset", "slow", "-crf", "18",
        "-c:a", "aac", "-b:a", "192k", "-af", "loudnorm=I=-14:TP=-1.5:LRA=11",
        "-movflags", "+faststart", str(temporary),
    ]
    try:
        subprocess.run(command, check=True, capture_output=True, text=True, timeout=900)
        if not temporary.is_file() or temporary.stat().st_size <= 0:
            raise PlatformExportError("FFmpeg produced an empty platform export")
        os.replace(temporary, output)
    except subprocess.CalledProcessError as exc:
        raise PlatformExportError(f"Platform export failed: {exc.stderr or exc}") from exc
    finally:
        temporary.unlink(missing_ok=True)

    technical_metrics = video_candidate_metrics(output, max_samples=8)
    _validate_export_metrics(technical_metrics, config, output)

    result = {
        "status": "ready",
        "preset": str(preset).strip().lower(),
        "label": config["label"],
        "width": width,
        "height": height,
        "fps": fps,
        "source_path": str(source),
        "source_signature": source_version,
        "source_sha256": source_sha256,
        "output_path": str(output),
        "output_signature": _signature(output),
        "output_sha256": _sha256(output),
        "technical_metrics": technical_metrics,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    _write_json(manifest_path, result)
    return result


def _validate_export_metrics(metrics: dict, config: dict, output: Path) -> None:
    """Reject an export unless its decoded media honors the preset contract."""
    if not isinstance(metrics, dict) or metrics.get("status") != "available":
        detail = metrics.get("error") if isinstance(metrics, dict) else None
        raise PlatformExportError(
            "Platform export could not be decoded for technical validation"
            + (f": {detail}" if detail else "")
        )
    actual_width = int(metrics.get("width") or 0)
    actual_height = int(metrics.get("height") or 0)
    if actual_width != int(config["width"]) or actual_height != int(config["height"]):
        raise PlatformExportError(
            f"Platform export geometry drifted to {actual_width}x{actual_height}; "
            f"expected {config['width']}x{config['height']}"
        )
    actual_fps = float(metrics.get("fps") or 0.0)
    if abs(actual_fps - float(config["fps"])) > 0.5:
        raise PlatformExportError(
            f"Platform export frame rate drifted to {actual_fps:g}fps; expected {config['fps']}fps"
        )
    if float(metrics.get("duration_seconds") or 0.0) <= 0:
        raise PlatformExportError(f"Platform export has no positive duration: {output}")
