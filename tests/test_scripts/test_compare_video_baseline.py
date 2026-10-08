import shutil
from pathlib import Path

import cv2
import numpy as np
import pytest

from scripts.compare_video_baseline import VideoStats, _parse_fps, compare


requires_ffprobe = pytest.mark.skipif(shutil.which("ffprobe") is None, reason="ffprobe is required")


def _write_test_video(path: Path, *, frames: int = 12, moving: bool = True, size: tuple[int, int] = (160, 90)) -> None:
    width, height = size
    writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"mp4v"), 8, size)
    assert writer.isOpened()
    for index in range(frames):
        frame = np.full((height, width, 3), 40, dtype=np.uint8)
        offset = min(index * 5 if moving else 0, max(width - 50, 0))
        top = max(4, height // 3)
        bottom = min(height - 4, top + max(16, height // 3))
        cv2.rectangle(frame, (10 + offset, top), (min(width - 8, 45 + offset), bottom), (220, 220, 220), -1)
        writer.write(frame)
    writer.release()


def test_parse_fps_fraction():
    assert _parse_fps("30000/1001") == pytest.approx(29.970, rel=0.001)


@requires_ffprobe
def test_compare_video_baseline_reports_measurable_gates(tmp_path):
    baseline = tmp_path / "seed_dance.mp4"
    candidate = tmp_path / "candidate.mp4"
    _write_test_video(baseline)
    _write_test_video(candidate)

    report = compare(candidate, baseline, max_samples=6, artifact_dir=tmp_path)

    assert report["kind"] == "seed_dance_baseline_comparison"
    assert report["status"] == "passed"
    assert report["score"] >= report["min_score"]
    assert report["candidate"]["sampled_frames"] >= 4
    assert report["gates"]["duration_close"] is True
    assert report["gates"]["motion_not_static"] is True
    assert Path(report["contact_sheet_path"]).is_file()
    assert Path(report["contact_sheet_path"]).name == "seed_dance_contact_sheet.png"


@requires_ffprobe
def test_compare_video_baseline_blocks_static_candidate(tmp_path):
    baseline = tmp_path / "seed_dance.mp4"
    candidate = tmp_path / "candidate_static.mp4"
    _write_test_video(baseline, moving=True)
    _write_test_video(candidate, moving=False)

    report = compare(candidate, baseline, max_samples=6, artifact_dir=tmp_path)

    assert report["status"] == "needs_review"
    assert report["score"] < report["min_score"]
    assert report["gates"]["motion_not_static"] is False


@requires_ffprobe
def test_compare_video_baseline_blocks_aspect_ratio_mismatch(tmp_path):
    baseline = tmp_path / "seed_dance_vertical.mp4"
    candidate = tmp_path / "candidate_horizontal.mp4"
    _write_test_video(baseline, size=(90, 160))
    _write_test_video(candidate, size=(160, 90))

    report = compare(candidate, baseline, max_samples=6, artifact_dir=tmp_path)

    assert report["status"] == "needs_review"
    assert report["gates"]["resolution_not_lower"] is True
    assert report["gates"]["aspect_ratio_close"] is False
    assert abs(report["differences"]["aspect_ratio_delta"]) > 1


def test_compare_video_baseline_rejects_aspect_ratio_mismatch_without_video_probe(monkeypatch, tmp_path):
    def fake_stats(path, max_samples):
        if "baseline" in path.name:
            return VideoStats(
                path=str(path),
                duration_seconds=2.0,
                width=90,
                height=160,
                fps=24,
                sampled_frames=6,
                motion_energy=8,
                sharpness=30,
                brightness=90,
                brightness_variance=40,
            )
        return VideoStats(
            path=str(path),
            duration_seconds=2.0,
            width=160,
            height=90,
            fps=24,
            sampled_frames=6,
            motion_energy=8,
            sharpness=30,
            brightness=90,
            brightness_variance=40,
        )

    monkeypatch.setattr("scripts.compare_video_baseline.video_stats", fake_stats)

    report = compare(tmp_path / "candidate.mp4", tmp_path / "baseline.mp4", max_samples=6)

    assert report["status"] == "needs_review"
    assert report["gates"]["resolution_not_lower"] is True
    assert report["gates"]["aspect_ratio_close"] is False
