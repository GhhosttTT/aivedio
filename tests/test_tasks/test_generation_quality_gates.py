import json
from pathlib import Path
from unittest.mock import Mock

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.database.models import Base, Character, Project, Scene, Task, TaskStatus, User
from src.services.generation_review import VIDEO_AESTHETIC_FEATURES, VIDEO_PERFORMANCE_FEATURES, fingerprint, write_report, ReviewError
from src.services.generation_provider import GenerationProviderName, GenerationResult
from src.services.shot_prompt_service import ShotPromptService
from src.tasks.image_tasks import _append_terms, _apply_image_repair_action, _character_sheet_generation_contract, _complexity_report, _composition_constraint, _feedback_repair_directive, _generate_quality_candidates, _get_reference_image, _project_complexity_report, _quality_parameters, _repair_action_from_reports, _repair_parameter_profile, _review_feedback, _turnaround_view_for_scene, _visible_character_payload, _visual_character, _visual_characters, _prepare_prompt
from src.tasks.review_tasks import current_story, generation_signature, require_generation_review
from src.services.video_director_service import VideoShotPlan, get_video_director_service
from src.tasks.video_tasks import _ComfyVideoGenerator, _apply_video_repair_action, _apply_video_repair_prompt, _aspect_ratio_for_size, _build_video_generator, _generate_quality_video_candidates, _review_final_video_after_postprocess, _scene_review_payload, _select_best_video_candidate, _video_repair_action_from_candidates


def passed_video_aesthetic_scores(score: int = 5) -> dict:
    return {
        feature: {"score": score, "evidence": "passes short-drama aesthetic gate"}
        for feature in VIDEO_AESTHETIC_FEATURES
    }


def passed_video_performance_scores(score: int = 5) -> dict:
    return {
        feature: {"score": score, "evidence": "acting reads like a short-drama performance"}
        for feature in VIDEO_PERFORMANCE_FEATURES
    }


@pytest.fixture(autouse=True)
def stable_quality_profile(monkeypatch):
    monkeypatch.setattr("src.services.generation_quality_policy.settings.GENERATION_QUALITY_PROFILE", "hongguo_reference")


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
    from src.services.character_identity_service import CharacterIdentityService
    identity_service = CharacterIdentityService()
    alice_spec = identity_service.build_identity_spec("Alice", "lead", project_id=project.id)
    bob_spec = identity_service.build_identity_spec("Bob", "rival", project_id=project.id, existing_specs=[alice_spec])
    character.visual_description = json.dumps(alice_spec)
    bob = Character(
        project_id=project.id,
        name="Bob",
        appearance="man, square jaw, navy coat",
        visual_description=json.dumps(bob_spec),
    )
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
    assert "Identity contrast contract" in compiled.prompt
    assert "Alice must not look like Bob" in compiled.prompt
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


def test_character_sheet_contract_carries_identity_contrast_matrix(project_data):
    from src.services.character_identity_service import CharacterIdentityService

    db, project, scene, character, _ = project_data
    identity_service = CharacterIdentityService()
    alice_spec = identity_service.build_identity_spec("Alice", "lead", project_id=project.id)
    bob_spec = identity_service.build_identity_spec("Bob", "rival", project_id=project.id, existing_specs=[alice_spec])
    character.appearance = alice_spec["identity_anchor"]
    character.visual_description = json.dumps(alice_spec)
    db.add(Character(
        project_id=project.id,
        name="Bob",
        appearance=bob_spec["identity_anchor"],
        visual_description=json.dumps(bob_spec),
    ))
    project.script = json.dumps({"scenes": [{"scene_number": 1, "characters": ["Alice", "Bob"]}]})
    db.commit()

    contract = _character_sheet_generation_contract(_visible_character_payload(scene, project.id, db))

    assert "Identity contrast contract" in contract["prompt"]
    assert contract["identity_contrast_matrix"]["pairs"][0]["contrast_fields"]
    assert "same facial geometry" in contract["negative"]


def test_turnaround_album_drives_scene_reference_view(project_data, tmp_path, monkeypatch):
    from PIL import Image
    from src.services.character_identity_service import CharacterIdentityService
    from src.services.character_turnaround_album import CharacterTurnaroundAlbumService, PRODUCTION_TURNAROUND_VIEWS
    from src.utils.storage import storage_manager

    db, project, scene, character, _ = project_data
    monkeypatch.setattr(storage_manager, "base_path", tmp_path / "storage")
    spec = CharacterIdentityService().build_identity_spec("Alice", "lead", project_id=project.id)
    character.appearance = spec["identity_anchor"]
    character.visual_description = json.dumps(spec)
    scene.visual_description = "Alice side profile by the office doorway, readable nose silhouette"
    views = {}
    colors = ("red", "orange", "yellow", "green", "blue", "purple", "white", "black")
    for view, color in zip(PRODUCTION_TURNAROUND_VIEWS, colors):
        image_path = tmp_path / f"{view}.png"
        Image.new("RGB", (32, 32), color).save(image_path)
        views[view] = str(image_path)
    CharacterTurnaroundAlbumService().freeze_album(character, views)
    db.commit()

    payload = _visible_character_payload(scene, project.id, db)
    reference_image = _get_reference_image(character, project.id, scene)

    assert _turnaround_view_for_scene(scene) == "side"
    assert reference_image == views["side"]
    assert payload[0]["turnaround_reference"]["view"] == "side"
    assert payload[0]["turnaround_reference"]["path"] == views["side"]
    assert "strict side profile" in payload[0]["turnaround_reference"]["control_prompt"]
    assert payload[0]["turnaround_reference"]["expected_features"]["nose_silhouette"] == spec["nose"]
    assert payload[0]["turnaround_reference"]["expected_features"]["wardrobe_side"] == spec["wardrobe"]

    contract = _character_sheet_generation_contract(payload)
    assert "Character sheet contract" in contract["prompt"]
    assert "view=side" in contract["prompt"]
    assert "strict side profile" in contract["prompt"]
    assert "nose_silhouette" in contract["prompt"]
    assert contract["references"][0]["view"] == "side"
    assert contract["references"][0]["path"] == views["side"]
    assert "identity drift" in contract["negative"]


def test_turnaround_view_for_scene_uses_production_character_sheet_assets():
    assert _turnaround_view_for_scene(None, "left 45 degree three-quarter close shot") == "three_quarter_left"
    assert _turnaround_view_for_scene(None, "right 45 degree reaction shot") == "three_quarter_right"
    assert _turnaround_view_for_scene(None, "full body head-to-toe reveal") == "full_body"
    assert _turnaround_view_for_scene(None, "crying close-up with intense expression") == "expression_intense"
    assert _turnaround_view_for_scene(None, "neutral expression reference close-up") == "expression_neutral"


def test_video_review_payload_carries_visible_character_anchors(project_data):
    db, project, scene, _, _ = project_data
    db.add(Character(project_id=project.id, name="Bob", appearance="man, square jaw, navy coat"))
    project.script = json.dumps({"scenes": [{"scene_number": 1, "characters": ["Alice", "Bob"]}]})
    db.commit()

    payload = _scene_review_payload(scene, project.id, db)

    assert payload["visible_characters"] == [
        {"name": "Alice", "appearance": "woman, short black hair, green jacket"},
        {"name": "Bob", "appearance": "man, square jaw, navy coat"},
    ]


def test_video_review_payload_carries_character_sheet_contract(project_data, tmp_path, monkeypatch):
    from PIL import Image
    from src.services.character_identity_service import CharacterIdentityService
    from src.services.character_turnaround_album import CharacterTurnaroundAlbumService, PRODUCTION_TURNAROUND_VIEWS
    from src.utils.storage import storage_manager

    db, project, scene, character, _ = project_data
    monkeypatch.setattr(storage_manager, "base_path", tmp_path / "storage")
    spec = CharacterIdentityService().build_identity_spec("Alice", "lead", project_id=project.id)
    character.appearance = spec["identity_anchor"]
    character.visual_description = json.dumps(spec)
    scene.visual_description = "Alice side profile by the office doorway"
    views = {}
    for view, color in zip(PRODUCTION_TURNAROUND_VIEWS, ("red", "orange", "yellow", "green", "blue", "purple", "white", "black")):
        image_path = tmp_path / f"{view}.png"
        Image.new("RGB", (32, 32), color).save(image_path)
        views[view] = str(image_path)
    CharacterTurnaroundAlbumService().freeze_album(character, views)
    db.commit()

    payload = _scene_review_payload(scene, project.id, db)

    assert "Character sheet contract" in payload["character_sheet_contract"]
    assert "view=side" in payload["character_sheet_contract"]
    assert payload["character_sheet_references"][0]["view"] == "side"
    assert payload["character_sheet_references"][0]["path"] == views["side"]
    assert payload["identity_contrast_matrix"] == {}


def test_video_review_payload_carries_identity_contrast_matrix(project_data):
    from src.services.character_identity_service import CharacterIdentityService

    db, project, scene, character, _ = project_data
    identity_service = CharacterIdentityService()
    alice_spec = identity_service.build_identity_spec("Alice", "lead", project_id=project.id)
    bob_spec = identity_service.build_identity_spec("Bob", "rival", project_id=project.id, existing_specs=[alice_spec])
    character.appearance = alice_spec["identity_anchor"]
    character.visual_description = json.dumps(alice_spec)
    db.add(Character(
        project_id=project.id,
        name="Bob",
        appearance=bob_spec["identity_anchor"],
        visual_description=json.dumps(bob_spec),
    ))
    project.script = json.dumps({"scenes": [{"scene_number": 1, "characters": ["Alice", "Bob"]}]})
    db.commit()

    payload = _scene_review_payload(scene, project.id, db)

    assert payload["identity_contrast_matrix"]["pairs"][0]["left"] == "Alice"
    assert payload["identity_contrast_matrix"]["pairs"][0]["right"] == "Bob"
    assert payload["identity_contrast_matrix"]["pairs"][0]["contrast_fields"]


def test_video_review_payload_carries_platform_aesthetic_contract(project_data):
    db, project, scene, _, _ = project_data

    payload = _scene_review_payload(scene, project.id, db)

    assert "Platform aesthetic contract" in payload["platform_aesthetic_contract"]["prompt"]
    assert "phone_readability" in payload["platform_aesthetic_contract"]["image_features"]
    assert "motion_smoothness" in payload["platform_aesthetic_contract"]["video_features"]


def test_seed_dance_profile_reaches_video_review_payload(project_data, monkeypatch):
    db, project, scene, _, _ = project_data
    monkeypatch.setattr("src.services.visual_style_assets.settings.GENERATION_QUALITY_PROFILE", "seed_dance_reference")

    payload = _scene_review_payload(scene, project.id, db)

    contract = payload["platform_aesthetic_contract"]
    assert contract["quality_profile"] == "seed_dance_reference"
    assert "Seed Dance reference target" in contract["prompt"]
    assert "AI generated gloss" in contract["negative_prompt"]


