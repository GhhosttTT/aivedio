"""Compare a generated shot against a Seed Dance baseline video.

The report is intentionally evidence-based and local: it checks technical
properties and sampled-frame motion/visual statistics before anyone makes a
subjective quality claim.
"""

from __future__ import annotations

import argparse
import json
import math
import re
import subprocess
from dataclasses import asdict, dataclass
from pathlib import Path

from src.config import settings


@dataclass
class VideoStats:
    path: str
    duration_seconds: float
    width: int
    height: int
    fps: float
    sampled_frames: int
    motion_energy: float
    sharpness: float
    brightness: float
    brightness_variance: float
    pixel_format: str | None = None
    audio_present: bool = False
    audio_duration_seconds: float | None = None
    audio_codec: str | None = None
    max_static_run_seconds: float = 0.0
    max_black_run_seconds: float = 0.0
    black_frame_ratio: float = 0.0
    brightness_step_p95: float = 0.0
    motion_jitter_ratio: float = 0.0
    temporal_jump_ratio: float = 0.0
    temporal_jump_p95: float = 0.0
    audio_signal_status: str | None = None
    audio_clipping_status: str | None = None
    audio_peak_db: float | None = None
    audio_video_start_delta_seconds: float | None = None


def _probe(path: Path) -> dict:
    result = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "stream=codec_type,width,height,r_frame_rate,duration,codec_name,pix_fmt,start_time:format=duration",
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
    audio_stream = next((item for item in streams if item.get("codec_type") == "audio"), None)
    duration = float((data.get("format") or {}).get("duration") or 0)
    fps = _parse_fps(str(stream.get("r_frame_rate") or "0/1"))
    return {
        "duration_seconds": duration,
        "width": int(stream.get("width") or 0),
        "height": int(stream.get("height") or 0),
        "fps": fps,
        "pixel_format": stream.get("pix_fmt"),
        "audio_present": audio_stream is not None,
        "audio_duration_seconds": (
            float(audio_stream.get("duration"))
            if audio_stream and audio_stream.get("duration") not in (None, "N/A")
            else None
        ),
        "audio_codec": audio_stream.get("codec_name") if audio_stream else None,
        "audio_video_start_delta_seconds": _stream_start_delta(stream, audio_stream),
    }


def _parse_fps(value: str) -> float:
    if "/" not in value:
        return float(value or 0)
    numerator, denominator = value.split("/", 1)
    denominator_value = float(denominator or 1)
    return float(numerator or 0) / denominator_value if denominator_value else 0.0


def _stream_start_delta(video_stream: dict, audio_stream: dict | None) -> float | None:
    if not isinstance(audio_stream, dict):
        return None
    try:
        video_start = float(video_stream.get("start_time") or 0.0)
        audio_start = float(audio_stream.get("start_time") or 0.0)
    except (TypeError, ValueError):
        return None
    return round(abs(audio_start - video_start), 3)


