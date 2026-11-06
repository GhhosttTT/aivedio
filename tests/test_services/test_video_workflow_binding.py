import json

import pytest

from src.services.video_workflow_binding import (
    VideoWorkflowBindingError,
    apply_video_workflow_bindings,
    discover_video_workflow_bindings,
    load_video_workflow_bindings,
    validate_video_workflow_bindings,
)


def test_sidecar_bindings_update_real_comfyui_node_inputs(tmp_path):
    workflow_path = tmp_path / "wan_api.json"
    workflow_path.write_text("{}", encoding="utf-8")
    sidecar = tmp_path / "wan_api.bindings.json"
    sidecar.write_text(json.dumps({
        "version": 1,
        "bindings": {
            "positive_prompt": {"node_id": "text", "input": "text"},
            "reference_image": {"node_id": "image", "input": "image"},
            "num_frames": {"node_id": "latent", "input": "length"},
            "seed": [
                {"node_id": "high", "input": "noise_seed"},
                {"node_id": "low", "input": "noise_seed"},
            ],
        },
        "derived_controls": ["repair_action", "quality_pipeline", "spatial_plan_json"],
    }), encoding="utf-8")
    workflow = {
        "text": {"class_type": "CLIPTextEncode", "inputs": {"text": "old"}},
        "image": {"class_type": "LoadImage", "inputs": {"image": "old.png"}},
        "latent": {"class_type": "EmptyHunyuanLatentVideo", "inputs": {"length": 81}},
        "high": {"class_type": "KSamplerAdvanced", "inputs": {"noise_seed": 1}},
        "low": {"class_type": "KSamplerAdvanced", "inputs": {"noise_seed": 1}},
    }

    manifest = load_video_workflow_bindings(workflow_path)
    validation = validate_video_workflow_bindings(workflow, manifest)
    resolved = apply_video_workflow_bindings(workflow, manifest, {
        "positive_prompt": "cinematic dialogue reaction",
        "reference_image": "input/lead.png",
        "num_frames": 97,
        "seed": 31001,
    })

    assert validation["status"] == "valid"
    assert manifest["sha256"]
    assert resolved["text"]["inputs"]["text"] == "cinematic dialogue reaction"
    assert resolved["image"]["inputs"]["image"] == "input/lead.png"
    assert resolved["latent"]["inputs"]["length"] == 97
    assert resolved["high"]["inputs"]["noise_seed"] == 31001
    assert resolved["low"]["inputs"]["noise_seed"] == 31001
    assert workflow["text"]["inputs"]["text"] == "old"


def test_binding_validation_rejects_missing_node_inputs(tmp_path):
    workflow_path = tmp_path / "wan_api.json"
    workflow_path.write_text("{}", encoding="utf-8")
    (tmp_path / "wan_api.bindings.json").write_text(json.dumps({
        "bindings": {"positive_prompt": {"node_id": "missing", "input": "text"}},
    }), encoding="utf-8")

    manifest = load_video_workflow_bindings(workflow_path)
    validation = validate_video_workflow_bindings({}, manifest)

    assert validation["status"] == "invalid"
    assert "node missing does not exist" in validation["errors"][0]
    with pytest.raises(VideoWorkflowBindingError, match="node missing"):
        apply_video_workflow_bindings({}, manifest, {"positive_prompt": "shot"})


def test_binding_discovery_handles_two_stage_wan_sampler_graph():
    workflow = {
        "positive": {"class_type": "CLIPTextEncode", "_meta": {"title": "Positive Prompt"}, "inputs": {"text": ""}},
        "negative": {"class_type": "CLIPTextEncode", "_meta": {"title": "Negative Prompt"}, "inputs": {"text": ""}},
        "first": {"class_type": "LoadImage", "_meta": {"title": "First Frame"}, "inputs": {"image": "a.png"}},
        "last": {"class_type": "LoadImage", "_meta": {"title": "Last Frame"}, "inputs": {"image": "b.png"}},
        "latent": {"class_type": "EmptyHunyuanLatentVideo", "inputs": {"width": 704, "height": 1280, "length": 81}},
        "high": {"class_type": "KSamplerAdvanced", "inputs": {"noise_seed": 1}},
        "low": {"class_type": "KSamplerAdvanced", "inputs": {"noise_seed": 2}},
        "save": {"class_type": "VHS_VideoCombine", "inputs": {"fps": 24, "filename_prefix": "wan"}},
    }

    report = discover_video_workflow_bindings(workflow)

    assert report["status"] == "ready_for_review"
    assert report["unresolved"] == []
    assert report["manifest"]["bindings"]["reference_image"]["node_id"] == "first"
    assert report["manifest"]["bindings"]["end_image"]["node_id"] == "last"
    assert [item["node_id"] for item in report["manifest"]["bindings"]["seed"]] == ["high", "low"]


