"""Technical quality metrics for generated video candidates."""

from __future__ import annotations

import json
import math
import re
import subprocess
from pathlib import Path
from typing import Any


def video_candidate_metrics(path: str | Path, max_samples: int | None = None) -> dict[str, Any]:
    """Return bounded, local technical metrics for one candidate clip.

    These metrics are a ranking signal only. VLM and human review remain the
    authority for story meaning, acting quality, identity, and taste.
    """

    video_path = Path(path)
    try:
        cv2, np = _load_cv2_numpy()
        probe = _probe(video_path)
        frames = _sample_frames(
            video_path,
            max_samples,
            cv2,
            np,
            duration_seconds=float(probe["duration_seconds"]),
        )
        gray_frames = [cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY) for frame in frames]
        histogram_jump_values = _frame_histogram_distances(frames, cv2)
        motion_values = [
            float(np.mean(cv2.absdiff(gray_frames[index], gray_frames[index - 1])))
            for index in range(1, len(gray_frames))
        ]
        static_transition_ratio = (
            sum(value < 0.5 for value in motion_values) / len(motion_values)
            if motion_values else 1.0
        )
        max_static_run = _max_consecutive_true(
            [value < 0.5 for value in motion_values]
        )
        sample_interval = (
            float(probe["duration_seconds"]) / max(len(gray_frames) - 1, 1)
        )
        sharpness_values = [float(cv2.Laplacian(gray, cv2.CV_64F).var()) for gray in gray_frames]
        brightness_values = [float(np.mean(gray)) for gray in gray_frames]
        motion_energy = float(np.mean(motion_values)) if motion_values else 0.0
        sharpness = float(np.mean(sharpness_values)) if sharpness_values else 0.0
        brightness = float(np.mean(brightness_values)) if brightness_values else 0.0
        brightness_variance = float(np.var(brightness_values)) if brightness_values else 0.0
        brightness_steps = [
            abs(brightness_values[index] - brightness_values[index - 1])
            for index in range(1, len(brightness_values))
        ]
        brightness_step_p95 = (
            float(np.percentile(brightness_steps, 95)) if brightness_steps else 0.0
        )
        motion_median = float(np.median(motion_values)) if motion_values else 0.0
        motion_jitter_ratio = (
            float(np.mean(np.abs(np.asarray(motion_values) - motion_median)))
            / max(motion_median, 1.0)
            if motion_values else 0.0
        )
        temporal_jump_ratio = (
            sum(value >= 0.55 for value in histogram_jump_values) / len(histogram_jump_values)
            if histogram_jump_values else 0.0
        )
        temporal_jump_p95 = (
            float(np.percentile(histogram_jump_values, 95))
            if histogram_jump_values else 0.0
        )
        black_frame_flags = [
            float(np.mean(gray < 12.0)) >= 0.98
            for gray in gray_frames
        ]
        max_black_run = _max_consecutive_true(black_frame_flags)
        metrics = {
            "status": "available",
            "path": str(video_path),
            "duration_seconds": round(float(probe["duration_seconds"]), 3),
            "width": int(probe["width"]),
            "height": int(probe["height"]),
            "fps": round(float(probe["fps"]), 3),
            "video_codec": probe.get("video_codec"),
            "pixel_format": probe.get("pixel_format"),
            "high_bit_depth": bool(probe.get("high_bit_depth")),
            "sampled_frames": len(frames),
            "sampling_interval_seconds": round(sample_interval, 3),
            "sampling_strategy": "explicit" if max_samples is not None else "adaptive_temporal",
            "motion_energy": round(motion_energy, 3),
            "static_transition_ratio": round(static_transition_ratio, 3),
            "max_static_run_seconds": round(max_static_run * sample_interval, 3),
            "sharpness": round(sharpness, 3),
            "brightness": round(brightness, 3),
            "brightness_variance": round(brightness_variance, 3),
            "brightness_step_p95": round(brightness_step_p95, 3),
            "motion_jitter_ratio": round(motion_jitter_ratio, 3),
            "temporal_jump_ratio": round(temporal_jump_ratio, 3),
            "temporal_jump_p95": round(temporal_jump_p95, 3),
            "black_frame_ratio": round(
                sum(black_frame_flags) / len(black_frame_flags), 3
            ) if black_frame_flags else 0.0,
            "max_black_run_seconds": round(max_black_run * sample_interval, 3),
            "audio_present": bool(probe.get("audio_present")),
            "audio_duration_seconds": (
                round(float(probe["audio_duration_seconds"]), 3)
                if probe.get("audio_duration_seconds") is not None else None
            ),
            "audio_codec": probe.get("audio_codec"),
            "audio_channels": probe.get("audio_channels"),
        }
        if metrics["audio_present"]:
            metrics.update(_audio_signal_metrics(video_path, metrics["duration_seconds"]))
        if metrics["audio_present"] and metrics["audio_duration_seconds"] is not None:
            metrics["audio_duration_delta_seconds"] = round(
                abs(metrics["duration_seconds"] - metrics["audio_duration_seconds"]), 3
            )
        if metrics["audio_present"] and metrics.get("audio_video_start_delta_seconds") is not None:
            metrics["audio_video_start_delta_seconds"] = round(
                float(metrics["audio_video_start_delta_seconds"]), 3
            )
        metrics["technical_score"] = video_technical_score(metrics)
        return metrics
    except Exception as exc:
        return {
            "status": "unavailable",
            "path": str(video_path),
            "technical_score": None,
            "error": str(exc),
        }