def _sample_frames(path: Path, max_samples: int) -> list[np.ndarray]:
    cv2, np = _load_cv2_numpy()
    capture = cv2.VideoCapture(str(path))
    if not capture.isOpened():
        raise RuntimeError(f"Cannot open video: {path}")
    frame_count = int(capture.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    if frame_count <= 0:
        raise RuntimeError(f"Video has no readable frames: {path}")
    sample_count = min(max_samples, frame_count)
    positions = np.linspace(0, frame_count - 1, sample_count, dtype=int)
    frames = []
    for position in positions:
        capture.set(cv2.CAP_PROP_POS_FRAMES, int(position))
        ok, frame = capture.read()
        if not ok or frame is None:
            continue
        frames.append(cv2.resize(frame, (256, 144), interpolation=cv2.INTER_AREA))
    capture.release()
    if len(frames) < 2:
        raise RuntimeError(f"Video has too few sampled frames: {path}")
    return frames


def video_stats(path: Path, max_samples: int = 16) -> VideoStats:
    cv2, np = _load_cv2_numpy()
    probe = _probe(path)
    frames = _sample_frames(path, max_samples)
    gray_frames = [cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY) for frame in frames]
    diffs = [
        float(np.mean(cv2.absdiff(gray_frames[index], gray_frames[index - 1])))
        for index in range(1, len(gray_frames))
    ]
    sharpness_values = [float(cv2.Laplacian(gray, cv2.CV_64F).var()) for gray in gray_frames]
    brightness_values = [float(np.mean(gray)) for gray in gray_frames]
    static_flags = [value < 0.5 for value in diffs]
    black_flags = [float(np.mean(gray < 12.0)) >= 0.98 for gray in gray_frames]
    brightness_steps = [
        abs(brightness_values[index] - brightness_values[index - 1])
        for index in range(1, len(brightness_values))
    ]
    histograms = []
    for frame in frames:
        histogram = cv2.calcHist([frame], [0, 1], None, [16, 16], [0, 256, 0, 256])
        cv2.normalize(histogram, histogram)
        histograms.append(histogram)
    histogram_jumps = [
        max(0.0, min(1.0, float(cv2.compareHist(
            histograms[index], histograms[index - 1], cv2.HISTCMP_BHATTACHARYYA
        ))))
        for index in range(1, len(histograms))
    ]
    motion_median = float(np.median(diffs)) if diffs else 0.0
    sample_interval = probe["duration_seconds"] / max(len(frames) - 1, 1)
    audio_metrics = _audio_signal_stats(path) if probe["audio_present"] else {}
    return VideoStats(
        path=str(path),
        duration_seconds=round(probe["duration_seconds"], 3),
        width=probe["width"],
        height=probe["height"],
        fps=round(probe["fps"], 3),
        pixel_format=probe.get("pixel_format"),
        sampled_frames=len(frames),
        motion_energy=round(float(np.mean(diffs)), 3),
        sharpness=round(float(np.mean(sharpness_values)), 3),
        brightness=round(float(np.mean(brightness_values)), 3),
        brightness_variance=round(float(np.var(brightness_values)), 3),
        audio_present=bool(probe["audio_present"]),
        audio_duration_seconds=(
            round(float(probe["audio_duration_seconds"]), 3)
            if probe["audio_duration_seconds"] is not None else None
        ),
        audio_codec=probe["audio_codec"],
        max_static_run_seconds=round(
            _max_consecutive_true(static_flags) * sample_interval, 3
        ),
        max_black_run_seconds=round(
            _max_consecutive_true(black_flags) * sample_interval, 3
        ),
        black_frame_ratio=round(float(np.mean(black_flags)) if black_flags else 0.0, 3),
        brightness_step_p95=round(
            float(np.percentile(brightness_steps, 95)) if brightness_steps else 0.0,
            3,
        ),
        motion_jitter_ratio=round(
            float(np.mean(np.abs(np.asarray(diffs) - motion_median)))
            / max(motion_median, 1.0)
            if diffs else 0.0,
            3,
        ),
        temporal_jump_ratio=round(
            sum(value >= 0.55 for value in histogram_jumps) / len(histogram_jumps)
            if histogram_jumps else 0.0,
            3,
        ),
        temporal_jump_p95=round(
            float(np.percentile(histogram_jumps, 95)) if histogram_jumps else 0.0,
            3,
        ),
        audio_signal_status=audio_metrics.get("audio_signal_status"),
        audio_clipping_status=audio_metrics.get("audio_clipping_status"),
        audio_peak_db=audio_metrics.get("audio_peak_db"),
        audio_video_start_delta_seconds=probe.get("audio_video_start_delta_seconds"),
    )


