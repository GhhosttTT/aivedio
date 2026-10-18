import pytest

from src.services.video_engine_preflight import preflight_video_provider, preflight_production_video_engine


def test_seedance_preflight_reports_result_endpoint(monkeypatch):
    from src.services.video_engine_preflight import settings

    monkeypatch.setattr(settings, "GENERATION_PROVIDER", "seedance_api")
    monkeypatch.setattr(settings, "SEEDANCE_ENDPOINT", "https://example.test/generate")
    monkeypatch.setattr(settings, "SEEDANCE_API_KEY", "secret")
    monkeypatch.setattr(settings, "SEEDANCE_STATUS_ENDPOINT", "https://example.test/status/{job_id}")
    monkeypatch.setattr(settings, "SEEDANCE_RESULT_ENDPOINT", "https://example.test/result/{request_id}")
    for name in (
        "SEEDANCE_ENDPOINT", "SEEDANCE_API_KEY", "SEEDANCE_STATUS_ENDPOINT",
        "SEEDANCE_RESULT_ENDPOINT",
    ):
        monkeypatch.delenv(name, raising=False)

    report = preflight_video_provider()

    assert report["status"] == "configured"
    assert report["checks"]["endpoint_configured"] is True
    assert report["checks"]["status_endpoint_configured"] is True
    assert report["checks"]["result_endpoint_configured"] is True


def test_local_preflight_does_not_require_api_endpoints(monkeypatch):
    from src.services.video_engine_preflight import settings

    monkeypatch.setattr(settings, "GENERATION_PROVIDER", "local_comfyui")

    report = preflight_video_provider()

    assert report["status"] == "skipped"
    assert report["checks"] == {}


def test_preflight_uses_runtime_provider_environment(monkeypatch):
    from src.services.video_engine_preflight import settings

    monkeypatch.setattr(settings, "GENERATION_PROVIDER", "local_comfyui")
    monkeypatch.setenv("GENERATION_PROVIDER", "seedance_api")
    monkeypatch.setenv("SEEDANCE_ENDPOINT", "https://ark.example/tasks")
    monkeypatch.setenv("SEEDANCE_API_KEY", "secret")
    monkeypatch.setenv("SEEDANCE_API_FORMAT", "ark_v3")

    report = preflight_video_provider()

    assert report["provider"] == "seedance_api"
    assert report["status"] == "configured"
    assert report["checks"]["native_ark_format"] is True


def test_seedance_preflight_reads_runtime_quality_overrides(monkeypatch):
    from src.services.video_engine_preflight import settings

    monkeypatch.setattr(settings, "GENERATION_PROVIDER", "seedance_api")
    monkeypatch.setattr(settings, "SEEDANCE_API_FORMAT", "legacy")
    monkeypatch.setattr(settings, "SEEDANCE_RESOLUTION", "1080p")
    monkeypatch.setattr(settings, "SEEDANCE_NATIVE_AUDIO", True)
    monkeypatch.setattr(settings, "SEEDANCE_RETURN_LAST_FRAME", True)
    monkeypatch.setenv("SEEDANCE_ENDPOINT", "https://ark.example/tasks")
    monkeypatch.setenv("SEEDANCE_API_KEY", "secret")
    monkeypatch.setenv("SEEDANCE_API_FORMAT", "ark_v3")
    monkeypatch.setenv("SEEDANCE_MODEL", "doubao-seedance-2-5-260628")
    monkeypatch.setenv("SEEDANCE_RESOLUTION", "720p")
    monkeypatch.setenv("SEEDANCE_NATIVE_AUDIO", "false")
    monkeypatch.setenv("SEEDANCE_RETURN_LAST_FRAME", "false")

    report = preflight_video_provider()

    assert report["configuration"]["resolution"] == "720p"
    assert report["checks"]["production_resolution"] is False
    assert report["capabilities"]["native_audio"] is False
    assert report["capabilities"]["continuity_last_frame"] is False
    assert report["warnings"]


