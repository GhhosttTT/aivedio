from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from src.config import settings
from src.services.video_director_service import VideoDirectorService


def test_measured_dialogue_controls_motion_duration(monkeypatch):
    monkeypatch.setattr(settings, "GENERATION_VIDEO_MAX_SECONDS", 6.0)
    monkeypatch.setattr(settings, "GENERATION_VIDEO_MAX_FRAMES", 48)
    monkeypatch.setattr(settings, "GENERATION_VIDEO_MODEL_FPS", 8)
    scene = SimpleNamespace(visual_description="woman looks toward the doorway", image_prompt="a close-up reaction", dialogue="Wait.", audio_duration=4.2)
    plan = VideoDirectorService().plan_scene(scene)
    assert plan.target_duration_seconds >= 4.5
    assert plan.num_frames >= 36
    assert any("measured dialogue" in note for note in plan.notes)


@pytest.mark.parametrize("visual,prompt,role,intensity", [
    ("A handsome man smiles quietly.", "portrait", "emotion_reaction", "low"),
    ("Alice is running toward the gate.", "portrait", "action", "high"),
    ("Alice chased Bob.", "portrait", "action", "high"),
    ("Alice is staring silently.", "portrait", "emotion_reaction", "low"),
    ("Reaction close-up of Bob absorbing the line.", "portrait", "emotion_reaction", "low"),
    ("她打扮精致，微笑着看向对方。", "portrait", "emotion_reaction", "low"),
    ("两人在走廊打斗。", "portrait", "action", "high"),
    ("Alice smiles quietly.", "running shoes, hands visible", "emotion_reaction", "low"),
    ("Alice waits.", "portrait", "dialogue_reaction", "low"),
])
def test_director_classification_uses_action_words(visual, prompt, role, intensity):
    director = VideoDirectorService()
    assert director._shot_role(visual, prompt, "Hello") == role
    assert director._action_intensity(visual, prompt) == intensity


def test_prop_name_does_not_match_part_of_an_unrelated_word():
    director = VideoDirectorService()
    assert director._prop_focus("An occupant waits at the doorway") == ""
    assert director._prop_focus("Alice holds two cups") == "cup"


def test_video_direction_keeps_action_instead_of_static_keyframe_instruction():
    scene = SimpleNamespace(
        visual_description="Alice picks up the letter and turns toward the door.",
        image_prompt="Alice holding a letter, frozen still, one static frame.",
        dialogue="", audio_duration=None,
    )
    plan = VideoDirectorService().plan_scene(scene)
    assert scene.visual_description in plan.director_prompt
    assert "frozen still" not in plan.director_prompt
    assert f"Camera direction: {plan.camera_movement}." in plan.director_prompt


def test_director_keeps_full_dialogue_and_falls_back_when_visual_is_empty():
    line = "Please listen carefully. " * 15 + "Meet me at the station."
    scene = SimpleNamespace(
        visual_description="", image_prompt="Alice at the doorway", dialogue=line,
        audio_duration=None,
    )
    plan = VideoDirectorService().plan_scene(scene)
    assert scene.image_prompt in plan.director_prompt
    assert f'"{line}"' in plan.director_prompt


def test_director_plan_exposes_structured_camera_and_editing_contract():
    scene = SimpleNamespace(
        visual_description="woman cries in close-up",
        image_prompt="a close-up reaction",
        dialogue="Who is there?",
        audio_duration=2.0,
    )
    plan = VideoDirectorService().plan_scene(scene)

    assert plan.framing == "close-up"
    assert "push-in" in plan.camera_movement or "locked" in plan.camera_movement
    assert plan.performance_direction
    assert "cut" in plan.edit_intent
    assert "facial performance and lip timing" in plan.continuity_priorities
    payload = plan.as_dict()
    assert payload["camera_movement"] == plan.camera_movement
    assert payload["edit_intent"] == plan.edit_intent


def test_spatial_plan_preserves_explicit_reverse_shot_positions_and_eyelines():
    director = VideoDirectorService()

    speaker = director._spatial_plan(
        "Clean close-up of Alice at frame left looking screen right.",
        "dialogue_reaction",
        [{"name": "Alice"}],
    )
    listener = director._spatial_plan(
        "Reaction close-up of Bob at frame right looking screen left.",
        "emotion_reaction",
        [{"name": "Bob"}],
    )

    assert speaker["character_positions"] == {"Alice": "frame left"}
    assert speaker["character_eyelines"] == {"Alice": "screen right"}
    assert listener["character_positions"] == {"Bob": "frame right"}
    assert listener["character_eyelines"] == {"Bob": "screen left"}
    assert "Alice eyeline screen right" in speaker["control_references"]["pose_reference_prompt"]
    assert "Bob looks screen left" in listener["continuity_prompt"]


def test_overlong_dialogue_requires_a_split_instead_of_frozen_tail(monkeypatch):
    monkeypatch.setattr(settings, "GENERATION_VIDEO_MAX_SECONDS", 6.0)
    monkeypatch.setattr(settings, "GENERATION_VIDEO_MAX_FRAMES", 40)
    monkeypatch.setattr(settings, "GENERATION_VIDEO_MODEL_FPS", 8)
    scene = SimpleNamespace(visual_description="woman waits", image_prompt="close-up reaction", dialogue="Wait.", audio_duration=5.5)
    with pytest.raises(ValueError, match="split the dialogue"):
        VideoDirectorService().plan_scene(scene)