def test_binding_discovery_finds_explicit_temporal_keyframe_node():
    workflow = {
        "model": {
            "class_type": "LTXVLoader",
            "inputs": {"model": "ltx-2-dev.safetensors"},
        },
        "conditioning": {
            "class_type": "VideoConditionByKeyframeIndex",
            "_meta": {"title": "LTX Keyframe Conditioning"},
            "inputs": {
                "conditioning_images": [],
                "conditioning_indices": [],
                "conditioning_strengths": [],
            },
        },
    }

    report = discover_video_workflow_bindings(workflow)
    bindings = report["manifest"]["bindings"]

    assert bindings["keyframe_images"] == {
        "node_id": "conditioning", "input": "conditioning_images",
    }
    assert bindings["keyframe_indices"]["input"] == "conditioning_indices"
    assert bindings["keyframe_strengths"]["input"] == "conditioning_strengths"
    assert report["manifest"]["model_profile"] == "ltx_2_keyframes"
    assert report["manifest"]["capabilities"]["temporal_keyframes"] is True


def test_binding_discovery_finds_driving_video_and_performance_audio_nodes():
    workflow = {
        "video": {"class_type": "VHS_LoadVideo", "inputs": {"video": "drive.mp4"}},
        "audio": {"class_type": "LoadAudio", "inputs": {"audio": "line.wav"}},
        "model": {"class_type": "Wan2.2-AnimateReferenceVideo", "inputs": {}},
    }

    report = discover_video_workflow_bindings(workflow)
    bindings = report["manifest"]["bindings"]

    assert bindings["driving_video"] == {"node_id": "video", "input": "video"}
    assert bindings["performance_audio"] == {"node_id": "audio", "input": "audio"}
    assert report["manifest"]["model_profile"] == "wan_2_2_animate"


def test_temporal_keyframe_workflow_does_not_require_independent_end_image():
    workflow = {
        "model": {
            "class_type": "LTXVLoader",
            "inputs": {"model": "ltx-2-dev.safetensors"},
        },
        "positive": {
            "class_type": "CLIPTextEncode",
            "_meta": {"title": "Positive Prompt"},
            "inputs": {"text": ""},
        },
        "negative": {
            "class_type": "CLIPTextEncode",
            "_meta": {"title": "Negative Prompt"},
            "inputs": {"text": ""},
        },
        "first": {
            "class_type": "LoadImage",
            "_meta": {"title": "First Frame"},
            "inputs": {"image": "opening.png"},
        },
        "conditioning": {
            "class_type": "VideoConditionByKeyframeIndex",
            "_meta": {"title": "LTX Keyframe Conditioning"},
            "inputs": {
                "conditioning_images": [],
                "conditioning_indices": [],
                "conditioning_strengths": [],
            },
        },
        "latent": {
            "class_type": "EmptyLTXVLatentVideo",
            "inputs": {"width": 704, "height": 1280, "length": 121},
        },
        "sampler": {
            "class_type": "KSampler",
            "inputs": {"seed": 1},
        },
        "save": {
            "class_type": "VHS_VideoCombine",
            "inputs": {"fps": 24, "filename_prefix": "ltx"},
        },
    }

    report = discover_video_workflow_bindings(workflow)

    assert report["status"] == "ready_for_review"
    assert report["unresolved"] == []
    assert "end_image" not in report["manifest"]["bindings"]
    assert report["manifest"]["capabilities"]["temporal_keyframes"] is True