def test_native_seedance_preflight_exposes_reference_limits(monkeypatch):
    from src.services.video_engine_preflight import settings

    monkeypatch.setattr(settings, "GENERATION_PROVIDER", "seedance_api")
    monkeypatch.setenv("SEEDANCE_ENDPOINT", "https://ark.cn-beijing.volces.com/api/v3/contents/generations/tasks")
    monkeypatch.setenv("SEEDANCE_API_KEY", "secret")
    monkeypatch.setenv("SEEDANCE_API_FORMAT", "ark_v3")
    monkeypatch.setenv("SEEDANCE_MODEL", "doubao-seedance-2-5-260628")

    report = preflight_video_provider()

    assert report["capabilities"]["reference_item_limit"] == 50
    assert report["capabilities"]["reference_category_limits"] == {
        "images": 30, "videos": 10, "audios": 10,
    }
    assert report["capabilities"]["reference_audio_supported"] is True


def test_native_seedance_20_preflight_exposes_reduced_reference_contract(monkeypatch):
    from src.services.video_engine_preflight import settings

    monkeypatch.setattr(settings, "GENERATION_PROVIDER", "seedance_api")
    monkeypatch.setenv("SEEDANCE_ENDPOINT", "https://ark.cn-beijing.volces.com/api/v3/contents/generations/tasks")
    monkeypatch.setenv("SEEDANCE_API_KEY", "secret")
    monkeypatch.setenv("SEEDANCE_API_FORMAT", "ark_v3")
    monkeypatch.setenv("SEEDANCE_MODEL", "doubao-seedance-2-0-260128")

    report = preflight_video_provider()

    assert report["status"] == "configured"
    assert report["capabilities"]["reference_item_limit"] == 15
    assert report["capabilities"]["reference_category_limits"] == {
        "images": 9, "videos": 3, "audios": 3,
    }
    assert report["capabilities"]["reference_audio_supported"] is True
    assert not any("does not support audio references" in item for item in report["warnings"])


def test_native_seedance_10_preflight_marks_reference_audio_unsupported(monkeypatch):
    from src.services.video_engine_preflight import settings

    monkeypatch.setattr(settings, "GENERATION_PROVIDER", "seedance_api")
    monkeypatch.setenv("SEEDANCE_ENDPOINT", "https://ark.cn-beijing.volces.com/api/v3/contents/generations/tasks")
    monkeypatch.setenv("SEEDANCE_API_KEY", "secret")
    monkeypatch.setenv("SEEDANCE_API_FORMAT", "ark_v3")
    monkeypatch.setenv("SEEDANCE_MODEL", "doubao-seedance-1-0-pro-250528")

    report = preflight_video_provider()

    assert report["capabilities"]["reference_audio_supported"] is False
    assert report["capabilities"]["multimodal_references"] is False
    assert report["capabilities"]["reference_category_limits"] == {
        "images": 2, "videos": 0, "audios": 0,
    }
    assert report["capabilities"]["edit_and_extend"] is False


def test_native_seedance_10_fast_preflight_disables_first_last_frame(monkeypatch):
    from src.services.video_engine_preflight import settings

    monkeypatch.setattr(settings, "GENERATION_PROVIDER", "seedance_api")
    monkeypatch.setenv("SEEDANCE_ENDPOINT", "https://ark.cn-beijing.volces.com/api/v3/contents/generations/tasks")
    monkeypatch.setenv("SEEDANCE_API_KEY", "secret")
    monkeypatch.setenv("SEEDANCE_API_FORMAT", "ark_v3")
    monkeypatch.setenv("SEEDANCE_MODEL", "doubao-seedance-1-0-pro-fast-251015")

    report = preflight_video_provider()

    assert report["capabilities"]["first_last_frame"] is False
    assert report["capabilities"]["reference_item_limit"] == 1


def test_native_seedance_10_preflight_blocks_edit_mode(monkeypatch):
    from src.services.video_engine_preflight import settings

    monkeypatch.setattr(settings, "GENERATION_PROVIDER", "seedance_api")
    monkeypatch.setenv("SEEDANCE_ENDPOINT", "https://ark.cn-beijing.volces.com/api/v3/contents/generations/tasks")
    monkeypatch.setenv("SEEDANCE_API_KEY", "secret")
    monkeypatch.setenv("SEEDANCE_API_FORMAT", "ark_v3")
    monkeypatch.setenv("SEEDANCE_MODEL", "doubao-seedance-1-0-pro-250528")
    monkeypatch.setenv("SEEDANCE_REQUEST_MODE", "edit")

    report = preflight_video_provider()

    assert report["status"] == "blocked"
    assert any("does not support edit tasks" in item for item in report["action_items"])