def video_technical_score(
    metrics: dict[str, Any],
    *,
    duration_low: float = 1.0,
    duration_high: float = 6.5,
    duration_soft_low: float = 0.5,
    duration_soft_high: float = 8.0,
) -> float:
    duration = float(metrics.get("duration_seconds") or 0.0)
    width = int(metrics.get("width") or 0)
    height = int(metrics.get("height") or 0)
    fps = float(metrics.get("fps") or 0.0)
    sampled_frames = int(metrics.get("sampled_frames") or 0)
    motion_energy = float(metrics.get("motion_energy") or 0.0)
    sharpness = float(metrics.get("sharpness") or 0.0)
    brightness = float(metrics.get("brightness") or 0.0)
    brightness_variance = float(metrics.get("brightness_variance") or 0.0)
    brightness_step_p95 = float(metrics.get("brightness_step_p95") or 0.0)
    motion_jitter_ratio = float(metrics.get("motion_jitter_ratio") or 0.0)
    static_transition_ratio = float(metrics.get("static_transition_ratio") or 0.0)
    max_black_run_seconds = float(metrics.get("max_black_run_seconds") or 0.0)

    resolution_score = min((width * height) / max(768 * 1344, 1), 1.0) * 5.0
    fps_score = _range_score(fps, low=7.5, high=30.5, soft_low=5.0, soft_high=36.0)
    duration_score = _range_score(
        duration,
        low=duration_low,
        high=duration_high,
        soft_low=duration_soft_low,
        soft_high=duration_soft_high,
    )
    sample_score = min(sampled_frames / 6.0, 1.0) * 5.0
    motion_score = _range_score(motion_energy, low=2.0, high=34.0, soft_low=0.4, soft_high=55.0)
    sharpness_score = _range_score(sharpness, low=8.0, high=220.0, soft_low=2.0, soft_high=380.0)
    exposure_score = max(0.0, 5.0 - min(abs(brightness - 128.0) / 25.6, 5.0))
    stability_score = max(0.0, 5.0 - min(brightness_variance / 180.0, 5.0))
    freeze_score = max(0.0, 5.0 - min(static_transition_ratio * 7.0, 5.0))
    black_score = max(0.0, 5.0 - min(max_black_run_seconds / 0.2 * 5.0, 5.0))
    exposure_step_score = max(0.0, 5.0 - min(brightness_step_p95 / 18.0, 5.0))
    motion_stability_score = max(0.0, 5.0 - min(motion_jitter_ratio * 2.5, 5.0))
    temporal_jump_ratio = float(metrics.get("temporal_jump_ratio") or 0.0)
    temporal_stability_score = (
        exposure_step_score * 0.6
        + motion_stability_score * 0.4
        - min(temporal_jump_ratio * 5.0, 5.0)
    )
    temporal_stability_score = max(0.0, temporal_stability_score)

    score = (
        resolution_score * 0.10
        + fps_score * 0.07
        + duration_score * 0.07
        + sample_score * 0.04
        + motion_score * 0.15
        + sharpness_score * 0.14
        + exposure_score * 0.09
        + stability_score * 0.07
        + freeze_score * 0.16
        + black_score * 0.05
        + temporal_stability_score * 0.06
    )
    return round(max(0.0, min(5.0, score)), 2)


