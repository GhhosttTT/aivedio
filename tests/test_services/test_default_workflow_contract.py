import json
from pathlib import Path


def _checkpoint_names(path: Path) -> set[str]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    nodes = payload.get("nodes", payload)
    return {
        str(node.get("inputs", {}).get("ckpt_name"))
        for node in nodes.values()
        if isinstance(node, dict)
        and str(node.get("class_type")) == "CheckpointLoaderSimple"
        and node.get("inputs", {}).get("ckpt_name")
    }


def test_default_keyframe_and_reference_workflows_share_a_checkpoint():
    root = Path(__file__).resolve().parents[2]
    image_workflow = root / "configs" / "comfyui_workflow_juggernaut_facedetailer.json"
    reference_workflow = root / "configs" / "comfyui_workflow_ipadapter_sdxl.json"

    assert _checkpoint_names(image_workflow) == _checkpoint_names(reference_workflow)


def test_default_keyframe_workflow_has_face_detail_stage():
    root = Path(__file__).resolve().parents[2]
    path = root / "configs" / "comfyui_workflow_juggernaut_facedetailer.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    nodes = payload.get("nodes", payload)

    assert any(node.get("class_type") == "FaceDetailer" for node in nodes.values())


def test_default_two_character_workflow_has_two_independent_reference_slots():
    from src.config import settings
    from src.models.workflow_config import WorkflowConfig

    config = WorkflowConfig.from_json_file(settings.COMFYUI_MULTI_REFERENCE_WORKFLOW_PATH)
    slots = config.parameters.default["reference_slots"]

    assert len(slots) == 2
    assert {slot["adapter"] for slot in slots} == {"left_identity", "right_identity"}
