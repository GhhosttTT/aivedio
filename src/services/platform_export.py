"""Quality-gated, reproducible platform export presets."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from src.services.video_quality_metrics import temporal_sample_evidence_error, video_candidate_metrics
from src.config import settings


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


def _validate_source_approval(source: Path, approval_report: dict | None) -> None:
    """Require the platform export to be derived from the reviewed master."""
    if not isinstance(approval_report, dict):
        raise PlatformExportError(
            "Final composition approval evidence is required before platform export"
        )
    human_approved = (
        approval_report.get("status") in {"needs_review", "review_unavailable"}
        and isinstance(approval_report.get("human_decision"), dict)
        and approval_report["human_decision"].get("decision") == "approved"
    )
    if approval_report.get("status") != "passed" and not human_approved:
        raise PlatformExportError("Final composition review is not approved for platform export")
    if Path(str(approval_report.get("video_path") or "")).resolve() != source.resolve():
        raise PlatformExportError("Final composition review points to a different source video")
    if approval_report.get("video_sha256") != _sha256(source):
        raise PlatformExportError("Final composition review is stale for the current source video")
    technical = approval_report.get("final_technical_metrics")
    if (
        not isinstance(technical, dict)
        or technical.get("status") != "available"
        or technical.get("temporal_sample_evidence") != "sufficient"
    ):
        raise PlatformExportError(
            "Final composition technical evidence is missing or insufficient for platform export"
        )
    if approval_report.get("final_audio_expected") is True and (
        technical.get("audio_signal_status") != "usable"
        or technical.get("audio_quality_status") != "passed"
    ):
        raise PlatformExportError("Final composition native-audio evidence is missing or failed")


def export_platform_video(
    final_video_path: str | Path,
    project_root: str | Path,
    preset: str,
    *,
    approval_report: dict | None = None,
) -> dict:
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
    _validate_source_approval(source, approval_report)
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
            and cached["technical_metrics"].get("temporal_sample_evidence") == "sufficient"
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

    source_metrics = video_candidate_metrics(source, max_samples=8)
    technical_metrics = video_candidate_metrics(output, max_samples=8)
    _validate_export_metrics(technical_metrics, config, output, source_metrics=source_metrics)

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
        "source_technical_metrics": source_metrics,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    _write_json(manifest_path, result)
    return result


def _validate_export_metrics(
    metrics: dict,
    config: dict,
    output: Path,
    *,
    source_metrics: dict | None = None,
) -> None:
    """Reject an export unless its decoded media honors the preset contract."""
    if not isinstance(metrics, dict) or metrics.get("status") != "available":
        detail = metrics.get("error") if isinstance(metrics, dict) else None
        raise PlatformExportError(
            "Platform export could not be decoded for technical validation"
            + (f": {detail}" if detail else "")
        )
    temporal_error = temporal_sample_evidence_error(metrics, context="Platform export")
    if temporal_error:
        raise PlatformExportError(temporal_error)
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
    max_black_run = float(metrics.get("max_black_run_seconds") or 0.0)
    if max_black_run > settings.GENERATION_VIDEO_MAX_BLACK_SECONDS:
        raise PlatformExportError(
            f"Platform export contains a black-frame run of {max_black_run:.3f}s"
        )
    black_frame_ratio = metrics.get("black_frame_ratio")
    if (
        isinstance(black_frame_ratio, (int, float))
        and black_frame_ratio > settings.GENERATION_VIDEO_MAX_BLACK_FRAME_RATIO
    ):
        raise PlatformExportError(
            "Platform export contains too many black frames: "
            f"black_frame_ratio={black_frame_ratio:.3f}, "
            f"limit={settings.GENERATION_VIDEO_MAX_BLACK_FRAME_RATIO:.3f}"
        )
    temporal_jump_ratio = metrics.get("temporal_jump_ratio")
    if (
        isinstance(temporal_jump_ratio, (int, float))
        and temporal_jump_ratio > settings.GENERATION_VIDEO_MAX_TEMPORAL_JUMP_RATIO
    ):
        raise PlatformExportError(
            "Platform export contains repeated temporal visual resets: "
            f"temporal_jump_ratio={temporal_jump_ratio:.3f}, "
            f"limit={settings.GENERATION_VIDEO_MAX_TEMPORAL_JUMP_RATIO:.3f}"
        )
    temporal_jump_p95 = metrics.get("temporal_jump_p95")
    if (
        isinstance(temporal_jump_p95, (int, float))
        and temporal_jump_p95 > settings.GENERATION_VIDEO_MAX_TEMPORAL_JUMP_P95
    ):
        raise PlatformExportError(
            "Platform export contains an extreme temporal visual reset: "
            f"temporal_jump_p95={temporal_jump_p95:.3f}, "
            f"limit={settings.GENERATION_VIDEO_MAX_TEMPORAL_JUMP_P95:.3f}"
        )
    motion_jitter_ratio = metrics.get("motion_jitter_ratio")
    if (
        isinstance(motion_jitter_ratio, (int, float))
        and motion_jitter_ratio > settings.GENERATION_VIDEO_MAX_MOTION_JITTER_RATIO
    ):
        raise PlatformExportError(
            "Platform export has unstable motion cadence: "
            f"motion_jitter_ratio={motion_jitter_ratio:.3f}, "
            f"limit={settings.GENERATION_VIDEO_MAX_MOTION_JITTER_RATIO:.3f}"
        )
    brightness_step_p95 = metrics.get("brightness_step_p95")
    if (
        isinstance(brightness_step_p95, (int, float))
        and brightness_step_p95 > settings.GENERATION_VIDEO_MAX_BRIGHTNESS_STEP_P95
    ):
        raise PlatformExportError(
            "Platform export has temporal exposure jumps: "
            f"brightness_step_p95={brightness_step_p95:.3f}, "
            f"limit={settings.GENERATION_VIDEO_MAX_BRIGHTNESS_STEP_P95:.3f}"
        )
    if metrics.get("audio_present") and metrics.get("audio_signal_status") != "usable":
        raise PlatformExportError(
            "Platform export audio signal is not usable: "
            f"{metrics.get('audio_signal_status') or 'unavailable'}"
        )
    if metrics.get("audio_present") and metrics.get("audio_clipping_status") == "clipped":
        raise PlatformExportError("Platform export audio signal is clipped at digital full scale")
    audio_rms_db = metrics.get("audio_rms_db")
    if metrics.get("audio_present") and isinstance(audio_rms_db, (int, float)):
        if audio_rms_db < settings.GENERATION_VIDEO_AUDIO_RMS_MIN_DB:
            raise PlatformExportError(
                "Platform export audio mix is too quiet: "
                f"audio_rms_db={audio_rms_db:.2f}, minimum="
                f"{settings.GENERATION_VIDEO_AUDIO_RMS_MIN_DB:.2f}"
            )
        if audio_rms_db > settings.GENERATION_VIDEO_AUDIO_RMS_MAX_DB:
            raise PlatformExportError(
                "Platform export audio mix is too loud: "
                f"audio_rms_db={audio_rms_db:.2f}, maximum="
                f"{settings.GENERATION_VIDEO_AUDIO_RMS_MAX_DB:.2f}"
            )
    audio_start_delta = metrics.get("audio_video_start_delta_seconds")
    if (
        metrics.get("audio_present")
        and isinstance(audio_start_delta, (int, float))
        and abs(float(audio_start_delta)) > settings.GENERATION_VIDEO_AUDIO_SYNC_TOLERANCE_SECONDS
    ):
        raise PlatformExportError(
            "Platform export audio/video start offset is out of sync: "
            f"{float(audio_start_delta):.3f}s; "
            f"limit={settings.GENERATION_VIDEO_AUDIO_SYNC_TOLERANCE_SECONDS:.3f}s"
        )
    if isinstance(source_metrics, dict) and source_metrics.get("status") == "available":
        source_duration = float(source_metrics.get("duration_seconds") or 0.0)
        output_duration = float(metrics.get("duration_seconds") or 0.0)
        if source_duration > 0:
            tolerance = max(
                settings.GENERATION_VIDEO_DURATION_SYNC_TOLERANCE_SECONDS,
                source_duration * 0.08,
            )
            if abs(output_duration - source_duration) > tolerance:
                raise PlatformExportError(
                    f"Platform export duration drifted to {output_duration:.3f}s; "
                    f"source is {source_duration:.3f}s"
                )
        if bool(metrics.get("audio_present")) != bool(source_metrics.get("audio_present")):
            raise PlatformExportError("Platform export changed source audio presence")
        source_peak = source_metrics.get("audio_peak_db")
        output_peak = metrics.get("audio_peak_db")
        if (
            source_metrics.get("audio_present")
            and isinstance(source_peak, (int, float))
            and isinstance(output_peak, (int, float))
            and abs(float(output_peak) - float(source_peak)) > settings.GENERATION_VIDEO_BASELINE_MAX_AUDIO_PEAK_DELTA_DB
        ):
            raise PlatformExportError(
                "Platform export audio level drifted by "
                f"{abs(float(output_peak) - float(source_peak)):.3f}dB"
            )
