"""End-to-end delivery package build and verification with real media."""

import shutil
import subprocess
import zipfile
from pathlib import Path
from types import SimpleNamespace

import pytest

from src.services.delivery_package import (
    _sha256,
    build_delivery_package,
    verify_delivery_package,
)
from src.services.video_quality_metrics import video_candidate_metrics


@pytest.fixture()
def require_ffmpeg():
    if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
        pytest.skip("ffmpeg/ffprobe are required")


def _make_final(path: Path) -> Path:
    subprocess.run(
        [
            "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
            "-f", "lavfi", "-i", "testsrc=size=320x180:rate=24:duration=2",
            "-f", "lavfi", "-i", "sine=frequency=440:duration=2",
            "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-shortest", str(path),
        ],
        check=True,
    )
    return path


def test_delivery_package_round_trip_with_real_media(tmp_path, require_ffmpeg):
    final = _make_final(tmp_path / "final.mp4")
    metrics = video_candidate_metrics(final)
    approval = {
        "status": "passed",
        "video_path": str(final),
        "video_sha256": _sha256(final),
        "video_signature": (
            f"{final.resolve()}:{final.stat().st_size}:{final.stat().st_mtime_ns}"
        ),
        "final_technical_metrics": metrics,
    }
    project = SimpleNamespace(
        id=7,
        name="Pilot",
        theme="都市悬疑",
        outline="outline",
        script="{}",
        final_video_path=str(final),
        scenes=[],
    )
    reports = {
        "production_story": {"status": "passed"},
        "generation": {"status": "passed"},
        "seed_dance_baseline_comparison": {"status": "passed"},
        "final_composition": approval,
    }
    summary = {
        "status": "ready",
        "reports": {
            "production_story": "passed",
            "generation": "passed",
            "seed_dance_baseline_comparison": "passed",
        },
    }

    manifest = build_delivery_package(project, tmp_path, reports, summary)

    package = tmp_path / "delivery" / "delivery_package.zip"
    assert manifest["status"] == "ready"
    assert manifest["verification"]["status"] == "passed"
    assert package.is_file()
    verification = verify_delivery_package(package)
    assert verification["status"] == "passed"
    assert verification["checked_files"] > 0
    with zipfile.ZipFile(package) as archive:
        names = set(archive.namelist())
    assert {
        "media/final_video.mp4",
        "metadata/project.json",
        "metadata/delivery_manifest.json",
        "metadata/cover.json",
        "cover/cover.jpg",
    } <= names
