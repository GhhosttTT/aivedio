import pytest


@pytest.mark.parametrize("opening_input", ["reference_image", "image", "start_image", "first_frame"])
def test_local_video_preflight_resolves_media_controls(monkeypatch, tmp_path, opening_input):
    import json
    from unittest.mock import MagicMock
    from src.services import video_engine_preflight as module

    fields = module.VIDEO_WORKFLOW_PLACEHOLDERS - {
        "reference_image", "image", "start_image", "first_frame",
    }
    fields.add(opening_input)
    workflow = {"output": {"class_type": "SaveVideo", "inputs": {
        name: "{" + name + "}" for name in fields
    }}}
    path = tmp_path / "video.json"
    path.write_text(json.dumps(workflow), encoding="utf-8")
    service = MagicMock()
    replacer = object.__new__(module.ComfyUIService)
    service._replace_workflow_placeholders.side_effect = replacer._replace_workflow_placeholders

    def validate_resolved(resolved):
        inputs = resolved["output"]["inputs"]
        assert module.scan_placeholders(resolved) == set()
        assert inputs[opening_input] == "validation_reference.png"
        assert inputs["end_image"] == inputs["last_frame"] == "validation_end.png"
        references = json.loads(inputs["reference_images_json"])
        assert len(references) == inputs["reference_image_count"] == 1
        assert json.loads(inputs["reference_videos_json"]) == []
        assert json.loads(inputs["reference_audios_json"]) == []
        assert inputs["continuity_image"] == inputs["previous_last_frame"]

    service.preflight.side_effect = validate_resolved
    service.client.get.return_value.json.return_value = {"devices": []}
    monkeypatch.setattr(module, "ComfyUIService", lambda **kwargs: service)

    report = module.preflight_video_workflow(workflow_path=str(path))

    assert report["status"] == "ready_for_live_test", report
    service.preflight.assert_called_once()
    service.client.close.assert_called_once()


def test_standard_wan_workflow_preflight_accepts_real_node_bindings(monkeypatch, tmp_path):
    import json
    from unittest.mock import MagicMock
    from src.services import video_engine_preflight as module

    workflow = {
        "positive": {"class_type": "CLIPTextEncode", "inputs": {"text": "positive"}},
        "negative": {"class_type": "CLIPTextEncode", "inputs": {"text": "negative"}},
        "first": {"class_type": "LoadImage", "inputs": {"image": "first.png"}},
        "last": {"class_type": "LoadImage", "inputs": {"image": "last.png"}},
        "latent": {"class_type": "EmptyHunyuanLatentVideo", "inputs": {
            "width": 704, "height": 1280, "length": 81,
        }},
        "sampler": {"class_type": "KSamplerAdvanced", "inputs": {"noise_seed": 1}},
        "save": {"class_type": "SaveVideo", "inputs": {"fps": 16, "filename_prefix": "old"}},
    }
    path = tmp_path / "wan22_api.json"
    path.write_text(json.dumps(workflow), encoding="utf-8")
    (tmp_path / "wan22_api.bindings.json").write_text(json.dumps({
        "bindings": {
            "positive_prompt": {"node_id": "positive", "input": "text"},
            "negative_prompt": {"node_id": "negative", "input": "text"},
            "reference_image": {"node_id": "first", "input": "image"},
            "end_image": {"node_id": "last", "input": "image"},
            "width": {"node_id": "latent", "input": "width"},
            "height": {"node_id": "latent", "input": "height"},
            "num_frames": {"node_id": "latent", "input": "length"},
            "seed": {"node_id": "sampler", "input": "noise_seed"},
            "fps": {"node_id": "save", "input": "fps"},
            "output_prefix": {"node_id": "save", "input": "filename_prefix"}
        }
    }), encoding="utf-8")
    service = MagicMock()
    replacer = object.__new__(module.ComfyUIService)
    service._replace_workflow_placeholders.side_effect = replacer._replace_workflow_placeholders
    service.client.get.return_value.json.return_value = {"devices": []}
    monkeypatch.setattr(module, "ComfyUIService", lambda **kwargs: service)
    monkeypatch.setattr(module.settings, "COMFYUI_VIDEO_BINDINGS_PATH", "")

    report = module.preflight_video_workflow(workflow_path=str(path))

    assert report["status"] == "ready_for_live_test", report
    assert report["placeholders"] == []
    assert report["binding_manifest"]["status"] == "valid"
    assert report["checks"]["quality_controls_effective"] is True
    assert report["checks"]["has_frame_count_control"] is True
    resolved = service.preflight.call_args.args[0]
    assert resolved["positive"]["inputs"]["text"] == "validation cinematic short-drama shot"
    assert resolved["latent"]["inputs"]["length"] > 0
    assert resolved["save"]["inputs"]["filename_prefix"] == "validation_video"


def test_video_preflight_blocks_missing_temporal_keyframe_control_when_enabled(monkeypatch, tmp_path):
    import json
    from src.services import video_engine_preflight as module

    workflow = {
        "output": {"class_type": "SaveVideo", "inputs": {
            name: "{" + name + "}"
            for name in module.VIDEO_WORKFLOW_PLACEHOLDERS
            if not name.startswith("keyframe_")
        }}
    }
    path = tmp_path / "video.json"
    path.write_text(json.dumps(workflow), encoding="utf-8")
    monkeypatch.setattr(module.settings, "GENERATION_VIDEO_MID_KEYFRAME_ENABLED", True)

    report = module.preflight_video_workflow(workflow_path=str(path))

    assert report["status"] == "blocked"
    assert report["checks"]["has_temporal_keyframe_control"] is False
    assert "has_temporal_keyframe_control" in report["required_checks"]
    assert any("keyframe_images_json" in item for item in report["action_items"])