def test_seedance_preflight_reports_missing_ffprobe_for_output_validation(monkeypatch):
    from src.services.video_engine_preflight import settings
    import src.services.video_engine_preflight as module

    monkeypatch.setattr(settings, "GENERATION_PROVIDER", "seedance_api")
    monkeypatch.setenv("SEEDANCE_ENDPOINT", "https://ark.example/tasks")
    monkeypatch.setenv("SEEDANCE_API_KEY", "secret")
    monkeypatch.setenv("SEEDANCE_API_FORMAT", "ark_v3")
    monkeypatch.setenv("SEEDANCE_VALIDATE_OUTPUT", "true")
    monkeypatch.setattr(module.shutil, "which", lambda name: None if name == "ffprobe" else "/usr/bin/ffmpeg")

    report = preflight_video_provider()

    assert report["checks"]["output_validation_enabled"] is True
    assert report["checks"]["ffprobe_available"] is False
    assert report["capabilities"]["output_artifact_validation"] is False
    assert any("ffprobe" in item for item in report["warnings"])


def test_seedance_preflight_blocks_unsigned_callback_configuration(monkeypatch):
    from src.services.video_engine_preflight import settings

    monkeypatch.setattr(settings, "GENERATION_PROVIDER", "seedance_api")
    monkeypatch.setenv("SEEDANCE_ENDPOINT", "https://ark.example/tasks")
    monkeypatch.setenv("SEEDANCE_API_KEY", "secret")
    monkeypatch.setenv("SEEDANCE_API_FORMAT", "ark_v3")
    monkeypatch.setenv("SEEDANCE_CALLBACK_URL", "https://app.example/api/webhooks/seedance")
    monkeypatch.delenv("SEEDANCE_CALLBACK_SECRET", raising=False)

    report = preflight_video_provider()

    assert report["status"] == "blocked"
    assert report["checks"]["callback_url_configured"] is True
    assert report["checks"]["callback_secret_configured"] is False
    assert any("CALLBACK_SECRET" in item for item in report["action_items"])


@pytest.mark.parametrize("template", [
    "http://cdn.example/{filename}",
    "https://127.0.0.1/{filename}",
    "https://[::1]/{filename}",
])
def test_seedance_preflight_rejects_non_public_media_template(monkeypatch, template):
    from src.services.video_engine_preflight import settings

    monkeypatch.setattr(settings, "GENERATION_PROVIDER", "seedance_api")
    monkeypatch.setenv("SEEDANCE_ENDPOINT", "https://ark.example/tasks")
    monkeypatch.setenv("SEEDANCE_API_KEY", "secret")
    monkeypatch.setenv("SEEDANCE_API_FORMAT", "ark_v3")
    monkeypatch.setenv("SEEDANCE_MEDIA_URL_TEMPLATE", template)

    report = preflight_video_provider()

    assert report["checks"]["local_video_reference_transport_configured"] is False


def test_seedance_ark_preflight_derives_status_and_allows_missing_result_endpoint(monkeypatch):
    from src.services.video_engine_preflight import settings

    monkeypatch.setattr(settings, "GENERATION_PROVIDER", "seedance_api")
    monkeypatch.setattr(settings, "SEEDANCE_ENDPOINT", "https://ark.example/api/v3/contents/generations/tasks")
    monkeypatch.setattr(settings, "SEEDANCE_API_KEY", "secret")
    monkeypatch.setattr(settings, "SEEDANCE_STATUS_ENDPOINT", "")
    monkeypatch.setattr(settings, "SEEDANCE_RESULT_ENDPOINT", "")
    monkeypatch.setattr(settings, "SEEDANCE_API_FORMAT", "ark_v3")
    for name in (
        "SEEDANCE_ENDPOINT", "SEEDANCE_API_KEY", "SEEDANCE_STATUS_ENDPOINT",
        "SEEDANCE_RESULT_ENDPOINT", "SEEDANCE_API_FORMAT",
    ):
        monkeypatch.delenv(name, raising=False)

    report = preflight_video_provider()

    assert report["status"] == "configured"
    assert report["checks"]["native_ark_format"] is True
    assert report["checks"]["status_endpoint_configured"] is True
    assert report["checks"]["result_endpoint_required"] is False