def test_normalization_cannot_conceal_a_short_generated_video(tmp_path, monkeypatch):
    source = tmp_path / "short.mp4"
    source.write_bytes(b"video")
    director = VideoDirectorService()
    monkeypatch.setattr(settings, "GENERATION_VIDEO_POSTPROCESS", True)
    monkeypatch.setattr(settings, "GENERATION_VIDEO_MAX_FREEZE_SECONDS", 0.2)
    monkeypatch.setattr("src.services.video_director_service.shutil.which", lambda _name: "ffmpeg")
    monkeypatch.setattr(director, "_probe_duration", lambda _path: 2.0)
    run = Mock()
    monkeypatch.setattr("src.services.video_director_service.subprocess.run", run)
    with pytest.raises(ValueError, match="freezing"):
        director.normalize_clip(str(source), str(tmp_path / "final.mp4"), 3.6)
    run.assert_not_called()


def test_failed_normalization_removes_partial_output(tmp_path, monkeypatch):
    source = tmp_path / "source.mp4"
    output = tmp_path / "final.mp4"
    source.write_bytes(b"video")
    output.write_bytes(b"stale partial output")
    director = VideoDirectorService()
    monkeypatch.setattr(settings, "GENERATION_VIDEO_POSTPROCESS", True)
    monkeypatch.setattr("src.services.video_director_service.shutil.which", lambda _name: "ffmpeg")
    monkeypatch.setattr(director, "_probe_duration", lambda _path: 3.6)

    def failed_run(*_args, **_kwargs):
        output.write_bytes(b"new truncated output")
        raise RuntimeError("encoder failed")

    monkeypatch.setattr("src.services.video_director_service.subprocess.run", failed_run)

    assert director.normalize_clip(str(source), str(output), 3.6) == str(source)
    assert not output.exists()


def test_seedance_normalization_preserves_high_bit_depth_provider_output(tmp_path, monkeypatch):
    source = tmp_path / "seedance.mp4"
    source.write_bytes(b"video")
    director = VideoDirectorService()
    monkeypatch.setattr(settings, "GENERATION_VIDEO_POSTPROCESS", True)
    monkeypatch.setattr("src.services.video_director_service.shutil.which", lambda _name: "ffmpeg")
    monkeypatch.setattr(director, "_probe_duration", lambda _path: 5.0)
    monkeypatch.setattr(director, "_probe_pixel_format", lambda _path: "yuv420p10le")
    run = Mock()
    monkeypatch.setattr("src.services.video_director_service.subprocess.run", run)

    result = director.normalize_clip(
        str(source), str(tmp_path / "final.mp4"), 5.0,
        preserve_provider_quality=True,
    )

    command = run.call_args.args[0]
    assert result == str(tmp_path / "final.mp4")
    assert "libx265" in command
    assert "yuv420p10le" in command
    assert "hvc1" in command


def test_seedance_normalization_preserves_mov_chroma_sampling(tmp_path, monkeypatch):
    source = tmp_path / "seedance.mov"
    source.write_bytes(b"video")
    director = VideoDirectorService()
    monkeypatch.setattr(settings, "GENERATION_VIDEO_POSTPROCESS", True)
    monkeypatch.setattr("src.services.video_director_service.shutil.which", lambda _name: "ffmpeg")
    monkeypatch.setattr(director, "_probe_duration", lambda _path: 5.0)
    monkeypatch.setattr(director, "_probe_pixel_format", lambda _path: "yuv444p")
    run = Mock()
    monkeypatch.setattr("src.services.video_director_service.subprocess.run", run)

    director.normalize_clip(
        str(source), str(tmp_path / "final.mov"), 5.0,
        preserve_provider_quality=True,
    )

    command = run.call_args.args[0]
    assert "format=yuv444p" in command[command.index("-vf") + 1]
    assert command[command.index("-pix_fmt") + 1] == "yuv444p"


def test_seedance_normalization_preserves_provider_geometry_and_frame_rate(tmp_path, monkeypatch):
    source = tmp_path / "seedance_1080p.mp4"
    source.write_bytes(b"video")
    director = VideoDirectorService()
    monkeypatch.setattr(settings, "GENERATION_VIDEO_POSTPROCESS", True)
    monkeypatch.setattr("src.services.video_director_service.shutil.which", lambda _name: "ffmpeg")
    monkeypatch.setattr(director, "_probe_duration", lambda _path: 5.0)
    monkeypatch.setattr(director, "_probe_pixel_format", lambda _path: "yuv420p")
    monkeypatch.setattr(director, "_probe_geometry", lambda _path: (1920, 1080, 24.0))
    run = Mock()
    monkeypatch.setattr("src.services.video_director_service.subprocess.run", run)

    director.normalize_clip(
        str(source), str(tmp_path / "final.mp4"), 5.0,
        preserve_provider_quality=True,
    )

    command = run.call_args.args[0]
    filter_arg = command[command.index("-vf") + 1]
    assert "scale=768:1344:force_original_aspect_ratio=decrease" not in filter_arg
    assert "pad=768:1344:(ow-iw)/2:(oh-ih)/2" not in filter_arg
    assert "fps=24" not in filter_arg
    assert "setsar=1" in filter_arg