def test_video_director_plan_turns_atomic_scene_into_motion_contract(project_data, monkeypatch):
    _, project, scene, _, _ = project_data
    scene.dialogue = "你把那封信递给我。"
    scene.visual_description = "Alice reaches across the bar and takes the red letter"
    monkeypatch.setattr("src.services.video_director_service.settings.GENERATION_VIDEO_TARGET_SECONDS", 3.6)
    monkeypatch.setattr("src.services.video_director_service.settings.GENERATION_VIDEO_MODEL_FPS", 8)

    plan = get_video_director_service().plan_scene(
        scene,
        project.id,
        [{"name": "Alice", "appearance": "woman, short black hair, green jacket"}],
    )

    assert plan.shot_role in {"action", "prop_interaction"}
    assert plan.target_duration_seconds >= 3.6
    assert plan.num_frames >= 25
    assert "Visible character identity anchors" in plan.director_prompt
    assert "Spatial continuity contract" in plan.director_prompt
    assert plan.spatial_plan["shot_scale"] in {"medium shot", "medium two-shot", "wide establishing shot", "close-up"}
    assert plan.spatial_plan["character_positions"]["Alice"] == "center foreground"
    assert set(plan.spatial_plan["control_references"]) == {
        "pose_reference_prompt",
        "depth_reference_prompt",
        "camera_reference_prompt",
    }
    assert "End frame:" in plan.end_frame_prompt
    assert "identity drift" in plan.negative_prompt


def test_video_director_normalize_clip_uses_production_frame_contract(tmp_path, monkeypatch):
    source = tmp_path / "source.mp4"
    output = tmp_path / "normalized.mp4"
    source.write_bytes(b"video")
    director = get_video_director_service()
    commands = []

    monkeypatch.setattr("src.services.video_director_service.shutil.which", lambda _name: "ffmpeg")
    monkeypatch.setattr(director, "_probe_duration", lambda _path: 2.0)

    def fake_run(command, **_kwargs):
        commands.append(command)
        output.write_bytes(b"normalized video")
        return Mock(returncode=0)

    monkeypatch.setattr("src.services.video_director_service.subprocess.run", fake_run)

    result = director.normalize_clip(str(source), str(output), target_duration=3.6)

    assert result == str(output)
    command = commands[0]
    vf = command[command.index("-vf") + 1]
    assert "scale=768:1344:force_original_aspect_ratio=decrease" in vf
    assert "pad=768:1344:(ow-iw)/2:(oh-ih)/2" in vf
    assert "setsar=1" in vf
    assert "fps=24" in vf
    assert "tpad=stop_mode=clone:stop_duration=1.600" in vf
    assert "format=yuv420p" in vf
    assert command[command.index("-c:v") + 1] == "libx264"
    assert command[command.index("-preset") + 1] == "slow"
    assert command[command.index("-crf") + 1] == "18"
    assert command[command.index("-movflags") + 1] == "+faststart"


def test_video_director_prompt_uses_turnaround_reference_contract(project_data):
    _, project, scene, _, _ = project_data

    plan = get_video_director_service().plan_scene(
        scene,
        project.id,
        [{
            "name": "Alice",
            "appearance": "woman, short black hair, green jacket",
            "turnaround_reference": {
                "view": "side",
                "path": "side.png",
                "control_prompt": "strict side profile view, nose silhouette, stable wardrobe",
            },
        }],
    )

    assert "Turnaround reference contract" in plan.director_prompt
    assert "Alice side reference locked" in plan.director_prompt
    assert "strict side profile view" in plan.director_prompt


def test_video_director_prompt_includes_identity_contrast(project_data):
    _, project, scene, _, _ = project_data
    from src.services.character_identity_service import CharacterIdentityService
    identity_service = CharacterIdentityService()
    alice_spec = identity_service.build_identity_spec("Alice", "lead", project_id=project.id)
    bob_spec = identity_service.build_identity_spec("Bob", "rival", project_id=project.id, existing_specs=[alice_spec])

    plan = get_video_director_service().plan_scene(
        scene,
        project.id,
        [
            {"name": "Alice", "appearance": alice_spec["identity_anchor"], "identity_spec": alice_spec},
            {"name": "Bob", "appearance": bob_spec["identity_anchor"], "identity_spec": bob_spec},
        ],
    )

    assert "Identity contrast contract" in plan.director_prompt
    assert "Alice must not look like Bob" in plan.director_prompt
    assert "No same-face cast" in plan.end_frame_prompt


def test_video_director_prompt_includes_project_visual_style(project_data):
    _, project, scene, _, _ = project_data
    from src.services.visual_style_assets import VisualStyleAssetService
    VisualStyleAssetService().freeze_project_style(
        project,
        [scene],
        style_prompt="consistent premium red-and-teal short drama look",
        negative_prompt="random color grade",
    )

    plan = get_video_director_service().plan_scene(
        scene,
        project.id,
        [{"name": "Alice", "appearance": "woman, short black hair, green jacket"}],
    )

    assert "consistent premium red-and-teal short drama look" in plan.director_prompt
    assert "Platform aesthetic contract" in plan.director_prompt
    assert "consistent premium red-and-teal short drama look" in plan.end_frame_prompt
    assert "Platform aesthetic contract" in plan.end_frame_prompt
    assert "random color grade" in plan.negative_prompt
    assert "plastic skin" in plan.negative_prompt


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


def test_visual_style_pack_is_added_to_image_prompt(project_data):
    db, project, scene, _, _ = project_data
    from src.services.visual_style_assets import VisualStyleAssetService
    VisualStyleAssetService().freeze_project_style(
        project,
        [scene],
        style_prompt="consistent premium red-and-teal short drama look",
        negative_prompt="random color grade",
    )
    llm = Mock()
    llm.generate.return_value = json.dumps({"subject": "the character", "action": "holding a red letter",
        "setting": "office doorway", "framing": "medium shot", "lighting": "window light", "style": "cinematic",
        "needs_split": False, "reason": ""})

    compiled, _ = _prepare_prompt(scene, project.id, scene.visual_description, db, ShotPromptService(llm))

    assert "consistent premium red-and-teal short drama look" in compiled.prompt
    assert "Platform aesthetic contract" in compiled.prompt
    assert "random color grade" in compiled.negative_prompt
    assert "plastic skin" in compiled.negative_prompt


def test_visual_style_negative_prompt_edit_invalidates_cached_prompt(project_data):
    db, project, scene, _, _ = project_data
    from src.services.visual_style_assets import VisualStyleAssetService
    style_service = VisualStyleAssetService()
    style_service.freeze_project_style(
        project,
        [scene],
        style_prompt="consistent premium red-and-teal short drama look",
        negative_prompt="old random color grade",
    )
    llm = Mock()
    llm.generate.return_value = json.dumps({"subject": "the character", "action": "holding a red letter",
        "setting": "office doorway", "framing": "medium shot", "lighting": "window light", "style": "cinematic",
        "needs_split": False, "reason": ""})
    compiler = ShotPromptService(llm)
    first, _ = _prepare_prompt(scene, project.id, scene.visual_description, db, compiler)
    style_service.freeze_project_style(
        project,
        [scene],
        style_prompt="consistent premium red-and-teal short drama look",
        negative_prompt="new random color grade",
    )

    second, _ = _prepare_prompt(scene, project.id, scene.visual_description, db, compiler)

    assert "old random color grade" in first.negative_prompt
    assert "new random color grade" in second.negative_prompt
    assert second.source_hash != first.source_hash
    assert llm.generate.call_count == 2


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


def test_prepare_generation_allows_single_shot_without_story_reviewer(project_data, monkeypatch):
    db, project, scene, _, Session = project_data
    import src.tasks.image_tasks as tasks
    from src.utils.storage import storage_manager
    monkeypatch.setattr(tasks, "get_db", lambda: iter([Session()]))
    monkeypatch.setattr(tasks.prepare_generation_task, "update_state", Mock())

    result = tasks.prepare_generation_task.run(project.id, 1, compile_images=False)

    report = json.loads((storage_manager.get_project_path(project.id) / "reviews" / "production_story.json").read_text())
    assert result["prepared"] == 1
    assert report["status"] == "passed"
    assert report["mode"] == "single_shot_smoke_test"
    assert report["review"]["reviewed_scenes"] == [scene.scene_number]
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

    def fake_review(self, index, image_path, scene, prompt, reference_image=None):
        score = 4.0 + (index * 0.1)
        return {
            "index": index,
            "path": image_path,
            "status": "passed",
            "average": score,
            "review": {
                "composition": {"score": 5, "evidence": "strong framing"},
                "aesthetic_quality": {"score": 5, "evidence": "commercial lighting"},
                "visual_integrity": {"score": 5, "evidence": "clean render"},
                "facial_identity": {"score": 5, "evidence": "face matches"},
                "identity_consistency": {"score": 5, "evidence": "wardrobe stable"},
                "platform_aesthetic_scores": {
                    "skin_texture": {"score": 5, "evidence": "natural skin"},
                    "lighting_quality": {"score": 5, "evidence": "commercial lighting"},
                    "color_grade": {"score": 5, "evidence": "clean color"},
                    "phone_readability": {"score": 5, "evidence": "face readable"},
                    "background_separation": {"score": 5, "evidence": "clear separation"},
                    "production_polish": {"score": 5, "evidence": "premium look"},
                    "repair_artifacts_absent": {"score": 5, "evidence": "no repair scar"},
                },
            },
            "metrics": {"technical_score": score},
        }

    monkeypatch.setattr("src.tasks.image_tasks.ImageQualitySelector.review_candidate", fake_review)
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
    assert report["postprocess"]["status"] == "skipped"


def test_image_generation_reviews_postprocessed_final_image(tmp_path, monkeypatch):
    from PIL import Image
    from src.services.generation_provider import ImageGenerationRequest, GenerationResult

    class FakeProvider:
        name = GenerationProviderName.LOCAL_COMFYUI

        def generate_image(self, request):
            Image.new("RGB", (request.width, request.height), (120, 120, 120)).save(request.output_path)
            return GenerationResult("local_comfyui", request.output_path, "image", {})

    reviewed_indices = []

    def fake_review(self, index, image_path, scene, prompt, reference_image=None):
        reviewed_indices.append(index)
        return {
            "index": index,
            "path": image_path,
            "status": "passed",
            "average": 4.6,
            "review": {
                "composition": {"score": 5, "evidence": "strong framing"},
                "aesthetic_quality": {"score": 5, "evidence": "commercial lighting"},
                "visual_integrity": {"score": 5, "evidence": "clean render"},
                "facial_identity": {"score": 5, "evidence": "face matches"},
                "identity_consistency": {"score": 5, "evidence": "wardrobe stable"},
                "platform_aesthetic_scores": {
                    "skin_texture": {"score": 5, "evidence": "natural skin"},
                    "lighting_quality": {"score": 5, "evidence": "commercial lighting"},
                    "color_grade": {"score": 5, "evidence": "clean color"},
                    "phone_readability": {"score": 5, "evidence": "face readable"},
                    "background_separation": {"score": 5, "evidence": "clear separation"},
                    "production_polish": {"score": 5, "evidence": "premium look"},
                    "repair_artifacts_absent": {"score": 5, "evidence": "no repair scar"},
                },
            },
            "metrics": {"technical_score": 4.6},
        }

    monkeypatch.setattr("src.tasks.image_tasks.ImageQualitySelector.review_candidate", fake_review)
    monkeypatch.setattr("src.tasks.image_tasks.ImagePostprocessor.process", lambda *args, **kwargs: {"status": "passed"})
    monkeypatch.setattr("src.tasks.image_tasks.settings.GENERATION_IMAGE_CANDIDATES", 1)
    monkeypatch.setattr("src.tasks.image_tasks.settings.GENERATION_IMAGE_REFINEMENT_PASSES", 0)
    monkeypatch.setattr("src.tasks.image_tasks.settings.GENERATION_REQUIRE_IMAGE_REVIEW", True)
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

    _, report = _generate_quality_candidates(FakeProvider(), request, {"scene_number": 1}, None)

    assert reviewed_indices == [1, 0]
    assert report["postprocess_review"]["stage"] == "postprocess_review"
    assert report["postprocess_review"]["status"] == "passed"