def compare(candidate: Path, baseline: Path, max_samples: int = 16, artifact_dir: Path | None = None) -> dict:
    candidate_stats = video_stats(candidate, max_samples)
    baseline_stats = video_stats(baseline, max_samples)
    contact_sheet_path = None
    if artifact_dir is not None:
        contact_sheet_path = _write_contact_sheet(candidate, baseline, artifact_dir, max_samples=min(6, max_samples))
    differences = {
        "duration_delta_seconds": round(candidate_stats.duration_seconds - baseline_stats.duration_seconds, 3),
        "fps_delta": round(candidate_stats.fps - baseline_stats.fps, 3),
        "pixel_format_match": _pixel_format_fidelity_rank(candidate_stats.pixel_format)
        >= _pixel_format_fidelity_rank(baseline_stats.pixel_format),
        "aspect_ratio_delta": round(
            _aspect_ratio(candidate_stats.width, candidate_stats.height)
            - _aspect_ratio(baseline_stats.width, baseline_stats.height),
            3,
        ),
        "motion_energy_ratio": _safe_ratio(candidate_stats.motion_energy, baseline_stats.motion_energy),
        "sharpness_ratio": _safe_ratio(candidate_stats.sharpness, baseline_stats.sharpness),
        "brightness_delta": round(candidate_stats.brightness - baseline_stats.brightness, 3),
        "brightness_variance_ratio": _safe_ratio(candidate_stats.brightness_variance, baseline_stats.brightness_variance),
        "max_static_run_delta_seconds": round(
            candidate_stats.max_static_run_seconds - baseline_stats.max_static_run_seconds, 3
        ),
        "max_black_run_delta_seconds": round(
            candidate_stats.max_black_run_seconds - baseline_stats.max_black_run_seconds, 3
        ),
        "brightness_step_p95_delta": round(
            candidate_stats.brightness_step_p95 - baseline_stats.brightness_step_p95, 3
        ),
        "motion_jitter_ratio_delta": round(
            candidate_stats.motion_jitter_ratio - baseline_stats.motion_jitter_ratio, 3
        ),
        "temporal_jump_ratio_delta": round(
            candidate_stats.temporal_jump_ratio - baseline_stats.temporal_jump_ratio, 3
        ),
        "temporal_jump_p95_delta": round(
            candidate_stats.temporal_jump_p95 - baseline_stats.temporal_jump_p95, 3
        ),
        "audio_duration_delta_seconds": (
            round(candidate_stats.audio_duration_seconds - baseline_stats.audio_duration_seconds, 3)
            if candidate_stats.audio_duration_seconds is not None
            and baseline_stats.audio_duration_seconds is not None else None
        ),
        "audio_peak_delta_db": (
            round(candidate_stats.audio_peak_db - baseline_stats.audio_peak_db, 3)
            if candidate_stats.audio_peak_db is not None
            and baseline_stats.audio_peak_db is not None else None
        ),
        "audio_video_start_delta_seconds": (
            round(candidate_stats.audio_video_start_delta_seconds, 3)
            if candidate_stats.audio_video_start_delta_seconds is not None else None
        ),
    }
    audio_duration_delta = differences["audio_duration_delta_seconds"]
    gates = {
        "duration_close": abs(differences["duration_delta_seconds"]) <= 0.5,
        "fps_close": abs(differences["fps_delta"]) <= 2.0,
        "pixel_format_not_lower": differences["pixel_format_match"],
        "resolution_not_lower": (
            candidate_stats.width * candidate_stats.height >= baseline_stats.width * baseline_stats.height
        ),
        "aspect_ratio_close": abs(differences["aspect_ratio_delta"]) <= 0.08,
        "motion_not_static": candidate_stats.motion_energy >= max(2.0, baseline_stats.motion_energy * 0.45),
        "sharpness_not_collapsed": candidate_stats.sharpness >= max(8.0, baseline_stats.sharpness * 0.45),
        "exposure_close": abs(differences["brightness_delta"]) <= 45.0,
        "brightness_stable": candidate_stats.brightness_variance <= max(900.0, baseline_stats.brightness_variance * 3.0),
        "no_prolonged_static_run": candidate_stats.max_static_run_seconds <= 1.8,
        "no_prolonged_black_run": candidate_stats.max_black_run_seconds <= 0.2,
        "black_frame_ratio_acceptable": candidate_stats.black_frame_ratio <= settings.GENERATION_VIDEO_MAX_BLACK_FRAME_RATIO,
        "no_temporal_exposure_jumps": candidate_stats.brightness_step_p95 <= 36.0,
        "stable_motion_cadence": candidate_stats.motion_jitter_ratio <= 1.5,
        "no_temporal_visual_resets": candidate_stats.temporal_jump_ratio <= settings.GENERATION_VIDEO_MAX_TEMPORAL_JUMP_RATIO,
        "no_extreme_temporal_visual_reset": candidate_stats.temporal_jump_p95 <= settings.GENERATION_VIDEO_MAX_TEMPORAL_JUMP_P95,
        "audio_presence_matches": candidate_stats.audio_present == baseline_stats.audio_present,
        "audio_duration_close": (
            not baseline_stats.audio_present
            or (
                candidate_stats.audio_present
                and audio_duration_delta is not None
                and abs(audio_duration_delta) <= 0.5
            )
        ),
        "audio_signal_usable": (
            not baseline_stats.audio_present
            or candidate_stats.audio_signal_status == "usable"
        ),
        "audio_not_clipped": (
            not baseline_stats.audio_present
            or candidate_stats.audio_clipping_status != "clipped"
        ),
        "audio_start_aligned": (
            not baseline_stats.audio_present
            or (
                candidate_stats.audio_video_start_delta_seconds is not None
                and candidate_stats.audio_video_start_delta_seconds <= settings.GENERATION_VIDEO_AUDIO_SYNC_TOLERANCE_SECONDS
            )
        ),
        "audio_level_close": (
            not baseline_stats.audio_present
            or (
                candidate_stats.audio_peak_db is not None
                and baseline_stats.audio_peak_db is not None
                and abs(candidate_stats.audio_peak_db - baseline_stats.audio_peak_db) <= 12.0
            )
        ),
    }
    score = _technical_similarity_score(differences, gates)
    status = "passed" if all(gates.values()) and score >= 4.0 else "needs_review"
    return {
        "kind": "seed_dance_baseline_comparison",
        "status": status,
        "score": score,
        "min_score": 4.0,
        "candidate": asdict(candidate_stats),
        "baseline": asdict(baseline_stats),
        "differences": differences,
        "gates": gates,
        "contact_sheet_path": str(contact_sheet_path) if contact_sheet_path else None,
        "limitations": [
            "This is a measurable first-pass comparison, not a final human taste judgment.",
            "Story meaning, acting emotion, and character identity still require VLM/human review.",
        ],
    }


