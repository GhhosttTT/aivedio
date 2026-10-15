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