def test_postprocess_review_blocks_degraded_final_image(tmp_path, monkeypatch):
    from PIL import Image
    from src.services.generation_provider import ImageGenerationRequest, GenerationResult

    class FakeProvider:
        name = GenerationProviderName.LOCAL_COMFYUI

        def generate_image(self, request):
            Image.new("RGB", (request.width, request.height), (120, 120, 120)).save(request.output_path)
            return GenerationResult("local_comfyui", request.output_path, "image", {})

    def fake_review(self, index, image_path, scene, prompt, reference_image=None):
        if index == 0:
            return {
                "index": index,
                "path": image_path,
                "status": "needs_review",
                "average": 2.0,
                "review": {
                    "composition": {"score": 4, "evidence": "usable framing"},
                    "aesthetic_quality": {"score": 2, "evidence": "plastic skin after face repair"},
                    "visual_integrity": {"score": 2, "evidence": "visible face repair scar"},
                    "facial_identity": {"score": 4, "evidence": "face mostly matches"},
                    "identity_consistency": {"score": 4, "evidence": "wardrobe stable"},
                    "issues": [],
                },
                "platform_aesthetic_gate": {
                    "status": "needs_review",
                    "low": {
                        "skin_texture": {"score": 2, "evidence": "plastic skin after face repair"},
                        "repair_artifacts_absent": {"score": 2, "evidence": "visible face repair scar"},
                    },
                },
                "metrics": {"technical_score": 2.0},
            }
        return {
            "index": index,
            "path": image_path,
            "status": "passed",
            "average": 4.6,
            "review": {
                "composition": {"score": 5, "evidence": "strong framing"},
                "aesthetic_quality": {"score": 5, "evidence": "commercial lighting"},
                "visual_integrity": {"score": 5, "evidence": "clean render"},
                "facial_identity": {"score": 5, "evidence": "face matches"},
                "identity_consistency": {"score": 5, "evidence": "wardrobe stable"},
                "platform_aesthetic_scores": {
                    "skin_texture": {"score": 5, "evidence": "natural skin"},
                    "lighting_quality": {"score": 5, "evidence": "commercial lighting"},
                    "color_grade": {"score": 5, "evidence": "clean color"},
                    "phone_readability": {"score": 5, "evidence": "face readable"},
                    "background_separation": {"score": 5, "evidence": "clear separation"},
                    "production_polish": {"score": 5, "evidence": "premium look"},
                    "repair_artifacts_absent": {"score": 5, "evidence": "no repair scar"},
                },
            },
            "metrics": {"technical_score": 4.6},
        }

    monkeypatch.setattr("src.tasks.image_tasks.ImageQualitySelector.review_candidate", fake_review)
    monkeypatch.setattr("src.tasks.image_tasks.ImagePostprocessor.process", lambda *args, **kwargs: {"status": "passed"})
    monkeypatch.setattr("src.tasks.image_tasks.settings.GENERATION_IMAGE_CANDIDATES", 1)
    monkeypatch.setattr("src.tasks.image_tasks.settings.GENERATION_IMAGE_REFINEMENT_PASSES", 0)
    monkeypatch.setattr("src.tasks.image_tasks.settings.GENERATION_REQUIRE_IMAGE_REVIEW", True)
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

    with pytest.raises(ReviewError, match="Postprocessed image failed"):
        _generate_quality_candidates(FakeProvider(), request, {"scene_number": 1}, None)

    quality_report = json.loads((tmp_path / "scene.quality.json").read_text(encoding="utf-8"))
    assert quality_report["postprocess_review"]["status"] == "needs_review"
    assert quality_report["repair_queue"][0]["action"] == "fix_workflow_profile"


def test_image_repair_action_boosts_quality_parameters(monkeypatch):
    monkeypatch.setattr("src.tasks.image_tasks.settings.GENERATION_STEP_VARIATION", 0)
    monkeypatch.setattr("src.tasks.image_tasks.settings.GENERATION_CFG_VARIATION", 0)

    steps, cfg = _quality_parameters(
        0,
        0,
        28,
        6.0,
        repair_action="refine_prompt_composition",
    )

    assert steps == 36
    assert cfg == 5.7
    assert _repair_parameter_profile("refine_prompt_composition")["reason"] == "composition_aesthetic_repair"


def test_image_repair_action_is_recorded_in_candidate_request(tmp_path, monkeypatch):
    from PIL import Image
    from src.services.generation_provider import ImageGenerationRequest

    class FakeProvider:
        name = GenerationProviderName.LOCAL_COMFYUI

        def __init__(self):
            self.requests = []

        def generate_image(self, request):
            self.requests.append(request)
            Image.new("RGB", (request.width, request.height), (130, 130, 130)).save(request.output_path)
            return GenerationResult(
                "local_comfyui",
                request.output_path,
                "image",
                {"workflow": {"steps": 45, "cfg": 7.0, "sampler_name": "dpmpp_2m"}},
            )

    def fake_review(self, index, image_path, scene, prompt, reference_image=None):
        scene["review_prompt"] = prompt
        return {
            "index": index,
            "path": image_path,
            "status": "passed",
            "average": 4.8,
            "review": {"composition": {"score": 5, "evidence": "clean framing"}},
            "metrics": {"technical_score": 4.8},
        }

    monkeypatch.setattr("src.tasks.image_tasks.ImageQualitySelector.review_candidate", fake_review)
    monkeypatch.setattr("src.tasks.image_tasks.settings.GENERATION_IMAGE_CANDIDATES", 1)
    monkeypatch.setattr("src.tasks.image_tasks.settings.GENERATION_IMAGE_REFINEMENT_PASSES", 0)
    monkeypatch.setattr("src.tasks.image_tasks.settings.GENERATION_STEP_VARIATION", 0)
    monkeypatch.setattr("src.tasks.image_tasks.settings.GENERATION_CFG_VARIATION", 0)
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
    provider = FakeProvider()

    _, report = _generate_quality_candidates(
        provider,
        request,
        {"scene_number": 1, "visual_description": "A woman opens a letter", "repair_action": "refine_prompt_composition"},
        reference_image=None,
        repair_action="refine_prompt_composition",
    )

    assert provider.requests[0].steps == 36
    assert provider.requests[0].cfg_scale == 5.7
    candidate_request = report["candidates"][0]["request"]
    assert candidate_request["repair_action"] == "refine_prompt_composition"
    assert candidate_request["repair_parameter_profile"]["reason"] == "composition_aesthetic_repair"
    assert report["candidates"][0]["scene"]["scene_number"] == 1
    assert report["candidates"][0]["scene"]["repair_action"] == "refine_prompt_composition"
    assert report["candidates"][0]["provider_metadata"]["workflow"]["steps"] == 45
    assert report["candidates"][0]["provider_metadata"]["workflow"]["sampler_name"] == "dpmpp_2m"


def test_image_repair_generation_expands_quality_budget(tmp_path, monkeypatch):
    from PIL import Image
    from src.services.generation_provider import ImageGenerationRequest

    class FakeProvider:
        name = GenerationProviderName.LOCAL_COMFYUI

        def __init__(self):
            self.requests = []

        def generate_image(self, request):
            self.requests.append(request)
            Image.new("RGB", (request.width, request.height), (120, 120, 120)).save(request.output_path)
            return GenerationResult("local_comfyui", request.output_path, "image", {})

    def fake_review(self, index, image_path, scene, prompt, reference_image=None):
        return {
            "index": index,
            "path": image_path,
            "status": "passed",
            "average": 4.6,
            "review": {"composition": {"score": 5, "evidence": "clean framing"}},
            "metrics": {"technical_score": 4.6},
        }

    monkeypatch.setattr("src.tasks.image_tasks.ImageQualitySelector.review_candidate", fake_review)
    monkeypatch.setattr("src.services.generation_quality_policy.settings.GENERATION_IMAGE_CANDIDATES", 2)
    monkeypatch.setattr("src.services.generation_quality_policy.settings.GENERATION_IMAGE_REFINEMENT_PASSES", 0)
    monkeypatch.setattr("src.services.generation_quality_policy.settings.GENERATION_MAX_IMAGE_CANDIDATES", 6)
    monkeypatch.setattr("src.services.generation_quality_policy.settings.GENERATION_REPAIR_IMAGE_CANDIDATE_MULTIPLIER", 2.0)
    monkeypatch.setattr("src.services.generation_quality_policy.settings.GENERATION_REPAIR_EXTRA_REFINEMENT_PASSES", 0)
    monkeypatch.setattr("src.tasks.image_tasks.settings.GENERATION_REQUIRE_IMAGE_REVIEW", False)

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
    provider = FakeProvider()

    _, report = _generate_quality_candidates(
        provider,
        request,
        {"scene_number": 1},
        reference_image=None,
        repair_action="regenerate_keyframe_with_identity_lock",
    )

    assert len(provider.requests) == 6
    assert report["quality_budget"]["candidate_count"] == 6
    assert report["quality_budget"]["reason"] == "repair_generation_budget"
    assert report["quality_budget"]["action_profile"] == "identity_lock"
    assert report["candidates"][0]["request"]["quality_budget"]["repair_action"] == "regenerate_keyframe_with_identity_lock"


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
            return {
                "status": "passed",
                "average": 4.7,
                "batches": [{
                    "review": {
                        "video_aesthetic_scores": passed_video_aesthetic_scores(),
                        "video_performance_scores": passed_video_performance_scores(),
                    }
                }],
            }

    fake_svd = FakeSVD()
    monkeypatch.setattr("src.tasks.video_tasks.GenerationReviewService", FakeReviewService)
    monkeypatch.setattr("src.tasks.video_tasks.settings.GENERATION_VIDEO_CANDIDATES", 2)
    monkeypatch.setattr("src.tasks.video_tasks.settings.GENERATION_VIDEO_MIN_SCORE", 4.0)
    monkeypatch.setattr("src.tasks.video_tasks.settings.GENERATION_REQUIRE_VIDEO_REVIEW", True)

    shot_plan = VideoShotPlan(
        shot_role="prop_interaction",
        action_intensity="medium",
        target_duration_seconds=3.6,
        fps=8,
        num_frames=29,
        motion_bucket_id=118,
        noise_aug_strength=0.018,
        director_prompt="directed short-drama prop handoff",
        end_frame_prompt="end frame after the prop handoff",
        negative_prompt="identity drift",
        notes=["test"],
    )

    final_path, report = _generate_quality_video_candidates(
        fake_svd, scene, project.id, str(tmp_path / "scene.mp4"), db,
        num_frames=29, fps=8, motion_bucket_id=118, noise_aug_strength=0.018, shot_plan=shot_plan,
    )

    assert Path(final_path).read_bytes() == b"video-2"
    assert report["status"] == "passed"
    assert report["selected_average"] == 4.7
    assert report["candidates"][0]["shot_plan"]["shot_role"] == "prop_interaction"
    assert report["candidates"][0]["scene"]["scene_number"] == scene.scene_number
    assert report["candidates"][0]["request"]["num_frames"] == 29
    assert report["candidates"][0]["request"]["fps"] == 8
    assert report["candidates"][0]["request"]["motion_bucket_id"] == report["candidates"][0]["motion_bucket_id"]
    assert report["candidates"][0]["request"]["noise_aug_strength"] == report["candidates"][0]["noise_aug_strength"]
    assert [candidate["index"] for candidate in report["candidates"]] == [2, 1]
    assert fake_svd.requests[0]["motion_bucket_id"] != fake_svd.requests[1]["motion_bucket_id"]