def _max_consecutive_true(values: list[bool]) -> int:
    longest = current = 0
    for value in values:
        if value:
            current += 1
            longest = max(longest, current)
        else:
            current = 0
    return longest


def _frame_histogram_distances(frames, cv2) -> list[float]:
    """Measure large content resets between adjacent sampled frames."""
    histograms = []
    for frame in frames:
        histogram = cv2.calcHist([frame], [0, 1], None, [16, 16], [0, 256, 0, 256])
        cv2.normalize(histogram, histogram)
        histograms.append(histogram)
    return [
        max(0.0, min(1.0, float(cv2.compareHist(
            histograms[index], histograms[index - 1], cv2.HISTCMP_BHATTACHARYYA
        ))))
        for index in range(1, len(histograms))
    ]


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
            "-show_entries",
            "stream=codec_type,codec_name,pix_fmt,width,height,r_frame_rate,channels,duration,start_time:format=duration",
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
    streams = data.get("streams") or []
    stream = next((item for item in streams if item.get("codec_type") == "video"), {})
    if not isinstance(stream, dict) or not stream:
        raise ValueError("ffprobe found no video stream")
    duration = float((data.get("format") or {}).get("duration") or 0)
    width = int(stream.get("width") or 0)
    height = int(stream.get("height") or 0)
    fps = _parse_fps(str(stream.get("r_frame_rate") or "0/1"))
    if not math.isfinite(duration) or duration <= 0:
        raise ValueError("ffprobe reported a non-positive video duration")
    if width <= 0 or height <= 0:
        raise ValueError("ffprobe reported invalid video geometry")
    if not math.isfinite(fps) or fps <= 0:
        raise ValueError("ffprobe reported an invalid video frame rate")
    audio_stream = next((item for item in streams if item.get("codec_type") == "audio"), None)
    audio_duration = None
    video_start_time = _stream_start_time(stream)
    audio_start_time = _stream_start_time(audio_stream)
    if isinstance(audio_stream, dict):
        try:
            audio_duration = float(audio_stream.get("duration")) if audio_stream.get("duration") is not None else None
        except (TypeError, ValueError):
            audio_duration = None
        if audio_duration is None:
            try:
                audio_duration = float((data.get("format") or {}).get("duration") or 0) or None
            except (TypeError, ValueError):
                audio_duration = None
    return {
        "duration_seconds": duration,
        "width": width,
        "height": height,
        "fps": fps,
        "video_codec": stream.get("codec_name"),
        "pixel_format": stream.get("pix_fmt"),
        "high_bit_depth": any(
            token in str(stream.get("pix_fmt") or "").lower() for token in ("p10", "p12", "p14")
        ),
        "audio_present": audio_stream is not None,
        "audio_duration_seconds": audio_duration,
        "audio_video_start_delta_seconds": (
            abs(audio_start_time - video_start_time)
            if audio_start_time is not None and video_start_time is not None else None
        ),
        "audio_codec": audio_stream.get("codec_name") if isinstance(audio_stream, dict) else None,
        "audio_channels": int(audio_stream.get("channels") or 0) if isinstance(audio_stream, dict) else None,
    }


def _stream_start_time(stream: dict | None) -> float | None:
    if not isinstance(stream, dict) or stream.get("start_time") is None:
        return None
    try:
        return float(stream["start_time"])
    except (TypeError, ValueError):
        return None


