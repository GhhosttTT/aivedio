"""Real media decoding tests. These do not claim to test an AI model's quality."""

import json
import shutil
import subprocess
from unittest.mock import Mock

import pytest
from PIL import Image, ImageStat

from src.services.generation_review import GenerationReviewService


pytestmark = pytest.mark.skipif(
    not (shutil.which("ffmpeg") and shutil.which("ffprobe")), reason="FFmpeg and ffprobe are required"
)


@pytest.fixture
def real_video(tmp_path):
    path = tmp_path / "test_pattern.mp4"
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i",
                    "testsrc2=size=160x90:rate=12", "-t", "2.2", "-c:v", "libx264",
                    "-pix_fmt", "yuv420p", str(path)], check=True, capture_output=True, timeout=60)
    return path


def test_real_frames_are_nonblank_and_cover_clip(real_video, tmp_path):
    frames = GenerationReviewService.sample_frames(real_video, tmp_path / "frames")
    assert len(frames) == 4
    assert frames[0]["timestamp"] < 0.2
    assert frames[-1]["timestamp"] > 2.0
    assert len({frame["sha256"] for frame in frames}) > 1
    for frame in frames:
        with Image.open(frame["path"]) as image:
            assert max(ImageStat.Stat(image).stddev) > 10
            assert image.width <= 768 and image.height <= 768


def test_real_decoding_then_unavailable_model_retains_evidence(real_video, tmp_path):
    reviewer = Mock()
    reviewer.evaluate.side_effect = RuntimeError("review model offline")
    path = tmp_path / "review.json"
    report = GenerationReviewService(reviewer).review_video(
        str(real_video), {"scene_number": 1, "description": "Moving test pattern"}, path,
    )
    assert report["status"] == "error"
    assert len(report["frames"]) == 4
    assert "average" not in report
    assert json.loads(path.read_text())["error"] == "review model offline"


def test_corrupt_video_fails_before_model(tmp_path):
    path = tmp_path / "bad.mp4"
    path.write_bytes(b"not a video")
    reviewer = Mock()
    report = GenerationReviewService(reviewer).review_video(str(path), {"scene_number": 1}, tmp_path / "review.json")
    assert report["status"] == "error"
    reviewer.evaluate.assert_not_called()