def test_video_selection_prefers_identity_safe_candidate(project_data, tmp_path, monkeypatch):
    db, project, scene, _, _ = project_data
    scene.image_path = str(tmp_path / "source.png")
    Path(scene.image_path).write_bytes(b"image")
    db.commit()

    class FakeSVD:
        def generate_video(self, **kwargs):
            Path(kwargs["output_path"]).write_bytes(f"video-{kwargs['output_path']}".encode())
            return kwargs["output_path"]

    class FakeReviewService:
        def review_video(self, _video, payload, _report_path, _reference=None):
            if payload["candidate_index"] == 1:
                return {
                    "status": "passed",
                    "average": 4.9,
                    "batches": [{
                        "review": {
                            "story_match": {"score": 5, "evidence": "scene matches"},
                            "composition": {"score": 5, "evidence": "strong framing"},
                            "aesthetic_quality": {"score": 5, "evidence": "commercial lighting"},
                            "visual_integrity": {"score": 5, "evidence": "clean render"},
                            "facial_identity": {"score": 2, "evidence": "face drift"},
                            "identity_consistency": {"score": 5, "evidence": "wardrobe stable"},
                            "temporal_consistency": {"score": 5, "evidence": "motion stable"},
                            "video_aesthetic_scores": passed_video_aesthetic_scores(),
                        }
                    }],
                }
            return {
                "status": "passed",
                "average": 4.3,
                "batches": [{
                        "review": {
                            "story_match": {"score": 5, "evidence": "scene matches"},
                            "composition": {"score": 5, "evidence": "strong framing"},
                            "aesthetic_quality": {"score": 5, "evidence": "commercial lighting"},
                            "visual_integrity": {"score": 5, "evidence": "clean render"},
                            "facial_identity": {"score": 4, "evidence": "face matches"},
                            "identity_consistency": {"score": 4, "evidence": "identity stable"},
                            "temporal_consistency": {"score": 4, "evidence": "motion stable"},
                            "video_aesthetic_scores": passed_video_aesthetic_scores(),
                    }
                }],
            }

    monkeypatch.setattr("src.tasks.video_tasks.GenerationReviewService", FakeReviewService)
    monkeypatch.setattr("src.tasks.video_tasks.settings.GENERATION_VIDEO_CANDIDATES", 2)
    monkeypatch.setattr("src.tasks.video_tasks.settings.GENERATION_VIDEO_MIN_SCORE", 4.0)
    monkeypatch.setattr("src.tasks.video_tasks.settings.GENERATION_VIDEO_IDENTITY_MIN_SCORE", 4.0)
    monkeypatch.setattr("src.tasks.video_tasks.settings.GENERATION_VIDEO_TEMPORAL_MIN_SCORE", 4.0)
    monkeypatch.setattr("src.tasks.video_tasks.settings.GENERATION_REQUIRE_VIDEO_REVIEW", True)

    final_path, report = _generate_quality_video_candidates(
        FakeSVD(), scene, project.id, str(tmp_path / "scene.mp4"), db,
        num_frames=16, fps=8, motion_bucket_id=127, noise_aug_strength=0.02,
    )

    assert report["status"] == "passed"
    assert report["candidates"][0]["index"] == 2
    assert report["selected_gate_scores"] == {
        "facial_identity": 4.0,
        "identity_consistency": 4.0,
        "temporal_consistency": 4.0,
    }
    assert Path(final_path).read_bytes() == Path(report["selected_path"]).read_bytes()


def test_required_video_review_blocks_low_identity_scores(project_data, tmp_path, monkeypatch):
    db, project, scene, _, _ = project_data
    scene.image_path = str(tmp_path / "source.png")
    Path(scene.image_path).write_bytes(b"image")
    db.commit()

    class FakeSVD:
        def generate_video(self, **kwargs):
            Path(kwargs["output_path"]).write_bytes(b"identity-drift")
            return kwargs["output_path"]

    class FakeReviewService:
        def review_video(self, *_args, **_kwargs):
            return {
                "status": "passed",
                "average": 4.8,
                "batches": [{
                    "review": {
                        "facial_identity": {"score": 2, "evidence": "face drift"},
                        "identity_consistency": {"score": 3, "evidence": "same-face issue"},
                        "temporal_consistency": {"score": 4, "evidence": "motion stable"},
                    }
                }],
            }

    output = tmp_path / "scene.mp4"
    monkeypatch.setattr("src.tasks.video_tasks.GenerationReviewService", FakeReviewService)
    monkeypatch.setattr("src.tasks.video_tasks.settings.GENERATION_VIDEO_CANDIDATES", 1)
    monkeypatch.setattr("src.tasks.video_tasks.settings.GENERATION_VIDEO_REFINEMENT_PASSES", 0)
    monkeypatch.setattr("src.tasks.video_tasks.settings.GENERATION_VIDEO_MIN_SCORE", 4.0)
    monkeypatch.setattr("src.tasks.video_tasks.settings.GENERATION_VIDEO_IDENTITY_MIN_SCORE", 4.0)
    monkeypatch.setattr("src.tasks.video_tasks.settings.GENERATION_VIDEO_TEMPORAL_MIN_SCORE", 4.0)
    monkeypatch.setattr("src.tasks.video_tasks.settings.GENERATION_REQUIRE_VIDEO_REVIEW", True)

    with pytest.raises(ReviewError, match="failed quality gate"):
        _generate_quality_video_candidates(
            FakeSVD(), scene, project.id, str(output), db,
            num_frames=16, fps=8, motion_bucket_id=127, noise_aug_strength=0.02,
        )

    report = json.loads(output.with_suffix(".quality.json").read_text(encoding="utf-8"))
    assert report["status"] == "needs_review"
    assert report["selected_gate_scores"]["facial_identity"] == 2.0


def test_required_video_review_blocks_low_platform_score(project_data, tmp_path, monkeypatch):
    db, project, scene, _, _ = project_data
    scene.image_path = str(tmp_path / "source.png")
    Path(scene.image_path).write_bytes(b"image")
    db.commit()

    class FakeSVD:
        def generate_video(self, **kwargs):
            Path(kwargs["output_path"]).write_bytes(b"cheap-filter-video")
            return kwargs["output_path"]

    class FakeReviewService:
        def review_video(self, *_args, **_kwargs):
            return {
                "status": "passed",
                "average": 4.6,
                "batches": [{
                    "review": {
                        "story_match": {"score": 5, "evidence": "scene matches"},
                        "composition": {"score": 4, "evidence": "framing is usable"},
                        "aesthetic_quality": {"score": 0, "evidence": "cheap filter look and plastic skin"},
                        "visual_integrity": {"score": 3, "evidence": "visible repair scar"},
                        "facial_identity": {"score": 5, "evidence": "face matches"},
                        "identity_consistency": {"score": 5, "evidence": "wardrobe stable"},
                        "temporal_consistency": {"score": 5, "evidence": "motion stable"},
                    }
                }],
            }

    output = tmp_path / "scene.mp4"
    monkeypatch.setattr("src.tasks.video_tasks.GenerationReviewService", FakeReviewService)
    monkeypatch.setattr("src.tasks.video_tasks.settings.GENERATION_VIDEO_CANDIDATES", 1)
    monkeypatch.setattr("src.tasks.video_tasks.settings.GENERATION_VIDEO_REFINEMENT_PASSES", 0)
    monkeypatch.setattr("src.tasks.video_tasks.settings.GENERATION_VIDEO_MIN_SCORE", 4.0)
    monkeypatch.setattr("src.tasks.video_tasks.settings.GENERATION_VIDEO_PLATFORM_MIN_SCORE", 4.1)
    monkeypatch.setattr("src.tasks.video_tasks.settings.GENERATION_REQUIRE_VIDEO_REVIEW", True)

    with pytest.raises(ReviewError, match="platform score"):
        _generate_quality_video_candidates(
            FakeSVD(), scene, project.id, str(output), db,
            num_frames=16, fps=8, motion_bucket_id=127, noise_aug_strength=0.02,
        )

    report = json.loads(output.with_suffix(".quality.json").read_text(encoding="utf-8"))
    assert report["status"] == "needs_review"
    assert report["selected_platform_score"] < 4.1
    assert report["repair_queue"][0]["action"] == "refine_prompt_composition"


def test_video_selection_uses_aesthetic_breakdown(project_data, tmp_path, monkeypatch):
    db, project, scene, _, _ = project_data
    scene.image_path = str(tmp_path / "source.png")
    Path(scene.image_path).write_bytes(b"image")
    db.commit()

    class FakeSVD:
        def generate_video(self, **kwargs):
            Path(kwargs["output_path"]).write_bytes(f"video-{kwargs['output_path']}".encode())
            return kwargs["output_path"]

    low_breakdown = {
        "skin_texture_stability": {"score": 4, "evidence": "skin stable"},
        "lighting_consistency": {"score": 1, "evidence": "light jumps"},
        "color_grade_consistency": {"score": 4, "evidence": "color stable"},
        "phone_readability": {"score": 4, "evidence": "face readable"},
        "motion_smoothness": {"score": 2, "evidence": "stutter"},
        "background_stability": {"score": 4, "evidence": "background stable"},
        "artifact_absence": {"score": 2, "evidence": "repair scar flickers"},
    }
    high_breakdown = {
        feature: {"score": 4, "evidence": "passes"}
        for feature in low_breakdown
    }

    class FakeReviewService:
        def review_video(self, _video, payload, _report_path, _reference=None):
            review = {
                "story_match": {"score": 5, "evidence": "scene matches"},
                "composition": {"score": 5, "evidence": "strong framing"},
                "aesthetic_quality": {"score": 5, "evidence": "commercial lighting"},
                "visual_integrity": {"score": 5, "evidence": "clean render"},
                "facial_identity": {"score": 5, "evidence": "face matches"},
                "identity_consistency": {"score": 5, "evidence": "wardrobe stable"},
                "temporal_consistency": {"score": 5, "evidence": "motion stable"},
                "video_aesthetic_scores": low_breakdown if payload["candidate_index"] == 1 else high_breakdown,
            }
            return {"status": "passed", "average": 4.8 if payload["candidate_index"] == 1 else 4.2, "batches": [{"review": review}]}

    monkeypatch.setattr("src.tasks.video_tasks.GenerationReviewService", FakeReviewService)
    monkeypatch.setattr("src.tasks.video_tasks.settings.GENERATION_VIDEO_CANDIDATES", 2)
    monkeypatch.setattr("src.tasks.video_tasks.settings.GENERATION_VIDEO_MIN_SCORE", 4.0)
    monkeypatch.setattr("src.tasks.video_tasks.settings.GENERATION_VIDEO_PLATFORM_MIN_SCORE", 4.0)
    monkeypatch.setattr("src.tasks.video_tasks.settings.GENERATION_VIDEO_AESTHETIC_FEATURE_MIN_SCORE", 4.0)
    monkeypatch.setattr("src.tasks.video_tasks.settings.GENERATION_REQUIRE_VIDEO_REVIEW", True)

    _, report = _generate_quality_video_candidates(
        FakeSVD(), scene, project.id, str(tmp_path / "scene.mp4"), db,
        num_frames=16, fps=8, motion_bucket_id=127, noise_aug_strength=0.02,
    )

    assert report["status"] == "passed"
    assert report["candidates"][0]["index"] == 2
    assert report["candidates"][1]["video_aesthetic_gate"]["status"] == "needs_review"
    assert set(report["candidates"][1]["video_aesthetic_gate"]["low"]) == {
        "lighting_consistency",
        "motion_smoothness",
        "artifact_absence",
    }