def _write_contact_sheet(candidate: Path, baseline: Path, artifact_dir: Path, max_samples: int = 6) -> Path:
    cv2, np = _load_cv2_numpy()
    candidate_frames = _sample_frames(candidate, max_samples)
    baseline_frames = _sample_frames(baseline, max_samples)
    count = min(len(candidate_frames), len(baseline_frames), max_samples)
    if count < 2:
        raise RuntimeError("Not enough frames to build comparison contact sheet")
    candidate_frames = candidate_frames[:count]
    baseline_frames = baseline_frames[:count]
    label_height = 28
    frame_height, frame_width = candidate_frames[0].shape[:2]
    sheet = np.full((label_height * 2 + frame_height * 2, frame_width * count, 3), 22, dtype=np.uint8)

    _draw_label(sheet, "Candidate", 0)
    _draw_label(sheet, "Seed Dance baseline", label_height + frame_height)
    for index, frame in enumerate(candidate_frames):
        x = index * frame_width
        sheet[label_height:label_height + frame_height, x:x + frame_width] = frame
    baseline_y = label_height * 2 + frame_height
    for index, frame in enumerate(baseline_frames):
        x = index * frame_width
        sheet[baseline_y:baseline_y + frame_height, x:x + frame_width] = frame

    artifact_dir.mkdir(parents=True, exist_ok=True)
    output = artifact_dir / "seed_dance_contact_sheet.png"
    if not cv2.imwrite(str(output), sheet):
        raise RuntimeError(f"Could not write contact sheet: {output}")
    return output


def _draw_label(image: np.ndarray, text: str, y: int) -> None:
    cv2, _np = _load_cv2_numpy()
    cv2.putText(
        image,
        text,
        (8, y + 19),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.55,
        (235, 235, 235),
        1,
        cv2.LINE_AA,
    )


def _load_cv2_numpy():
    try:
        import cv2
        import numpy as np
    except ModuleNotFoundError as exc:
        raise RuntimeError(
            "Seed Dance baseline comparison requires opencv-python and numpy. "
            "Install them before running video baseline comparison."
        ) from exc
    return cv2, np


