import io
import json
from pathlib import Path
from unittest.mock import Mock

import httpx
from PIL import Image
import pytest

from src.config import settings
from src.models.workflow_config import WorkflowType
from src.services.comfyui_service import ComfyUIService, ComfyUIError, ComfyUIWaitTimeout


@pytest.fixture
def service():
    service = ComfyUIService()
    yield service
    service.client.close()


def test_selected_checkpoint_and_parameters_are_not_overwritten(service, monkeypatch, tmp_path):
    monkeypatch.setattr(service, "preflight", Mock())
    submit = Mock(return_value=str(tmp_path / "out.png"))
    monkeypatch.setattr(service, "_submit_and_wait", submit)
    service.generate_image("empty room, wide shot, animation", width=1344, height=768, seed=42,
                           steps=28, cfg_scale=6, negative_prompt="blurry", output_path=str(tmp_path / "out.png"))
    graph = submit.call_args.args[0]
    classes = {node["class_type"]: node["inputs"] for node in graph.values()}
    assert classes["CheckpointLoaderSimple"]["ckpt_name"] == "Juggernaut-XL_v9_RunDiffusionPhoto_v2.safetensors"
    assert "LoraLoader" not in classes
    sampler = classes["KSampler"]
    assert (sampler["steps"], sampler["cfg"], sampler["seed"]) == (28, 6, 42)
    assert graph[sampler["positive"][0]]["inputs"]["text"] == "empty room, wide shot, animation"
    assert json.loads((tmp_path / "out.workflow.json").read_text()) == graph


def test_service_uses_configured_workflow_path(monkeypatch, tmp_path):
    workflow = {
        "workflow": {"name": "Configured Workflow", "version": "1.0.0"},
        "nodes": {
            "checkpoint_loader": {
                "class_type": "CheckpointLoaderSimple",
                "inputs": {"ckpt_name": "configured.safetensors"},
            },
        },
    }
    path = tmp_path / "configured_workflow.json"
    path.write_text(json.dumps(workflow), encoding="utf-8")
    monkeypatch.setattr(settings, "COMFYUI_WORKFLOW_PATH", str(path))

    configured = ComfyUIService()
    try:
        assert configured.workflow_path == str(path)
        assert configured.workflow_manager.get_current_workflow().workflow.name == "Configured Workflow"
    finally:
        configured.client.close()


def test_conditioning_uses_graph_edges_not_node_order(service):
    cfg = service.workflow_manager.get_current_workflow()
    items = list(cfg.nodes.items())
    cfg.nodes = dict(reversed(items))
    graph = service._build_workflow("positive", "negative", 1024, 576, 28, 6, 42)
    sampler = next(n["inputs"] for n in graph.values() if n["class_type"] == "KSampler")
    assert graph[sampler["positive"][0]]["inputs"]["text"] == "positive"
    assert graph[sampler["negative"][0]]["inputs"]["text"] == "negative"


def test_reference_uploaded_using_comfyui_input_name(service, tmp_path):
    reference = tmp_path / "ref.png"
    reference.write_bytes(b"a reference")
    calls = []
    def handler(request):
        calls.append(request)
        return httpx.Response(200, json={"name": "ref_renamed.png", "subfolder": "references"})
    service.client.close()
    service.client = httpx.Client(transport=httpx.MockTransport(handler))
    service.workflow_manager.load_workflow(workflow_path="configs/comfyui_workflow_ipadapter_sdxl.json")
    graph = service._build_workflow("subject", "blurry", 1344, 768, 28, 6, 42, str(reference), True)
    loader = next(n for n in graph.values() if n["class_type"] == "LoadImage")
    assert loader["inputs"]["image"] == "references/ref_renamed.png"
    assert calls[0].url.path == "/upload/image"
    assert b"a reference" in calls[0].content


