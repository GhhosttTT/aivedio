"""Technical quality metrics for generated video candidates."""

from __future__ import annotations

import json
import math
import subprocess
from pathlib import Path
from typing import Any


def video_candidate_metrics(path: str | Path, max_samples: int = 12) -> dict[str, Any]:
    """Return bounded, local technical metrics for one candidate clip.

    These metrics are a ranking signal only. VLM and human review remain the
    authority for story meaning, acting quality, identity, and taste.
    """

    video_path = Path(path)
    try:
        cv2, np = _load_cv2_numpy()
        probe = _probe(video_path)
        frames = _sample_frames(video_path, max_samples, cv2, np)
        gray_frames = [cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY) for frame in frames]
        motion_values = [
            float(np.mean(cv2.absdiff(gray_frames[index], gray_frames[index - 1])))
            for index in range(1, len(gray_frames))
        ]
        sharpness_values = [float(cv2.Laplacian(gray, cv2.CV_64F).var()) for gray in gray_frames]
        brightness_values = [float(np.mean(gray)) for gray in gray_frames]
        motion_energy = float(np.mean(motion_values)) if motion_values else 0.0
        sharpness = float(np.mean(sharpness_values)) if sharpness_values else 0.0
        brightness = float(np.mean(brightness_values)) if brightness_values else 0.0
        brightness_variance = float(np.var(brightness_values)) if brightness_values else 0.0
        metrics = {
            "status": "available",
            "path": str(video_path),
            "duration_seconds": round(float(probe["duration_seconds"]), 3),
            "width": int(probe["width"]),
            "height": int(probe["height"]),
            "fps": round(float(probe["fps"]), 3),
            "sampled_frames": len(frames),
            "motion_energy": round(motion_energy, 3),
            "sharpness": round(sharpness, 3),
            "brightness": round(brightness, 3),
            "brightness_variance": round(brightness_variance, 3),
        }
        metrics["technical_score"] = video_technical_score(metrics)
        return metrics
    except Exception as exc:
        return {
            "status": "unavailable",
            "path": str(video_path),
            "technical_score": None,
            "error": str(exc),
        }


def video_technical_score(metrics: dict[str, Any]) -> float:
    duration = float(metrics.get("duration_seconds") or 0.0)
    width = int(metrics.get("width") or 0)
    height = int(metrics.get("height") or 0)
    fps = float(metrics.get("fps") or 0.0)
    sampled_frames = int(metrics.get("sampled_frames") or 0)
    motion_energy = float(metrics.get("motion_energy") or 0.0)
    sharpness = float(metrics.get("sharpness") or 0.0)
    brightness = float(metrics.get("brightness") or 0.0)
    brightness_variance = float(metrics.get("brightness_variance") or 0.0)

    resolution_score = min((width * height) / max(768 * 1344, 1), 1.0) * 5.0
    fps_score = _range_score(fps, low=7.5, high=30.5, soft_low=5.0, soft_high=36.0)
    duration_score = _range_score(duration, low=1.0, high=6.5, soft_low=0.5, soft_high=8.0)
    sample_score = min(sampled_frames / 6.0, 1.0) * 5.0
    motion_score = _range_score(motion_energy, low=2.0, high=34.0, soft_low=0.4, soft_high=55.0)
    sharpness_score = _range_score(sharpness, low=8.0, high=220.0, soft_low=2.0, soft_high=380.0)
    exposure_score = max(0.0, 5.0 - min(abs(brightness - 128.0) / 25.6, 5.0))
    stability_score = max(0.0, 5.0 - min(brightness_variance / 180.0, 5.0))

    score = (
        resolution_score * 0.12
        + fps_score * 0.08
        + duration_score * 0.08
        + sample_score * 0.06
        + motion_score * 0.22
        + sharpness_score * 0.18
        + exposure_score * 0.14
        + stability_score * 0.12
    )
    return round(max(0.0, min(5.0, score)), 2)


def _range_score(value: float, *, low: float, high: float, soft_low: float, soft_high: float) -> float:
    if not math.isfinite(value):
        return 0.0
    if low <= value <= high:
        return 5.0
    if value < low:
        return max(0.0, 5.0 * (value - soft_low) / max(low - soft_low, 1e-6))
    return max(0.0, 5.0 * (soft_high - value) / max(soft_high - high, 1e-6))


def _probe(path: Path) -> dict[str, Any]:
    result = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-select_streams",
            "v:0",
            "-show_entries",
            "stream=width,height,r_frame_rate:format=duration",
            "-of",
            "json",
            str(path),
        ],
        capture_output=True,
        text=True,
        check=True,
        timeout=60,
    )
    data = json.loads(result.stdout)
    stream = (data.get("streams") or [{}])[0]
    return {
        "duration_seconds": float((data.get("format") or {}).get("duration") or 0),
        "width": int(stream.get("width") or 0),
        "height": int(stream.get("height") or 0),
        "fps": _parse_fps(str(stream.get("r_frame_rate") or "0/1")),
    }


def _parse_fps(value: str) -> float:
    if "/" not in value:
        return float(value or 0)
    numerator, denominator = value.split("/", 1)
    denominator_value = float(denominator or 1)
    return float(numerator or 0) / denominator_value if denominator_value else 0.0


def _sample_frames(path: Path, max_samples: int, cv2, np) -> list[Any]:
    capture = cv2.VideoCapture(str(path))
    if not capture.isOpened():
        raise RuntimeError(f"Cannot open video: {path}")
    try:
        frame_count = int(capture.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
        if frame_count <= 0:
            raise RuntimeError(f"Video has no readable frames: {path}")
        sample_count = min(max(2, max_samples), frame_count)
        positions = np.linspace(0, frame_count - 1, sample_count, dtype=int)
        frames = []
        for position in positions:
            capture.set(cv2.CAP_PROP_POS_FRAMES, int(position))
            ok, frame = capture.read()
            if ok and frame is not None:
                frames.append(cv2.resize(frame, (256, 144), interpolation=cv2.INTER_AREA))
    finally:
        capture.release()
    if len(frames) < 2:
        raise RuntimeError(f"Video has too few sampled frames: {path}")
    return frames


def _load_cv2_numpy():
    try:
        import cv2
        import numpy as np
    except ModuleNotFoundError as exc:
        raise RuntimeError("Video technical metrics require opencv-python and numpy") from exc
    return cv2, np