def _audio_signal_metrics(path: Path, duration_seconds: float) -> dict[str, Any]:
    """Measure whether an audio stream contains usable signal, not only packets."""
    try:
        result = subprocess.run(
            [
                "ffmpeg", "-v", "info", "-i", str(path), "-vn",
                "-af", "silencedetect=noise=-45dB:d=0.25,astats=metadata=1:reset=1",
                "-f", "null", "-",
            ],
            capture_output=True,
            text=True,
            check=False,
            timeout=90,
        )
        if result.returncode != 0:
            raise ValueError(f"ffmpeg audio analysis failed with exit code {result.returncode}")
        output = f"{result.stdout}\n{result.stderr}"
        starts = [float(value) for value in re.findall(r"silence_start:\s*([0-9.]+)", output)]
        ends = [float(value) for value in re.findall(r"silence_end:\s*([0-9.]+)", output)]
        silent_seconds = 0.0
        for index, start in enumerate(starts):
            end = ends[index] if index < len(ends) else duration_seconds
            silent_seconds += max(0.0, min(float(duration_seconds), end) - max(0.0, start))
        peak_values = [
            float(value) for value in re.findall(
                r"Peak level dB:\s*(-?(?:\d+(?:\.\d+)?|inf))", output, re.I
            ) if value.lower() != "inf"
        ]
        rms_values = [
            float(value) for value in re.findall(
                r"RMS level dB:\s*(-?(?:\d+(?:\.\d+)?|inf))", output, re.I
            ) if value.lower() != "inf"
        ]
        if not peak_values and not rms_values:
            raise ValueError("ffmpeg audio analysis produced no measurable signal")
        silence_ratio = min(1.0, silent_seconds / max(float(duration_seconds), 1e-6))
        peak_db = max(peak_values) if peak_values else None
        rms_db = max(rms_values) if rms_values else None
        near_silent = bool(
            (peak_db is not None and peak_db <= -55.0)
            or silence_ratio >= 0.95
        )
        clipping = bool(peak_db is not None and peak_db >= -0.1)
        return {
            "audio_silence_ratio": round(silence_ratio, 3),
            "audio_peak_db": round(peak_db, 2) if peak_db is not None else None,
            "audio_rms_db": round(rms_db, 2) if rms_db is not None else None,
            "audio_signal_status": "near_silent" if near_silent else "usable",
            "audio_clipping_status": "clipped" if clipping else "ok",
        }
    except Exception as exc:
        return {
            "audio_signal_status": "unavailable",
            "audio_signal_error": str(exc),
        }


