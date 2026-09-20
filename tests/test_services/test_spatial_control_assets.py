import json

from src.database.models import Character, Project, Scene
from src.services.character_identity_service import CharacterIdentityService
from src.services.spatial_control_assets import SpatialControlAssetService
from src.utils.storage import storage_manager


def test_spatial_control_pack_freezes_pose_depth_camera_contracts(tmp_path, monkeypatch):
    monkeypatch.setattr(storage_manager, "base_path", tmp_path / "storage")
    spec = CharacterIdentityService().build_identity_spec("Alice", "lead", project_id=1)
    project = Project(id=1, name="Drama", user_id=1, script=json.dumps({
        "scenes": [{"scene_number": 1, "characters": ["Alice"]}]
    }))
    scenes = [Scene(project_id=1, scene_number=1, visual_description="Alice holds a letter at the office table.", dialogue="Look at this.")]
    characters = [Character(project_id=1, name="Alice", appearance=spec["identity_anchor"], visual_description=json.dumps(spec))]
    service = SpatialControlAssetService()

    pack = service.freeze_project_pack(project, scenes, characters, notes="approved blocking")

    assert pack["status"] == "frozen"
    assert pack["required_control_types"] == ["pose", "depth", "camera"]
    controls = pack["scenes"][0]["control_references"]
    assert "pose_reference_prompt" in controls
    assert "depth_reference_prompt" in controls
    assert "camera_reference_prompt" in controls
    assert service.validate_project_pack(project, scenes, characters)["status"] == "valid"

    scenes[0].visual_description = "Alice runs from the office table to the door."
    stale = service.validate_project_pack(project, scenes, characters)
    assert stale["status"] == "stale"
    assert "scene_contracts" in stale["stale"]
    assert stale["scene_stale"][0]["scene_number"] == 1
