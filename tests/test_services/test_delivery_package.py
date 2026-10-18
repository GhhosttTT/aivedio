import json
import zipfile
from types import SimpleNamespace

import pytest

from src.services.delivery_package import DeliveryPackageError, _sha256, build_delivery_package, verify_delivery_package


def _passed_final_composition(final):
    return {"status": "passed", "video_path": str(final), "video_sha256": _sha256(final)}


def test_delivery_package_contains_media_evidence_and_hashes(tmp_path):
    final = tmp_path / "final.mp4"
    final.write_bytes(b"final-video")
    final.with_suffix(".composition_review.json").write_text(json.dumps({"status": "passed"}), encoding="utf-8")
    reviews = tmp_path / "reviews"
    reviews.mkdir()
    (reviews / "generation.json").write_text(json.dumps({"status": "passed"}), encoding="utf-8")
    project = SimpleNamespace(id=7, name="Pilot", theme="都市悬疑", outline="outline", script='{"scenes": []}', final_video_path=str(final), scenes=[])

    manifest = build_delivery_package(project, tmp_path, {"generation": {"status": "passed"}, "final_composition": _passed_final_composition(final)}, {"status": "ready"})

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


def test_delivery_package_requires_final_composition_evidence(tmp_path):
    final = tmp_path / "final.mp4"
    final.write_bytes(b"final-video")
    project = SimpleNamespace(id=7, name="Pilot", final_video_path=str(final), scenes=[])

    with pytest.raises(DeliveryPackageError, match="Final composition review"):
        build_delivery_package(project, tmp_path, {"generation": {"status": "passed"}}, {"status": "ready"})


def test_delivery_package_persists_dynamic_audit_evidence(tmp_path):
    final = tmp_path / "final.mp4"
    final.write_bytes(b"final-video")
    project = SimpleNamespace(id=7, name="Pilot", final_video_path=str(final), scenes=[])

    build_delivery_package(
        project,
        tmp_path,
        {
            "generation": {"status": "passed"},
            "final_composition": _passed_final_composition(final),
            "continuity_audit": {"kind": "continuity_audit", "status": "passed", "pair_count": 1},
            "rhythm_audit": {"kind": "rhythm_audit", "status": "passed", "scene_count": 2},
        },
        {"status": "ready"},
    )

    assert (tmp_path / "reviews" / "continuity_audit.json").is_file()
    assert (tmp_path / "reviews" / "rhythm_audit.json").is_file()
    with zipfile.ZipFile(tmp_path / "delivery" / "delivery_package.zip") as archive:
        names = set(archive.namelist())
    assert {"reviews/continuity_audit.json", "reviews/rhythm_audit.json"}.issubset(names)


def test_delivery_package_verification_detects_tampering(tmp_path):
    final = tmp_path / "final.mp4"
    final.write_bytes(b"final-video")
    project = SimpleNamespace(id=7, name="Pilot", final_video_path=str(final), scenes=[])
    manifest = build_delivery_package(project, tmp_path, {"generation": {"status": "passed"}, "final_composition": _passed_final_composition(final)}, {"status": "ready"})
    package = tmp_path / "delivery" / "delivery_package.zip"
    assert manifest["verification"]["status"] == "passed"

    tampered = tmp_path / "tampered.zip"
    with zipfile.ZipFile(package) as source, zipfile.ZipFile(tampered, "w") as target:
        for item in source.infolist():
            payload = source.read(item.filename)
            if item.filename == "media/final_video.mp4":
                payload = b"tampered"
            target.writestr(item, payload)
    verification = verify_delivery_package(tampered)
    assert verification["status"] == "failed"
    assert any("SHA-256 mismatch" in error for error in verification["errors"])


def test_delivery_package_includes_scene_assets_and_quality_sidecars(tmp_path):
    final = tmp_path / "final.mp4"
    image = tmp_path / "scene.png"
    video = tmp_path / "scene.mp4"
    audio = tmp_path / "scene.wav"
    subtitle = tmp_path / "scene.srt"
    for path, payload in (
        (final, b"final"), (image, b"image"), (video, b"video"),
        (audio, b"audio"), (subtitle, b"subtitle"),
    ):
        path.write_bytes(payload)
    video.with_suffix(".quality.json").write_text('{"status":"passed"}', encoding="utf-8")
    audio.with_suffix(".quality.json").write_text('{"status":"passed"}', encoding="utf-8")
    subtitle.with_suffix(".quality.json").write_text('{"status":"passed"}', encoding="utf-8")
    scene = SimpleNamespace(
        scene_number=1,
        image_path=str(image),
        video_path=str(video),
        audio_path=str(audio),
        subtitle_path=str(subtitle),
    )
    project = SimpleNamespace(
        id=7, name="Pilot", theme="悬疑", outline="outline", script="{}",
        final_video_path=str(final), scenes=[scene],
    )

    build_delivery_package(project, tmp_path, {"generation": {"status": "passed"}, "final_composition": _passed_final_composition(final)}, {"status": "ready"})

    with zipfile.ZipFile(tmp_path / "delivery" / "delivery_package.zip") as archive:
        names = set(archive.namelist())
    assert "media/scenes/scene_0001_image.png" in names
    assert "media/scenes/scene_0001_video.mp4" in names
    assert "media/scenes/scene_0001_audio.wav" in names
    assert "reviews/scenes/scene_0001_video.quality.json" in names
    assert "reviews/scenes/scene_0001_subtitle.quality.json" in names