def test_seedance_preflight_blocks_invalid_request_contract(monkeypatch):
    from src.services.video_engine_preflight import settings

    monkeypatch.setattr(settings, "GENERATION_PROVIDER", "seedance_api")
    monkeypatch.setenv("SEEDANCE_ENDPOINT", "https://ark.example/tasks")
    monkeypatch.setenv("SEEDANCE_API_KEY", "secret")
    monkeypatch.setenv("SEEDANCE_API_FORMAT", "typo_format")
    monkeypatch.setenv("SEEDANCE_OUTPUT_FORMAT", "avi")

    report = preflight_video_provider()

    assert report["status"] == "blocked"
    assert report["checks"]["api_format_valid"] is False
    assert report["checks"]["output_format_valid"] is False


def test_seedance_25_preflight_rejects_4k_resolution(monkeypatch):
    from src.services.video_engine_preflight import settings

    monkeypatch.setattr(settings, "GENERATION_PROVIDER", "seedance_api")
    monkeypatch.setattr(settings, "SEEDANCE_ENDPOINT", "https://ark.example/api/v3/contents/generations/tasks")
    monkeypatch.setattr(settings, "SEEDANCE_API_KEY", "secret")
    monkeypatch.setattr(settings, "SEEDANCE_API_FORMAT", "ark_v3")
    monkeypatch.setattr(settings, "SEEDANCE_MODEL", "doubao-seedance-2-5-260628")
    monkeypatch.setenv("SEEDANCE_RESOLUTION", "4k")
    for name in ("GENERATION_PROVIDER", "SEEDANCE_ENDPOINT", "SEEDANCE_API_KEY", "SEEDANCE_API_FORMAT", "SEEDANCE_MODEL"):
        monkeypatch.delenv(name, raising=False)

    report = preflight_video_provider()

    assert report["status"] == "blocked"
    assert report["checks"]["resolution_valid"] is False
    assert any("does not support 4k" in item for item in report["action_items"])


def test_seedance_20_fast_preflight_rejects_1080p_resolution(monkeypatch):
    from src.services.video_engine_preflight import settings

    monkeypatch.setattr(settings, "GENERATION_PROVIDER", "seedance_api")
    monkeypatch.setenv("SEEDANCE_ENDPOINT", "https://ark.example/api/v3/contents/generations/tasks")
    monkeypatch.setenv("SEEDANCE_API_KEY", "secret")
    monkeypatch.setenv("SEEDANCE_API_FORMAT", "ark_v3")
    monkeypatch.setenv("SEEDANCE_MODEL", "doubao-seedance-2-0-fast-260128")
    monkeypatch.setenv("SEEDANCE_RESOLUTION", "1080p")

    report = preflight_video_provider()

    assert report["checks"]["resolution_valid"] is False
    assert any("does not support 1080p" in item for item in report["action_items"])


def test_seedance_20_preflight_rejects_overlong_multi_shot_duration(monkeypatch):
    from src.services.video_engine_preflight import settings

    monkeypatch.setattr(settings, "GENERATION_PROVIDER", "seedance_api")
    monkeypatch.setattr(settings, "SEEDANCE_ENDPOINT", "https://ark.cn-beijing.volces.com/api/v3/contents/generations/tasks")
    monkeypatch.setattr(settings, "SEEDANCE_API_KEY", "secret")
    monkeypatch.setattr(settings, "SEEDANCE_API_FORMAT", "ark_v3")
    monkeypatch.setattr(settings, "SEEDANCE_MODEL", "doubao-seedance-2-0-260128")
    monkeypatch.setenv("SEEDANCE_REQUEST_MODE", "multi_shot")
    monkeypatch.setenv("SEEDANCE_MULTI_SHOT_DURATION_SECONDS", "30")
    for name in ("GENERATION_PROVIDER", "SEEDANCE_ENDPOINT", "SEEDANCE_API_KEY", "SEEDANCE_API_FORMAT", "SEEDANCE_MODEL"):
        monkeypatch.delenv(name, raising=False)

    report = preflight_video_provider()

    assert report["status"] == "blocked"
    assert report["checks"]["multi_shot_duration_valid"] is False
    assert any("must be between 4 and 15 seconds" in item for item in report["action_items"])


