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