def test_video_preflight_accepts_temporal_keyframe_json_control(monkeypatch, tmp_path):
    import json
    from unittest.mock import MagicMock
    from src.services import video_engine_preflight as module

    workflow = {"output": {"class_type": "SaveVideo", "inputs": {
        name: "{" + name + "}" for name in module.VIDEO_WORKFLOW_PLACEHOLDERS
    }}}
    path = tmp_path / "video.json"
    path.write_text(json.dumps(workflow), encoding="utf-8")
    service = MagicMock()
    replacer = object.__new__(module.ComfyUIService)
    service._replace_workflow_placeholders.side_effect = replacer._replace_workflow_placeholders
    service.client.get.return_value.json.return_value = {"devices": []}
    monkeypatch.setattr(module, "ComfyUIService", lambda **kwargs: service)
    monkeypatch.setattr(module.settings, "GENERATION_VIDEO_MID_KEYFRAME_ENABLED", True)

    report = module.preflight_video_workflow(workflow_path=str(path))

    assert report["status"] == "ready_for_live_test", report
    assert report["checks"]["has_temporal_keyframe_control"] is True
    resolved = service.preflight.call_args.args[0]
    keyframes = json.loads(resolved["output"]["inputs"]["keyframe_images_json"])
    assert keyframes[0]["role"] == "performance_peak"


def test_video_preflight_accepts_temporal_keyframes_as_end_frame_control(monkeypatch, tmp_path):
    import json
    from unittest.mock import MagicMock
    from src.services import video_engine_preflight as module

    fields = module.VIDEO_WORKFLOW_PLACEHOLDERS - {"end_image", "last_frame"}
    workflow = {"output": {"class_type": "SaveVideo", "inputs": {
        name: "{" + name + "}" for name in fields
    }}}
    path = tmp_path / "ltx_video.json"
    path.write_text(json.dumps(workflow), encoding="utf-8")
    service = MagicMock()
    replacer = object.__new__(module.ComfyUIService)
    service._replace_workflow_placeholders.side_effect = replacer._replace_workflow_placeholders
    service.client.get.return_value.json.return_value = {"devices": []}
    monkeypatch.setattr(module, "ComfyUIService", lambda **kwargs: service)
    monkeypatch.setattr(module.settings, "GENERATION_VIDEO_END_FRAME_ENABLED", True)
    monkeypatch.setattr(module.settings, "GENERATION_VIDEO_MID_KEYFRAME_ENABLED", True)

    report = module.preflight_video_workflow(workflow_path=str(path))

    assert report["status"] == "ready_for_live_test", report
    assert report["checks"]["has_native_end_frame_control"] is False
    assert report["checks"]["has_temporal_keyframe_control"] is True
    assert report["checks"]["has_end_frame_placeholder"] is True


def test_engine_registry_preflight_validates_every_registered_engine(monkeypatch, tmp_path):
    import json
    from src.services import video_engine_preflight as module

    for name in ("wan.json", "ltx.json"):
        (tmp_path / name).write_text("{}", encoding="utf-8")
    registry = tmp_path / "registry.json"
    registry.write_text(json.dumps({"engines": [
        {
            "id": "dialogue",
            "model_profile": "hunyuanvideo_avatar",
            "workflow_path": "wan.json",
            "capabilities": {
                "identity_reference": True,
                "performance_control": True,
                "multi_character": True,
            },
        },
        {
            "id": "ltx",
            "model_profile": "ltx_2_keyframes",
            "workflow_path": "ltx.json",
            "capabilities": {
                "identity_reference": True,
                "motion_control": True,
                "temporal_keyframes": True,
            },
        },
    ]}), encoding="utf-8")
    seen = []

    def fake_workflow(_base_url, workflow_path, bindings_path=None):
        seen.append((workflow_path, bindings_path))
        return {
            "status": "ready_for_live_test",
            "checks": {
                "has_temporal_keyframe_control": workflow_path.endswith("ltx.json"),
                "has_performance_audio_control": workflow_path.endswith("wan.json"),
                "has_driving_video_control": workflow_path.endswith("ltx.json"),
            },
            "action_items": [],
        }

    def fake_model(workflow_path, configured_profile_override=None):
        native = (
            ["identity_reference", "performance_control", "multi_character"]
            if configured_profile_override == "hunyuanvideo_avatar"
            else ["identity_reference", "motion_control", "temporal_keyframes"]
        )
        return {
            "status": "ready",
            "profile": configured_profile_override,
            "supports_temporal_keyframes": workflow_path.endswith("ltx.json"),
            "native_capabilities": native,
            "action_items": [],
        }

    monkeypatch.setattr(module, "preflight_video_workflow", fake_workflow)
    monkeypatch.setattr(module, "inspect_local_video_model", fake_model)

    report = module.preflight_local_video_engine_registry(registry_path=str(registry))

    assert report["status"] == "ready_for_live_test"
    assert [item["engine_id"] for item in report["engines"]] == ["dialogue", "ltx"]
    assert len(seen) == 2
    assert report["checks"]["short_drama_profiles_covered"] is True