def test_missing_model_is_caught_before_queue_submission(service):
    service.client.close()
    service.client = httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(200, json={
        "CheckpointLoaderSimple": {"input": {"required": {"ckpt_name": [["other.safetensors"]]}}}
    })))
    with pytest.raises(ComfyUIError, match="missing model"):
        service.preflight({"1": {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": "wanted.safetensors"}}})


def test_missing_reference_config_does_not_fall_back(service, monkeypatch):
    monkeypatch.setattr(settings, "COMFYUI_REFERENCE_WORKFLOW_PATH", "")
    with pytest.raises(ComfyUIError, match="REFERENCE_WORKFLOW"):
        service.generate_image("subject", reference_image="ref.png", use_ipadapter=True)


def test_no_face_does_not_silently_drop_identity(service, monkeypatch):
    monkeypatch.setattr(settings, "COMFYUI_REFERENCE_WORKFLOW_PATH", "configs/comfyui_workflow_ipadapter_sdxl.json")
    monkeypatch.setattr(service, "_upload_reference_image", lambda path: "ref.png")
    monkeypatch.setattr(service, "preflight", Mock())
    submit = Mock(side_effect=ComfyUIError("InsightFace: No face detected"))
    monkeypatch.setattr(service, "_submit_and_wait", submit)
    with pytest.raises(ComfyUIError, match="select another reference"):
        service.generate_image("subject", reference_image="ref.png", use_ipadapter=True)
    assert submit.call_count == 1


def test_observation_timeout_does_not_resubmit(service, monkeypatch):
    monkeypatch.setattr(service, "preflight", Mock())
    submit = Mock(side_effect=ComfyUIWaitTimeout("pending job 123"))
    monkeypatch.setattr(service, "_submit_and_wait", submit)
    with pytest.raises(ComfyUIWaitTimeout):
        service.generate_image("subject")
    assert submit.call_count == 1


def test_completed_error_is_still_error(service):
    service.client.close()
    service.client = httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(200, json={
        "123": {"status": {"completed": True, "status_str": "error", "messages": ["OOM"]}}
    })))
    with pytest.raises(ComfyUIError, match="OOM"):
        service._wait_for_completion("123", poll_interval=0)


def test_faceid_weight_setting_fills_missing_workflow_default(service, tmp_path, monkeypatch):
    reference = tmp_path / "ref.png"
    reference.write_bytes(b"a reference")
    service.workflow_manager.load_workflow(workflow_path="configs/comfyui_workflow_ipadapter_sdxl.json")
    config = service.workflow_manager.get_current_workflow()
    config.parameters.default.pop("ipadapter_weight", None)
    monkeypatch.setattr(settings, "FACEID_WEIGHT", 0.42)
    monkeypatch.setattr(service, "_upload_reference_image", lambda path: "ref.png")

    graph = service._build_workflow(
        "subject", "blurry", 1344, 768, 28, 6, 42, str(reference), True
    )

    adapter = next(node for node in graph.values() if node["class_type"] == "IPAdapterFaceID")
    assert adapter["inputs"]["weight"] == 0.42


def test_face_detailer_settings_override_workflow_defaults(service, monkeypatch):
    service.workflow_manager.load_workflow(
        workflow_path="configs/comfyui_workflow_juggernaut_facedetailer.json"
    )
    monkeypatch.setattr(settings, "FACE_DETAILER_STEPS", 30)
    monkeypatch.setattr(settings, "FACE_DETAILER_CFG", 4.5)
    monkeypatch.setattr(settings, "FACE_DETAILER_DENOISE", 0.31)
    monkeypatch.setattr(settings, "FACE_DETAILER_GUIDE_SIZE", 896)

    graph = service._build_workflow("subject", "blurry", 1024, 576, 28, 6, 42)

    detailer = next(node for node in graph.values() if node["class_type"] == "FaceDetailer")
    assert detailer["inputs"]["steps"] == 30
    assert detailer["inputs"]["cfg"] == 4.5
    assert detailer["inputs"]["denoise"] == 0.31
    assert detailer["inputs"]["guide_size"] == 896


def test_face_detailer_enabled_requires_supporting_workflow(service, monkeypatch):
    monkeypatch.setattr(settings, "FACE_DETAILER_ENABLED", True)

    with pytest.raises(ComfyUIError, match="FaceDetailer"):
        service._build_workflow("subject", "blurry", 1024, 576, 28, 6, 42)

    service.workflow_manager.load_workflow(
        workflow_path="configs/comfyui_workflow_juggernaut_facedetailer.json"
    )
    graph = service._build_workflow("subject", "blurry", 1024, 576, 28, 6, 42)
    assert any(node["class_type"] == "FaceDetailer" for node in graph.values())


def test_face_detailer_target_updates_detector_prompt(service, monkeypatch):
    service.workflow_manager.load_workflow(
        workflow_path="configs/comfyui_workflow_juggernaut_facedetailer.json"
    )
    monkeypatch.setattr(settings, "FACE_DETAILER_TARGET", "face, hands")

    graph = service._build_workflow("subject", "blurry", 1024, 576, 28, 6, 42)

    detector = next(node for node in graph.values() if node["class_type"] == "CLIPSegDetectorProvider")
    assert detector["inputs"]["text"] == "face, hands"