def video_boundary_continuity(video_paths: list[str | Path]) -> dict[str, Any]:
    """Measure technical discontinuities at adjacent shot boundaries.

    A hard cut is not inherently an error, so this is an evidence report rather
    than a blanket similarity gate. It catches accidental black frames,
    extreme exposure jumps, mismatched geometry, and other failures that a
    semantic VLM review can overlook.
    """
    paths = [Path(path) for path in video_paths if path]
    if len(paths) < 2:
        return {"status": "not_applicable", "boundary_count": 0, "boundaries": []}
    try:
        cv2, np = _load_cv2_numpy()
        boundaries = []
        for index, (previous, current) in enumerate(zip(paths, paths[1:]), start=1):
            previous_frame = _read_boundary_frame(previous, cv2, np, from_end=True)
            current_frame = _read_boundary_frame(current, cv2, np, from_end=False)
            previous_probe = _probe(previous)
            current_probe = _probe(current)
            previous_gray = cv2.cvtColor(previous_frame, cv2.COLOR_BGR2GRAY)
            current_gray = cv2.cvtColor(current_frame, cv2.COLOR_BGR2GRAY)
            previous_hsv = cv2.cvtColor(previous_frame, cv2.COLOR_BGR2HSV)
            current_hsv = cv2.cvtColor(current_frame, cv2.COLOR_BGR2HSV)
            previous_small = cv2.resize(previous_frame, (256, 144), interpolation=cv2.INTER_AREA)
            current_small = cv2.resize(current_frame, (256, 144), interpolation=cv2.INTER_AREA)
            brightness_delta = abs(
                float(np.mean(previous_gray)) - float(np.mean(current_gray))
            ) / 255.0
            saturation_delta = abs(
                float(np.mean(previous_hsv[:, :, 1]))
                - float(np.mean(current_hsv[:, :, 1]))
            ) / 255.0
            contrast_delta = abs(
                float(np.std(previous_gray)) - float(np.std(current_gray))
            ) / 255.0
            pixel_delta = float(np.mean(cv2.absdiff(previous_small, current_small))) / 255.0
            previous_hist = cv2.calcHist([previous_small], [0, 1], None, [16, 16], [0, 256, 0, 256])
            current_hist = cv2.calcHist([current_small], [0, 1], None, [16, 16], [0, 256, 0, 256])
            cv2.normalize(previous_hist, previous_hist)
            cv2.normalize(current_hist, current_hist)
            histogram_distance = max(
                0.0,
                min(1.0, float(cv2.compareHist(previous_hist, current_hist, cv2.HISTCMP_BHATTACHARYYA))),
            )
            severe = brightness_delta >= 0.65 and histogram_distance >= 0.7
            severe_style = (
                (saturation_delta >= 0.35 or contrast_delta >= 0.4)
                and histogram_distance >= 0.7
            )
            previous_fps = float(previous_probe.get("fps") or 0.0)
            current_fps = float(current_probe.get("fps") or 0.0)
            fps_match = (
                previous_fps > 0
                and current_fps > 0
                and abs(previous_fps - current_fps) <= 2.0
            )
            previous_pixel_format = str(previous_probe.get("pixel_format") or "").lower()
            current_pixel_format = str(current_probe.get("pixel_format") or "").lower()
            pixel_format_match = bool(previous_pixel_format and current_pixel_format) and (
                previous_pixel_format == current_pixel_format
            )
            boundaries.append({
                "boundary_index": index,
                "previous_path": str(previous),
                "current_path": str(current),
                "previous_geometry": [previous_probe["width"], previous_probe["height"]],
                "current_geometry": [current_probe["width"], current_probe["height"]],
                "previous_fps": round(previous_fps, 3),
                "current_fps": round(current_fps, 3),
                "fps_delta": round(abs(previous_fps - current_fps), 3),
                "fps_match": fps_match,
                "previous_pixel_format": previous_pixel_format,
                "current_pixel_format": current_pixel_format,
                "pixel_format_match": pixel_format_match,
                "geometry_match": (
                    previous_probe["width"] == current_probe["width"]
                    and previous_probe["height"] == current_probe["height"]
                ),
                "brightness_delta": round(brightness_delta, 3),
                "saturation_delta": round(saturation_delta, 3),
                "contrast_delta": round(contrast_delta, 3),
                "pixel_delta": round(pixel_delta, 3),
                "histogram_distance": round(histogram_distance, 3),
                "severe_exposure_or_black_transition": severe,
                "severe_style_transition": severe_style,
            })
        severe_count = sum(item["severe_exposure_or_black_transition"] for item in boundaries)
        severe_style_count = sum(item["severe_style_transition"] for item in boundaries)
        geometry_mismatch_count = sum(not item["geometry_match"] for item in boundaries)
        fps_mismatch_count = sum(not item["fps_match"] for item in boundaries)
        pixel_format_mismatch_count = sum(not item["pixel_format_match"] for item in boundaries)
        return {
            "status": "available",
            "boundary_count": len(boundaries),
            "severe_transition_count": severe_count,
            "severe_style_transition_count": severe_style_count,
            "geometry_mismatch_count": geometry_mismatch_count,
            "fps_mismatch_count": fps_mismatch_count,
            "pixel_format_mismatch_count": pixel_format_mismatch_count,
            "boundaries": boundaries,
        }
    except Exception as exc:
        return {
            "status": "unavailable",
            "boundary_count": max(0, len(paths) - 1),
            "boundaries": [],
            "error": str(exc),
        }