def test_seedance_non_25_preflight_rejects_native_mov(monkeypatch):
    from src.services.video_engine_preflight import settings

    monkeypatch.setattr(settings, "GENERATION_PROVIDER", "seedance_api")
    monkeypatch.setattr(settings, "SEEDANCE_ENDPOINT", "https://ark.example/api/v3/contents/generations/tasks")
    monkeypatch.setattr(settings, "SEEDANCE_API_KEY", "secret")
    monkeypatch.setattr(settings, "SEEDANCE_API_FORMAT", "ark_v3")
    monkeypatch.setattr(settings, "SEEDANCE_MODEL", "doubao-seedance-2-0-260128")
    monkeypatch.setenv("SEEDANCE_OUTPUT_FORMAT", "mov")
    for name in ("GENERATION_PROVIDER", "SEEDANCE_ENDPOINT", "SEEDANCE_API_KEY", "SEEDANCE_API_FORMAT", "SEEDANCE_MODEL"):
        monkeypatch.delenv(name, raising=False)

    report = preflight_video_provider()

    assert report["status"] == "blocked"
    assert report["checks"]["output_format_valid"] is False
    assert any("requires Seedance 2.5" in item for item in report["action_items"])


def test_seedance_non_25_preflight_rejects_auto_task_type(monkeypatch):
    from src.services.video_engine_preflight import settings

    monkeypatch.setattr(settings, "GENERATION_PROVIDER", "seedance_api")
    monkeypatch.setattr(settings, "SEEDANCE_ENDPOINT", "https://ark.cn-beijing.volces.com/api/v3/contents/generations/tasks")
    monkeypatch.setattr(settings, "SEEDANCE_API_KEY", "secret")
    monkeypatch.setattr(settings, "SEEDANCE_API_FORMAT", "ark_v3")
    monkeypatch.setattr(settings, "SEEDANCE_MODEL", "doubao-seedance-2-0-260128")
    monkeypatch.setenv("SEEDANCE_REQUEST_MODE", "auto")
    for name in ("GENERATION_PROVIDER", "SEEDANCE_ENDPOINT", "SEEDANCE_API_KEY", "SEEDANCE_API_FORMAT", "SEEDANCE_MODEL"):
        monkeypatch.delenv(name, raising=False)

    report = preflight_video_provider()

    assert report["status"] == "blocked"
    assert any("does not support omni_reference_task_type=auto" in item for item in report["action_items"])


def test_seedance_preflight_blocks_unknown_request_mode(monkeypatch):
    from src.services.video_engine_preflight import settings

    monkeypatch.setattr(settings, "GENERATION_PROVIDER", "seedance_api")
    monkeypatch.setenv("SEEDANCE_ENDPOINT", "https://ark.example/tasks")
    monkeypatch.setenv("SEEDANCE_API_KEY", "secret")
    monkeypatch.setenv("SEEDANCE_API_FORMAT", "ark_v3")
    monkeypatch.setenv("SEEDANCE_REQUEST_MODE", "unknown_mode")

    report = preflight_video_provider()

    assert report["status"] == "blocked"
    assert report["checks"]["request_mode_valid"] is False
    assert any("SEEDANCE_REQUEST_MODE" in item for item in report["action_items"])


def test_seedance_preflight_uses_default_model_for_empty_override(monkeypatch):
    from src.services.video_engine_preflight import settings

    monkeypatch.setattr(settings, "GENERATION_PROVIDER", "seedance_api")
    monkeypatch.setenv("SEEDANCE_ENDPOINT", "https://ark.example/tasks")
    monkeypatch.setenv("SEEDANCE_API_KEY", "secret")
    monkeypatch.setenv("SEEDANCE_API_FORMAT", "ark_v3")
    monkeypatch.setenv("SEEDANCE_MODEL", "")

    report = preflight_video_provider()

    assert report["checks"]["model_configured"] is True
    assert report["configuration"]["model"] == "doubao-seedance-2-5-260628"


