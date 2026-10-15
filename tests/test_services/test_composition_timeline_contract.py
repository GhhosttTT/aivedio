import math
import subprocess
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from src.services.video_composer import VideoComposer, VideoComposerError
from src.tasks.composition_tasks import (
    _require_audio_video_duration_alignment,
    _subtitle_matches_dialogue,
)


def scene(number, dialogue="Wait."):
    return SimpleNamespace(
        scene_number=number, dialogue=dialogue,
        video_path=f"{number}.mp4", audio_path=f"{number}.wav", audio_duration=1.0,
    )


def test_scene_errors_cannot_cancel_each_other_in_the_total_duration():
    composer = Mock()
    composer._get_duration.side_effect = [4.0, 2.0, 2.0, 4.0]
    with pytest.raises(ValueError, match="1: audio/video duration mismatch.*2: audio/video duration mismatch"):
        _require_audio_video_duration_alignment([scene(1), scene(2)], composer)


def test_silent_shot_preserves_its_own_timeline_slot():
    composer = Mock()
    composer._get_duration.side_effect = [4.0, 3.5, 2.0, 3.0, 2.8]
    segments = _require_audio_video_duration_alignment([
        scene(1), scene(2, ""), scene(3),
    ], composer)
    assert segments == [("1.wav", 4.0), (None, 2.0), ("3.wav", 3.0)]


def test_short_video_cannot_cut_dialogue_even_within_old_one_second_tolerance():
    composer = Mock()
    composer._get_duration.side_effect = [3.0, 3.3]
    with pytest.raises(ValueError, match="duration mismatch"):
        _require_audio_video_duration_alignment([scene(1)], composer)


@pytest.mark.parametrize("duration", [0.0, -1.0, math.nan, math.inf])
def test_unreadable_duration_never_reaches_ffmpeg(duration, monkeypatch, tmp_path):
    run = Mock()
    monkeypatch.setattr("src.services.video_composer.subprocess.run", run)
    with pytest.raises(ValueError, match="finite and positive"):
        VideoComposer().compose_scene_audio([(None, duration)], str(tmp_path / "track.wav"))
    run.assert_not_called()


def test_audio_alignment_pads_each_scene_and_inserts_silence(monkeypatch, tmp_path):
    first = tmp_path / "first.wav"
    last = tmp_path / "last.wav"
    first.write_bytes(b"audio")
    last.write_bytes(b"audio")
    composer = VideoComposer()
    monkeypatch.setattr(composer, "_get_duration", lambda _path: 1.0)
    calls = []

    def run(cmd, **kwargs):
        calls.append(cmd)
        Path(cmd[-1]).write_bytes(b"aligned audio")
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr("src.services.video_composer.subprocess.run", run)
    result = composer.compose_scene_audio([
        (str(first), 1.5), (None, 2.0), (str(last), 1.2),
    ], str(tmp_path / "track.wav"))
    assert result == str(tmp_path / "track.wav")
    assert len(calls) == 4
    assert [cmd[cmd.index("-t") + 1] for cmd in calls[:3]] == ["1.500000", "2.000000", "1.200000"]
    assert "anullsrc=r=48000:cl=stereo" in calls[1]
    assert all("pcm_s16le" in cmd for cmd in calls[:3])
    assert not list(tmp_path.glob("scene_audio_*"))
    assert not list(tmp_path.glob("*_concat_list.txt"))


def test_alignment_failure_cleans_temporary_tracks(monkeypatch, tmp_path):
    def fail(cmd, **_kwargs):
        raise subprocess.CalledProcessError(1, cmd, stderr="encoder failed")

    monkeypatch.setattr("src.services.video_composer.subprocess.run", fail)
    with pytest.raises(VideoComposerError, match="encoder failed"):
        VideoComposer().compose_scene_audio([(None, 1.0)], str(tmp_path / "track.wav"))
    assert not list(tmp_path.glob("scene_audio_*"))


def test_short_dialogue_does_not_shorten_the_final_video(monkeypatch, tmp_path):
    video, audio = tmp_path / "video.mp4", tmp_path / "audio.wav"
    video.write_bytes(b"video")
    audio.write_bytes(b"audio")
    composer = VideoComposer()
    monkeypatch.setattr(composer, "_get_duration", Mock(side_effect=[5.0, 4.5]))
    run = Mock()
    monkeypatch.setattr("src.services.video_composer.subprocess.run", run)
    composer.sync_audio_video(str(video), str(audio))
    cmd = run.call_args.args[0]
    assert "-shortest" not in cmd
    assert cmd[cmd.index("-t") + 1] == "5.000000"
    assert "apad" in cmd


def test_incomplete_subtitle_prefix_does_not_pass_full_dialogue_coverage():
    assert not _subtitle_matches_dialogue("1\n00:00:00,000 --> 00:00:01,000\nWait", "Wait. I know the truth.")
    assert _subtitle_matches_dialogue("1\n00:00:00,000 --> 00:00:01,000\nWait!", "Wait.")
