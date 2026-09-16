import json
from pathlib import Path
from unittest.mock import Mock

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.database.models import Base, Character, Project, Scene, Task, TaskStatus, User
from src.services.generation_review import fingerprint, write_report, ReviewError
from src.services.generation_provider import GenerationProviderName, GenerationResult
from src.services.shot_prompt_service import ShotPromptService
from src.tasks.image_tasks import _append_terms, _complexity_report, _composition_constraint, _generate_quality_candidates, _project_complexity_report, _review_feedback, _visible_character_payload, _visual_character, _visual_characters, _prepare_prompt
from src.tasks.review_tasks import current_story, generation_signature, require_generation_review
from src.tasks.video_tasks import _ComfyVideoGenerator, _generate_quality_video_candidates


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


def test_multiple_visible_characters_are_preserved_in_prompt(project_data):
    db, project, scene, character, _ = project_data
    bob = Character(project_id=project.id, name="Bob", appearance="man, square jaw, navy coat")
    db.add(bob)
    project.script = json.dumps({"scenes": [{"scene_number": 1, "characters": ["Alice", "Bob"]}]})
    db.commit()
    llm = Mock()
    llm.generate.return_value = json.dumps({"subject": "the two characters", "action": "facing each other",
        "setting": "office doorway", "framing": "medium two shot", "lighting": "window light", "style": "cinematic",
        "needs_split": False, "reason": ""})
    compiler = ShotPromptService(llm)

    compiled, reference_character = _prepare_prompt(scene, project.id, "Alice and Bob face each other", db, compiler)

    assert [c.name for c in _visual_characters(scene, project.id, db)] == ["Alice", "Bob"]
    assert reference_character is None
    assert "Alice identity: woman, short black hair, green jacket" in compiled.prompt
    assert "Bob identity: man, square jaw, navy coat" in compiled.prompt
    assert "Keep every visible character distinct" in compiled.prompt
    assert "Alice on frame left and Bob on frame right" in compiled.prompt


def test_visible_character_payload_carries_identity_anchors(project_data):
    db, project, scene, _, _ = project_data
    db.add(Character(project_id=project.id, name="Bob", appearance="man, square jaw, navy coat"))
    project.script = json.dumps({"scenes": [{"scene_number": 1, "characters": ["Alice", "Bob"]}]})
    db.commit()

    payload = _visible_character_payload(scene, project.id, db)

    assert payload == [
        {"name": "Alice", "appearance": "woman, short black hair, green jacket"},
        {"name": "Bob", "appearance": "man, square jaw, navy coat"},
    ]


def test_composition_constraint_tracks_visible_actor_count(project_data):
    db, project, scene, _, _ = project_data
    assert "Alice is the only visible person" in _composition_constraint(scene, project.id, db)
    project.script = json.dumps({"scenes": [{"scene_number": 1, "characters": ["Alice", "Bob", "Cara"]}]})
    db.commit()
    hint = _composition_constraint(scene, project.id, db)
    assert "group layout" in hint
    assert "Alice at frame left" in hint
    assert "Bob at center" in hint
    assert "Cara at frame right" in hint


def test_complexity_constraint_is_added_to_prompt(project_data):
    db, project, scene, _, _ = project_data
    llm = Mock()
    llm.generate.return_value = json.dumps({"subject": "the character", "action": "holding a red letter",
        "setting": "office doorway", "framing": "medium shot", "lighting": "window light", "style": "cinematic",
        "needs_split": False, "reason": ""})
    compiled, _ = _prepare_prompt(scene, project.id, scene.visual_description, db, ShotPromptService(llm))

    assert "one frozen instant" in compiled.prompt
    assert _complexity_report(scene, project.id, db)["status"] == "ok"


def test_complex_shot_can_be_blocked_before_generation(project_data, monkeypatch):
    db, project, scene, _, _ = project_data
    project.script = json.dumps({"scenes": [{"scene_number": 1, "characters": ["Alice", "Bob", "Cara"]}]})
    db.add(Character(project_id=project.id, name="Bob", appearance="man, navy coat"))
    db.add(Character(project_id=project.id, name="Cara", appearance="woman, red dress"))
    scene.visual_description = "Alice enters and then sits while Bob and Cara fight as the camera pans around them"
    db.commit()
    monkeypatch.setattr("src.tasks.image_tasks.settings.GENERATION_BLOCK_COMPLEX_SHOTS", True)

    with pytest.raises(ValueError, match="too complex"):
        _prepare_prompt(scene, project.id, scene.visual_description, db, ShotPromptService(Mock()))


