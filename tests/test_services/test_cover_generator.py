from pathlib import Path
import subprocess
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from src.services.cover_generator import CoverGenerationError, generate_cover


def test_cover_generator_uses_hook_timestamp_and_vertical_frame(tmp_path):
    video = tmp_path / "final.mp4"
    cover = tmp_path / "cover.jpg"
    video.write_bytes(b"video")

    def run(command, **_kwargs):
        if command[0] == "ffprobe":
            return SimpleNamespace(stdout="10.0\n")
        Path(command[-1]).write_bytes(b"jpeg")
        return SimpleNamespace(stdout="", returncode=0)

    with patch("src.services.cover_generator.subprocess.run", side_effect=run) as mocked:
        report = generate_cover(video, cover)

    assert report["status"] == "ready"
    assert report["timestamp_seconds"] == 1.8
    ffmpeg = mocked.call_args.args[0]
    assert "scale=768:1344" in ffmpeg[ffmpeg.index("-vf") + 1]
    assert cover.read_bytes() == b"jpeg"


def test_cover_generator_accepts_platform_dimensions(tmp_path):
    video = tmp_path / "landscape.mp4"
    cover = tmp_path / "landscape.jpg"
    video.write_bytes(b"video")

    def run(command, **_kwargs):
        if command[0] == "ffprobe":
            return SimpleNamespace(stdout="5.0\n")
        Path(command[-1]).write_bytes(b"jpeg")
        return SimpleNamespace(stdout="", returncode=0)

    with patch("src.services.cover_generator.subprocess.run", side_effect=run) as mocked:
        report = generate_cover(video, cover, width=1920, height=1080)

    assert report["width"] == 1920
    assert report["height"] == 1080
    ffmpeg = mocked.call_args.args[0]
    assert "scale=1920:1080" in ffmpeg[ffmpeg.index("-vf") + 1]


def test_cover_generator_keeps_previous_cover_when_ffmpeg_fails(tmp_path):
    video = tmp_path / "final.mp4"
    cover = tmp_path / "cover.jpg"
    video.write_bytes(b"video")
    cover.write_bytes(b"previous-good-cover")

    def fail_run(command, **_kwargs):
        if command[0] == "ffprobe":
            return SimpleNamespace(stdout="10.0\n")
        raise subprocess.CalledProcessError(1, command, stderr="ffmpeg failed")

    with patch("src.services.cover_generator.subprocess.run", side_effect=fail_run):
        with pytest.raises(CoverGenerationError, match="Cover extraction failed"):
            generate_cover(video, cover)

    assert cover.read_bytes() == b"previous-good-cover"
    assert not list(tmp_path.glob(".cover.*.part.jpg"))
