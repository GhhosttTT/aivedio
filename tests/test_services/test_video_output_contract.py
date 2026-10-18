import hashlib
import json

import pytest

from src.services.video_output_contract import (
    VideoRequestPlanError,
    audit_video_output_contract,
    validate_sequence_request_plan,
)


def _contract(**overrides):
    value = {
        "contract_hash": "abc",
        "resolution": "1080p",
        "output_format": "mp4",
        "duration_seconds": 5.0,
        "generate_audio": True,
        "model": "model-a",
    }
    value.update(overrides)
    return value


def _metrics(**overrides):
    value = {
        "status": "available",
        "width": 1080,
        "height": 1920,
        "duration_seconds": 5.1,
        "audio_present": True,
    }
    value.update(overrides)
    return value


def _versioned_contract(**overrides):
    value = _contract(
        provider_request_version=2,
        prompt_fingerprint="prompt-hash",
        negative_prompt_fingerprint=None,
        shot_plan_fingerprint=None,
    )
    value.update(overrides)
    value.pop("contract_hash", None)
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    value["contract_hash"] = hashlib.sha256(encoded).hexdigest()
    return value


def _v3_contract(**overrides):
    value = _versioned_contract(
        provider_request_version=3,
        width=768,
        height=1344,
        fps=8,
        seed=11,
        motion_bucket_id=92,
        noise_aug_strength=0.012,
        quality_mode="commercial",
        repair_action=None,
        quality_pipeline_fingerprint="pipeline-hash",
    )
    value.update(overrides)
    value.pop("contract_hash", None)
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    value["contract_hash"] = hashlib.sha256(encoded).hexdigest()
    return value


def test_output_contract_passes_matching_media():
    report = audit_video_output_contract(
        _contract(), {"provider_model": "model-a"}, _metrics(), "/tmp/scene.mp4"
    )
    assert report["status"] == "passed"
    assert {"resolution", "output_format", "duration", "audio", "model"}.issubset(report["checked"])


def test_output_contract_allows_declared_mov_to_mp4_postprocess_conversion():
    report = audit_video_output_contract(
        _contract(output_format="mov"),
        {"provider_model": "model-a"},
        _metrics(),
        "/tmp/scene.mp4",
        allow_postprocess_container_conversion=True,
    )

    assert report["status"] == "passed"
    assert "postprocess_container_conversion" in report["checked"]


def test_output_contract_keeps_mov_drift_strict_by_default():
    report = audit_video_output_contract(
        _contract(output_format="mov"),
        {"provider_model": "model-a"},
        _metrics(),
        "/tmp/scene.mp4",
    )

    assert report["status"] == "needs_review"
    assert "output_format_drift" in {issue["code"] for issue in report["issues"]}


def test_output_contract_validates_versioned_request_contract_integrity():
    report = audit_video_output_contract(
        _versioned_contract(), {"provider_model": "model-a"}, _metrics(), "/tmp/scene.mp4"
    )
    assert report["status"] == "passed"
    assert "request_contract_integrity" in report["checked"]


def test_output_contract_rejects_tampered_versioned_request_contract():
    contract = _versioned_contract()
    contract["prompt_fingerprint"] = "changed-after-hash"
    report = audit_video_output_contract(contract, {"provider_model": "model-a"}, _metrics(), "/tmp/scene.mp4")
    assert report["status"] == "needs_review"
    assert "request_contract_hash_mismatch" in {item["code"] for item in report["issues"]}


def test_output_contract_rejects_incomplete_versioned_request_contract():
    contract = _versioned_contract()
    del contract["shot_plan_fingerprint"]
    report = audit_video_output_contract(contract, {"provider_model": "model-a"}, _metrics(), "/tmp/scene.mp4")
    assert report["status"] == "needs_review"
    assert "request_contract_fingerprints_missing" in {item["code"] for item in report["issues"]}


def test_output_contract_rejects_incomplete_v3_generation_controls():
    contract = _v3_contract()
    del contract["motion_bucket_id"]
    report = audit_video_output_contract(contract, {"provider_model": "model-a"}, _metrics(), "/tmp/scene.mp4")
    assert report["status"] == "needs_review"
    assert "request_contract_controls_missing" in {item["code"] for item in report["issues"]}