def test_video_selection_prefers_character_distinctiveness(project_data, tmp_path, monkeypatch):
    db, project, scene, _, _ = project_data
    scene.image_path = str(tmp_path / "source.png")
    scene.visual_description = "Alice and Bob argue in a premium office doorway"
    project.script = json.dumps({
        "scenes": [{"scene_number": scene.scene_number, "characters": ["Alice", "Bob"]}]
    })
    from src.database.models import Character
    from src.services.character_identity_service import CharacterIdentityService
    identity_service = CharacterIdentityService()
    alice = identity_service.build_identity_spec("Alice", "lead", project_id=project.id)
    bob = identity_service.build_identity_spec("Bob", "rival", project_id=project.id, existing_specs=[alice])
    db.add(Character(project_id=project.id, name="Alice", appearance=alice["identity_anchor"], visual_description=json.dumps(alice)))
    db.add(Character(project_id=project.id, name="Bob", appearance=bob["identity_anchor"], visual_description=json.dumps(bob)))
    Path(scene.image_path).write_bytes(b"image")
    db.commit()

    class FakeSVD:
        def generate_video(self, **kwargs):
            marker = b"same-face-video" if kwargs["output_path"].endswith("candidate_01.mp4") else b"distinct-video"
            Path(kwargs["output_path"]).write_bytes(marker)
            return kwargs["output_path"]

    weak_distinctiveness = {
        "face_geometry_separation": {"score": 2, "evidence": "copied facial geometry"},
        "hair_separation": {"score": 4, "evidence": "hair mostly separate"},
        "wardrobe_separation": {"score": 4, "evidence": "wardrobe mostly separate"},
        "role_readability": {"score": 3, "evidence": "roles are unclear during motion"},
        "no_same_face_casting": {"score": 2, "evidence": "same-face casting between Alice and Bob"},
    }
    strong_distinctiveness = {
        feature: {"score": 4, "evidence": "characters remain visually distinct"}
        for feature in weak_distinctiveness
    }
    video_aesthetic_scores = {
        "skin_texture_stability": {"score": 4, "evidence": "skin stable"},
        "lighting_consistency": {"score": 4, "evidence": "lighting stable"},
        "color_grade_consistency": {"score": 4, "evidence": "color stable"},
        "phone_readability": {"score": 4, "evidence": "faces readable"},
        "motion_smoothness": {"score": 4, "evidence": "motion smooth"},
        "background_stability": {"score": 4, "evidence": "background stable"},
        "artifact_absence": {"score": 4, "evidence": "no artifacts"},
    }

    class FakeReviewService:
        def review_video(self, _video, payload, _report_path, _reference=None):
            assert payload["visible_characters"]
            assert payload["identity_contrast_matrix"]["pairs"]
            review = {
                "story_match": {"score": 5, "evidence": "scene matches"},
                "composition": {"score": 5, "evidence": "strong framing"},
                "aesthetic_quality": {"score": 5, "evidence": "commercial lighting"},
                "visual_integrity": {"score": 5, "evidence": "clean render"},
                "facial_identity": {"score": 5, "evidence": "faces match"},
                "identity_consistency": {"score": 5, "evidence": "wardrobe stable"},
                "temporal_consistency": {"score": 5, "evidence": "motion stable"},
                "video_aesthetic_scores": video_aesthetic_scores,
                "character_distinctiveness_scores": (
                    weak_distinctiveness if payload["candidate_index"] == 1 else strong_distinctiveness
                ),
            }
            return {"status": "passed", "average": 4.9 if payload["candidate_index"] == 1 else 4.3, "batches": [{"review": review}]}

    monkeypatch.setattr("src.tasks.video_tasks.GenerationReviewService", FakeReviewService)
    monkeypatch.setattr("src.tasks.video_tasks.settings.GENERATION_VIDEO_CANDIDATES", 2)
    monkeypatch.setattr("src.tasks.video_tasks.settings.GENERATION_VIDEO_MIN_SCORE", 4.0)
    monkeypatch.setattr("src.tasks.video_tasks.settings.GENERATION_VIDEO_PLATFORM_MIN_SCORE", 4.0)
    monkeypatch.setattr("src.tasks.video_tasks.settings.GENERATION_VIDEO_CHARACTER_DISTINCTIVENESS_MIN_SCORE", 4.0)
    monkeypatch.setattr("src.tasks.video_tasks.settings.GENERATION_REQUIRE_VIDEO_REVIEW", True)

    final_path, report = _generate_quality_video_candidates(
        FakeSVD(), scene, project.id, str(tmp_path / "scene.mp4"), db,
        num_frames=16, fps=8, motion_bucket_id=127, noise_aug_strength=0.02,
    )

    assert Path(final_path).read_bytes() == b"distinct-video"
    assert report["status"] == "passed"
    assert report["candidates"][0]["index"] == 2
    assert report["selected_character_distinctiveness_gate"]["status"] == "passed"
    assert report["candidates"][1]["character_distinctiveness_gate"]["status"] == "needs_review"
    assert report["candidates"][1]["scene"]["identity_contrast_matrix"]["pairs"]


def test_video_selection_uses_technical_score_when_review_scores_tie(tmp_path, monkeypatch):
    weak = tmp_path / "weak.mp4"
    strong = tmp_path / "strong.mp4"
    weak.write_bytes(b"weak")
    strong.write_bytes(b"strong")

    def fake_metrics(path):
        score = 4.8 if Path(path).name == "strong.mp4" else 2.2
        return {
            "status": "available",
            "path": str(path),
            "technical_score": score,
            "motion_energy": 8.0 if score > 4 else 1.0,
            "sharpness": 90.0 if score > 4 else 5.0,
        }

    monkeypatch.setattr("src.tasks.video_tasks.video_candidate_metrics", fake_metrics)
    monkeypatch.setattr("src.tasks.video_tasks.settings.GENERATION_REQUIRE_VIDEO_REVIEW", False)
    monkeypatch.setattr("src.tasks.video_tasks.settings.GENERATION_VIDEO_MIN_SCORE", 4.0)
    monkeypatch.setattr("src.tasks.video_tasks.settings.GENERATION_VIDEO_PLATFORM_MIN_SCORE", 4.0)

    final_path, report = _select_best_video_candidate(
        [
            {"index": 1, "path": str(weak), "status": "passed", "average": 4.4, "platform_score": 4.4},
            {"index": 2, "path": str(strong), "status": "passed", "average": 4.4, "platform_score": 4.4},
        ],
        str(tmp_path / "final.mp4"),
        tmp_path / "final.quality.json",
    )

    assert Path(final_path).read_bytes() == b"strong"
    assert report["status"] == "passed"
    assert report["candidates"][0]["index"] == 2
    assert report["selected_technical_score"] == 4.8
    assert report["selected_selection_score"] > report["candidates"][1]["selection_score"]


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
    report = json.loads(output.with_suffix(".quality.json").read_text(encoding="utf-8"))
    assert report["repair_queue"]
    assert report["repair_queue"][0]["action"] in {"manual_review", "lower_motion_and_regenerate_video"}
    assert report["repair_queue"][0]["scene_number"] == scene.scene_number


def test_video_generation_blocks_when_all_candidate_reviews_error_even_if_review_not_required(project_data, tmp_path, monkeypatch):
    db, project, scene, _, _ = project_data
    scene.image_path = str(tmp_path / "source.png")
    Path(scene.image_path).write_bytes(b"image")
    db.commit()

    class FakeSVD:
        def generate_video(self, **kwargs):
            Path(kwargs["output_path"]).write_bytes(b"unreviewed-video")
            return kwargs["output_path"]

    class FakeReviewService:
        def review_video(self, *_args, **_kwargs):
            return {"status": "error", "average": 0, "error": "review service unavailable"}

    output = tmp_path / "scene.mp4"
    monkeypatch.setattr("src.tasks.video_tasks.GenerationReviewService", FakeReviewService)
    monkeypatch.setattr("src.tasks.video_tasks.settings.GENERATION_VIDEO_CANDIDATES", 1)
    monkeypatch.setattr("src.tasks.video_tasks.settings.GENERATION_REQUIRE_VIDEO_REVIEW", False)

    with pytest.raises(ReviewError, match="All video candidate reviews failed"):
        _generate_quality_video_candidates(
            FakeSVD(), scene, project.id, str(output), db,
            num_frames=16, fps=8, motion_bucket_id=127, noise_aug_strength=0.02,
        )

    assert not output.exists()
    report = json.loads(output.with_suffix(".quality.json").read_text(encoding="utf-8"))
    assert report["status"] == "review_unavailable"
    assert report["repair_queue"]
    assert "promoted_path" not in report


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
            return {
                "status": "passed",
                "average": 4.5,
                "batches": [{
                    "review": {"video_aesthetic_scores": passed_video_aesthetic_scores()}
                }],
            }

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


def test_video_repair_action_from_candidates_promotes_motion_repair():
    action = _video_repair_action_from_candidates([
        {
            "average": 2.2,
            "status": "needs_review",
            "scene": {"scene_number": 1},
            "video_aesthetic_gate": {
                "low": {
                    "motion_smoothness": {"score": 2, "evidence": "stutter and camera jump"},
                    "artifact_absence": {"score": 2, "evidence": "repair scar flickers"},
                }
            },
        }
    ])

    assert action == "lower_motion_and_regenerate_video"


def test_video_repair_action_from_candidates_promotes_static_motion_repair():
    action = _video_repair_action_from_candidates([
        {
            "average": 2.8,
            "status": "needs_review",
            "scene": {"scene_number": 1},
            "technical_metrics": {
                "technical_score": 2.4,
                "motion_energy": 0.3,
                "sharpness": 42.0,
                "brightness": 128.0,
                "brightness_variance": 20.0,
            },
        }
    ])

    assert action == "increase_motion_and_regenerate_video"


def test_video_repair_action_ignores_image_stage_aesthetic_repairs():
    action = _video_repair_action_from_candidates([
        {
            "average": 2.3,
            "status": "needs_review",
            "scene": {"scene_number": 1},
            "video_aesthetic_gate": {
                "low": {
                    "skin_texture_stability": {"score": 2, "evidence": "plastic skin and AI generated gloss"},
                    "lighting_consistency": {"score": 2, "evidence": "muddy low-budget set lighting"},
                    "phone_readability": {"score": 2, "evidence": "cheap filter look hides face"},
                }
            },
        }
    ])

    assert action is None