def test_project_complexity_report_marks_split_scenes(project_data):
    db, project, scene, _, _ = project_data
    project.script = json.dumps({"scenes": [{"scene_number": 1, "characters": ["Alice", "Bob", "Cara"]}]})
    scene.visual_description = "Alice enters and then sits while Bob and Cara fight as the camera pans around them"
    db.commit()

    report = _project_complexity_report([scene], project.id, db)

    assert report["status"] == "needs_split"
    assert report["summary"]["needs_split"] == 1
    assert report["scenes"][0]["scene_number"] == 1


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


def test_prepare_generation_writes_project_complexity_report(project_data, monkeypatch):
    db, project, scene, _, Session = project_data
    import src.tasks.image_tasks as tasks
    from src.utils.storage import storage_manager
    write_report(
        storage_manager.get_project_path(project.id) / "reviews" / "production_story.json",
        {"status": "passed", "input_hash": fingerprint(current_story(project, [scene]))},
    )
    monkeypatch.setattr(tasks, "get_db", lambda: iter([Session()]))
    monkeypatch.setattr(tasks.prepare_generation_task, "update_state", Mock())

    result = tasks.prepare_generation_task.run(project.id, 1, compile_images=False)

    report = json.loads((storage_manager.get_project_path(project.id) / "reviews" / "shot_complexity.json").read_text())
    assert result["complexity"]["status"] == "passed"
    assert report["scenes"][0]["scene_number"] == scene.scene_number
    db.expire_all()


def test_prepare_generation_blocks_complex_project_when_required(project_data, monkeypatch):
    db, project, scene, _, Session = project_data
    import src.tasks.image_tasks as tasks
    from src.utils.storage import storage_manager
    project.script = json.dumps({"scenes": [{"scene_number": 1, "characters": ["Alice", "Bob", "Cara"]}]})
    scene.visual_description = "Alice enters and then sits while Bob and Cara fight as the camera pans around them"
    db.commit()
    write_report(
        storage_manager.get_project_path(project.id) / "reviews" / "production_story.json",
        {"status": "passed", "input_hash": fingerprint(current_story(project, [scene]))},
    )
    monkeypatch.setattr(tasks, "get_db", lambda: iter([Session()]))
    monkeypatch.setattr(tasks.prepare_generation_task, "update_state", Mock())
    monkeypatch.setattr("src.tasks.image_tasks.settings.GENERATION_BLOCK_COMPLEX_SHOTS", True)

    with pytest.raises(ValueError, match="need splitting"):
        tasks.prepare_generation_task.run(project.id, 1, compile_images=False)


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


def test_video_generation_selects_best_reviewed_candidate(project_data, tmp_path, monkeypatch):
    db, project, scene, _, _ = project_data
    scene.image_path = str(tmp_path / "source.png")
    Path(scene.image_path).write_bytes(b"image")
    db.commit()

    class FakeSVD:
        def __init__(self):
            self.requests = []

        def generate_video(self, **kwargs):
            self.requests.append(kwargs)
            Path(kwargs["output_path"]).write_bytes(f"video-{len(self.requests)}".encode())
            return kwargs["output_path"]

    class FakeReviewService:
        def review_video(self, _video, payload, _report_path, _reference=None):
            if payload["candidate_index"] == 1:
                return {"status": "needs_review", "average": 2.8}
            return {"status": "passed", "average": 4.7}

    fake_svd = FakeSVD()
    monkeypatch.setattr("src.tasks.video_tasks.GenerationReviewService", FakeReviewService)
    monkeypatch.setattr("src.tasks.video_tasks.settings.GENERATION_VIDEO_CANDIDATES", 2)
    monkeypatch.setattr("src.tasks.video_tasks.settings.GENERATION_VIDEO_MIN_SCORE", 4.0)
    monkeypatch.setattr("src.tasks.video_tasks.settings.GENERATION_REQUIRE_VIDEO_REVIEW", True)

    final_path, report = _generate_quality_video_candidates(
        fake_svd, scene, project.id, str(tmp_path / "scene.mp4"), db,
        num_frames=16, fps=8, motion_bucket_id=127, noise_aug_strength=0.02,
    )

    assert Path(final_path).read_bytes() == b"video-2"
    assert report["status"] == "passed"
    assert report["selected_average"] == 4.7
    assert [candidate["index"] for candidate in report["candidates"]] == [2, 1]
    assert fake_svd.requests[0]["motion_bucket_id"] != fake_svd.requests[1]["motion_bucket_id"]


