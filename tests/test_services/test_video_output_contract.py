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


def test_output_contract_passes_matching_media():
    report = audit_video_output_contract(
        _contract(), {"provider_model": "model-a"}, _metrics(), "/tmp/scene.mp4"
    )
    assert report["status"] == "passed"
    assert {"resolution", "output_format", "duration", "audio", "model"}.issubset(report["checked"])


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