def test_seedance_preflight_blocks_ark_endpoint_with_legacy_contract(monkeypatch):
    from src.services.video_engine_preflight import settings

    monkeypatch.setattr(settings, "GENERATION_PROVIDER", "seedance_api")
    monkeypatch.setenv("SEEDANCE_ENDPOINT", "https://ark.cn-beijing.volcengine.com/api/v3/contents/generations/tasks")
    monkeypatch.setenv("SEEDANCE_API_KEY", "secret")
    monkeypatch.setenv("SEEDANCE_API_FORMAT", "legacy")

    report = preflight_video_provider()

    assert report["status"] == "blocked"
    assert report["checks"]["ark_endpoint_detected"] is True
    assert any("ark_v3" in item for item in report["action_items"])


def test_seedance_preflight_recognizes_official_volces_ark_endpoint(monkeypatch):
    from src.services.video_engine_preflight import settings

    monkeypatch.setattr(settings, "GENERATION_PROVIDER", "seedance_api")
    monkeypatch.setenv("SEEDANCE_ENDPOINT", "https://ark.cn-beijing.volces.com/api/v3/contents/generations/tasks")
    monkeypatch.setenv("SEEDANCE_API_KEY", "secret")
    monkeypatch.setenv("SEEDANCE_API_FORMAT", "ark_v3")

    report = preflight_video_provider()

    assert report["status"] == "configured"


def test_seedance_preflight_auto_detects_official_ark_without_format_override(monkeypatch):
    from src.services.video_engine_preflight import settings

    monkeypatch.setattr(settings, "GENERATION_PROVIDER", "seedance_api")
    monkeypatch.delenv("SEEDANCE_API_FORMAT", raising=False)
    monkeypatch.setenv("SEEDANCE_ENDPOINT", "https://ark.cn-beijing.volces.com/api/v3/contents/generations/tasks")
    monkeypatch.setenv("SEEDANCE_API_KEY", "secret")
    monkeypatch.setenv("SEEDANCE_MODEL", "doubao-seedance-2-5-260628")

    report = preflight_video_provider()

    assert report["configuration"]["api_format"] == "ark_v3"
    assert report["checks"]["native_ark_format"] is True
    assert report["status"] == "configured"
    assert report["checks"]["ark_endpoint_detected"] is True
    assert not any("not Volcano Ark" in item for item in report.get("warnings", []))


def test_seedance_preflight_warns_when_ark_contract_targets_generic_gateway(monkeypatch):
    from src.services.video_engine_preflight import settings

    monkeypatch.setattr(settings, "GENERATION_PROVIDER", "seedance_api")
    monkeypatch.setenv("SEEDANCE_ENDPOINT", "https://gateway.example/v1/video/generations")
    monkeypatch.setenv("SEEDANCE_API_KEY", "secret")
    monkeypatch.setenv("SEEDANCE_API_FORMAT", "ark_v3")

    report = preflight_video_provider()

    assert report["status"] == "configured"
    assert report["checks"]["ark_endpoint_detected"] is False
    assert any("not Volcano Ark" in item for item in report["warnings"])


def test_seedance_ark_edit_preflight_requires_public_video_transport(monkeypatch):
    from src.services.video_engine_preflight import settings

    monkeypatch.setattr(settings, "GENERATION_PROVIDER", "seedance_api")
    monkeypatch.setattr(settings, "SEEDANCE_ENDPOINT", "https://ark.example/tasks")
    monkeypatch.setattr(settings, "SEEDANCE_API_KEY", "secret")
    monkeypatch.setattr(settings, "SEEDANCE_API_FORMAT", "ark_v3")
    monkeypatch.setattr(settings, "SEEDANCE_REQUEST_MODE", "edit")
    monkeypatch.setattr(settings, "SEEDANCE_MEDIA_URL_TEMPLATE", "")
    for name in (
        "GENERATION_PROVIDER", "SEEDANCE_ENDPOINT", "SEEDANCE_API_KEY",
        "SEEDANCE_API_FORMAT", "SEEDANCE_REQUEST_MODE", "SEEDANCE_MEDIA_URL_TEMPLATE",
    ):
        monkeypatch.delenv(name, raising=False)

    report = preflight_video_provider()

    assert report["status"] == "blocked"
    assert report["checks"]["local_video_reference_transport_configured"] is False
    assert report["capabilities"]["local_video_audio_references"] is False
    assert report["warnings"]


