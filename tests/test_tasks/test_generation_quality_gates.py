import json
from pathlib import Path
from unittest.mock import Mock

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.database.models import Base, Character, Project, Scene, Task, TaskStatus, User
from src.services.generation_review import fingerprint, write_report, ReviewError
from src.services.generation_provider import GenerationProviderName
from src.services.shot_prompt_service import ShotPromptService
from src.tasks.image_tasks import _generate_quality_candidates, _visual_character, _prepare_prompt
from src.tasks.review_tasks import current_story, generation_signature, require_generation_review


@pytest.fixture
def project_data(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    db = Session()
    user = User(username="quality", email="quality@example.com", hashed_password="x")
    db.add(user)
    db.flush()
    project = Project(name="Quality test", user_id=user.id, script=json.dumps({
        "script": "Alice listens to Bob", "scenes": [{"scene_number": 1, "characters": ["Alice"]}]}))
    db.add(project)
    db.flush()
    character = Character(project_id=project.id, name="Alice", appearance="woman, short black hair, green jacket")
    db.add(character)
    scene = Scene(project_id=project.id, scene_number=1, character_name="Bob", dialogue="Listen carefully",
                  visual_description="Alice holds a red letter in the office doorway")
    db.add(scene)
    db.commit()
    yield db, project, scene, character, Session
    db.close()
    engine.dispose()


def test_visible_actor_is_distinct_from_speaker(project_data):
    db, project, scene, character, _ = project_data
    assert _visual_character(scene, project.id, db).id == character.id
    project.script = json.dumps({"scenes": [{"scene_number": 1, "characters": []}]})
    db.commit()
    assert _visual_character(scene, project.id, db) is None


def test_prompt_is_cached_but_identity_edit_invalidates_it(project_data):
    db, project, scene, character, _ = project_data
    llm = Mock()
    llm.generate.return_value = json.dumps({"subject": "the character", "action": "holding a red letter",
        "setting": "office doorway", "framing": "medium shot", "lighting": "window light", "style": "anime",
        "needs_split": False, "reason": ""})
    compiler = ShotPromptService(llm)
    first, _ = _prepare_prompt(scene, project.id, scene.visual_description, db, compiler)
    second, _ = _prepare_prompt(scene, project.id, scene.visual_description, db, compiler)
    assert first == second
    assert llm.generate.call_count == 1
    character.appearance = "woman, short black hair, blue jacket"
    db.commit()
    third, _ = _prepare_prompt(scene, project.id, scene.visual_description, db, compiler)
    assert third.source_hash != first.source_hash
    assert third.prompt.startswith(character.appearance)
    assert llm.generate.call_count == 2


def test_review_becomes_invalid_after_media_or_story_changes(project_data):
    _, project, scene, _, _ = project_data
    from src.utils.storage import storage_manager
    path = Path("clip.mp4")
    path.write_bytes(b"first video")
    scene.video_path = str(path)
    root = storage_manager.get_project_path(project.id) / "reviews"
    write_report(root / "production_story.json", {"status": "passed", "input_hash": fingerprint(current_story(project, [scene]))})
    write_report(root / "generation.json", {"status": "passed", "input_hash": generation_signature(project, [scene])})
    assert require_generation_review(project, [scene])["status"] == "passed"
    path.write_bytes(b"changed video")
    with pytest.raises(ReviewError, match="media changed"):
        require_generation_review(project, [scene])
    scene.dialogue = "A different plot"
    with pytest.raises(ReviewError, match="Story changed"):
        require_generation_review(project, [scene])


def test_image_failure_is_not_replaced_by_draft_by_default(project_data, monkeypatch):
    db, project, scene, _, Session = project_data
    import src.tasks.image_tasks as tasks
    from src.services.shot_prompt_service import CompiledShot
    monkeypatch.delenv("ENABLE_DRAFT_MEDIA_FALLBACK", raising=False)
    monkeypatch.setattr(tasks, "get_db", lambda: iter([Session()]))
    monkeypatch.setattr(tasks, "_prepare_prompt", lambda *args: (CompiledShot("woman holding a letter", "blurry", "hash", 4), None))
    monkeypatch.setattr(tasks.generate_image_task, "update_state", Mock())
    provider = Mock()
    provider.generate_image.side_effect = RuntimeError("CUDA out of memory")
    monkeypatch.setattr(tasks, "get_generation_provider", lambda *args: provider)
    draft = Mock()
    monkeypatch.setattr(tasks, "get_draft_media_service", draft)
    with pytest.raises(RuntimeError, match="CUDA"):
        tasks.generate_image_task.run(scene.id, "woman holding a letter", project.id, 1)
    draft.assert_not_called()
    db.refresh(scene)
    assert scene.image_path is None


def test_composition_cannot_bypass_missing_review(project_data):
    _, project, scene, _, _ = project_data
    with pytest.raises(ReviewError, match="Missing production story"):
        require_generation_review(project, [scene])


def test_image_generation_uses_multiple_quality_candidates(tmp_path, monkeypatch):
    from PIL import Image
    from src.services.generation_provider import ImageGenerationRequest, GenerationResult

    class FakeProvider:
        name = GenerationProviderName.LOCAL_COMFYUI

        def __init__(self):
            self.requests = []

        def generate_image(self, request):
            self.requests.append(request)
            shade = 90 + len(self.requests) * 20
            Image.new("RGB", (request.width, request.height), (shade, shade, shade)).save(request.output_path)
            return GenerationResult("local_comfyui", request.output_path, "image", {})

    provider = FakeProvider()
    monkeypatch.setattr("src.tasks.image_tasks.settings.GENERATION_IMAGE_CANDIDATES", 3)
    monkeypatch.setattr("src.tasks.image_tasks.settings.GENERATION_IMAGE_REFINEMENT_PASSES", 0)
    monkeypatch.setattr("src.tasks.image_tasks.settings.GENERATION_IMAGE_MIN_SCORE", 0.0)
    monkeypatch.setattr("src.tasks.image_tasks.settings.GENERATION_REQUIRE_IMAGE_REVIEW", False)
    request = ImageGenerationRequest(
        prompt="cinematic short drama still",
        negative_prompt="blurry",
        output_path=str(tmp_path / "scene.png"),
        width=512,
        height=512,
        steps=28,
        cfg_scale=6.0,
        seed=123,
    )

    final_path, report = _generate_quality_candidates(
        provider,
        request,
        {"scene_number": 1, "visual_description": "A woman opens a letter"},
        reference_image=None,
    )

    assert final_path == request.output_path
    assert Path(final_path).is_file()
    assert len(provider.requests) == 3
    assert len({item.seed for item in provider.requests}) == 3
    assert report["kind"] == "image_candidate_selection"
