import json
import hashlib
import zipfile
from types import SimpleNamespace

import pytest

from src.services.delivery_package import DeliveryPackageError, _sha256, build_delivery_package, verify_delivery_package


def _passed_final_composition(final):
    return {
        "status": "passed",
        "video_path": str(final),
        "video_sha256": _sha256(final),
        "final_technical_metrics": {
            "status": "available",
            "temporal_sample_evidence": "sufficient",
        },
    }


def test_delivery_package_contains_media_evidence_and_hashes(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "src.services.video_quality_metrics.video_candidate_metrics",
        lambda path, max_samples=8: {
            "status": "available",
            "temporal_sample_evidence": "sufficient",
        },
    )
    final = tmp_path / "final.mp4"
    final.write_bytes(b"final-video")
    final.with_suffix(".composition_review.json").write_text(
        json.dumps(_passed_final_composition(final)), encoding="utf-8"
    )
    reviews = tmp_path / "reviews"
    reviews.mkdir()
    (reviews / "generation.json").write_text(json.dumps({"status": "passed"}), encoding="utf-8")
    exports = tmp_path / "exports"
    exports.mkdir()
    (exports / "douyin.mp4").write_bytes(b"platform-video")
    (exports / "douyin.json").write_text(json.dumps({
        "status": "ready",
        "preset": "douyin",
        "output_sha256": _sha256(exports / "douyin.mp4"),
        "technical_metrics": {"status": "available", "temporal_sample_evidence": "sufficient"},
    }), encoding="utf-8")
    (tmp_path / "topic_brief.json").write_text(json.dumps({"platform": "抖音", "genre": "都市悬疑"}), encoding="utf-8")
    (tmp_path / "market_signals.json").write_text(json.dumps({"comparables": [{"title": "对照剧 A"}]}), encoding="utf-8")
    project = SimpleNamespace(id=7, name="Pilot", theme="都市悬疑", outline="outline", script='{"scenes": []}', final_video_path=str(final), scenes=[])

    manifest = build_delivery_package(project, tmp_path, {
        "generation": {
            "status": "passed",
            "generation_run_evidence": {
                "status": "passed",
                "request_contract_hashes": ["request-hash"],
                "spatial_scene_contract_hashes": ["scene-hash"],
                "spatial_project_signatures": ["project-hash"],
                "providers": ["seedance_api"],
            },
        },
        "final_composition": _passed_final_composition(final),
    }, {"status": "ready"})

    package = tmp_path / "delivery" / "delivery_package.zip"
    assert package.is_file()
    assert manifest["status"] == "ready"
    assert manifest["schema_version"] == 2
    assert any(item["path"] == "media/final_video.mp4" and len(item["sha256"]) == 64 for item in manifest["files"])
    with zipfile.ZipFile(package) as archive:
        names = set(archive.namelist())
        assert {"media/final_video.mp4", "reviews/generation.json", "metadata/project.json", "metadata/delivery_manifest.json"}.issubset(names)
        assert "metadata/review_index.json" in names
        review_index = json.loads(archive.read("metadata/review_index.json").decode())
        assert review_index["final_video_sha256"] == manifest["files"][0]["sha256"]
        assert review_index["critical_reports"]["final_composition"]["status"] == "passed"
    assert "metadata/cover.json" in names
    assert {"exports/douyin.mp4", "exports/douyin.json"}.issubset(names)
    with zipfile.ZipFile(package) as archive:
        metadata = json.loads(archive.read("metadata/project.json").decode("utf-8"))
    assert metadata["topic_brief"]["platform"] == "抖音"
    assert metadata["market_signals"]["comparables"][0]["title"] == "对照剧 A"
    assert metadata["generation_evidence"][0]["spatial_scene_contract_hashes"] == ["scene-hash"]
    assert manifest["generation_evidence"][0]["request_contract_hashes"] == ["request-hash"]
    assert "metadata/platform_covers.json" in names


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


def test_delivery_package_persists_in_memory_final_composition_report(tmp_path):
    final = tmp_path / "final.mp4"
    final.write_bytes(b"final-video")
    project = SimpleNamespace(id=7, name="Pilot", final_video_path=str(final), scenes=[])
    report = _passed_final_composition(final)

    manifest = build_delivery_package(
        project,
        tmp_path,
        {"generation": {"status": "passed"}, "final_composition": report},
        {"status": "ready"},
    )

    assert manifest["verification"]["status"] == "passed"
    with zipfile.ZipFile(tmp_path / "delivery" / "delivery_package.zip") as archive:
        packaged = json.loads(archive.read("reviews/final_composition.json").decode("utf-8"))
    assert packaged == report


