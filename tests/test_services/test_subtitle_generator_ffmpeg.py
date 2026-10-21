"""Real-ffmpeg smoke tests for subtitle generation and burn-in."""

import shutil
import subprocess
from pathlib import Path

import pytest

from src.services.subtitle_generator import SubtitleGenerator


@pytest.fixture()
def require_ffmpeg():
    if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
        pytest.skip("ffmpeg/ffprobe are required")


def _make_video(path: Path, *, with_audio: bool) -> Path:
    command = [
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
        "-f", "lavfi", "-i", "testsrc=size=320x180:rate=24:duration=2",
    ]
    if with_audio:
        command += ["-f", "lavfi", "-i", "sine=frequency=440:duration=2"]
    command += ["-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p"]
    if with_audio:
        command += ["-c:a", "aac"]
    command += ["-shortest", str(path)]
    subprocess.run(command, check=True)
    return path


def _duration(path: Path) -> float:
    result = subprocess.run(
        [
            "ffprobe", "-v", "error", "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1", str(path),
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    return float(result.stdout.strip())


def _has_audio(path: Path) -> bool:
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "a:0", "-show_entries",
         "stream=index", "-of", "csv=p=0", str(path)],
        capture_output=True,
        text=True,
        check=True,
    )
    return bool(result.stdout.strip())


def test_generate_srt_writes_expected_timing(tmp_path):
    srt = SubtitleGenerator().generate_srt(
        [{"text": "第一句 First line", "start_time": 0.2, "duration": 1.2}],
        str(tmp_path / "subtitle.srt"),
    )

    content = Path(srt).read_text(encoding="utf-8")
    assert "00:00:00,200 --> 00:00:01,399" in content
    assert "第一句 First line" in content


def test_burn_subtitle_produces_video_and_keeps_audio(tmp_path, require_ffmpeg):
    video = _make_video(tmp_path / "input.mp4", with_audio=True)
    srt = SubtitleGenerator().generate_srt(
        [{"text": "烧录字幕 Test", "start_time": 0.2, "duration": 1.2}],
        str(tmp_path / "subtitle.srt"),
    )
    output = tmp_path / "subtitled.mp4"

    result = SubtitleGenerator().burn_subtitle(str(video), srt, str(output))

    assert Path(result) == output
    assert output.is_file() and output.stat().st_size > 0
    assert _duration(output) == pytest.approx(2.0, abs=0.3)
    assert _has_audio(output) is True


def test_burn_subtitle_handles_apostrophe_in_project_path(tmp_path, require_ffmpeg):
    work = tmp_path / "it's a dir"
    work.mkdir()
    video = _make_video(work / "input.mp4", with_audio=False)
    srt = SubtitleGenerator().generate_srt(
        [{"text": "Apostrophe Test", "start_time": 0.1, "duration": 0.8}],
        str(work / "subtitle.srt"),
    )
    output = work / "subtitled.mp4"

    result = SubtitleGenerator().burn_subtitle(str(video), srt, str(output))

    assert Path(result) == output
    assert output.is_file() and output.stat().st_size > 0
