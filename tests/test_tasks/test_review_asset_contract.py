from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from src.database.models import Project
from src.tasks import review_tasks


@pytest.fixture
def assets(tmp_path):
    paths = {}
    for kind in ("image", "video", "audio", "subtitle"):
        path = tmp_path / kind
        path.write_bytes(kind.encode())
        paths[kind] = str(path)
    project = SimpleNamespace(id=1, script=None, outline="A confrontation", theme="drama", characters=[])
    scene = SimpleNamespace(
        id=2, scene_number=1, visual_description="Two actors confront each other", dialogue="Wait.",
        character_name="Alice", image_prompt="two actors at the doorway", audio_duration=2.0,
        **{f"{kind}_path": path for kind, path in paths.items()},
    )
    return project, scene


@pytest.mark.parametrize("kind", ["audio", "subtitle", "image", "video"])
def test_modified_media_invalidates_the_previous_review(assets, kind):
    project, scene = assets
    previous = review_tasks.generation_signature(project, [scene])
    Path(getattr(scene, f"{kind}_path")).write_bytes(b"changed media")
    assert review_tasks.generation_signature(project, [scene]) != previous


def test_retimed_audio_invalidates_the_previous_review(assets):
    project, scene = assets
    previous = review_tasks.generation_signature(project, [scene])
    scene.audio_duration = 2.4
    assert review_tasks.generation_signature(project, [scene]) != previous


def test_provider_contract_changes_invalidate_the_previous_review(assets):
    project, scene = assets
    provider_metadata = Path(scene.video_path).with_suffix(".provider.json")
    provider_metadata.write_text(
        '{"provider_name":"seedance_api","provider_model":"doubao-seedance-2-5-260628",'
        '"request_contract_hash":"contract-v1","request_contract":{"model":"doubao-seedance-2-5-260628",'
        '"resolution":"1080p","generate_audio":true}}',
        encoding="utf-8",
    )
    previous = review_tasks.generation_signature(project, [scene])
    provider_metadata.write_text(
        '{"provider_name":"seedance_api","provider_model":"doubao-seedance-2-0-260128",'
        '"request_contract_hash":"contract-v2","request_contract":{"model":"doubao-seedance-2-0-260128",'
        '"resolution":"720p","generate_audio":false}}',
        encoding="utf-8",
    )

    assert review_tasks.generation_signature(project, [scene]) != previous


def test_character_asset_changes_invalidate_the_previous_review(assets, monkeypatch, tmp_path):
    project, scene = assets
    reference = tmp_path / "alice.png"
    reference.write_bytes(b"identity-v1")
    project.characters = [SimpleNamespace(id=7, name="Alice", description="black hair", appearance="black hair")]

    class FakeCharacterManager:
        def get_character_asset_pack(self, character_id, project_id):
            return {
                "status": "frozen",
                "identity_spec_hash": "identity-spec-v1",
                "reference_paths": [str(reference)],
                "reference_hashes": {str(reference): review_tasks.file_hash(reference)},
            }

        def get_character_references(self, character_id, project_id):
            return [str(reference)]

    monkeypatch.setattr(
        "src.services.character_service.get_character_manager",
        lambda: FakeCharacterManager(),
    )
    previous = review_tasks.generation_signature(project, [scene])
    reference.write_bytes(b"identity-v2")

    assert review_tasks.generation_signature(project, [scene]) != previous


def test_draft_smoke_review_is_not_production_evidence(assets):
    project, scene = assets
    evidence = review_tasks.validate_generation_review_evidence(
        {"mode": "single_shot_smoke_test", "status": "passed"},
        [scene],
    )

    assert evidence["passed"] is False
    assert "not production review evidence" in evidence["reason"]


def test_project_reviewer_receives_the_complete_scene_cast(assets, monkeypatch, tmp_path):
    project, scene = assets
    db = Mock()
    db.query.side_effect = lambda model: (
        Mock(filter=Mock(return_value=Mock(first=Mock(return_value=project))))
        if model is Project else Mock(filter=Mock(return_value=Mock(
            order_by=Mock(return_value=Mock(all=Mock(return_value=[scene]))),
        )))
    )

    def get_db():
        yield db

    reviewer = Mock(review_video=Mock(return_value={"status": "passed", "average": 5.0}))
    payload = {
        "visible_characters": [{"name": "Alice"}, {"name": "Bob"}],
        "character_sheet_references": [{"name": "Alice", "path": "alice.png"}, {"name": "Bob", "path": "bob.png"}],
        "identity_contrast_matrix": {"pairs": [{"names": ["Alice", "Bob"]}]},
    }
    monkeypatch.setenv("ENABLE_DRAFT_MEDIA_FALLBACK", "false")
    monkeypatch.setattr(review_tasks, "get_db", get_db)
    monkeypatch.setattr(review_tasks, "require_story_review", lambda *_args: None)
    monkeypatch.setattr(review_tasks, "GenerationReviewService", lambda: reviewer)
    monkeypatch.setattr(review_tasks.storage_manager, "get_project_path", lambda _id: tmp_path)
    monkeypatch.setattr("src.tasks.image_tasks._visual_character", lambda *_args: None)
    builder = Mock(return_value=payload)
    monkeypatch.setattr("src.tasks.video_tasks._scene_review_payload", builder)
    result = review_tasks.review_generation_task.run(project.id, 3)
    assert result["status"] == "passed"
    builder.assert_called_once_with(scene, project.id, db)
    received = reviewer.review_video.call_args.args[1]
    assert [item["name"] for item in received["visible_characters"]] == ["Alice", "Bob"]
    assert received["character_sheet_references"] == payload["character_sheet_references"]
    assert received["identity_contrast_matrix"] == payload["identity_contrast_matrix"]
    db.close.assert_called_once()