def test_video_refinement_converts_motion_failure_into_repair_action(project_data, tmp_path, monkeypatch):
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
                return {
                    "status": "needs_review",
                    "average": 2.5,
                    "batches": [{
                        "review": {
                            "story_match": {"score": 4, "evidence": "scene matches"},
                            "composition": {"score": 4, "evidence": "usable framing"},
                            "aesthetic_quality": {"score": 3, "evidence": "motion artifacts weaken polish"},
                            "visual_integrity": {"score": 3, "evidence": "minor warping"},
                            "facial_identity": {"score": 4, "evidence": "face matches"},
                            "identity_consistency": {"score": 4, "evidence": "wardrobe stable"},
                            "temporal_consistency": {"score": 2, "evidence": "stutter and camera jump"},
                            "video_aesthetic_scores": {
                                "skin_texture_stability": {"score": 4, "evidence": "skin stable"},
                                "lighting_consistency": {"score": 4, "evidence": "lighting stable"},
                                "color_grade_consistency": {"score": 4, "evidence": "color stable"},
                                "phone_readability": {"score": 4, "evidence": "face readable"},
                                "motion_smoothness": {"score": 2, "evidence": "stutter"},
                                "background_stability": {"score": 3, "evidence": "background wobbles"},
                                "artifact_absence": {"score": 2, "evidence": "repair scar flickers"},
                            },
                        }
                    }],
                }
            assert payload["repair_action"] == "lower_motion_and_regenerate_video"
            return {
                "status": "passed",
                "average": 4.5,
                "batches": [{
                    "review": {"video_aesthetic_scores": passed_video_aesthetic_scores()}
                }],
            }

    fake_svd = FakeSVD()
    monkeypatch.setattr("src.tasks.video_tasks.GenerationReviewService", FakeReviewService)
    monkeypatch.setattr("src.tasks.video_tasks.settings.GENERATION_VIDEO_CANDIDATES", 1)
    monkeypatch.setattr("src.tasks.video_tasks.settings.GENERATION_VIDEO_REFINEMENT_PASSES", 1)
    monkeypatch.setattr("src.tasks.video_tasks.settings.GENERATION_VIDEO_MIN_SCORE", 4.0)
    monkeypatch.setattr("src.tasks.video_tasks.settings.GENERATION_VIDEO_AESTHETIC_FEATURE_MIN_SCORE", 4.0)
    monkeypatch.setattr("src.tasks.video_tasks.settings.GENERATION_REQUIRE_VIDEO_REVIEW", True)

    _, report = _generate_quality_video_candidates(
        fake_svd, scene, project.id, str(tmp_path / "scene.mp4"), db,
        num_frames=16, fps=8, motion_bucket_id=150, noise_aug_strength=0.08,
    )

    assert len(fake_svd.requests) == 2
    assert fake_svd.requests[1]["motion_bucket_id"] < int(fake_svd.requests[0]["motion_bucket_id"] * 0.72)
    assert fake_svd.requests[1]["noise_aug_strength"] < round(fake_svd.requests[0]["noise_aug_strength"] * 0.6, 4)
    assert report["candidates"][0]["request"]["repair_action"] == "lower_motion_and_regenerate_video"
    assert report["status"] == "passed"


def test_video_repair_generation_expands_quality_budget(project_data, tmp_path, monkeypatch):
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
            return {
                "status": "passed",
                "average": 4.6,
                "batches": [{
                    "review": {
                        "facial_identity": {"score": 5, "evidence": "face matches"},
                        "identity_consistency": {"score": 5, "evidence": "wardrobe stable"},
                        "temporal_consistency": {"score": 5, "evidence": "motion stable"},
                        "video_aesthetic_scores": passed_video_aesthetic_scores(),
                    }
                }],
            }

    fake_svd = FakeSVD()
    monkeypatch.setattr("src.tasks.video_tasks.GenerationReviewService", FakeReviewService)
    monkeypatch.setattr("src.services.generation_quality_policy.settings.GENERATION_VIDEO_CANDIDATES", 2)
    monkeypatch.setattr("src.services.generation_quality_policy.settings.GENERATION_VIDEO_REFINEMENT_PASSES", 0)
    monkeypatch.setattr("src.services.generation_quality_policy.settings.GENERATION_MAX_VIDEO_CANDIDATES", 6)
    monkeypatch.setattr("src.services.generation_quality_policy.settings.GENERATION_REPAIR_VIDEO_CANDIDATE_MULTIPLIER", 2.0)
    monkeypatch.setattr("src.services.generation_quality_policy.settings.GENERATION_REPAIR_EXTRA_REFINEMENT_PASSES", 0)
    monkeypatch.setattr("src.tasks.video_tasks.settings.GENERATION_VIDEO_MIN_SCORE", 4.0)
    monkeypatch.setattr("src.tasks.video_tasks.settings.GENERATION_VIDEO_PLATFORM_MIN_SCORE", 4.0)
    monkeypatch.setattr("src.tasks.video_tasks.settings.GENERATION_VIDEO_AESTHETIC_FEATURE_MIN_SCORE", 4.0)
    monkeypatch.setattr("src.tasks.video_tasks.settings.GENERATION_REQUIRE_VIDEO_REVIEW", True)

    _, report = _generate_quality_video_candidates(
        fake_svd, scene, project.id, str(tmp_path / "scene.mp4"), db,
        num_frames=16, fps=8, motion_bucket_id=150, noise_aug_strength=0.08,
        repair_action="lower_motion_and_regenerate_video",
    )

    assert len(fake_svd.requests) == 6
    assert report["quality_budget"]["candidate_count"] == 6
    assert report["quality_budget"]["reason"] == "repair_generation_budget"
    assert report["quality_budget"]["action_profile"] == "temporal_identity_stabilization"
    assert report["candidates"][0]["request"]["quality_budget"]["repair_action"] == "lower_motion_and_regenerate_video"


def test_video_candidate_selection_prefers_passing_performance_gate(tmp_path, monkeypatch):
    weak = tmp_path / "weak.mp4"
    strong = tmp_path / "strong.mp4"
    weak.write_bytes(b"weak")
    strong.write_bytes(b"strong")
    monkeypatch.setattr("src.tasks.video_tasks.video_candidate_metrics", lambda _path: {"technical_score": 4.5})
    monkeypatch.setattr("src.tasks.video_tasks.settings.GENERATION_REQUIRE_VIDEO_REVIEW", True)
    monkeypatch.setattr("src.tasks.video_tasks.settings.GENERATION_VIDEO_MIN_SCORE", 4.0)
    monkeypatch.setattr("src.tasks.video_tasks.settings.GENERATION_VIDEO_PLATFORM_MIN_SCORE", 4.0)

    final_path, report = _select_best_video_candidate(
        [
            {
                "index": 1,
                "path": str(weak),
                "status": "passed",
                "average": 4.8,
                "platform_score": 4.8,
                "gate_scores": {"facial_identity": 5, "identity_consistency": 5, "temporal_consistency": 5},
                "video_aesthetic_gate": {"status": "passed", "average": 5},
                "video_performance_gate": {
                    "status": "needs_review",
                    "average": 0,
                    "low": {"emotion_readability": {"score": 2, "evidence": "flat acting"}},
                    "missing": [],
                },
                "video_performance_score": 0,
            },
            {
                "index": 2,
                "path": str(strong),
                "status": "passed",
                "average": 4.2,
                "platform_score": 4.2,
                "gate_scores": {"facial_identity": 4.2, "identity_consistency": 4.2, "temporal_consistency": 4.2},
                "video_aesthetic_gate": {"status": "passed", "average": 4.2},
                "video_performance_gate": {"status": "passed", "average": 4.2, "low": {}, "missing": []},
                "video_performance_score": 4.2,
            },
        ],
        str(tmp_path / "final.mp4"),
        tmp_path / "quality.json",
    )

    assert final_path.endswith("final.mp4")
    assert Path(final_path).read_bytes() == b"strong"
    assert report["selected_path"] == str(strong)
    assert report["selected_video_performance_gate"]["status"] == "passed"


def test_video_candidate_report_records_character_sheet_reference(project_data, tmp_path, monkeypatch):
    from PIL import Image
    from src.services.character_identity_service import CharacterIdentityService
    from src.services.character_turnaround_album import CharacterTurnaroundAlbumService, PRODUCTION_TURNAROUND_VIEWS
    from src.utils.storage import storage_manager

    db, project, scene, character, _ = project_data
    monkeypatch.setattr(storage_manager, "base_path", tmp_path / "storage")
    spec = CharacterIdentityService().build_identity_spec("Alice", "lead", project_id=project.id)
    character.appearance = spec["identity_anchor"]
    character.visual_description = json.dumps(spec)
    scene.visual_description = "Alice side profile holding the letter"
    scene.image_path = str(tmp_path / "source.png")
    Image.new("RGB", (32, 32), "white").save(scene.image_path)
    views = {}
    for view, color in zip(PRODUCTION_TURNAROUND_VIEWS, ("red", "orange", "yellow", "green", "blue", "purple", "white", "black")):
        image_path = tmp_path / f"{view}.png"
        Image.new("RGB", (32, 32), color).save(image_path)
        views[view] = str(image_path)
    CharacterTurnaroundAlbumService().freeze_album(character, views)
    db.commit()

    class FakeSVD:
        def generate_video(self, **kwargs):
            Path(kwargs["output_path"]).write_bytes(b"video")
            return kwargs["output_path"]

    class FakeReviewService:
        def review_video(self, _video, payload, _report_path, _reference=None):
            assert "Character sheet contract" in payload["character_sheet_contract"]
            assert payload["character_sheet_references"][0]["view"] == "side"
            assert "motion_smoothness" in payload["platform_aesthetic_contract"]["video_features"]
            return {
                "status": "passed",
                "average": 4.6,
                "batches": [{"review": {"video_aesthetic_scores": passed_video_aesthetic_scores()}}],
            }

    monkeypatch.setattr("src.tasks.video_tasks.GenerationReviewService", FakeReviewService)
    monkeypatch.setattr("src.tasks.video_tasks.settings.GENERATION_VIDEO_CANDIDATES", 1)
    monkeypatch.setattr("src.tasks.video_tasks.settings.GENERATION_VIDEO_REFINEMENT_PASSES", 0)
    monkeypatch.setattr("src.tasks.video_tasks.settings.GENERATION_VIDEO_MIN_SCORE", 4.0)
    monkeypatch.setattr("src.tasks.video_tasks.settings.GENERATION_VIDEO_AESTHETIC_FEATURE_MIN_SCORE", 4.0)
    monkeypatch.setattr("src.tasks.video_tasks.settings.GENERATION_REQUIRE_VIDEO_REVIEW", True)

    _, report = _generate_quality_video_candidates(
        FakeSVD(), scene, project.id, str(tmp_path / "scene.mp4"), db,
        num_frames=16, fps=8, motion_bucket_id=127, noise_aug_strength=0.02,
    )

    candidate = report["candidates"][0]
    assert candidate["request"]["character_sheet_references"][0]["view"] == "side"
    assert candidate["request"]["character_sheet_references"][0]["path"] == views["side"]
    assert "motion_smoothness" in candidate["request"]["platform_aesthetic_contract"]["video_features"]


def test_final_normalized_video_is_reviewed_before_acceptance(project_data, tmp_path, monkeypatch):
    db, project, scene, _, _ = project_data
    scene.image_path = str(tmp_path / "source.png")
    video = tmp_path / "scene.mp4"
    Path(scene.image_path).write_bytes(b"image")
    video.write_bytes(b"video")
    db.commit()

    class FakeReviewService:
        def review_video(self, _video, payload, _report_path, _reference=None):
            assert payload["final_stage"] == "postprocess_normalized_clip"
            return {
                "status": "passed",
                "average": 4.6,
                "batches": [{
                    "review": {
                        "facial_identity": {"score": 5, "evidence": "face matches"},
                        "identity_consistency": {"score": 5, "evidence": "wardrobe stable"},
                        "temporal_consistency": {"score": 5, "evidence": "motion stable"},
                        "video_aesthetic_scores": passed_video_aesthetic_scores(),
                    }
                }],
            }

    monkeypatch.setattr("src.tasks.video_tasks.GenerationReviewService", FakeReviewService)
    monkeypatch.setattr("src.tasks.video_tasks.settings.GENERATION_REQUIRE_VIDEO_REVIEW", True)

    report = _review_final_video_after_postprocess(
        str(video),
        scene,
        project.id,
        db,
        quality_report={"kind": "video_candidate_selection", "status": "passed"},
    )

    assert report["final_video_review"]["status"] == "passed"
    assert report["final_video_review"]["video_aesthetic_gate"]["status"] == "passed"
    assert json.loads(video.with_suffix(".quality.json").read_text(encoding="utf-8"))["final_video_review"]["status"] == "passed"


