"""Real-ffmpeg tests for localized subtitle rendering."""

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from src.services.subtitle_rendering_service import SubtitleRenderingService


@pytest.fixture()
def require_ffmpeg():
    if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
        pytest.skip("ffmpeg/ffprobe are required")


def _make_video(path: Path, seconds: float = 2.0) -> Path:
    subprocess.run(
        [
            "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
            "-f", "lavfi", "-i", f"testsrc=size=320x180:rate=24:duration={seconds}",
            "-f", "lavfi", "-i", f"sine=frequency=440:duration={seconds}",
            "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-shortest", str(path),
        ],
        check=True,
    )
    return path


def _write_srt(path: Path, text: str = "Hello") -> Path:
    path.write_text(
        f"1\n00:00:00,200 --> 00:00:01,200\n{text}\n",
        encoding="utf-8",
    )
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


def test_render_all_produces_per_language_videos(tmp_path, require_ffmpeg):
    video = _make_video(tmp_path / "clean.mp4")
    subtitles = tmp_path / "subtitles"
    subtitles.mkdir()
    _write_srt(subtitles / "en.srt", "Hello")
    _write_srt(subtitles / "es.srt", "Hola")
    output = tmp_path / "rendered"

    results = SubtitleRenderingService().render_all(
        str(video), str(subtitles), str(output), ["en", "es"]
    )

    assert set(results) == {"en", "es"}
    manifest = json.loads((output / "rendered_videos.json").read_text(encoding="utf-8"))
    assert set(manifest["videos"]) == {"en", "es"}
    for language, result in results.items():
        rendered = Path(result.video_path)
        assert rendered.is_file() and rendered.stat().st_size > 0
        assert _duration(rendered) == pytest.approx(2.0, abs=0.3)
        assert _has_audio(rendered) is True


def test_render_one_handles_apostrophe_in_project_path(tmp_path, require_ffmpeg):
    work = tmp_path / "it's a dir"
    work.mkdir()
    video = _make_video(work / "clean.mp4")
    subtitle = _write_srt(work / "en.srt")
    output = work / "rendered.mp4"

    result = SubtitleRenderingService().render_one(
        str(video), str(subtitle), str(output), "en"
    )

    assert Path(result) == output
    assert output.is_file() and output.stat().st_size > 0
