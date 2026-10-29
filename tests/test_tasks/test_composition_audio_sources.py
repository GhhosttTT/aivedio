"""Audio repair must replace the delivered dialogue, including native clips."""

import array
import hashlib
import json
import shutil
import subprocess
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from src.tasks.composition_tasks import _composition_audio_plan, _dialogue_fingerprint, composition_input_signature
from src.services.video_composer import VideoComposer
from src.config import settings


def _scene(tmp_path, index):
    audio = tmp_path / f"{index}.wav"
    video = tmp_path / f"{index}.mp4"
    audio.write_bytes(b"approved dialogue")
    video.write_bytes(b"native video")
    return SimpleNamespace(id=index, scene_number=index, dialogue="Wait", character_name="hero",
                           audio_path=str(audio), video_path=str(video), subtitle_path=None, image_path=None)


def _approve(scene, profile="short_drama_repair"):
    from pathlib import Path

    audio = Path(scene.audio_path)
    report = {
        "status": "passed", "audio_path": str(audio),
        "audio_sha256": hashlib.sha256(audio.read_bytes()).hexdigest(),
        "dialogue_fingerprint": _dialogue_fingerprint(scene.dialogue),
        "speaker": scene.character_name,
        "audio_profile": {"profile": profile},
        "dialogue_audio_quality_gate": {"status": "passed"},
    }
    audio.with_suffix(".quality.json").write_text(json.dumps(report), encoding="utf-8")


def test_audio_plan_replaces_repaired_track_and_retains_other_native_tracks(tmp_path):
    scenes = [_scene(tmp_path, index) for index in (1, 2)]
    _approve(scenes[0])
    composer = Mock()
    composer._get_duration.return_value = 1.0
    composer.has_audio_stream.return_value = True

    preserve, segments = _composition_audio_plan(scenes, composer, True)

    assert preserve is False
    assert segments == [(scenes[0].audio_path, 1.0), (scenes[1].video_path, 1.0)]
    composer.has_audio_stream.assert_called_once_with(scenes[1].video_path)


def test_default_tts_reference_does_not_override_native_track(tmp_path):
    scene = _scene(tmp_path, 1)
    _approve(scene, "short_drama_default")
    composer = Mock()
    composer.has_audio_stream.return_value = True
    assert _composition_audio_plan([scene], composer, True) == (True, None)


@pytest.mark.parametrize("native", [True, False])
def test_all_repaired_shots_use_approved_dialogue_without_requiring_old_audio(tmp_path, native):
    scenes = [_scene(tmp_path, index) for index in (1, 2)]
    for scene in scenes:
        _approve(scene)
    composer = Mock()
    composer._get_duration.return_value = 1.0
    composer.has_audio_stream.return_value = False

    preserve, segments = _composition_audio_plan(scenes, composer, native)

    assert preserve is False
    assert segments == [(scene.audio_path, 1.0) for scene in scenes]
    composer.has_audio_stream.assert_not_called()


def test_untouched_native_shot_still_requires_its_audio_stream(tmp_path):
    scenes = [_scene(tmp_path, index) for index in (1, 2)]
    _approve(scenes[0])
    composer = Mock()
    composer._get_duration.return_value = 1.0
    composer.has_audio_stream.return_value = False

    with pytest.raises(ValueError, match="no audio stream"):
        _composition_audio_plan(scenes, composer, True)


@pytest.mark.parametrize("fault", ["stale", "too_long", "failed_gate"])
def test_repaired_audio_cannot_fall_back_to_old_native_dialogue(tmp_path, fault):
    from pathlib import Path

    scene = _scene(tmp_path, 1)
    _approve(scene)
    composer = Mock()
    composer._get_duration.side_effect = lambda path: 2.0 if fault == "too_long" and path == scene.audio_path else 1.0
    if fault == "stale":
        Path(scene.audio_path).write_bytes(b"changed unreviewed audio")
    if fault == "failed_gate":
        report_path = Path(scene.audio_path).with_suffix(".quality.json")
        report = json.loads(report_path.read_text())
        report["dialogue_audio_quality_gate"]["status"] = "needs_review"
        report_path.write_text(json.dumps(report))

    with pytest.raises(ValueError):
        _composition_audio_plan([scene], composer, True)


def test_audio_source_evidence_change_invalidates_composition_approval(tmp_path):
    scene = _scene(tmp_path, 1)
    project = SimpleNamespace(id=1, script="{}", outline="")
    _approve(scene, "short_drama_default")
    before = composition_input_signature(project, [scene])
    _approve(scene)
    assert composition_input_signature(project, [scene]) != before


@pytest.mark.skipif(not shutil.which("ffmpeg") or not shutil.which("ffprobe"), reason="requires FFmpeg")
def test_delivered_video_contains_repaired_dialogue_and_untouched_native_audio(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "GENERATION_WIDTH", 160)
    monkeypatch.setattr(settings, "GENERATION_HEIGHT", 96)
    monkeypatch.setattr(settings, "GENERATION_VIDEO_OUTPUT_FPS", 12)
    scenes = [_scene(tmp_path, index) for index in (1, 2)]
    for scene, frequency in zip(scenes, (440, 660)):
        subprocess.run([
            "ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "color=c=blue:s=160x96:r=12:d=1",
            "-f", "lavfi", "-i", f"sine=frequency={frequency}:duration=1",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", scene.video_path,
        ], check=True)
    subprocess.run([
        "ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "sine=frequency=880:duration=1", scenes[0].audio_path,
    ], check=True)
    _approve(scenes[0])
    composer = VideoComposer()
    preserve, segments = _composition_audio_plan(scenes, composer, True)
    joined = composer.concat_videos([scene.video_path for scene in scenes], str(tmp_path / "joined.mp4"), preserve_audio=preserve)
    audio = composer.compose_scene_audio(segments, str(tmp_path / "dialogue.wav"))
    final = composer.sync_audio_video(joined, audio, str(tmp_path / "final.mp4"))

    for start, expected in ((0.2, 880), (1.2, 660)):
        result = subprocess.run([
            "ffmpeg", "-v", "error", "-i", final, "-ss", str(start), "-t", "0.5",
            "-map", "0:a:0", "-ar", "8000", "-ac", "1", "-f", "s16le", "pipe:1",
        ], capture_output=True, check=True)
        samples = array.array("h", result.stdout)
        crossings = sum(a <= 0 < b for a, b in zip(samples, samples[1:]))
        assert crossings / (len(samples) / 8000) == pytest.approx(expected, abs=10)