def test_final_normalized_video_review_blocks_flat_performance(project_data, tmp_path, monkeypatch):
    db, project, scene, _, _ = project_data
    scene.image_path = str(tmp_path / "source.png")
    video = tmp_path / "scene.mp4"
    Path(scene.image_path).write_bytes(b"image")
    video.write_bytes(b"video")
    db.commit()

    class FakeReviewService:
        def review_video(self, _video, _payload, _report_path, _reference=None):
            return {
                "status": "passed",
                "average": 4.6,
                "batches": [{
                    "review": {
                        "facial_identity": {"score": 5, "evidence": "face matches"},
                        "identity_consistency": {"score": 5, "evidence": "wardrobe stable"},
                        "temporal_consistency": {"score": 5, "evidence": "motion stable"},
                        "video_aesthetic_scores": passed_video_aesthetic_scores(),
                        "video_performance_scores": {
                            "emotion_readability": {"score": 2, "evidence": "flat acting and unreadable emotion"},
                            "gaze_intent": {"score": 3, "evidence": "dead eyes"},
                            "dialogue_reaction": {"score": 2, "evidence": "no reaction to dialogue"},
                            "body_language": {"score": 4, "evidence": "posture is readable"},
                            "action_intent": {"score": 4, "evidence": "gesture is readable"},
                        },
                    }
                }],
            }

    shot_plan = VideoShotPlan(
        shot_role="dialogue_reaction",
        action_intensity="low",
        target_duration_seconds=4.0,
        fps=8,
        num_frames=32,
        motion_bucket_id=96,
        noise_aug_strength=0.012,
        director_prompt="dialogue reaction",
        end_frame_prompt="end frame",
        negative_prompt="identity drift",
        notes=[],
    )
    monkeypatch.setattr("src.tasks.video_tasks.GenerationReviewService", FakeReviewService)
    monkeypatch.setattr("src.tasks.video_tasks.settings.GENERATION_REQUIRE_VIDEO_REVIEW", True)
    monkeypatch.setattr("src.tasks.video_tasks.settings.GENERATION_VIDEO_PERFORMANCE_MIN_SCORE", 4.0)

    with pytest.raises(ReviewError, match="Final normalized video failed"):
        _review_final_video_after_postprocess(
            str(video),
            scene,
            project.id,
            db,
            quality_report={"kind": "video_candidate_selection", "status": "passed"},
            shot_plan=shot_plan,
        )

    report = json.loads(video.with_suffix(".quality.json").read_text(encoding="utf-8"))
    assert report["final_video_review"]["video_performance_gate"]["status"] == "needs_review"
    assert report["repair_queue"][0]["action"] == "regenerate_video_with_performance_direction"


def test_final_normalized_video_review_blocks_temporal_regression(project_data, tmp_path, monkeypatch):
    db, project, scene, _, _ = project_data
    scene.image_path = str(tmp_path / "source.png")
    video = tmp_path / "scene.mp4"
    Path(scene.image_path).write_bytes(b"image")
    video.write_bytes(b"video")
    db.commit()

    class FakeReviewService:
        def review_video(self, _video, _payload, _report_path, _reference=None):
            return {
                "status": "needs_review",
                "average": 2.8,
                "batches": [{
                    "review": {
                        "facial_identity": {"score": 5, "evidence": "face matches"},
                        "identity_consistency": {"score": 5, "evidence": "wardrobe stable"},
                        "temporal_consistency": {"score": 2, "evidence": "normalized clip stutters and camera jumps"},
                        "video_aesthetic_scores": {
                            "skin_texture_stability": {"score": 4, "evidence": "skin stable"},
                            "lighting_consistency": {"score": 4, "evidence": "lighting stable"},
                            "color_grade_consistency": {"score": 4, "evidence": "color stable"},
                            "phone_readability": {"score": 4, "evidence": "face readable"},
                            "motion_smoothness": {"score": 2, "evidence": "stutter after padding"},
                            "background_stability": {"score": 3, "evidence": "background jumps"},
                            "artifact_absence": {"score": 4, "evidence": "no scars"},
                        },
                    }
                }],
            }

    monkeypatch.setattr("src.tasks.video_tasks.GenerationReviewService", FakeReviewService)
    monkeypatch.setattr("src.tasks.video_tasks.settings.GENERATION_REQUIRE_VIDEO_REVIEW", True)
    monkeypatch.setattr("src.tasks.video_tasks.settings.GENERATION_VIDEO_MIN_SCORE", 4.0)
    monkeypatch.setattr("src.tasks.video_tasks.settings.GENERATION_VIDEO_TEMPORAL_MIN_SCORE", 4.0)
    monkeypatch.setattr("src.tasks.video_tasks.settings.GENERATION_VIDEO_AESTHETIC_FEATURE_MIN_SCORE", 4.0)

    with pytest.raises(ReviewError, match="Final normalized video failed"):
        _review_final_video_after_postprocess(
            str(video),
            scene,
            project.id,
            db,
            quality_report={"kind": "video_candidate_selection", "status": "passed"},
        )

    report = json.loads(video.with_suffix(".quality.json").read_text(encoding="utf-8"))
    assert report["status"] == "needs_review"
    assert report["final_video_review"]["status"] == "needs_review"
    assert report["repair_queue"][0]["action"] == "lower_motion_and_regenerate_video"


def test_comfy_video_generator_uses_scene_prompt_and_reference(project_data, tmp_path):
    _, project, scene, _, _ = project_data
    from src.services.visual_style_assets import VisualStyleAssetService
    VisualStyleAssetService().freeze_project_style(
        project,
        [scene],
        style_prompt="premium red-and-teal mobile drama look",
        negative_prompt="random color grade",
    )
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
    shot_plan = VideoShotPlan(
        shot_role="emotion_reaction",
        action_intensity="low",
        target_duration_seconds=4.2,
        fps=8,
        num_frames=34,
        motion_bucket_id=92,
        noise_aug_strength=0.012,
        director_prompt="directed emotional reaction",
        end_frame_prompt="end frame emotional reaction",
        negative_prompt="identity drift",
        notes=[],
    )

    result = _ComfyVideoGenerator(scene, provider, shot_plan).with_end_image(str(tmp_path / "end.png")).generate_video(
        image_path=str(tmp_path / "source.png"),
        output_path=str(output),
        num_frames=16,
        fps=8,
        motion_bucket_id=120,
        noise_aug_strength=0.02,
    )

    assert result == str(output)
    assert provider.request.prompt == "directed emotional reaction"
    assert "identity drift" in provider.request.negative_prompt
    assert "random color grade" in provider.request.negative_prompt
    assert "plastic skin" in provider.request.negative_prompt
    assert provider.request.reference_image.endswith("source.png")
    assert provider.request.end_image.endswith("end.png")
    assert provider.request.duration_seconds == 4.2
    assert provider.request.aspect_ratio == "4:7"
    assert provider.request.fps == 8
    assert provider.request.motion_bucket_id == 120
    assert provider.request.noise_aug_strength == 0.02


def test_comfy_video_generator_applies_performance_repair_prompt(project_data, tmp_path):
    _, _, scene, _, _ = project_data

    class FakeProvider:
        def __init__(self):
            self.request = None

        def generate_video(self, request):
            self.request = request
            Path(request.output_path).write_bytes(b"comfy-video")
            return GenerationResult("local_comfyui", request.output_path, "video", {})

    provider = FakeProvider()
    shot_plan = VideoShotPlan(
        shot_role="dialogue_reaction",
        action_intensity="low",
        target_duration_seconds=4.0,
        fps=8,
        num_frames=32,
        motion_bucket_id=92,
        noise_aug_strength=0.012,
        director_prompt="directed dialogue reaction",
        end_frame_prompt="end frame",
        negative_prompt="identity drift",
        notes=[],
    )

    _ComfyVideoGenerator(scene, provider, shot_plan).with_repair_action(
        "regenerate_video_with_performance_direction"
    ).generate_video(
        image_path=str(tmp_path / "source.png"),
        output_path=str(tmp_path / "scene.mp4"),
        num_frames=16,
        fps=8,
        motion_bucket_id=120,
        noise_aug_strength=0.02,
    )

    assert "Strengthen short-drama acting performance" in provider.request.prompt
    assert "visible reaction to dialogue" in provider.request.prompt
    assert "flat acting" in provider.request.negative_prompt
    assert "dead eyes" in provider.request.negative_prompt
    assert "identity drift" in provider.request.negative_prompt


def test_video_generator_routes_external_provider_instead_of_svd(project_data, monkeypatch):
    _, _, scene, _, _ = project_data
    shot_plan = get_video_director_service().plan_scene(scene)

    class FakeProvider:
        name = GenerationProviderName.HTTP_VIDEO_API

        def generate_video(self, _request):
            return GenerationResult("http_video_api", "out.mp4", "video", {})

    monkeypatch.setattr("src.tasks.video_tasks.get_generation_provider", lambda provider_name: FakeProvider())
    monkeypatch.setattr("src.tasks.video_tasks.get_svd_service", lambda: (_ for _ in ()).throw(AssertionError("SVD should not be used")))

    generator = _build_video_generator(scene, shot_plan, "http_video_api", "end.png")

    assert isinstance(generator, _ComfyVideoGenerator)
    assert generator.provider.name == GenerationProviderName.HTTP_VIDEO_API


def test_video_generator_uses_svd_for_local_comfy_without_workflow(project_data, monkeypatch):
    _, _, scene, _, _ = project_data
    shot_plan = get_video_director_service().plan_scene(scene)
    fake_svd = object()
    monkeypatch.setattr("src.tasks.video_tasks.settings.COMFYUI_VIDEO_WORKFLOW_PATH", "")
    monkeypatch.setattr("src.tasks.video_tasks.get_svd_service", lambda: fake_svd)

    generator = _build_video_generator(scene, shot_plan, "local_comfyui", None)

    assert generator is fake_svd


def test_video_aspect_ratio_is_derived_from_generation_size():
    assert _aspect_ratio_for_size(768, 1344) == "4:7"
    assert _aspect_ratio_for_size(1344, 768) == "7:4"
    assert _aspect_ratio_for_size(0, 768) == "unknown"


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
                "composition": {"score": 2 if index == 1 else 5, "evidence": "face is cropped and lighting is muddy" if index == 1 else "strong framing"},
                "aesthetic_quality": {"score": 2 if index == 1 else 5, "evidence": "cheap filter look" if index == 1 else "commercial lighting"},
                "visual_integrity": {"score": 2 if index == 1 else 5, "evidence": "broken rendering" if index == 1 else "clean render"},
                "facial_identity": {"score": 4, "evidence": "face matches"},
                "identity_consistency": {"score": 4, "evidence": "wardrobe stable"},
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


