"""Real-ffmpeg smoke tests for the video composer."""

import shutil
import subprocess
from pathlib import Path

import pytest
import numpy as np

from src.services.video_composer import VideoComposer, VideoComposerError


def _make_clip(path: Path, *, with_audio: bool = True) -> Path:
    command = [
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
        "-f", "lavfi", "-i", "testsrc=size=160x96:rate=12:duration=1",
    ]
    if with_audio:
        command += ["-f", "lavfi", "-i", "sine=frequency=440:duration=1"]
    command += ["-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p"]
    if with_audio:
        command += ["-c:a", "aac"]
    command += ["-shortest", str(path)]
    subprocess.run(command, check=True)
    return path


@pytest.fixture()
def require_ffmpeg():
    if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
        pytest.skip("ffmpeg/ffprobe are required")


def test_concat_videos_produces_playable_output(tmp_path, require_ffmpeg):
    clips = [_make_clip(tmp_path / f"clip{index}.mp4") for index in range(2)]
    output = tmp_path / "concat.mp4"

    result = VideoComposer().concat_videos([str(clip) for clip in clips], str(output))

    assert Path(result) == output
    assert output.is_file() and output.stat().st_size > 0
    assert VideoComposer()._get_duration(str(output)) == pytest.approx(2.0, abs=0.3)


def test_audio_stream_detection_on_real_clips(tmp_path, require_ffmpeg):
    with_audio = _make_clip(tmp_path / "with-audio.mp4", with_audio=True)
    without_audio = _make_clip(tmp_path / "silent.mp4", with_audio=False)
    composer = VideoComposer()

    assert composer.has_audio_stream(str(with_audio)) is True
    assert composer.has_audio_stream(str(without_audio)) is False


def _make_audio(path: Path, seconds: float = 1.0, frequency: int = 330) -> Path:
    subprocess.run(
        [
            "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
            "-f", "lavfi", "-i", f"sine=frequency={frequency}:duration={seconds}",
            str(path),
        ],
        check=True,
    )
    return path


def test_concat_audio_reencodes_wav_inputs_to_mp3(tmp_path, require_ffmpeg):
    audio = [_make_audio(tmp_path / f"a{index}.wav") for index in range(2)]
    output = tmp_path / "merged.mp3"

    result = VideoComposer()._concat_audio([str(path) for path in audio], str(output))

    assert Path(result) == output
    assert output.is_file() and output.stat().st_size > 0
    assert VideoComposer()._get_duration(str(output)) == pytest.approx(2.0, abs=0.3)


def test_compose_video_end_to_end_keeps_audio(tmp_path, require_ffmpeg):
    clips = [_make_clip(tmp_path / f"clip{index}.mp4") for index in range(2)]
    audio = [_make_audio(tmp_path / f"a{index}.wav") for index in range(2)]
    bgm = _make_audio(tmp_path / "bgm.mp3", seconds=2.0, frequency=220)
    output = tmp_path / "final.mp4"

    result = VideoComposer().compose_video(
        [str(clip) for clip in clips],
        [str(path) for path in audio],
        bgm_path=str(bgm),
        output_path=str(output),
    )

    assert Path(result) == output
    assert output.is_file() and output.stat().st_size > 0
    composer = VideoComposer()
    assert composer._get_duration(str(output)) == pytest.approx(2.0, abs=0.4)
    assert composer.has_audio_stream(str(output)) is True


def test_compose_scene_audio_pads_segments_to_timeline(tmp_path, require_ffmpeg):
    first = _make_audio(tmp_path / "a0.wav", seconds=1.0)
    second = _make_audio(tmp_path / "a1.wav", seconds=1.2)
    output = tmp_path / "scene.wav"

    result = VideoComposer().compose_scene_audio(
        [(str(first), 2.0), (str(second), 1.5)],
        str(output),
    )

    assert Path(result) == output
    assert output.is_file() and output.stat().st_size > 0
    assert VideoComposer()._get_duration(str(output)) == pytest.approx(3.5, abs=0.15)


def test_compose_scene_audio_applies_crossfade_overlap(tmp_path, require_ffmpeg):
    first = _make_audio(tmp_path / "a0.wav", seconds=1.0)
    second = _make_audio(tmp_path / "a1.wav", seconds=1.2)
    output = tmp_path / "scene-crossfade.wav"

    result = VideoComposer().compose_scene_audio(
        [(str(first), 2.0), (str(second), 1.5)],
        str(output),
        editing_plan=[{}, {"transition": {"video": "crossfade", "duration_seconds": 0.1}}],
    )

    assert Path(result) == output
    duration = VideoComposer()._get_duration(str(output))
    assert 3.3 <= duration <= 3.5


