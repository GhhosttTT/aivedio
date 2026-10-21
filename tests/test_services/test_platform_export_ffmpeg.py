"""Real-ffmpeg tests for platform export presets and approval gating."""

import hashlib
import json
import shutil
import subprocess
from pathlib import Path

import pytest

from src.services.platform_export import (
    PlatformExportError,
    _signature,
    export_platform_video,
)
from src.services.video_quality_metrics import video_candidate_metrics


@pytest.fixture()
def require_ffmpeg():
    if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
        pytest.skip("ffmpeg/ffprobe are required")


def _make_source(path: Path, seconds: float = 2.0) -> Path:
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


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _approval(source: Path) -> dict:
    return {
        "status": "passed",
        "video_path": str(source),
        "video_sha256": _sha256(source),
        "video_signature": _signature(source),
        "final_technical_metrics": video_candidate_metrics(source),
        "final_audio_expected": False,
    }


def _probe_geometry(path: Path) -> tuple[int, int, float]:
    result = subprocess.run(
        [
            "ffprobe", "-v", "error", "-select_streams", "v:0",
            "-show_entries", "stream=width,height,avg_frame_rate",
            "-of", "json", str(path),
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    stream = json.loads(result.stdout)["streams"][0]
    numerator, denominator = stream["avg_frame_rate"].split("/")
    fps = float(numerator) / max(float(denominator), 1.0)
    return int(stream["width"]), int(stream["height"]), fps


def test_platform_export_honors_square_preset(tmp_path, require_ffmpeg):
    source = _make_source(tmp_path / "final.mp4")
    output = export_platform_video(
        source,
        tmp_path / "project",
        "square",
        approval_report=_approval(source),
    )

    export_path = Path(output["output_path"])
    assert export_path.is_file() and export_path.stat().st_size > 0
    width, height, fps = _probe_geometry(export_path)
    assert (width, height) == (1080, 1080)
    assert abs(fps - 30.0) < 0.5
    assert output["width"] == 1080 and output["height"] == 1080


def test_platform_export_rejects_stale_approval(tmp_path, require_ffmpeg):
    source = _make_source(tmp_path / "final.mp4")
    approval = _approval(source)
    approval["video_sha256"] = "0" * 64

    with pytest.raises(PlatformExportError, match="stale"):
        export_platform_video(
            source, tmp_path / "project", "square", approval_report=approval
        )

    assert not (tmp_path / "project" / "exports" / "square.mp4").exists()
