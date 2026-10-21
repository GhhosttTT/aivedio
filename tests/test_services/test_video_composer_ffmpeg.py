"""Real-ffmpeg smoke tests for the video composer."""

import shutil
import subprocess
from pathlib import Path

import pytest

from src.services.video_composer import VideoComposer


def _make_clip(path: Path, *, with_audio: bool = True) -> Path:
    command = [
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
        "-f", "lavfi", "-i", "testsrc=size=160x96:rate=12:duration=1",
    ]
    if with_audio:
        command += ["-f", "lavfi", "-i", "sine=frequency=440:duration=1"]
    command += ["-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p"]
    if with_audio:
        command += ["-c:a", "aac"]
    command += ["-shortest", str(path)]
    subprocess.run(command, check=True)
    return path


@pytest.fixture()
def require_ffmpeg():
    if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
        pytest.skip("ffmpeg/ffprobe are required")


def test_concat_videos_produces_playable_output(tmp_path, require_ffmpeg):
    clips = [_make_clip(tmp_path / f"clip{index}.mp4") for index in range(2)]
    output = tmp_path / "concat.mp4"

    result = VideoComposer().concat_videos([str(clip) for clip in clips], str(output))

    assert Path(result) == output
    assert output.is_file() and output.stat().st_size > 0
    assert VideoComposer()._get_duration(str(output)) == pytest.approx(2.0, abs=0.3)


def test_audio_stream_detection_on_real_clips(tmp_path, require_ffmpeg):
    with_audio = _make_clip(tmp_path / "with-audio.mp4", with_audio=True)
    without_audio = _make_clip(tmp_path / "silent.mp4", with_audio=False)
    composer = VideoComposer()

    assert composer.has_audio_stream(str(with_audio)) is True
    assert composer.has_audio_stream(str(without_audio)) is False