def test_engine_registry_preflight_rejects_unproven_temporal_capability(monkeypatch, tmp_path):
    import json
    from src.services import video_engine_preflight as module

    workflow = tmp_path / "claimed_ltx.json"
    workflow.write_text("{}", encoding="utf-8")
    registry = tmp_path / "registry.json"
    registry.write_text(json.dumps({"engines": [{
        "id": "claimed-ltx",
        "model_profile": "ltx_2_keyframes",
        "workflow_path": "claimed_ltx.json",
        "capabilities": {"temporal_keyframes": True},
    }]}), encoding="utf-8")
    monkeypatch.setattr(module, "preflight_video_workflow", lambda *_args, **_kwargs: {
        "status": "ready_for_live_test",
        "checks": {"has_temporal_keyframe_control": False},
        "action_items": [],
    })
    monkeypatch.setattr(module, "inspect_local_video_model", lambda *_args, **_kwargs: {
        "status": "ready",
        "profile": "ltx_2_keyframes",
        "supports_temporal_keyframes": True,
        "native_capabilities": ["identity_reference", "motion_control", "temporal_keyframes"],
        "action_items": [],
    })

    report = module.preflight_local_video_engine_registry(registry_path=str(registry))

    assert report["status"] == "blocked"
    assert "does not prove" in report["engines"][0]["capability_issues"][0]


def test_engine_registry_preflight_blocks_runtime_above_vram_budget(monkeypatch, tmp_path):
    import json
    from src.services import video_engine_preflight as module

    workflow = tmp_path / "wan.json"
    workflow.write_text("{}", encoding="utf-8")
    registry = tmp_path / "registry.json"
    registry.write_text(json.dumps({"engines": [{
        "id": "wan-large",
        "model_profile": "wan_2_2_i2v_14b",
        "workflow_path": "wan.json",
        "capabilities": {"identity_reference": True},
        "runtime": {"minimum_vram_gb": 60, "precision": "bf16"},
    }]}), encoding="utf-8")
    monkeypatch.setattr(module.settings, "LOCAL_VIDEO_VRAM_BUDGET_GB", 12)
    monkeypatch.setattr(module, "preflight_video_workflow", lambda *_args, **_kwargs: {
        "status": "ready_for_live_test", "checks": {}, "action_items": [],
    })
    monkeypatch.setattr(module, "inspect_local_video_model", lambda *_args, **_kwargs: {
        "status": "ready",
        "profile": "wan_2_2_i2v_14b",
        "supports_temporal_keyframes": False,
        "native_capabilities": ["identity_reference"],
        "action_items": [],
    })

    report = module.preflight_local_video_engine_registry(registry_path=str(registry))

    assert report["status"] == "blocked"
    assert "requires 60GB VRAM" in report["engines"][0]["capability_issues"][0]


def test_engine_registry_preflight_blocks_parallel_low_vram_worker(monkeypatch, tmp_path):
    import json
    from src.services import video_engine_preflight as module

    workflow = tmp_path / "wan.json"
    workflow.write_text("{}", encoding="utf-8")
    registry = tmp_path / "registry.json"
    registry.write_text(json.dumps({"engines": [{
        "id": "wan-low-vram",
        "model_profile": "wan_2_2_ti2v_5b",
        "workflow_path": "wan.json",
        "capabilities": {"identity_reference": True},
        "runtime": {
            "minimum_vram_gb": 12,
            "precision": "fp8",
            "cpu_offload": True,
            "sequential_only": True,
        },
    }]}), encoding="utf-8")
    monkeypatch.setenv("CELERY_WORKER_CONCURRENCY", "2")
    monkeypatch.setattr(module.settings, "LOCAL_VIDEO_VRAM_BUDGET_GB", 12)
    monkeypatch.setattr(module, "preflight_video_workflow", lambda *_args, **_kwargs: {
        "status": "ready_for_live_test", "checks": {}, "action_items": [],
    })
    monkeypatch.setattr(module, "inspect_local_video_model", lambda *_args, **_kwargs: {
        "status": "ready",
        "profile": "wan_2_2_ti2v_5b",
        "supports_temporal_keyframes": False,
        "native_capabilities": ["identity_reference"],
        "action_items": [],
    })

    report = module.preflight_local_video_engine_registry(registry_path=str(registry))

    assert report["status"] == "blocked"
    assert any(
        "requires sequential rendering" in item
        for item in report["engines"][0]["capability_issues"]
    )


def test_video_workflow_runtime_inspection_finds_precision_and_offload_evidence():
    from src.services.video_engine_preflight import inspect_video_workflow_runtime

    report = inspect_video_workflow_runtime({
        "1": {"class_type": "UNETLoader", "inputs": {
            "unet_name": "wan2.2_ti2v_5b_fp8_e4m3fn.safetensors",
            "weight_dtype": "fp8_e4m3fn",
        }},
        "2": {"class_type": "BlockSwapOffload", "inputs": {
            "offload_device": "cpu",
        }},
    })

    assert report["model_assets"][0]["input"] == "unet_name"
    assert report["precision_evidence"]["fp8"]
    assert report["offload_evidence"]


