import json
from types import SimpleNamespace

from src.services.generation_context_audit import GenerationContextAuditService


def _scene(number, video_path=None):
    return SimpleNamespace(scene_number=number, video_path=str(video_path) if video_path else None)


def _metadata(model="doubao-seedance-2-5-260628", resolution="1080p", mode="reference", hash_value="hash"):
    return {
        "provider_name": "seedance_api",
        "provider_model": model,
        "request_mode": mode,
        "requested_resolution": resolution,
        "requested_output_format": "mp4",
        "requested_aspect_ratio": "9:16",
        "request_contract_hash": hash_value,
        "request_contract": {
            "spatial_asset_pack": {"project_signature": "spatial-v1"},
        },
    }


def test_generation_context_audit_passes_one_locked_context(tmp_path):
    paths = []
    for number in (1, 2):
        video = tmp_path / f"scene_{number}.mp4"
        video.write_bytes(b"video")
        video.with_suffix(".provider.json").write_text(json.dumps(_metadata()), encoding="utf-8")
        paths.append(video)

    report = GenerationContextAuditService().audit([_scene(1, paths[0]), _scene(2, paths[1])], {})

    assert report.status == "passed"
    assert report.context_count == 1


def test_generation_context_audit_flags_model_drift(tmp_path):
    first = tmp_path / "scene_1.mp4"
    second = tmp_path / "scene_2.mp4"
    first.write_bytes(b"video")
    second.write_bytes(b"video")
    first.with_suffix(".provider.json").write_text(json.dumps(_metadata()), encoding="utf-8")
    second.with_suffix(".provider.json").write_text(json.dumps(_metadata(model="doubao-seedance-2-0-260128", hash_value="hash-2")), encoding="utf-8")

    report = GenerationContextAuditService().audit([_scene(1, first), _scene(2, second)], {})

    assert report.status == "needs_review"
    assert report.issues[0]["code"] == "provider_context_drift"
    assert report.to_dict()["repair_queue"][0]["action"] == "fix_video_output_contract"


def test_generation_context_audit_can_use_report_metadata():
    reports = {
        "generation": {
            "cases": [
                {"scene_number": 1, "provider_metadata": _metadata()},
                {"scene_number": 2, "provider_metadata": _metadata()},
            ]
        }
    }

    report = GenerationContextAuditService().audit([_scene(1), _scene(2)], reports)

    assert report.status == "passed"
    assert report.checked_scene_count == 2


def test_generation_context_audit_blocks_partial_provider_context_coverage(tmp_path):
    first = tmp_path / "scene_1.mp4"
    second = tmp_path / "scene_2.mp4"
    first.write_bytes(b"video")
    second.write_bytes(b"video")
    first.with_suffix(".provider.json").write_text(json.dumps(_metadata()), encoding="utf-8")

    report = GenerationContextAuditService().audit(
        [_scene(1, first), _scene(2, second)],
        {},
    )

    assert report.status == "needs_review"
    assert report.checked_scene_count == 2
    assert report.issues[0]["code"] == "missing_provider_context_evidence"