def test_seedance_ark_edit_preflight_rejects_non_public_media_template(monkeypatch):
    from src.services.video_engine_preflight import settings

    monkeypatch.setattr(settings, "GENERATION_PROVIDER", "seedance_api")
    monkeypatch.setattr(settings, "SEEDANCE_ENDPOINT", "https://ark.example/tasks")
    monkeypatch.setattr(settings, "SEEDANCE_API_KEY", "secret")
    monkeypatch.setattr(settings, "SEEDANCE_API_FORMAT", "ark_v3")
    monkeypatch.setattr(settings, "SEEDANCE_REQUEST_MODE", "edit")
    monkeypatch.setattr(settings, "SEEDANCE_MEDIA_URL_TEMPLATE", "file:///tmp/{filename}")
    for name in (
        "GENERATION_PROVIDER", "SEEDANCE_ENDPOINT", "SEEDANCE_API_KEY",
        "SEEDANCE_API_FORMAT", "SEEDANCE_REQUEST_MODE", "SEEDANCE_MEDIA_URL_TEMPLATE",
    ):
        monkeypatch.delenv(name, raising=False)

    report = preflight_video_provider()

    assert report["status"] == "blocked"
    assert report["checks"]["local_video_reference_transport_configured"] is False


@pytest.mark.parametrize("template", [
    "http://localhost:8000/media/{filename}",
    "https://127.0.0.1/media/{filename}",
    "https://192.168.1.20/media/{filename}",
])
def test_seedance_ark_edit_preflight_rejects_private_media_hosts(monkeypatch, template):
    from src.services.video_engine_preflight import settings

    monkeypatch.setattr(settings, "GENERATION_PROVIDER", "seedance_api")
    monkeypatch.setattr(settings, "SEEDANCE_ENDPOINT", "https://ark.example/tasks")
    monkeypatch.setattr(settings, "SEEDANCE_API_KEY", "secret")
    monkeypatch.setattr(settings, "SEEDANCE_API_FORMAT", "ark_v3")
    monkeypatch.setattr(settings, "SEEDANCE_REQUEST_MODE", "edit")
    monkeypatch.setattr(settings, "SEEDANCE_MEDIA_URL_TEMPLATE", template)
    for name in (
        "GENERATION_PROVIDER", "SEEDANCE_ENDPOINT", "SEEDANCE_API_KEY",
        "SEEDANCE_API_FORMAT", "SEEDANCE_REQUEST_MODE", "SEEDANCE_MEDIA_URL_TEMPLATE",
    ):
        monkeypatch.delenv(name, raising=False)

    report = preflight_video_provider()

    assert report["status"] == "blocked"
    assert report["checks"]["local_video_reference_transport_configured"] is False


def test_production_preflight_surfaces_provider_blockers(monkeypatch):
    import src.services.video_engine_preflight as module

    monkeypatch.setattr(module, "preflight_video_workflow", lambda *_args, **_kwargs: {
        "status": "skipped",
        "action_items": ["local workflow disabled"],
    })
    monkeypatch.setattr(module, "preflight_video_provider", lambda: {
        "provider": "seedance_api",
        "status": "blocked",
        "action_items": ["Configure a public media URL template"],
        "warnings": ["Local video references are not reachable by Ark"],
    })

    report = preflight_production_video_engine()

    assert report["status"] == "production_not_ready"
    assert report["action_items"] == ["Configure a public media URL template"]
    assert report["warnings"] == ["Local video references are not reachable by Ark"]