def test_engine_registry_preflight_rejects_generic_i2v_claiming_dialogue_controls(monkeypatch, tmp_path):
    import json
    from src.services import video_engine_preflight as module

    workflow = tmp_path / "wan.json"
    workflow.write_text("{}", encoding="utf-8")
    registry = tmp_path / "registry.json"
    registry.write_text(json.dumps({"engines": [{
        "id": "generic-wan",
        "model_profile": "wan_2_2_i2v_14b",
        "workflow_path": "wan.json",
        "capabilities": {
            "identity_reference": True,
            "performance_control": True,
            "multi_character": True,
        },
    }]}), encoding="utf-8")
    monkeypatch.setattr(module, "preflight_video_workflow", lambda *_args, **_kwargs: {
        "status": "ready_for_live_test", "checks": {}, "action_items": [],
    })
    monkeypatch.setattr(module, "inspect_local_video_model", lambda *_args, **_kwargs: {
        "status": "ready",
        "profile": "wan_2_2_i2v_14b",
        "supports_temporal_keyframes": False,
        "native_capabilities": ["identity_reference"],
        "action_items": [],
    })

    report = module.preflight_local_video_engine_registry(registry_path=str(registry))

    assert report["status"] == "blocked"
    assert report["engines"] == []
    assert "multi_character" in report["action_items"][0]
    assert "performance_control" in report["action_items"][0]


def test_motion_reference_library_preflight_records_approved_assets(tmp_path):
    import json
    from src.services import video_engine_preflight as module

    clip = tmp_path / "turn.mp4"
    clip.write_bytes(b"approved-turn")
    manifest = tmp_path / "motion-library.json"
    manifest.write_text(json.dumps({"assets": [{
        "id": "turn",
        "path": "turn.mp4",
        "tags": ["turn around", "转身"],
        "shot_roles": ["action"],
        "action_intensities": ["medium"],
    }]}), encoding="utf-8")

    report = module.preflight_motion_reference_library(str(manifest))

    assert report["status"] == "ready"
    assert report["assets"][0]["asset_id"] == "turn"
    assert report["assets"][0]["sha256"]
    assert report["assets"][0]["character_range"] == [1, 1]


def test_motion_reference_library_preflight_blocks_missing_asset(tmp_path):
    import json
    from src.services import video_engine_preflight as module

    manifest = tmp_path / "motion-library.json"
    manifest.write_text(json.dumps({"assets": [{
        "id": "turn",
        "path": "missing.mp4",
        "tags": ["turn around"],
    }]}), encoding="utf-8")

    report = module.preflight_motion_reference_library(str(manifest))

    assert report["status"] == "blocked"
    assert "does not exist" in report["action_items"][0]

from src.services.video_engine_preflight import (
    preflight_end_frame_workflow,
    preflight_video_provider,
    preflight_production_video_engine,
)


def test_local_model_inspection_rejects_svd_for_final_short_drama(monkeypatch, tmp_path):
    import json
    from src.services import video_engine_preflight as module

    workflow = tmp_path / "svd_video.json"
    workflow.write_text(json.dumps({
        "1": {"class_type": "SVD_img2vid_Conditioning"},
        "2": {"class_type": "VHS_VideoCombine"},
    }), encoding="utf-8")
    monkeypatch.setattr(module.settings, "LOCAL_VIDEO_MODEL_PROFILE", "auto")

    report = module.inspect_local_video_model(str(workflow))

    assert report["status"] == "blocked"
    assert report["profile"] == "svd_legacy"
    assert report["production_ready"] is False


def test_local_model_inspection_accepts_explicit_wan_22_workflow(monkeypatch, tmp_path):
    import json
    from src.services import video_engine_preflight as module

    workflow = tmp_path / "wan_video.json"
    workflow.write_text(json.dumps({
        "1": {"class_type": "Wan2.2ImageToVideo"},
        "model": {"class_type": "UNETLoader", "inputs": {"unet_name": "wan2.2_ti2v_5B_fp16.safetensors"}},
        "2": {"class_type": "VHS_VideoCombine"},
    }), encoding="utf-8")
    monkeypatch.setattr(module.settings, "LOCAL_VIDEO_MODEL_PROFILE", "auto")
    monkeypatch.setattr(module.settings, "GENERATION_VIDEO_MODEL_FPS", 24)
    monkeypatch.setattr(module.settings, "GENERATION_VIDEO_MAX_FRAMES", 96)

    report = module.inspect_local_video_model(str(workflow))

    assert report["status"] == "ready"
    assert report["profile"] == "wan_2_2_ti2v_5b"