def test_delivery_package_rejects_missing_native_audio_evidence(tmp_path):
    final = tmp_path / "final.mp4"
    final.write_bytes(b"final-video")
    project = SimpleNamespace(id=7, name="Pilot", final_video_path=str(final), scenes=[])
    report = _passed_final_composition(final)
    report["final_audio_expected"] = True

    with pytest.raises(DeliveryPackageError, match="native-audio evidence"):
        build_delivery_package(
            project,
            tmp_path,
            {"generation": {"status": "passed"}, "final_composition": report},
            {"status": "ready"},
        )


def test_delivery_package_rejects_final_review_without_temporal_evidence(tmp_path):
    final = tmp_path / "final.mp4"
    final.write_bytes(b"final-video")
    project = SimpleNamespace(id=7, name="Pilot", final_video_path=str(final), scenes=[])
    report = {
        "status": "passed",
        "video_path": str(final),
        "video_sha256": _sha256(final),
    }

    with pytest.raises(DeliveryPackageError, match="technical evidence"):
        build_delivery_package(project, tmp_path, {"final_composition": report}, {"status": "ready"})


def test_delivery_package_accepts_approved_manual_final_review(tmp_path):
    final = tmp_path / "final.mp4"
    final.write_bytes(b"final-video")
    project = SimpleNamespace(id=7, name="Pilot", final_video_path=str(final), scenes=[])
    report = {
        "status": "needs_review",
        "video_path": str(final),
        "video_sha256": _sha256(final),
        "human_decision": {"decision": "approved", "note": "人工确认"},
        "final_technical_metrics": {
            "status": "available",
            "temporal_sample_evidence": "sufficient",
        },
    }

    manifest = build_delivery_package(
        project,
        tmp_path,
        {"generation": {"status": "passed"}, "final_composition": report},
        {"status": "ready"},
    )

    assert manifest["status"] == "ready"


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


def test_delivery_package_verification_rejects_unmanifested_file(tmp_path):
    final = tmp_path / "final.mp4"
    final.write_bytes(b"final-video")
    project = SimpleNamespace(id=7, name="Pilot", final_video_path=str(final), scenes=[])
    build_delivery_package(
        project,
        tmp_path,
        {"generation": {"status": "passed"}, "final_composition": _passed_final_composition(final)},
        {"status": "ready"},
    )
    package = tmp_path / "delivery" / "delivery_package.zip"
    tampered = tmp_path / "extra-file.zip"
    with zipfile.ZipFile(package) as source, zipfile.ZipFile(tampered, "w") as target:
        for item in source.infolist():
            target.writestr(item, source.read(item.filename))
        target.writestr("metadata/unapproved.txt", b"not covered by manifest")

    verification = verify_delivery_package(tampered)
    assert verification["status"] == "failed"
    assert any("missing from manifest" in error for error in verification["errors"])


def test_delivery_package_verification_rejects_duplicate_manifest_path(tmp_path):
    final = tmp_path / "final.mp4"
    final.write_bytes(b"final-video")
    project = SimpleNamespace(id=7, name="Pilot", final_video_path=str(final), scenes=[])
    build_delivery_package(
        project,
        tmp_path,
        {"generation": {"status": "passed"}, "final_composition": _passed_final_composition(final)},
        {"status": "ready"},
    )
    package = tmp_path / "delivery" / "delivery_package.zip"
    with zipfile.ZipFile(package) as source:
        manifest = json.loads(source.read("metadata/delivery_manifest.json"))
        manifest["files"].append(dict(manifest["files"][0]))
        tampered = tmp_path / "duplicate-manifest.zip"
        with zipfile.ZipFile(tampered, "w") as target:
            for item in source.infolist():
                payload = source.read(item.filename)
                if item.filename == "metadata/delivery_manifest.json":
                    payload = (json.dumps(manifest) + "\n").encode("utf-8")
                target.writestr(item, payload)

    verification = verify_delivery_package(tampered)
    assert verification["status"] == "failed"
    assert any("Duplicate manifest path" in error for error in verification["errors"])


def test_delivery_package_verification_rejects_inconsistent_review_index(tmp_path):
    final = tmp_path / "final.mp4"
    final.write_bytes(b"final-video")
    project = SimpleNamespace(id=7, name="Pilot", final_video_path=str(final), scenes=[])
    build_delivery_package(
        project,
        tmp_path,
        {"generation": {"status": "passed"}, "final_composition": _passed_final_composition(final)},
        {"status": "ready"},
    )
    package = tmp_path / "delivery" / "delivery_package.zip"
    tampered = tmp_path / "inconsistent-review-index.zip"
    with zipfile.ZipFile(package) as source:
        review_index = json.loads(source.read("metadata/review_index.json"))
        review_index["review_files"].append({"path": "reviews/missing.json", "size": 0, "sha256": "0" * 64})
        review_payload = (json.dumps(review_index) + "\n").encode("utf-8")
        manifest = json.loads(source.read("metadata/delivery_manifest.json"))
        entry = next(item for item in manifest["files"] if item["path"] == "metadata/review_index.json")
        entry["size"] = len(review_payload)
        entry["sha256"] = hashlib.sha256(review_payload).hexdigest()
        with zipfile.ZipFile(tampered, "w") as target:
            for item in source.infolist():
                payload = source.read(item.filename)
                if item.filename == "metadata/review_index.json":
                    payload = review_payload
                elif item.filename == "metadata/delivery_manifest.json":
                    payload = (json.dumps(manifest) + "\n").encode("utf-8")
                target.writestr(item, payload)

    verification = verify_delivery_package(tampered)
    assert verification["status"] == "failed"
    assert any("unmanifested file" in error for error in verification["errors"])