def test_required_video_review_blocks_low_scoring_candidates(project_data, tmp_path, monkeypatch):
    db, project, scene, _, _ = project_data
    scene.image_path = str(tmp_path / "source.png")
    Path(scene.image_path).write_bytes(b"image")
    db.commit()

    class FakeSVD:
        def generate_video(self, **kwargs):
            Path(kwargs["output_path"]).write_bytes(b"bad-video")
            return kwargs["output_path"]

    class FakeReviewService:
        def review_video(self, *_args, **_kwargs):
            return {"status": "needs_review", "average": 2.0}

    output = tmp_path / "scene.mp4"
    monkeypatch.setattr("src.tasks.video_tasks.GenerationReviewService", FakeReviewService)
    monkeypatch.setattr("src.tasks.video_tasks.settings.GENERATION_VIDEO_CANDIDATES", 1)
    monkeypatch.setattr("src.tasks.video_tasks.settings.GENERATION_VIDEO_MIN_SCORE", 4.0)
    monkeypatch.setattr("src.tasks.video_tasks.settings.GENERATION_REQUIRE_VIDEO_REVIEW", True)

    with pytest.raises(ReviewError, match="Video candidates failed quality gate"):
        _generate_quality_video_candidates(
            FakeSVD(), scene, project.id, str(output), db,
            num_frames=16, fps=8, motion_bucket_id=127, noise_aug_strength=0.02,
        )

    assert not output.exists()
    assert output.with_suffix(".quality.json").is_file()


def test_video_refinement_pass_reduces_motion_after_low_score(project_data, tmp_path, monkeypatch):
    db, project, scene, _, _ = project_data
    scene.image_path = str(tmp_path / "source.png")
    Path(scene.image_path).write_bytes(b"image")
    db.commit()

    class FakeSVD:
        def __init__(self):
            self.requests = []

        def generate_video(self, **kwargs):
            self.requests.append(kwargs)
            Path(kwargs["output_path"]).write_bytes(f"video-{len(self.requests)}".encode())
            return kwargs["output_path"]

    class FakeReviewService:
        def review_video(self, _video, payload, _report_path, _reference=None):
            if payload["refinement_pass"] == 0:
                return {"status": "needs_review", "average": 2.5}
            return {"status": "passed", "average": 4.5}

    fake_svd = FakeSVD()
    monkeypatch.setattr("src.tasks.video_tasks.GenerationReviewService", FakeReviewService)
    monkeypatch.setattr("src.tasks.video_tasks.settings.GENERATION_VIDEO_CANDIDATES", 1)
    monkeypatch.setattr("src.tasks.video_tasks.settings.GENERATION_VIDEO_REFINEMENT_PASSES", 1)
    monkeypatch.setattr("src.tasks.video_tasks.settings.GENERATION_VIDEO_MIN_SCORE", 4.0)
    monkeypatch.setattr("src.tasks.video_tasks.settings.GENERATION_REQUIRE_VIDEO_REVIEW", True)

    final_path, report = _generate_quality_video_candidates(
        fake_svd, scene, project.id, str(tmp_path / "scene.mp4"), db,
        num_frames=16, fps=8, motion_bucket_id=150, noise_aug_strength=0.05,
    )

    assert Path(final_path).read_bytes() == b"video-2"
    assert len(fake_svd.requests) == 2
    assert fake_svd.requests[1]["motion_bucket_id"] < fake_svd.requests[0]["motion_bucket_id"]
    assert fake_svd.requests[1]["noise_aug_strength"] < fake_svd.requests[0]["noise_aug_strength"]
    assert report["candidates"][0]["pass"] == 1
    assert report["status"] == "passed"


