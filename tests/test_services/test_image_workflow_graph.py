from pathlib import Path
from unittest.mock import Mock

import pytest
from PIL import Image

from src.models.workflow_config import NodeConfig
from src.services.comfyui_service import ComfyUIError, ComfyUIService
from src.services.image_workflow_graph import ImageWorkflowGraph, ImageWorkflowGraphError, stage_seed
from src.services.workflow_manager import WorkflowManager, WorkflowManagerError


ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def service():
    instance = ComfyUIService(workflow_path=str(ROOT / "configs/comfyui_workflow_sdxl_multistage.json"))
    yield instance
    instance.client.close()


def build(instance, **kwargs):
    return instance._build_workflow("actor at a doorway", "blurry, text", 768, 1344, 48, 5.4, 123, **kwargs)


def by_name(instance, graph, name):
    names = list(instance.workflow_manager.get_current_workflow().nodes)
    return graph[str(names.index(name) + 1)]


def test_multistage_graph_keeps_detail_denoise_and_parameters_when_reordered(service):
    config = service.workflow_manager.get_current_workflow()
    config.nodes = dict(reversed(list(config.nodes.items())))
    graph = build(service)
    base = by_name(service, graph, "composition_sampler")["inputs"]
    detail = by_name(service, graph, "detail_sampler")["inputs"]
    assert (base["steps"], base["cfg"], base["seed"], base["denoise"]) == (48, 5.4, 123, 1.0)
    assert (detail["steps"], detail["cfg"], detail["denoise"]) == (20, 4.8, 0.24)
    assert detail["seed"] == stage_seed(123, "detail_sampler")
    assert detail["seed"] != base["seed"]
    assert by_name(service, graph, "positive")["inputs"]["text"] == "actor at a doorway"


def test_output_resolution_follows_final_pass_instead_of_base_preview(service):
    config = service.workflow_manager.get_current_workflow()
    config.nodes["decode_base"] = NodeConfig("VAEDecode", {
        "samples": ["composition_sampler", 0], "vae": ["checkpoint_loader", 2],
    })
    config.nodes["save_base"] = NodeConfig("SaveImage", {"images": ["decode_base", 0], "filename_prefix": "preview"})
    config.parameters.default.pop("output_node")
    graph = build(service)
    output = ImageWorkflowGraph(graph).output_node()
    assert graph[graph[output]["inputs"]["images"][0]]["inputs"]["samples"][0] == str(
        list(config.nodes).index("detail_sampler") + 1
    )
    service._download_image = Mock(return_value="final.png")
    result = {"outputs": {
        "preview": {"images": [{"filename": "base.png"}]},
        output: {"images": [{"filename": "detailed.png"}]},
    }}
    assert service._get_generated_image(result, "out.png", output) == "final.png"
    assert service._download_image.call_args.kwargs["filename"] == "detailed.png"


def test_ambiguous_independent_outputs_require_explicit_selection():
    graph = ImageWorkflowGraph({
        "a": {"class_type": "LoadImage", "inputs": {}},
        "b": {"class_type": "LoadImage", "inputs": {}},
        "x": {"class_type": "SaveImage", "inputs": {"images": ["a", 0]}},
        "y": {"class_type": "SaveImage", "inputs": {"images": ["b", 0]}},
    })
    with pytest.raises(ImageWorkflowGraphError, match="ambiguous"):
        graph.output_node()
    assert graph.output_node("y") == "y"


def test_controlnet_conditioning_keeps_positive_and_negative_text_separate():
    nodes = {
        "p": {"class_type": "CLIPTextEncode", "inputs": {"text": "positive"}},
        "n": {"class_type": "CLIPTextEncode", "inputs": {"text": "negative"}},
        "control": {"class_type": "ControlNetApplyAdvanced", "inputs": {"positive": ["p", 0], "negative": ["n", 0]}},
        "sample": {"class_type": "KSampler", "inputs": {"positive": ["control", 0], "negative": ["control", 1]}},
    }
    graph = ImageWorkflowGraph(nodes)
    assert graph.prompt_nodes("sample", "positive") == {"p"}
    assert graph.prompt_nodes("sample", "negative") == {"n"}


def test_single_reference_does_not_bypass_model_chain_or_change_detailer_weight(service):
    service.workflow_manager.load_workflow(workflow_path=str(ROOT / "configs/comfyui_workflow_sdxl_multistage_reference.json"))
    config = service.workflow_manager.get_current_workflow()
    config.nodes["patched_model"] = NodeConfig("ModelSamplingDiscrete", {"model": ["identity_adapter", 0], "sampling": "eps"})
    config.nodes["composition_sampler"].inputs["model"] = ["patched_model", 0]
    config.nodes["identity_adapter"].inputs["weight_faceidv2"] = 1.35
    service._upload_reference_image = Mock(return_value="refs/actor.png")
    graph = build(service, reference_image="actor.png", use_ipadapter=True)
    model = by_name(service, graph, "composition_sampler")["inputs"]["model"]
    assert graph[model[0]]["class_type"] == "ModelSamplingDiscrete"
    assert by_name(service, graph, "identity_adapter")["inputs"]["weight_faceidv2"] == 1.35
    assert by_name(service, graph, "reference_image")["inputs"]["image"] == "refs/actor.png"