def test_delivery_package_verification_rejects_stale_final_composition_report(tmp_path):
    final = tmp_path / "final.mp4"
    final.write_bytes(b"final-video")
    project = SimpleNamespace(id=7, name="Pilot", final_video_path=str(final), scenes=[])
    build_delivery_package(
        project,
        tmp_path,
        {"generation": {"status": "passed"}, "final_composition": _passed_final_composition(final)},
        {"status": "ready"},
    )
    package = tmp_path / "delivery" / "delivery_package.zip"
    final_review = json.dumps({
        "status": "passed",
        "video_path": str(final),
        "video_sha256": "0" * 64,
        "final_technical_metrics": {
            "status": "available",
            "temporal_sample_evidence": "sufficient",
        },
    }).encode("utf-8")
    tampered = tmp_path / "stale-final-review.zip"
    with zipfile.ZipFile(package) as source:
        manifest = json.loads(source.read("metadata/delivery_manifest.json"))
        manifest["files"].append({
            "path": "reviews/final_composition.json",
            "size": len(final_review),
            "sha256": hashlib.sha256(final_review).hexdigest(),
        })
        with zipfile.ZipFile(tampered, "w") as target:
            for item in source.infolist():
                payload = source.read(item.filename)
                if item.filename == "metadata/delivery_manifest.json":
                    payload = (json.dumps(manifest) + "\n").encode("utf-8")
                target.writestr(item, payload)
            target.writestr("reviews/final_composition.json", final_review)
    verification = verify_delivery_package(tampered)

    assert verification["status"] == "failed"
    assert any("Final composition review video hash" in error for error in verification["errors"])


def test_delivery_package_revalidates_detailed_final_metrics(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "src.services.video_quality_metrics.video_candidate_metrics",
        lambda path, max_samples=8: {
            "status": "available",
            "temporal_sample_evidence": "sufficient",
        },
    )
    final = tmp_path / "final.mp4"
    final.write_bytes(b"final-video")
    report = _passed_final_composition(final)
    report["final_technical_metrics"].update({"width": 720, "height": 1280, "sampled_frames": 8})
    final.with_suffix(".composition_review.json").write_text(json.dumps(report), encoding="utf-8")
    project = SimpleNamespace(id=7, name="Pilot", final_video_path=str(final), scenes=[])

    manifest = build_delivery_package(
        project,
        tmp_path,
        {"generation": {"status": "passed"}, "final_composition": report},
        {"status": "ready"},
    )

    assert manifest["verification"]["status"] == "passed"


def test_delivery_package_rejects_stale_platform_export_manifest(tmp_path):
    final = tmp_path / "final.mp4"
    final.write_bytes(b"final-video")
    exports = tmp_path / "exports"
    exports.mkdir()
    export = exports / "douyin.mp4"
    export.write_bytes(b"platform-video")
    (exports / "douyin.json").write_text(json.dumps({
        "status": "ready", "preset": "douyin", "output_sha256": "0" * 64,
    }), encoding="utf-8")
    project = SimpleNamespace(id=7, name="Pilot", final_video_path=str(final), scenes=[])

    with pytest.raises(DeliveryPackageError, match="manifest is stale"):
        build_delivery_package(
            project,
            tmp_path,
            {"generation": {"status": "passed"}, "final_composition": _passed_final_composition(final)},
            {"status": "ready"},
        )


def test_delivery_package_rejects_platform_export_without_quality_evidence(tmp_path):
    final = tmp_path / "final.mp4"
    final.write_bytes(b"final-video")
    exports = tmp_path / "exports"
    exports.mkdir()
    export = exports / "douyin.mp4"
    export.write_bytes(b"platform-video")
    (exports / "douyin.json").write_text(json.dumps({
        "status": "ready",
        "preset": "douyin",
        "output_sha256": _sha256(export),
    }), encoding="utf-8")
    project = SimpleNamespace(id=7, name="Pilot", final_video_path=str(final), scenes=[])

    with pytest.raises(DeliveryPackageError, match="stale or incomplete"):
        build_delivery_package(
            project,
            tmp_path,
            {"generation": {"status": "passed"}, "final_composition": _passed_final_composition(final)},
            {"status": "ready"},
        )


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