@pytest.mark.parametrize(("marker", "expected_profile", "expected_capabilities"), [
    (
        "HunyuanCustomImageVideoConditioning",
        "hunyuan_custom",
        {"identity_reference", "performance_control", "multi_character", "motion_control"},
    ),
    (
        "HunyuanVideo-AvatarAudioConditioning",
        "hunyuanvideo_avatar",
        {"identity_reference", "performance_control", "multi_character"},
    ),
    (
        "Wan2.2-AnimateReferenceVideo",
        "wan_2_2_animate",
        {"identity_reference", "performance_control", "motion_control"},
    ),
])
def test_local_model_inspection_recognizes_specialized_short_drama_profiles(
    monkeypatch, tmp_path, marker, expected_profile, expected_capabilities,
):
    import json
    from src.services import video_engine_preflight as module

    workflow = tmp_path / f"{expected_profile}.json"
    workflow.write_text(json.dumps({"1": {"class_type": marker}}), encoding="utf-8")
    monkeypatch.setattr(module.settings, "LOCAL_VIDEO_MODEL_PROFILE", "auto")
    monkeypatch.setattr(module.settings, "GENERATION_VIDEO_MODEL_FPS", 24)
    monkeypatch.setattr(module.settings, "GENERATION_VIDEO_MAX_FRAMES", 120)
    monkeypatch.setattr(module.settings, "GENERATION_VIDEO_MID_KEYFRAME_ENABLED", False)

    report = module.inspect_local_video_model(str(workflow))

    assert report["status"] == "ready"
    assert report["profile"] == expected_profile
    assert set(report["native_capabilities"]) == expected_capabilities


def test_local_model_inspection_blocks_plain_wan_when_temporal_anchors_enabled(monkeypatch, tmp_path):
    import json
    from src.services import video_engine_preflight as module

    workflow = tmp_path / "wan_video.json"
    workflow.write_text(json.dumps({
        "1": {"class_type": "Wan2.2ImageToVideo"},
        "model": {"class_type": "UNETLoader", "inputs": {"unet_name": "wan2.2_ti2v_5B_fp16.safetensors"}},
    }), encoding="utf-8")
    monkeypatch.setattr(module.settings, "LOCAL_VIDEO_MODEL_PROFILE", "auto")
    monkeypatch.setattr(module.settings, "GENERATION_VIDEO_MODEL_FPS", 24)
    monkeypatch.setattr(module.settings, "GENERATION_VIDEO_MAX_FRAMES", 120)
    monkeypatch.setattr(module.settings, "GENERATION_VIDEO_MID_KEYFRAME_ENABLED", True)

    report = module.inspect_local_video_model(str(workflow))

    assert report["status"] == "blocked"
    assert report["supports_temporal_keyframes"] is False
    assert "does not natively support" in report["action_items"][0]


def test_local_model_inspection_accepts_ltx2_temporal_keyframes(monkeypatch, tmp_path):
    import json
    from src.services import video_engine_preflight as module

    workflow = tmp_path / "ltx2_video.json"
    workflow.write_text(json.dumps({
        "model": {"class_type": "LTXVLoader", "inputs": {"model": "ltx-2-dev.safetensors"}},
        "conditioning": {"class_type": "VideoConditionByKeyframeIndex", "inputs": {
            "conditioning_images": [], "conditioning_indices": [],
        }},
    }), encoding="utf-8")
    monkeypatch.setattr(module.settings, "LOCAL_VIDEO_MODEL_PROFILE", "auto")
    monkeypatch.setattr(module.settings, "GENERATION_VIDEO_MODEL_FPS", 24)
    monkeypatch.setattr(module.settings, "GENERATION_VIDEO_MAX_FRAMES", 120)
    monkeypatch.setattr(module.settings, "GENERATION_VIDEO_MID_KEYFRAME_ENABLED", True)

    report = module.inspect_local_video_model(str(workflow))

    assert report["status"] == "ready"
    assert report["profile"] == "ltx_2_keyframes"
    assert report["supports_temporal_keyframes"] is True


def test_local_model_inspection_blocks_ambiguous_wan_variant(monkeypatch, tmp_path):
    import json
    from src.services import video_engine_preflight as module

    workflow = tmp_path / "wan_video.json"
    workflow.write_text(json.dumps({"1": {"class_type": "Wan2.2ImageToVideo"}}), encoding="utf-8")
    monkeypatch.setattr(module.settings, "LOCAL_VIDEO_MODEL_PROFILE", "auto")

    report = module.inspect_local_video_model(str(workflow))

    assert report["status"] == "blocked"
    assert report["profile"] == "wan_2_2"
    assert "does not identify" in report["action_items"][0]


def test_local_video_model_fingerprint_changes_when_native_sampling_changes(monkeypatch, tmp_path):
    import json
    from src.services import video_engine_preflight as module

    workflow = tmp_path / "wan_video.json"
    workflow.write_text(json.dumps({
        "1": {"class_type": "Wan2.2ImageToVideo"},
        "model": {"class_type": "UNETLoader", "inputs": {"unet_name": "wan2.2_ti2v_5B_fp16.safetensors"}},
    }), encoding="utf-8")
    monkeypatch.setattr(module.settings, "LOCAL_VIDEO_MODEL_PROFILE", "auto")
    monkeypatch.setattr(module.settings, "GENERATION_VIDEO_MODEL_FPS", 24)
    monkeypatch.setattr(module.settings, "GENERATION_VIDEO_MAX_FRAMES", 96)

    baseline = module.local_video_model_fingerprint(str(workflow))
    monkeypatch.setattr(module.settings, "GENERATION_VIDEO_MAX_FRAMES", 120)
    changed = module.local_video_model_fingerprint(str(workflow))

    assert baseline["model_status"] == "ready"
    assert baseline["workflow_sha256"]
    assert baseline["fingerprint"] != changed["fingerprint"]