def test_output_contract_blocks_resolution_audio_and_model_drift():
    report = audit_video_output_contract(
        _contract(),
        {"provider_model": "model-b"},
        _metrics(width=720, height=1280, audio_present=False),
        "/tmp/scene.mp4",
    )
    assert report["status"] == "needs_review"
    assert {item["code"] for item in report["issues"]} == {
        "resolution_drift", "audio_missing", "model_drift",
    }


def test_output_contract_is_not_applicable_to_legacy_assets_without_contract():
    report = audit_video_output_contract(None, {}, _metrics(), "/tmp/scene.mp4")
    assert report["status"] == "not_applicable"


def test_output_contract_requires_per_shot_spatial_contracts_for_frozen_sequence():
    report = audit_video_output_contract(
        _contract(
            sequence_level_multi_shot=True,
            spatial_asset_pack={"scene_contract_hash": "current"},
            sequence_shot_contracts=[],
        ),
        {"provider_model": "model-a"},
        _metrics(),
        "/tmp/scene.mp4",
    )

    assert report["status"] == "needs_review"
    assert "sequence_spatial_contracts_missing" in {item["code"] for item in report["issues"]}


def test_output_contract_accepts_unique_sequence_spatial_contracts():
    report = audit_video_output_contract(
        _contract(
            sequence_level_multi_shot=True,
            spatial_asset_pack={"scene_contract_hash": "current"},
            sequence_shot_contracts=[
                {"scene_number": 1, "scene_contract_hash": "scene-1"},
                {"scene_number": 2, "scene_contract_hash": "scene-2"},
            ],
        ),
        {"provider_model": "model-a"},
        _metrics(),
        "/tmp/scene.mp4",
    )

    assert report["status"] == "passed"
    assert "sequence_spatial_contracts" in report["checked"]


def test_sequence_request_plan_rejects_duplicate_scene_numbers():
    with pytest.raises(VideoRequestPlanError, match="duplicate scene_number"):
        validate_sequence_request_plan(
            {"shots": [{"scene_number": 1}, {"scene_number": 1}]},
            sequence_level=True,
        )


def test_sequence_request_plan_rejects_misaligned_timeline():
    with pytest.raises(VideoRequestPlanError, match="does not match"):
        validate_sequence_request_plan(
            {
                "shots": [{"scene_number": 1}, {"scene_number": 2}],
                "sequence_timeline": [
                    {"scene_number": 1, "start_seconds": 0, "end_seconds": 2},
                    {"scene_number": 3, "start_seconds": 2, "end_seconds": 4},
                ],
            },
            sequence_level=True,
        )


def test_sequence_request_plan_accepts_ordered_timeline():
    validate_sequence_request_plan(
        {
            "shots": [
                {"scene_number": 1, "duration_seconds": 2},
                {"scene_number": 2, "duration_seconds": 2},
            ],
            "sequence_timeline": [
                {"scene_number": 1, "start_seconds": 0, "end_seconds": 2},
                {"scene_number": 2, "start_seconds": 2, "end_seconds": 4},
            ],
        },
        sequence_level=True,
    )


def test_sequence_request_plan_rejects_timeline_longer_than_request():
    with pytest.raises(VideoRequestPlanError, match="request duration"):
        validate_sequence_request_plan(
            {
                "shots": [{"scene_number": 1}],
                "sequence_timeline": [
                    {"scene_number": 1, "start_seconds": 0, "end_seconds": 6},
                ],
            },
            sequence_level=True,
            expected_duration_seconds=5,
        )


def test_sequence_request_plan_rejects_duration_field_drift():
    with pytest.raises(VideoRequestPlanError, match="disagrees with start/end"):
        validate_sequence_request_plan(
            {
                "shots": [{"scene_number": 1}],
                "sequence_timeline": [
                    {
                        "scene_number": 1,
                        "start_seconds": 0,
                        "end_seconds": 2,
                        "duration_seconds": 3,
                    },
                ],
            },
            sequence_level=True,
        )