def test_production_preflight_accepts_per_run_provider_override(monkeypatch):
    import src.services.video_engine_preflight as module

    seen = {}
    monkeypatch.setattr(module, "preflight_video_workflow", lambda *_args, **_kwargs: {
        "status": "skipped",
        "action_items": [],
    })

    def fake_provider_preflight(*, provider_override=None):
        seen["provider"] = provider_override
        return {"provider": provider_override, "status": "configured", "checks": {}}

    monkeypatch.setattr(module, "preflight_video_provider", fake_provider_preflight)

    report = module.preflight_production_video_engine(provider_override="seedance_api")

    assert seen["provider"] == "seedance_api"
    assert report["status"] == "ready_for_production_video_test"


def test_production_preflight_accepts_per_run_model_override(monkeypatch):
    import src.services.video_engine_preflight as module

    monkeypatch.setattr(module, "preflight_video_workflow", lambda *_args, **_kwargs: {
        "status": "skipped",
        "action_items": [],
    })
    seen = {}

    def fake_provider_preflight(*, provider_override=None, model_override=None):
        seen.update(provider=provider_override, model=model_override)
        return {"provider": provider_override, "status": "configured", "checks": {}}

    monkeypatch.setattr(module, "preflight_video_provider", fake_provider_preflight)
    report = module.preflight_production_video_engine(
        provider_override="seedance_api",
        model_override="doubao-seedance-2-0-260128",
    )

    assert report["provider"]["provider"] == "seedance_api"
    assert seen == {
        "provider": "seedance_api",
        "model": "doubao-seedance-2-0-260128",
    }


def test_production_preflight_does_not_drop_non_provider_overrides(monkeypatch):
    import src.services.video_engine_preflight as module

    monkeypatch.setattr(module, "preflight_video_workflow", lambda *_args, **_kwargs: {
        "status": "skipped",
        "action_items": [],
    })
    seen = {}

    def fake_provider_preflight(**kwargs):
        seen.update(kwargs)
        return {"provider": "seedance_api", "status": "configured", "checks": {}}

    monkeypatch.setattr(module, "preflight_video_provider", fake_provider_preflight)
    report = module.preflight_production_video_engine(
        request_mode_override="multi_shot",
        resolution_override="720p",
        output_format_override="mp4",
        duration_override=2,
    )

    assert report["status"] == "ready_for_production_video_test"
    assert seen == {
        "provider_override": None,
        "request_mode_override": "multi_shot",
        "resolution_override": "720p",
        "output_format_override": "mp4",
        "duration_override": 2,
    }


def test_provider_preflight_accepts_per_run_request_mode_override(monkeypatch):
    monkeypatch.setattr("src.services.video_engine_preflight.settings.GENERATION_PROVIDER", "seedance_api")
    monkeypatch.setenv("SEEDANCE_ENDPOINT", "https://ark.cn-beijing.volces.com/api/v3/contents/generations/tasks")
    monkeypatch.setenv("SEEDANCE_API_KEY", "secret")
    monkeypatch.setenv("SEEDANCE_API_FORMAT", "ark_v3")
    monkeypatch.setenv("SEEDANCE_MODEL", "doubao-seedance-2-5-260628")
    monkeypatch.setenv("SEEDANCE_REQUEST_MODE", "reference")

    report = preflight_video_provider(request_mode_override="edit")

    assert report["configuration"]["request_mode"] == "edit"


def test_provider_preflight_accepts_per_run_resolution_override(monkeypatch):
    monkeypatch.setattr("src.services.video_engine_preflight.settings.GENERATION_PROVIDER", "seedance_api")
    monkeypatch.setenv("SEEDANCE_ENDPOINT", "https://ark.cn-beijing.volces.com/api/v3/contents/generations/tasks")
    monkeypatch.setenv("SEEDANCE_API_KEY", "secret")
    monkeypatch.setenv("SEEDANCE_API_FORMAT", "ark_v3")
    monkeypatch.setenv("SEEDANCE_MODEL", "doubao-seedance-2-5-260628")

    report = preflight_video_provider(resolution_override="4k")

    assert report["configuration"]["resolution"] == "4k"
    assert report["checks"]["resolution_valid"] is False
