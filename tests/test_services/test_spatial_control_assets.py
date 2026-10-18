import json

from PIL import Image

from src.database.models import Character, Project, Scene
from src.services.character_identity_service import CharacterIdentityService
from src.services.character_turnaround_album import CharacterTurnaroundAlbumService, PRODUCTION_TURNAROUND_VIEWS
from src.services.spatial_control_assets import SpatialControlAssetService
from src.utils.storage import storage_manager


def _image(path, color):
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (32, 32), color).save(path)
    return str(path)


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
    assert pack["version"] == 2
    assert pack["planner_contract_version"] == SpatialControlAssetService.PLANNER_CONTRACT_VERSION
    assert pack["required_control_types"] == ["pose", "depth", "camera", "character_turnaround"]
    controls = pack["scenes"][0]["control_references"]
    assert "pose_reference_prompt" in controls
    assert "depth_reference_prompt" in controls
    assert "camera_reference_prompt" in controls
    assert service.validate_project_pack(project, scenes, characters)["status"] == "valid"

    contract = service.get_scene_contract(1, 1)
    assert contract["project_signature"] == pack["project_signature"]
    assert contract["scene_contract_hash"]
    assert contract["spatial_plan"] == pack["scenes"][0]["spatial_plan"]
    assert service.get_scene_contract(1, 99) is None

    pack_path = service._pack_path(1)
    tampered = json.loads(pack_path.read_text(encoding="utf-8"))
    tampered["required_control_types"] = ["pose"]
    tampered["scenes"][0]["control_references"].pop("depth_reference_prompt")
    pack_path.write_text(json.dumps(tampered), encoding="utf-8")
    invalid = service.validate_project_pack(project, scenes, characters)
    assert invalid["status"] == "stale"
    assert "required_control_types" in invalid["stale"]
    assert "scene_contracts" in invalid["stale"]

    service.PLANNER_CONTRACT_VERSION = "spatial-director-v3"
    assert service.validate_project_pack(project, scenes, characters)["status"] == "stale"

    scenes[0].visual_description = "Alice runs from the office table to the door."
    stale = service.validate_project_pack(project, scenes, characters)
    assert stale["status"] == "stale"
    assert "scene_contracts" in stale["stale"]
    assert stale["scene_stale"][0]["scene_number"] == 1


def test_spatial_control_pack_embeds_turnaround_album_controls(tmp_path, monkeypatch):
    monkeypatch.setattr(storage_manager, "base_path", tmp_path / "storage")
    spec = CharacterIdentityService().build_identity_spec("Alice", "lead", project_id=1)
    project = Project(id=1, name="Drama", user_id=1, script=json.dumps({
        "scenes": [{"scene_number": 1, "characters": ["Alice"]}]
    }))
    scenes = [
        Scene(
            project_id=1,
            scene_number=1,
            visual_description="Alice turns from the mirror and checks the letter.",
            dialogue="This changes everything.",
        )
    ]
    character = Character(
        id=7,
        project_id=1,
        name="Alice",
        appearance=spec["identity_anchor"],
        visual_description=json.dumps(spec),
    )
    views = {
        view: _image(tmp_path / f"{view}.png", color)
        for view, color in zip(
            PRODUCTION_TURNAROUND_VIEWS,
            ("red", "orange", "yellow", "green", "blue", "purple", "white", "black"),
        )
    }
    CharacterTurnaroundAlbumService().freeze_album(character, views)

    service = SpatialControlAssetService()
    pack = service.freeze_project_pack(project, scenes, [character], notes="approved production character-sheet controls")

    character_controls = pack["scenes"][0]["character_turnaround_controls"]["Alice"]
    assert character_controls["status"] == "valid"
    assert set(character_controls["views"]) == set(PRODUCTION_TURNAROUND_VIEWS)
    assert "expression_intense" in character_controls["views"]
    assert character_controls["views"]["side"]["path"] == views["side"]
    assert "strict side profile" in character_controls["views"]["side"]["control_prompt"]
    assert service.validate_project_pack(project, scenes, [character])["status"] == "valid"

    Image.new("RGB", (32, 32), "black").save(views["front"])
    stale = service.validate_project_pack(project, scenes, [character])

    assert stale["status"] == "stale"
    assert "scene_contracts" in stale["stale"]
    assert "turnaround_controls_hash" in stale["scene_stale"][0]["changed"]
