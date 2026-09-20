"""Compare a generated shot against a Seed Dance baseline video.

The report is intentionally evidence-based and local: it checks technical
properties and sampled-frame motion/visual statistics before anyone makes a
subjective quality claim.
"""

from __future__ import annotations

import argparse
import json
import math
import subprocess
from dataclasses import asdict, dataclass
from pathlib import Path


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


def _probe(path: Path) -> dict:
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
    duration = float((data.get("format") or {}).get("duration") or 0)
    fps = _parse_fps(str(stream.get("r_frame_rate") or "0/1"))
    return {
        "duration_seconds": duration,
        "width": int(stream.get("width") or 0),
        "height": int(stream.get("height") or 0),
        "fps": fps,
    }


def _parse_fps(value: str) -> float:
    if "/" not in value:
        return float(value or 0)
    numerator, denominator = value.split("/", 1)
    denominator_value = float(denominator or 1)
    return float(numerator or 0) / denominator_value if denominator_value else 0.0


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
    return VideoStats(
        path=str(path),
        duration_seconds=round(probe["duration_seconds"], 3),
        width=probe["width"],
        height=probe["height"],
        fps=round(probe["fps"], 3),
        sampled_frames=len(frames),
        motion_energy=round(float(np.mean(diffs)), 3),
        sharpness=round(float(np.mean(sharpness_values)), 3),
        brightness=round(float(np.mean(brightness_values)), 3),
        brightness_variance=round(float(np.var(brightness_values)), 3),
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
        "motion_energy_ratio": _safe_ratio(candidate_stats.motion_energy, baseline_stats.motion_energy),
        "sharpness_ratio": _safe_ratio(candidate_stats.sharpness, baseline_stats.sharpness),
        "brightness_delta": round(candidate_stats.brightness - baseline_stats.brightness, 3),
        "brightness_variance_ratio": _safe_ratio(candidate_stats.brightness_variance, baseline_stats.brightness_variance),
    }
    gates = {
        "duration_close": abs(differences["duration_delta_seconds"]) <= 0.5,
        "resolution_not_lower": (
            candidate_stats.width * candidate_stats.height >= baseline_stats.width * baseline_stats.height
        ),
        "motion_not_static": candidate_stats.motion_energy >= max(2.0, baseline_stats.motion_energy * 0.45),
        "sharpness_not_collapsed": candidate_stats.sharpness >= max(8.0, baseline_stats.sharpness * 0.45),
        "brightness_stable": candidate_stats.brightness_variance <= max(900.0, baseline_stats.brightness_variance * 3.0),
    }
    status = "passed" if all(gates.values()) else "needs_review"
    return {
        "kind": "seed_dance_baseline_comparison",
        "status": status,
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


def _safe_ratio(value: float, baseline: float) -> float | None:
    if not math.isfinite(baseline) or abs(baseline) < 1e-6:
        return None
    return round(value / baseline, 3)


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
