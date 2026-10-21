"""Real-ffmpeg tests for cover extraction."""

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from src.services.cover_generator import CoverGenerationError, generate_cover


@pytest.fixture()
def require_ffmpeg():
    if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
        pytest.skip("ffmpeg/ffprobe are required")


def _make_video(path: Path, seconds: float = 2.0) -> Path:
    subprocess.run(
        [
            "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
            "-f", "lavfi", "-i", f"testsrc=size=320x180:rate=24:duration={seconds}",
            "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p",
            str(path),
        ],
        check=True,
    )
    return path


def _image_size(path: Path) -> tuple[int, int]:
    result = subprocess.run(
        [
            "ffprobe", "-v", "error", "-select_streams", "v:0",
            "-show_entries", "stream=width,height", "-of", "json", str(path),
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    stream = json.loads(result.stdout)["streams"][0]
    return int(stream["width"]), int(stream["height"])


def test_generate_cover_extracts_expected_frame(tmp_path, require_ffmpeg):
    video = _make_video(tmp_path / "final.mp4")
    cover = tmp_path / "cover.jpg"

    report = generate_cover(video, cover, width=768, height=1344)

    assert report["status"] == "ready"
    assert cover.is_file() and cover.stat().st_size > 0
    assert (report["width"], report["height"]) == (768, 1344)
    assert _image_size(cover) == (768, 1344)
    assert 0.1 <= report["timestamp_seconds"] <= 1.9


def test_generate_cover_rejects_missing_video(tmp_path):
    with pytest.raises(CoverGenerationError, match="missing"):
        generate_cover(tmp_path / "missing.mp4", tmp_path / "cover.jpg")