def _audio_signal_stats(path: Path) -> dict[str, object]:
    """Measure whether a present audio stream contains usable, unclipped signal."""
    try:
        result = subprocess.run(
            [
                "ffmpeg", "-v", "info", "-i", str(path), "-vn",
                "-af", "volumedetect", "-f", "null", "-",
            ],
            capture_output=True,
            text=True,
            check=False,
            timeout=90,
        )
        output = f"{result.stdout}\n{result.stderr}"
        matches = re.findall(
            r"max_volume:\s*(-?(?:\d+(?:\.\d+)?|inf))\s*dB",
            output,
            re.I,
        )
        if result.returncode != 0 or not matches or matches[-1].lower() == "inf":
            return {"audio_signal_status": "unavailable", "audio_clipping_status": "unavailable"}
        peak_db = float(matches[-1])
        return {
            "audio_signal_status": "near_silent" if peak_db <= -55.0 else "usable",
            "audio_clipping_status": "clipped" if peak_db >= -0.1 else "ok",
            "audio_peak_db": round(peak_db, 3),
        }
    except (OSError, subprocess.SubprocessError, ValueError):
        return {"audio_signal_status": "unavailable", "audio_clipping_status": "unavailable"}


def _safe_ratio(value: float, baseline: float) -> float | None:
    if not math.isfinite(baseline) or abs(baseline) < 1e-6:
        return None
    return round(value / baseline, 3)


def _max_consecutive_true(values: list[bool]) -> int:
    longest = current = 0
    for value in values:
        if value:
            current += 1
            longest = max(longest, current)
        else:
            current = 0
    return longest


def _aspect_ratio(width: int, height: int) -> float:
    return width / height if height else 0.0


def _pixel_format_fidelity_rank(pixel_format: str | None) -> tuple[int, int]:
    """Rank common pixel formats by bit depth and chroma fidelity."""
    normalized = str(pixel_format or "").strip().lower()
    if not normalized:
        return (0, 0)
    bit_depth = 12 if "p12" in normalized else 10 if "p10" in normalized else 8
    chroma = 3 if "444" in normalized else 2 if "422" in normalized else 1 if "420" in normalized else 0
    return (bit_depth, chroma)


def _ratio_score(value: float | None, ideal: float = 1.0, tolerance: float = 0.55) -> float:
    if value is None or not math.isfinite(value):
        return 2.5
    distance = abs(value - ideal)
    return max(0.0, min(5.0, 5.0 * (1.0 - distance / max(tolerance, 1e-6))))


def _delta_score(value: float, tolerance: float) -> float:
    return max(0.0, min(5.0, 5.0 * (1.0 - abs(value) / max(tolerance, 1e-6))))


def _technical_similarity_score(differences: dict, gates: dict[str, bool]) -> float:
    gate_score = 5.0 * (sum(1 for passed in gates.values() if passed) / max(len(gates), 1))
    component_scores = [
        _delta_score(float(differences["duration_delta_seconds"]), 1.0),
        _delta_score(float(differences["fps_delta"]), 8.0),
        _delta_score(float(differences["aspect_ratio_delta"]), 0.16),
        _ratio_score(differences.get("motion_energy_ratio"), tolerance=0.75),
        _ratio_score(differences.get("sharpness_ratio"), tolerance=0.75),
        _delta_score(float(differences["brightness_delta"]), 60.0),
        _ratio_score(differences.get("brightness_variance_ratio"), tolerance=2.0),
        _delta_score(float(differences["temporal_jump_ratio_delta"]), 0.5),
        _delta_score(float(differences["audio_duration_delta_seconds"] or 0.0), 1.0),
    ]
    metric_score = sum(component_scores) / len(component_scores)
    score = gate_score * 0.45 + metric_score * 0.55

    # A static candidate can still look deceptively similar on duration,
    # exposure, and sharpness. Motion is therefore a hard quality signal,
    # rather than just one more independent metric in the average.
    if not gates.get("motion_not_static", True):
        score -= 0.5

    return round(max(0.0, min(5.0, score)), 2)


def main() -> int:
    parser = argparse.ArgumentParser(description="Compare generated video against a Seed Dance baseline")
    parser.add_argument("--candidate", required=True, help="Generated video path")
    parser.add_argument("--baseline", required=True, help="Seed Dance baseline video path")
    parser.add_argument("--output", help="Optional JSON report path")
    parser.add_argument("--samples", type=int, default=16, help="Maximum sampled frames per video")
    args = parser.parse_args()

    if args.output:
        output = Path(args.output)
        artifact_dir = output.parent
    else:
        output = None
        artifact_dir = None
    report = compare(Path(args.candidate), Path(args.baseline), max_samples=max(4, args.samples), artifact_dir=artifact_dir)
    text = json.dumps(report, ensure_ascii=False, indent=2)
    if output:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(text, encoding="utf-8")
    print(text)
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
