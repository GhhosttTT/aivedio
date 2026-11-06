import json

from src.database.models import Project, Scene
from src.services.continuity_asset_pack import ContinuityAssetPackService
from src.utils.storage import storage_manager


def _project():
    return Project(id=12, name="Drama", user_id=3, script=json.dumps({"scenes": [
        {
            "scene_number": 1,
            "shot_spec": {
                "continuity_assets": [{
                    "asset_id": "prop:letter", "kind": "prop",
                    "start_state": {"holder": "Alice", "hand": "right"},
                    "end_state": {"holder": "Alice", "hand": "right"},
                }],
            },
        },
        {
            "scene_number": 2,
            "shot_spec": {
                "continuity_assets": [{
                    "asset_id": "prop:letter", "kind": "prop",
                    "start_state": {"holder": "Alice", "hand": "right"},
                    "end_state": {"holder": "Bob", "hand": "left"},
                    "transition_note": "Alice hands the letter to Bob",
                }],
            },
        },
    ]}))


def _scenes(project):
    return [
        Scene(project=project, project_id=12, scene_number=1, visual_description="Alice holds a letter"),
        Scene(project=project, project_id=12, scene_number=2, visual_description="Alice hands the letter to Bob"),
    ]


def test_freezes_validates_and_exposes_scene_contract(tmp_path, monkeypatch):
    monkeypatch.setattr(storage_manager, "base_path", tmp_path / "storage")
    project = _project()
    scenes = _scenes(project)
    service = ContinuityAssetPackService()

    frozen = service.freeze_project_pack(project, scenes, notes="approved prop handoff")
    validation = service.validate_project_pack(project, scenes)
    contract = service.get_scene_contract(project.id, 2)

    assert frozen["status"] == "frozen"
    assert frozen["asset_ids"] == ["prop:letter"]
    assert validation["status"] == "valid"
    assert contract["assets"][0]["end_state"]["holder"] == "Bob"
    assert "prop:letter: holder=Alice, hand=right" in service.prompt_directive(contract, phase="opening")
    assert "prop:letter: holder=Bob, hand=left" in service.prompt_directive(contract, phase="ending")


def test_detects_script_asset_state_drift_after_freeze(tmp_path, monkeypatch):
    monkeypatch.setattr(storage_manager, "base_path", tmp_path / "storage")
    project = _project()
    scenes = _scenes(project)
    service = ContinuityAssetPackService()
    service.freeze_project_pack(project, scenes)

    payload = json.loads(project.script)
    payload["scenes"][1]["shot_spec"]["continuity_assets"][0]["end_state"]["hand"] = "right"
    project.script = json.dumps(payload)

    validation = service.validate_project_pack(project, scenes)

    assert validation["status"] == "stale"
    assert validation["scene_stale"] == [{"scene_number": 2, "changed": ["source_hash", "continuity_asset_hash"]}]
