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
    from src.config import settings

    root = Path(__file__).resolve().parents[2]
    image_workflow = root / settings.COMFYUI_WORKFLOW_PATH
    reference_workflow = root / settings.COMFYUI_REFERENCE_WORKFLOW_PATH

    assert _checkpoint_names(image_workflow) == _checkpoint_names(reference_workflow)


def test_default_keyframe_workflow_has_face_detail_stage():
    from src.config import settings

    root = Path(__file__).resolve().parents[2]
    path = root / settings.COMFYUI_WORKFLOW_PATH
    payload = json.loads(path.read_text(encoding="utf-8"))
    nodes = payload.get("nodes", payload)

    assert any(node.get("class_type") == "FaceDetailer" for node in nodes.values())


def test_default_keyframe_workflow_runs_multistage_face_and_hand_pipeline():
    from src.config import settings

    root = Path(__file__).resolve().parents[2]
    payload = json.loads((root / settings.COMFYUI_WORKFLOW_PATH).read_text(encoding="utf-8"))
    nodes = payload["nodes"]

    assert sum(node.get("class_type") == "KSampler" for node in nodes.values()) == 2
    assert sum(node.get("class_type") == "FaceDetailer" for node in nodes.values()) == 2
    assert nodes["hand_detailer"]["inputs"]["image"] == ["face_detailer", 0]
    assert nodes["save_final"]["inputs"]["images"] == ["hand_detailer", 0]


def test_reference_production_workflow_keeps_identity_in_every_sampling_stage():
    from src.config import settings

    root = Path(__file__).resolve().parents[2]
    payload = json.loads((root / settings.COMFYUI_REFERENCE_WORKFLOW_PATH).read_text(encoding="utf-8"))
    nodes = payload["nodes"]
    controlled = [
        node for node in nodes.values()
        if node.get("class_type") in {"KSampler", "FaceDetailer"}
    ]

    assert len(controlled) == 4
    assert all(node["inputs"]["model"] == ["identity_adapter", 0] for node in controlled)


def test_default_two_character_workflow_has_two_independent_reference_slots():
    from src.config import settings
    from src.models.workflow_config import WorkflowConfig

    config = WorkflowConfig.from_json_file(settings.COMFYUI_MULTI_REFERENCE_WORKFLOW_PATH)
    slots = config.parameters.default["reference_slots"]

    assert len(slots) == 2
    assert {slot["adapter"] for slot in slots} == {"left_identity", "right_identity"}

    controlled = [
        node for node in config.nodes.values()
        if node.class_type in {"KSampler", "FaceDetailer"}
    ]
    assert len(controlled) == 4
    assert all(node.inputs["model"] == ["right_identity", 0] for node in controlled)
    assert config.nodes["save_final"].inputs["images"] == ["hand_detailer", 0]