def test_regional_cast_uses_independent_images_and_disjoint_pixel_masks(service):
    service.workflow_manager.load_workflow(workflow_path=str(ROOT / "configs/comfyui_workflow_sdxl_regional_two_character.json"))
    uploads = []
    masks = []

    def upload(path):
        uploads.append(path)
        if Path(path).name == "region.png":
            with Image.open(path) as image:
                masks.append(image.copy())
        return f"uploaded/{len(uploads)}.png"

    service._upload_reference_image = upload
    graph = build(service, character_references=[{"name": "Alice", "path": "alice.png"}, {"name": "Bob", "path": "bob.png"}])
    assert uploads[0] == "alice.png" and uploads[2] == "bob.png"
    assert by_name(service, graph, "left_reference")["inputs"]["image"] != by_name(service, graph, "right_reference")["inputs"]["image"]
    assert masks[0].size == masks[1].size == (768, 1344)
    assert masks[0].getpixel((100, 600)) == (255, 255, 255)
    assert masks[0].getpixel((600, 600)) == (0, 0, 0)
    assert masks[1].getpixel((100, 600)) == (0, 0, 0)
    assert masks[1].getpixel((600, 600)) == (255, 255, 255)
    assert by_name(service, graph, "detail_sampler")["inputs"]["model"] == by_name(service, graph, "composition_sampler")["inputs"]["model"]


@pytest.mark.parametrize("region", [[0, 0, 0, 1], [0.8, 0, 0.2, 1], [0, 0, float("nan"), 1], [0, 0, 2, 1]])
def test_invalid_region_does_not_upload_a_mask(service, region):
    service._upload_reference_image = Mock()
    with pytest.raises(ComfyUIError, match="bounds"):
        service._upload_region_mask(768, 1344, region)
    service._upload_reference_image.assert_not_called()


def test_regional_workflow_requires_one_slot_per_reference(service):
    service.workflow_manager.load_workflow(workflow_path=str(ROOT / "configs/comfyui_workflow_sdxl_regional_two_character.json"))
    with pytest.raises(ComfyUIError, match="count"):
        build(service, character_references=[{"path": f"{i}.png"} for i in range(3)])


def test_detail_stage_cannot_bypass_the_single_character_identity_adapter(service):
    service.workflow_manager.load_workflow(workflow_path=str(ROOT / "configs/comfyui_workflow_sdxl_multistage_reference.json"))
    config = service.workflow_manager.get_current_workflow()
    config.nodes["detail_sampler"].inputs["model"] = ["checkpoint_loader", 0]
    service._upload_reference_image = Mock()
    with pytest.raises(ComfyUIError, match="retain all character identity adapters"):
        build(service, reference_image="actor.png", use_ipadapter=True)
    service._upload_reference_image.assert_not_called()


def test_invalid_second_regional_mask_is_rejected_before_uploading_anything(service):
    service.workflow_manager.load_workflow(workflow_path=str(ROOT / "configs/comfyui_workflow_sdxl_regional_two_character.json"))
    config = service.workflow_manager.get_current_workflow()
    config.parameters.default["reference_slots"][1]["region"] = [0, 0, 0.6, 1]
    service._upload_reference_image = Mock()
    with pytest.raises(ComfyUIError, match="overlap"):
        build(service, character_references=[{"path": "a.png"}, {"path": "b.png"}])
    service._upload_reference_image.assert_not_called()


def test_video_output_wins_over_preview_image_from_an_earlier_node(service):
    service._download_media = Mock(return_value="final.mp4")
    result = {"outputs": {
        "preview": {"images": [{"filename": "preview.png"}]},
        "video": {"videos": [{"filename": "final.mp4"}]},
    }}
    assert service._get_generated_media(result, "out.mp4") == "final.mp4"
    assert service._download_media.call_args.kwargs["filename"] == "final.mp4"


def test_video_generation_rejects_a_still_image_only_result(service):
    with pytest.raises(ComfyUIError, match="输出"):
        service._get_generated_media({"outputs": {"1": {"images": [{"filename": "frame.png"}]}}}, "out.mp4")


def test_invalid_explicit_workflow_never_silently_loads_default(tmp_path):
    path = tmp_path / "invalid.json"
    path.write_text("{invalid", encoding="utf-8")
    with pytest.raises(WorkflowManagerError, match="格式"):
        WorkflowManager().load_workflow(workflow_path=str(path), allow_fallback=False)