def test_local_video_registry_fingerprint_binds_all_routable_workflows(monkeypatch, tmp_path):
    import json
    from src.services import video_engine_preflight as module

    workflow = tmp_path / "ltx.json"
    bindings = tmp_path / "ltx.bindings.json"
    workflow.write_text(json.dumps({
        "model": {"class_type": "LTXVLoader", "inputs": {"model": "ltx-2-dev.safetensors"}},
        "conditioning": {
            "class_type": "VideoConditionByKeyframeIndex",
            "inputs": {"conditioning_images": [], "conditioning_indices": []},
        },
    }), encoding="utf-8")
    bindings.write_text('{"version":2}', encoding="utf-8")
    registry = tmp_path / "registry.json"
    registry.write_text(json.dumps({"engines": [{
        "id": "ltx",
        "model_profile": "ltx_2_keyframes",
        "workflow_path": "ltx.json",
        "bindings_path": "ltx.bindings.json",
        "capabilities": {"temporal_keyframes": True},
    }]}), encoding="utf-8")
    monkeypatch.setattr(module.settings, "GENERATION_VIDEO_MODEL_FPS", 24)
    monkeypatch.setattr(module.settings, "GENERATION_VIDEO_MAX_FRAMES", 120)
    monkeypatch.setattr(module.settings, "GENERATION_VIDEO_MID_KEYFRAME_ENABLED", True)
    monkeypatch.setattr(module.settings, "COMFYUI_VIDEO_ENGINE_REGISTRY_PATH", str(registry))

    baseline = module.local_video_configuration_fingerprint()
    bindings.write_text('{"version":3}', encoding="utf-8")
    changed = module.local_video_configuration_fingerprint()

    assert baseline["profile"] == "engine_registry"
    assert baseline["model_status"] == "ready"
    assert baseline["engines"][0]["workflow_sha256"]
    assert baseline["fingerprint"] != changed["fingerprint"]


def test_local_model_inspection_blocks_wan_when_only_output_is_24fps(monkeypatch, tmp_path):
    import json
    from src.services import video_engine_preflight as module

    workflow = tmp_path / "wan_video.json"
    workflow.write_text(json.dumps({
        "1": {"class_type": "Wan2.2ImageToVideo"},
        "model": {"class_type": "UNETLoader", "inputs": {"unet_name": "wan2.2_ti2v_5B_fp16.safetensors"}},
    }), encoding="utf-8")
    monkeypatch.setattr(module.settings, "LOCAL_VIDEO_MODEL_PROFILE", "auto")
    monkeypatch.setattr(module.settings, "GENERATION_VIDEO_MODEL_FPS", 8)

    report = module.inspect_local_video_model(str(workflow))

    assert report["status"] == "blocked"
    assert "output interpolation" in report["action_items"][0]


def test_local_model_inspection_blocks_wan_when_frame_capacity_truncates_shots(monkeypatch, tmp_path):
    import json
    from src.services import video_engine_preflight as module

    workflow = tmp_path / "wan_video.json"
    workflow.write_text(json.dumps({
        "1": {"class_type": "Wan2.2ImageToVideo"},
        "model": {"class_type": "UNETLoader", "inputs": {"unet_name": "wan2.2_ti2v_5B_fp16.safetensors"}},
    }), encoding="utf-8")
    monkeypatch.setattr(module.settings, "LOCAL_VIDEO_MODEL_PROFILE", "auto")
    monkeypatch.setattr(module.settings, "GENERATION_VIDEO_MODEL_FPS", 24)
    monkeypatch.setattr(module.settings, "GENERATION_VIDEO_TARGET_SECONDS", 3.6)
    monkeypatch.setattr(module.settings, "GENERATION_VIDEO_MAX_FRAMES", 40)

    report = module.inspect_local_video_model(str(workflow))

    assert report["status"] == "blocked"
    assert report["required_target_frames"] == 87
    assert "cannot hold" in report["action_items"][0]


def test_production_preflight_blocks_local_svd_even_when_graph_is_reachable(monkeypatch):
    from src.services import video_engine_preflight as module

    monkeypatch.setattr(module, "preflight_video_workflow", lambda *_args, **_kwargs: {
        "status": "ready_for_live_test",
        "action_items": [],
    })
    monkeypatch.setattr(module, "preflight_video_provider", lambda *_args, **_kwargs: {
        "provider": "local_comfyui",
        "status": "skipped",
        "checks": {},
    })
    monkeypatch.setattr(module, "inspect_local_video_model", lambda *_args, **_kwargs: {
        "status": "blocked",
        "profile": "svd_legacy",
        "action_items": ["SVD is draft-only."],
    })

    report = module.preflight_production_video_engine()

    assert report["status"] == "production_not_ready"
    assert report["local_model"]["profile"] == "svd_legacy"
    assert report["action_items"] == ["SVD is draft-only."]


def test_remote_end_frame_preflight_requires_both_image_workflows(monkeypatch, tmp_path):
    from src.services.video_engine_preflight import settings

    monkeypatch.setattr(settings, "GENERATION_VIDEO_END_FRAME_ENABLED", True)
    monkeypatch.setattr(settings, "COMFYUI_WORKFLOW_PATH", str(tmp_path / "image.json"))
    monkeypatch.setattr(settings, "COMFYUI_REFERENCE_WORKFLOW_PATH", str(tmp_path / "reference.json"))

    report = preflight_end_frame_workflow("seedance_api")

    assert report["status"] == "blocked"
    assert report["checks"]["image_workflow_file"] is False
    assert report["checks"]["reference_workflow_file"] is False
    assert "both local ComfyUI image workflows" in report["action_items"][0]