def test_sync_audio_video_pads_short_dialogue(tmp_path, require_ffmpeg):
    video = _make_clip(tmp_path / "video.mp4", with_audio=False)
    dialogue = _make_audio(tmp_path / "short.wav", seconds=0.8)
    output = tmp_path / "synced.mp4"

    result = VideoComposer().sync_audio_video(str(video), str(dialogue), str(output))

    assert Path(result) == output
    composer = VideoComposer()
    assert composer._get_duration(str(output)) == pytest.approx(1.0, abs=0.2)
    assert composer.has_audio_stream(str(output)) is True


def test_sync_audio_video_rejects_dialogue_longer_than_video(tmp_path, require_ffmpeg):
    video = _make_clip(tmp_path / "video.mp4", with_audio=False)
    dialogue = _make_audio(tmp_path / "long.wav", seconds=3.0)

    with pytest.raises(VideoComposerError, match="longer than the video"):
        VideoComposer().sync_audio_video(
            str(video), str(dialogue), str(tmp_path / "synced.mp4")
        )


def test_add_bgm_without_dialogue_source(tmp_path, require_ffmpeg):
    video = _make_clip(tmp_path / "silent.mp4", with_audio=False)
    bgm = _make_audio(tmp_path / "bgm.mp3", seconds=1.0, frequency=220)
    output = tmp_path / "with-bgm.mp4"

    result = VideoComposer().add_bgm(str(video), str(bgm), str(output))

    assert Path(result) == output
    composer = VideoComposer()
    assert composer._get_duration(str(output)) == pytest.approx(1.0, abs=0.3)
    assert composer.has_audio_stream(str(output)) is True


def _beep_onsets(path: Path) -> list[float]:
    decoded = subprocess.run(
        ["ffmpeg", "-v", "error", "-i", str(path), "-map", "0:a:0",
         "-ac", "1", "-ar", "48000", "-f", "f32le", "pipe:1"],
        capture_output=True, check=True,
    )
    samples = np.frombuffer(decoded.stdout, dtype="<f4")
    window = 240  # 5ms envelopes ignore zero-crossings without hiding drift.
    levels = np.sqrt(np.mean(samples[:len(samples) // window * window].reshape(-1, window) ** 2, axis=1))
    active = levels > levels.max() * 0.2
    return (np.flatnonzero(active & ~np.r_[False, active[:-1]]) * window / 48000).tolist()


@pytest.mark.parametrize("audio_source", ["separate-dialogue", "native-audio", "short-native-audio"])
def test_dialogue_prelap_is_local_to_each_cut_not_accumulated(tmp_path, require_ffmpeg, monkeypatch, audio_source):
    from src.config import settings

    monkeypatch.setattr(settings, "GENERATION_WIDTH", 160)
    monkeypatch.setattr(settings, "GENERATION_HEIGHT", 96)
    monkeypatch.setattr(settings, "GENERATION_VIDEO_OUTPUT_FPS", 24)
    monkeypatch.setattr(settings, "GENERATION_VIDEO_DIALOGUE_PRELAP_SECONDS", 0.08)
    source = tmp_path / "beep.wav"
    subprocess.run([
        "ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i",
        "aevalsrc=if(between(t\\,0.2\\,0.3)\\,0.4*sin(2*PI*700*t)\\,0):s=48000:d=1",
        str(source),
    ], check=True)
    count = 6
    plan = [{"transition": {"video": "none", "duration_seconds": 0.0}}] + [
        {"audio_strategy": "dialogue_pre_lap", "transition": {"video": "hard_cut", "duration_seconds": 0.0}}
        for _ in range(count - 1)
    ]
    composer = VideoComposer()
    if audio_source != "separate-dialogue":
        clip = _make_clip(tmp_path / "video.mp4", with_audio=False)
        native = tmp_path / "native.mp4"
        mux = [
            "ffmpeg", "-v", "error", "-y", "-i", str(clip), "-i", str(source),
            "-map", "0:v:0", "-map", "1:a:0", "-c:v", "copy", "-c:a", "aac",
        ]
        if audio_source == "short-native-audio":
            mux += ["-af", "atrim=duration=0.8"]
        subprocess.run([*mux, str(native)], check=True)
        output = Path(composer.concat_videos([str(native)] * count, str(tmp_path / "result.mp4"),
                                            preserve_audio=True, editing_plan=plan))
    else:
        output = Path(composer.compose_scene_audio([(str(source), 1.0)] * count,
                                                 str(tmp_path / "result.wav"), editing_plan=plan))
    expected_onsets = [0.2] + [index * 0.999 - 0.079 + 0.2 for index in range(1, count)]
    assert _beep_onsets(output) == pytest.approx(expected_onsets, abs=0.025)
    assert composer._get_duration(str(output)) == pytest.approx(count - (count - 1) * 0.001, abs=0.05)