def test_comfy_video_generator_uses_scene_prompt_and_reference(project_data, tmp_path):
    _, _, scene, _, _ = project_data
    scene.image_prompt = "cinematic woman holding a red letter"

    class FakeProvider:
        def __init__(self):
            self.request = None

        def generate_video(self, request):
            self.request = request
            Path(request.output_path).write_bytes(b"comfy-video")
            return GenerationResult("local_comfyui", request.output_path, "video", {})

    provider = FakeProvider()
    output = tmp_path / "scene.mp4"
    result = _ComfyVideoGenerator(scene, provider).generate_video(
        image_path=str(tmp_path / "source.png"),
        output_path=str(output),
        num_frames=16,
        fps=8,
        motion_bucket_id=120,
        noise_aug_strength=0.02,
    )

    assert result == str(output)
    assert provider.request.prompt == "cinematic woman holding a red letter"
    assert provider.request.reference_image.endswith("source.png")
    assert provider.request.duration_seconds == 2.0
    assert provider.request.fps == 8
    assert provider.request.motion_bucket_id == 120
    assert provider.request.noise_aug_strength == 0.02


def test_quality_refinement_uses_previous_review_feedback(tmp_path, monkeypatch):
    from PIL import Image
    from src.services.generation_provider import ImageGenerationRequest, GenerationResult

    class FakeProvider:
        name = GenerationProviderName.LOCAL_COMFYUI

        def __init__(self):
            self.requests = []

        def generate_image(self, request):
            self.requests.append(request)
            shade = 110 + len(self.requests) * 10
            Image.new("RGB", (request.width, request.height), (shade, shade, shade)).save(request.output_path)
            return GenerationResult("local_comfyui", request.output_path, "image", {})

    review_calls = []

    def fake_review(self, index, image_path, scene, prompt, reference_image=None):
        review_calls.append((index, prompt))
        score = 2.0 if index == 1 else 4.6
        return {
            "index": index,
            "path": image_path,
            "status": "needs_review" if index == 1 else "passed",
            "average": score,
            "review": {
                "composition": {"score": 2, "evidence": "face is cropped and lighting is muddy"},
                "issues": [{"severity": "major", "reason": "bad crop on the main actor", "scene_number": 1}],
            },
            "metrics": {"technical_score": score},
        }

    monkeypatch.setattr("src.tasks.image_tasks.ImageQualitySelector.review_candidate", fake_review)
    monkeypatch.setattr("src.tasks.image_tasks.settings.GENERATION_IMAGE_CANDIDATES", 1)
    monkeypatch.setattr("src.tasks.image_tasks.settings.GENERATION_IMAGE_REFINEMENT_PASSES", 1)
    monkeypatch.setattr("src.tasks.image_tasks.settings.GENERATION_IMAGE_MIN_SCORE", 4.0)
    monkeypatch.setattr("src.tasks.image_tasks.settings.GENERATION_REQUIRE_IMAGE_REVIEW", False)
    monkeypatch.setattr("src.tasks.image_tasks.settings.GENERATION_QUALITY_PROMPT_APPEND", "balanced lighting")
    monkeypatch.setattr("src.tasks.image_tasks.settings.GENERATION_QUALITY_NEGATIVE_APPEND", "bad crop")
    request = ImageGenerationRequest(
        prompt="short drama still",
        negative_prompt="blurry",
        output_path=str(tmp_path / "scene.png"),
        width=512,
        height=512,
        steps=28,
        cfg_scale=6.0,
        seed=123,
    )

    _generate_quality_candidates(FakeProvider(), request, {"scene_number": 1}, None)

    assert "balanced lighting" in review_calls[0][1]
    assert "bad crop on the main actor" in review_calls[1][1]
    assert "face is cropped" in review_calls[1][1]


def test_review_feedback_deduplicates_low_score_evidence():
    feedback = _review_feedback([
        {"average": 2, "review": {
            "issues": [{"reason": "bad crop", "scene_number": 1, "severity": "major"}],
            "composition": {"score": 2, "evidence": "bad crop"},
            "visual_integrity": {"score": 1, "evidence": "broken fingers"},
        }}
    ])

    assert "bad crop" in feedback
    assert "broken fingers" in feedback


def test_append_terms_does_not_duplicate_terms():
    assert _append_terms("blurry, bad crop", "bad crop, watermark") == "blurry, bad crop, watermark"