def test_local_end_frame_preflight_is_skipped_for_local_video(monkeypatch):
    from src.services.video_engine_preflight import settings

    monkeypatch.setattr(settings, "GENERATION_VIDEO_END_FRAME_ENABLED", True)

    report = preflight_end_frame_workflow("local_comfyui")

    assert report["status"] == "skipped"


def test_remote_end_frame_preflight_validates_workflow_contract(monkeypatch, tmp_path):
    import json
    from src.services.video_engine_preflight import settings

    base = {
        "nodes": {
            "checkpoint": {"class_type": "CheckpointLoaderSimple", "inputs": {}},
            "sampler": {"class_type": "KSampler", "inputs": {}},
            "decode": {"class_type": "VAEDecode", "inputs": {}},
            "save": {"class_type": "SaveImage", "inputs": {}},
        }
    }
    reference = {
        "nodes": {
            **base["nodes"],
            "load": {"class_type": "LoadImage", "inputs": {}},
            "adapter": {"class_type": "IPAdapterFaceID", "inputs": {}},
        }
    }
    image_path = tmp_path / "image.json"
    reference_path = tmp_path / "reference.json"
    image_path.write_text(json.dumps(base), encoding="utf-8")
    reference_path.write_text(json.dumps(reference), encoding="utf-8")
    monkeypatch.setattr(settings, "GENERATION_VIDEO_END_FRAME_ENABLED", True)
    monkeypatch.setattr(settings, "COMFYUI_WORKFLOW_PATH", str(image_path))
    monkeypatch.setattr(settings, "COMFYUI_REFERENCE_WORKFLOW_PATH", str(reference_path))

    report = preflight_end_frame_workflow("seedance_api")

    assert report["status"] == "ready"
    assert report["image_workflow"]["valid"] is True
    assert report["reference_workflow"]["valid"] is True


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


def test_remote_cancel_endpoint_requires_task_id_placeholder(monkeypatch):
    from src.services.video_engine_preflight import settings

    monkeypatch.setattr(settings, "GENERATION_PROVIDER", "http_video_api")
    monkeypatch.setattr(settings, "HTTP_VIDEO_ENDPOINT", "https://example.test/generate")
    monkeypatch.setattr(settings, "HTTP_VIDEO_API_KEY", "secret")
    monkeypatch.setattr(settings, "HTTP_VIDEO_STATUS_ENDPOINT", "https://example.test/status/{job_id}")
    monkeypatch.setattr(settings, "HTTP_VIDEO_CANCEL_ENDPOINT", "https://example.test/cancel")
    for name in (
        "HTTP_VIDEO_ENDPOINT", "HTTP_VIDEO_API_KEY", "HTTP_VIDEO_STATUS_ENDPOINT",
        "HTTP_VIDEO_CANCEL_ENDPOINT",
    ):
        monkeypatch.delenv(name, raising=False)

    report = preflight_video_provider()

    assert report["status"] == "blocked"
    assert report["checks"]["remote_cancel_endpoint_configured"] is True
    assert report["checks"]["remote_cancel_endpoint_valid"] is False
    assert "HTTP_VIDEO_CANCEL_ENDPOINT" in report["action_items"][0]


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


def test_native_seedance_preflight_exposes_complete_model_catalog(monkeypatch):
    from src.services.video_engine_preflight import settings

    monkeypatch.setattr(settings, "GENERATION_PROVIDER", "seedance_api")
    monkeypatch.setenv("SEEDANCE_ENDPOINT", "https://ark.cn-beijing.volces.com/api/v3/contents/generations/tasks")
    monkeypatch.setenv("SEEDANCE_API_KEY", "secret")
    monkeypatch.setenv("SEEDANCE_API_FORMAT", "ark_v3")
    monkeypatch.setenv("SEEDANCE_MODEL", "doubao-seedance-2-0-fast-260128")

    report = preflight_video_provider()

    assert [item["id"] for item in report["capabilities"]["available_models"]] == [
        "doubao-seedance-2-5-260628",
        "doubao-seedance-2-0-260128",
        "doubao-seedance-2-0-fast-260128",
        "doubao-seedance-2-0-mini-260128",
        "doubao-seedance-1-0-pro-250528",
        "doubao-seedance-1-0-pro-fast-251015",
    ]


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


def test_native_seedance_25_preflight_accepts_explicit_first_frame_mode(monkeypatch):
    from src.services.video_engine_preflight import settings

    monkeypatch.setattr(settings, "GENERATION_PROVIDER", "seedance_api")
    monkeypatch.setenv("SEEDANCE_ENDPOINT", "https://ark.cn-beijing.volces.com/api/v3/contents/generations/tasks")
    monkeypatch.setenv("SEEDANCE_API_KEY", "secret")
    monkeypatch.setenv("SEEDANCE_API_FORMAT", "ark_v3")
    monkeypatch.setenv("SEEDANCE_MODEL", "doubao-seedance-2-5-260628")

    report = preflight_video_provider(request_mode_override="first_frame")

    assert report["status"] == "configured"
    assert report["checks"]["request_mode_valid"] is True
    assert report["checks"]["first_frame_mode_supported"] is True
    assert report["capabilities"]["supports_first_frame_mode"] is True


