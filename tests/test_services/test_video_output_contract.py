from src.services.video_output_contract import audit_video_output_contract


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