def video_start_frame_reference_metrics(
    video_path: str | Path,
    reference_image: str | Path | None,
) -> dict[str, Any]:
    """Compare a generated clip's first frame with its locked keyframe."""
    if not reference_image:
        return {"status": "not_applicable"}
    try:
        cv2, np = _load_cv2_numpy()
        capture = cv2.VideoCapture(str(video_path))
        if not capture.isOpened():
            raise RuntimeError(f"Video cannot be opened: {video_path}")
        try:
            ok, first_frame = capture.read()
        finally:
            capture.release()
        reference = cv2.imread(str(reference_image), cv2.IMREAD_COLOR)
        if not ok or first_frame is None or reference is None:
            raise RuntimeError("video first frame or reference image is unreadable")
        first_frame = cv2.resize(first_frame, (256, 144), interpolation=cv2.INTER_AREA)
        reference = cv2.resize(reference, (256, 144), interpolation=cv2.INTER_AREA)
        first_gray = cv2.cvtColor(first_frame, cv2.COLOR_BGR2GRAY)
        reference_gray = cv2.cvtColor(reference, cv2.COLOR_BGR2GRAY)
        brightness_delta = abs(
            float(np.mean(first_gray)) - float(np.mean(reference_gray))
        ) / 255.0
        pixel_delta = float(np.mean(cv2.absdiff(first_frame, reference))) / 255.0
        first_hist = cv2.calcHist([first_frame], [0, 1], None, [16, 16], [0, 256, 0, 256])
        reference_hist = cv2.calcHist([reference], [0, 1], None, [16, 16], [0, 256, 0, 256])
        cv2.normalize(first_hist, first_hist)
        cv2.normalize(reference_hist, reference_hist)
        histogram_distance = max(
            0.0,
            min(1.0, float(cv2.compareHist(first_hist, reference_hist, cv2.HISTCMP_BHATTACHARYYA))),
        )
        score = max(
            0.0,
            min(5.0, 5.0 * (0.35 * (1.0 - pixel_delta) + 0.65 * (1.0 - histogram_distance))),
        )
        return {
            "status": "available",
            "reference_image": str(reference_image),
            "brightness_delta": round(brightness_delta, 3),
            "pixel_delta": round(pixel_delta, 3),
            "histogram_distance": round(histogram_distance, 3),
            "score": round(score, 2),
        }
    except Exception as exc:
        return {"status": "unavailable", "error": str(exc)}


def _read_boundary_frame(path: Path, cv2, np, *, from_end: bool):
    capture = cv2.VideoCapture(str(path))
    if not capture.isOpened():
        raise RuntimeError(f"Video cannot be opened for boundary analysis: {path}")
    try:
        frame_count = int(capture.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
        if frame_count <= 0:
            raise RuntimeError(f"Video has no frames for boundary analysis: {path}")
        capture.set(cv2.CAP_PROP_POS_FRAMES, frame_count - 1 if from_end else 0)
        ok, frame = capture.read()
        if not ok or frame is None:
            raise RuntimeError(f"Video boundary frame is unreadable: {path}")
        return frame
    finally:
        capture.release()


def _parse_fps(value: str) -> float:
    if "/" not in value:
        return float(value or 0)
    numerator, denominator = value.split("/", 1)
    denominator_value = float(denominator or 1)
    return float(numerator or 0) / denominator_value if denominator_value else 0.0


def _sample_frames(
    path: Path,
    max_samples: int | None,
    cv2,
    np,
    *,
    duration_seconds: float | None = None,
) -> list[Any]:
    capture = cv2.VideoCapture(str(path))
    if not capture.isOpened():
        raise RuntimeError(f"Cannot open video: {path}")
    try:
        frame_count = int(capture.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
        if frame_count <= 0:
            raise RuntimeError(f"Video has no readable frames: {path}")
        if max_samples is None:
            # Dense enough to expose short temporal defects while keeping a
            # long-form composition bounded for local review and ranking.
            duration = max(0.0, float(duration_seconds or 0.0))
            target_samples = max(24, int(math.ceil(duration * 4.0)) + 1)
            target_samples = min(96, target_samples)
        else:
            target_samples = max(2, int(max_samples))
        sample_count = min(target_samples, frame_count)
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