def test_native_seedance_20_preflight_blocks_explicit_first_frame_mode(monkeypatch):
    from src.services.video_engine_preflight import settings

    monkeypatch.setattr(settings, "GENERATION_PROVIDER", "seedance_api")
    monkeypatch.setenv("SEEDANCE_ENDPOINT", "https://ark.cn-beijing.volces.com/api/v3/contents/generations/tasks")
    monkeypatch.setenv("SEEDANCE_API_KEY", "secret")
    monkeypatch.setenv("SEEDANCE_API_FORMAT", "ark_v3")
    monkeypatch.setenv("SEEDANCE_MODEL", "doubao-seedance-2-0-260128")

    report = preflight_video_provider(request_mode_override="first_frame")

    assert report["status"] == "blocked"
    assert report["checks"]["first_frame_mode_supported"] is False
    assert any("explicit first_frame" in item for item in report["action_items"])


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


def test_native_seedance_10_fast_blocks_explicit_first_last_frame_mode(monkeypatch):
    from src.services.video_engine_preflight import settings

    monkeypatch.setattr(settings, "GENERATION_PROVIDER", "seedance_api")
    monkeypatch.setenv("SEEDANCE_ENDPOINT", "https://ark.cn-beijing.volces.com/api/v3/contents/generations/tasks")
    monkeypatch.setenv("SEEDANCE_API_KEY", "secret")
    monkeypatch.setenv("SEEDANCE_API_FORMAT", "ark_v3")
    monkeypatch.setenv("SEEDANCE_MODEL", "doubao-seedance-1-0-pro-fast-251015")

    report = preflight_video_provider(request_mode_override="first_last_frame")

    assert report["status"] == "blocked"
    assert report["checks"]["first_last_frame_mode_supported"] is False


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


def test_seedance_preflight_blocks_disabled_output_validation(monkeypatch):
    from src.services.video_engine_preflight import settings

    monkeypatch.setattr(settings, "GENERATION_PROVIDER", "seedance_api")
    monkeypatch.setenv("SEEDANCE_ENDPOINT", "https://ark.example/tasks")
    monkeypatch.setenv("SEEDANCE_API_KEY", "secret")
    monkeypatch.setenv("SEEDANCE_API_FORMAT", "ark_v3")
    monkeypatch.setenv("SEEDANCE_VALIDATE_OUTPUT", "false")

    report = preflight_video_provider()

    assert report["status"] == "blocked"
    assert report["checks"]["output_validation_enabled"] is False
    assert report["capabilities"]["output_artifact_validation"] is False
    assert any("not allowed for production" in item for item in report["warnings"])


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


def test_seedance_preflight_exposes_canonical_model_capabilities(monkeypatch):
    from src.services.video_engine_preflight import settings

    monkeypatch.setattr(settings, "GENERATION_PROVIDER", "seedance_api")
    monkeypatch.setenv("SEEDANCE_ENDPOINT", "https://ark.example/tasks")
    monkeypatch.setenv("SEEDANCE_API_KEY", "secret")
    monkeypatch.setenv("SEEDANCE_API_FORMAT", "ark_v3")
    monkeypatch.setenv("SEEDANCE_MODEL", "doubao-seedance-2-5-260628")

    report = preflight_video_provider()
    capabilities = report["capabilities"]

    assert capabilities["supported_resolutions"] == ["1080p", "480p", "720p"]
    assert capabilities["duration_min_seconds"] == 2
    assert capabilities["duration_max_seconds"] == 30
    assert capabilities["supports_draft"] is True
    assert capabilities["supports_auto_mode"] is True
    assert capabilities["supports_mov"] is True


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


def test_production_preflight_uses_ready_local_engine_registry(monkeypatch):
    import src.services.video_engine_preflight as module

    monkeypatch.setattr(module, "preflight_video_workflow", lambda *_args, **_kwargs: {
        "status": "skipped",
        "action_items": [],
    })
    monkeypatch.setattr(module, "preflight_video_provider", lambda: {
        "provider": "local_comfyui",
        "status": "blocked",
        "action_items": [],
    })
    registry_report = {
        "status": "ready_for_live_test",
        "engines": [{
            "engine_id": "ltx",
            "status": "ready",
            "model": {"status": "ready", "profile": "ltx_2_keyframes"},
        }],
        "action_items": [],
    }
    monkeypatch.setattr(
        module,
        "preflight_local_video_engine_registry",
        lambda *_args, **_kwargs: registry_report,
    )

    report = module.preflight_production_video_engine()

    assert report["status"] == "ready_for_production_video_test"
    assert report["workflow"] is registry_report
    assert report["local_model"]["profiles"] == ["ltx_2_keyframes"]


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


def test_production_preflight_blocks_seedance_without_output_artifact_validation(monkeypatch):
    import src.services.video_engine_preflight as module

    monkeypatch.setattr(module, "preflight_video_workflow", lambda *_args, **_kwargs: {
        "status": "skipped",
        "action_items": [],
    })
    monkeypatch.setattr(module, "preflight_video_provider", lambda *_args, **_kwargs: {
        "provider": "seedance_api",
        "status": "configured",
        "checks": {},
        "capabilities": {"output_artifact_validation": False},
    })

    report = module.preflight_production_video_engine(provider_override="seedance_api")

    assert report["status"] == "production_not_ready"
    assert "ffprobe" in report["action_items"][0]


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
