import shutil
from pathlib import Path

import cv2
import numpy as np
import pytest

from scripts.compare_video_baseline import _parse_fps, compare


pytestmark = pytest.mark.skipif(shutil.which("ffprobe") is None, reason="ffprobe is required")


def _write_test_video(path: Path, *, frames: int = 12, moving: bool = True) -> None:
    writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"mp4v"), 8, (160, 90))
    assert writer.isOpened()
    for index in range(frames):
        frame = np.full((90, 160, 3), 40, dtype=np.uint8)
        offset = index * 5 if moving else 0
        cv2.rectangle(frame, (10 + offset, 25), (45 + offset, 65), (220, 220, 220), -1)
        writer.write(frame)
    writer.release()


def test_parse_fps_fraction():
    assert _parse_fps("30000/1001") == pytest.approx(29.970, rel=0.001)


def test_compare_video_baseline_reports_measurable_gates(tmp_path):
    baseline = tmp_path / "seed_dance.mp4"
    candidate = tmp_path / "candidate.mp4"
    _write_test_video(baseline)
    _write_test_video(candidate)

    report = compare(candidate, baseline, max_samples=6, artifact_dir=tmp_path)

    assert report["kind"] == "seed_dance_baseline_comparison"
    assert report["status"] == "passed"
    assert report["candidate"]["sampled_frames"] >= 4
    assert report["gates"]["duration_close"] is True
    assert report["gates"]["motion_not_static"] is True
    assert Path(report["contact_sheet_path"]).is_file()
    assert Path(report["contact_sheet_path"]).name == "seed_dance_contact_sheet.png"
