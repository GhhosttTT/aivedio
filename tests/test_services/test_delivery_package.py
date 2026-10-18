import json
import zipfile
from types import SimpleNamespace

import pytest

from src.services.delivery_package import DeliveryPackageError, build_delivery_package


def test_delivery_package_contains_media_evidence_and_hashes(tmp_path):
    final = tmp_path / "final.mp4"
    final.write_bytes(b"final-video")
    final.with_suffix(".composition_review.json").write_text(json.dumps({"status": "passed"}), encoding="utf-8")
    reviews = tmp_path / "reviews"
    reviews.mkdir()
    (reviews / "generation.json").write_text(json.dumps({"status": "passed"}), encoding="utf-8")
    project = SimpleNamespace(id=7, name="Pilot", theme="都市悬疑", outline="outline", script='{"scenes": []}', final_video_path=str(final), scenes=[])

    manifest = build_delivery_package(project, tmp_path, {"generation": {"status": "passed"}}, {"status": "ready"})

    package = tmp_path / "delivery" / "delivery_package.zip"
    assert package.is_file()
    assert manifest["status"] == "ready"
    assert any(item["path"] == "media/final_video.mp4" and len(item["sha256"]) == 64 for item in manifest["files"])
    with zipfile.ZipFile(package) as archive:
        names = set(archive.namelist())
    assert {"media/final_video.mp4", "reviews/generation.json", "metadata/project.json", "metadata/delivery_manifest.json"}.issubset(names)


def test_delivery_package_requires_ready_review(tmp_path):
    project = SimpleNamespace(id=7, name="Pilot", final_video_path=str(tmp_path / "final.mp4"), scenes=[])

    with pytest.raises(DeliveryPackageError, match="not ready"):
        build_delivery_package(project, tmp_path, {}, {"status": "blocked"})