def test_image_candidate_report_records_reference_contract(tmp_path, monkeypatch):
    from PIL import Image
    from src.services.generation_provider import ImageGenerationRequest, GenerationResult

    class FakeProvider:
        name = GenerationProviderName.LOCAL_COMFYUI

        def __init__(self):
            self.requests = []

        def generate_image(self, request):
            self.requests.append(request)
            Image.new("RGB", (request.width, request.height), (120, 120, 120)).save(request.output_path)
            return GenerationResult("local_comfyui", request.output_path, "image", {"workflow": {"steps": request.steps}})

    def fake_review(self, index, image_path, scene, prompt, reference_image=None):
        scene["review_prompt"] = prompt
        return {
            "index": index,
            "path": image_path,
            "status": "passed",
            "average": 4.6,
            "review": {},
            "metrics": {"technical_score": 4.6},
        }

    monkeypatch.setattr("src.tasks.image_tasks.ImageQualitySelector.review_candidate", fake_review)
    monkeypatch.setattr("src.tasks.image_tasks.settings.GENERATION_IMAGE_CANDIDATES", 1)
    monkeypatch.setattr("src.tasks.image_tasks.settings.GENERATION_IMAGE_REFINEMENT_PASSES", 0)
    monkeypatch.setattr("src.tasks.image_tasks.settings.GENERATION_IMAGE_MIN_SCORE", 4.0)
    monkeypatch.setattr("src.tasks.image_tasks.settings.GENERATION_REQUIRE_IMAGE_REVIEW", False)
    reference = str(tmp_path / "side.png")
    Image.new("RGB", (32, 32), (20, 120, 20)).save(reference)
    request = ImageGenerationRequest(
        prompt="short drama side profile keyframe",
        negative_prompt="blurry",
        output_path=str(tmp_path / "scene.png"),
        width=512,
        height=512,
        steps=28,
        cfg_scale=6.0,
        seed=123,
        reference_image=reference,
        use_ipadapter=True,
    )
    scene_payload = {
        "scene_number": 1,
        "character_sheet_contract": "Character sheet contract: Alice character-sheet reference view=side; strict side profile",
        "character_sheet_references": [{
            "name": "Alice",
            "view": "side",
            "path": reference,
            "expected_features": {"nose_silhouette": "straight nose bridge"},
        }],
        "visible_characters": [{
            "name": "Alice",
            "appearance": "Alice identity",
            "turnaround_reference": {
                "view": "side",
                "path": reference,
                "expected_features": {"nose_silhouette": "straight nose bridge"},
            },
        }],
        "platform_aesthetic_contract": {
            "prompt": "Platform aesthetic contract: premium mobile short-drama finish",
            "negative_prompt": "AI generated gloss, plastic skin",
            "image_features": ["skin_texture", "phone_readability"],
            "video_features": ["motion_smoothness"],
            "review_instruction": "score platform polish",
        },
    }

    provider = FakeProvider()
    _, report = _generate_quality_candidates(provider, request, scene_payload, reference)

    candidate = report["candidates"][0]
    assert candidate["request"]["reference_image"] == reference
    assert candidate["request"]["use_ipadapter"] is True
    assert candidate["request"]["character_sheet_references"][0]["view"] == "side"
    assert candidate["request"]["identity_contrast_matrix"] == {}
    assert candidate["request"]["platform_aesthetic_contract"]["image_features"] == ["skin_texture", "phone_readability"]
    assert "Platform aesthetic contract: premium mobile short-drama finish" in scene_payload["review_prompt"]
    assert "Character sheet contract" in scene_payload["review_prompt"]
    assert "AI generated gloss" in provider.requests[0].negative_prompt
    assert "plastic skin" in provider.requests[0].negative_prompt
    assert candidate["scene"]["visible_characters"][0]["turnaround_reference"]["view"] == "side"
    assert candidate["scene"]["platform_aesthetic_contract"]["review_instruction"] == "score platform polish"
    assert candidate["scene"]["visible_characters"][0]["turnaround_reference"]["expected_features"]["nose_silhouette"] == "straight nose bridge"


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


def test_review_feedback_reads_nested_aesthetic_gate_evidence():
    feedback = _review_feedback([
        {
            "average": 2,
            "review": {
                "platform_aesthetic_scores": {
                    "skin_texture": {"score": 2, "evidence": "plastic skin"},
                    "lighting_quality": {"score": 2, "evidence": "muddy light"},
                },
            },
            "platform_aesthetic_gate": {
                "low": {
                    "production_polish": {"score": 2, "evidence": "low production value"},
                }
            },
        }
    ])

    assert "plastic skin" in feedback
    assert "muddy light" in feedback
    assert "production_polish: low production value" in feedback
    assert "low production value" in feedback


def test_feedback_repair_directive_maps_aesthetic_evidence_to_generation_strategy():
    prompt, negative = _feedback_repair_directive(
        "skin_texture: plastic skin; lighting_quality: muddy light; phone_readability: tiny unreadable face"
    )

    assert "natural skin texture" in prompt
    assert "controlled soft key light" in prompt
    assert "phone-readable face" in prompt
    assert "plastic skin" in negative
    assert "muddy lighting" in negative
    assert "tiny face" in negative


def test_feedback_repair_directive_maps_seed_dance_profile_defects():
    prompt, negative = _feedback_repair_directive(
        "AI generated gloss; wax museum face; messy wardrobe; low-budget set dressing"
    )

    assert "natural skin texture" in prompt
    assert "styled but believable wardrobe" in prompt
    assert "AI generated gloss" in negative
    assert "messy wardrobe" in negative


def test_repair_action_from_reports_promotes_auto_image_repair():
    action = _repair_action_from_reports([
        {
            "average": 2,
            "review": {
                "composition": {"score": 2, "evidence": "bad crop on the main actor"},
                "aesthetic_quality": {"score": 2, "evidence": "cheap filter look"},
            },
            "platform_aesthetic_gate": {
                "low": {
                    "production_polish": {"score": 2, "evidence": "low production value"},
                }
            },
        }
    ])

    assert action == "refine_prompt_composition"


def test_quality_refinement_converts_review_failure_into_repair_action(tmp_path, monkeypatch):
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

    def fake_review(self, index, image_path, scene, prompt, reference_image=None):
        if index == 1:
            return {
                "index": index,
                "path": image_path,
                "status": "needs_review",
                "average": 2.0,
                "review": {
                    "composition": {"score": 2, "evidence": "bad crop on the main actor"},
                    "aesthetic_quality": {"score": 2, "evidence": "cheap filter look"},
                    "visual_integrity": {"score": 3, "evidence": "render is usable but weak"},
                    "facial_identity": {"score": 4, "evidence": "face matches"},
                    "identity_consistency": {"score": 4, "evidence": "wardrobe stable"},
                    "issues": [],
                },
                "metrics": {"technical_score": 2.0},
            }
        return {
            "index": index,
            "path": image_path,
            "status": "passed",
            "average": 4.6,
            "review": {
                "composition": {"score": 5, "evidence": "strong framing"},
                "aesthetic_quality": {"score": 5, "evidence": "commercial lighting"},
                "visual_integrity": {"score": 5, "evidence": "clean render"},
                "facial_identity": {"score": 4, "evidence": "face matches"},
                "identity_consistency": {"score": 4, "evidence": "wardrobe stable"},
                "issues": [],
            },
            "metrics": {"technical_score": 4.6},
        }

    fake_provider = FakeProvider()
    monkeypatch.setattr("src.tasks.image_tasks.ImageQualitySelector.review_candidate", fake_review)
    monkeypatch.setattr("src.tasks.image_tasks.settings.GENERATION_IMAGE_CANDIDATES", 1)
    monkeypatch.setattr("src.tasks.image_tasks.settings.GENERATION_IMAGE_REFINEMENT_PASSES", 1)
    monkeypatch.setattr("src.tasks.image_tasks.settings.GENERATION_IMAGE_MIN_SCORE", 4.0)
    monkeypatch.setattr("src.tasks.image_tasks.settings.GENERATION_REQUIRE_IMAGE_REVIEW", False)
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

    _, report = _generate_quality_candidates(fake_provider, request, {"scene_number": 1}, None)

    repaired_request = fake_provider.requests[1]
    repaired_candidate = report["candidates"][0]
    assert "balanced composition" in repaired_request.prompt
    assert "cinematic lighting" in repaired_request.prompt
    assert "tasteful commercial color grade" in repaired_request.prompt
    assert "bad crop" in repaired_request.negative_prompt
    assert "cheap filter look" in repaired_request.negative_prompt
    assert repaired_candidate["request"]["repair_action"] == "refine_prompt_composition"
    assert repaired_candidate["request"]["repair_parameter_profile"]["reason"] == "composition_aesthetic_repair"


def test_append_terms_does_not_duplicate_terms():
    assert _append_terms("blurry, bad crop", "bad crop, watermark") == "blurry, bad crop, watermark"


def test_image_repair_action_adds_targeted_generation_constraints():
    prompt, negative = _apply_image_repair_action(
        "short drama close-up",
        "blurry",
        "regenerate_keyframe_with_prop_constraints",
    )

    assert "readable hands" in prompt
    assert "stable prop color" in prompt
    assert "broken fingers" in negative
    assert "disappearing prop" in negative


def test_image_composition_repair_adds_commercial_framing_constraints():
    prompt, negative = _apply_image_repair_action(
        "short drama still",
        "blurry",
        "refine_prompt_composition",
    )

    assert "balanced composition" in prompt
    assert "cinematic lighting" in prompt
    assert "bad crop" in negative
    assert "low production value" in negative


def test_image_face_aesthetic_repair_adds_natural_skin_constraints():
    prompt, negative = _apply_image_repair_action(
        "short drama close-up",
        "blurry",
        "refine_face_aesthetic_detail",
    )

    assert "natural skin texture with subtle pores" in prompt
    assert "clean catchlights" in prompt
    assert "plastic skin" in negative
    assert "AI generated gloss" in negative
    assert "cheap beauty filter" in negative
    profile = _repair_parameter_profile("refine_face_aesthetic_detail")
    assert profile["reason"] == "face_aesthetic_detail_repair"
    steps, cfg = _quality_parameters(1, 0, 40, 6.0, "refine_face_aesthetic_detail")
    assert steps > 40
    assert cfg < 6.0


def test_image_identity_lock_repair_adds_character_sheet_constraints():
    prompt, negative = _apply_image_repair_action(
        "short drama close-up",
        "blurry",
        "regenerate_keyframe_with_identity_lock",
    )

    assert "lock the approved character-sheet identity" in prompt
    assert "preserve exact face geometry" in prompt
    assert "wardrobe color and silhouette" in prompt
    assert "wrong view angle" in negative
    assert "same-face cast" in negative


def test_unknown_image_repair_action_keeps_prompt_unchanged():
    assert _apply_image_repair_action("prompt", "negative", "unknown_action") == ("prompt", "negative")


def test_video_repair_action_lowers_motion_and_noise():
    motion, noise = _apply_video_repair_action(150, 0.08, "lower_motion_and_regenerate_video")

    assert motion == 87
    assert noise == 0.036


def test_video_repair_action_raises_motion_floor():
    motion, noise = _apply_video_repair_action(120, 0.02, "increase_motion_and_regenerate_video")

    assert motion == 146
    assert noise == 0.026


def test_video_repair_action_raises_performance_direction_slightly():
    motion, noise = _apply_video_repair_action(120, 0.02, "regenerate_video_with_performance_direction")

    assert motion == 129
    assert noise == 0.024


def test_video_repair_action_from_candidates_detects_flat_performance():
    action = _video_repair_action_from_candidates([
        {
            "index": 1,
            "status": "needs_review",
            "average": 4.4,
            "scene": {"scene_number": 1},
            "video_performance_gate": {
                "status": "needs_review",
                "low": {
                    "emotion_readability": {"score": 2, "evidence": "flat acting and unreadable emotion"},
                    "dialogue_reaction": {"score": 2, "evidence": "no reaction to dialogue"},
                },
                "missing": [],
            },
        }
    ])

    assert action == "regenerate_video_with_performance_direction"


def test_unknown_video_repair_action_keeps_parameters_unchanged():
    assert _apply_video_repair_action(150, 0.08, "manual_review") == (150, 0.08)


def test_unknown_video_repair_prompt_keeps_text_unchanged():
    assert _apply_video_repair_prompt("prompt", "negative", "manual_review") == ("prompt", "negative")
