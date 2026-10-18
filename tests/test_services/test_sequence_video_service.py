from pathlib import Path

import pytest

from src.services.sequence_plan import SequenceSegment
from src.services.sequence_video_service import (
    SequenceVideoError,
    _source_is_high_bit_depth,
    split_sequence_video,
)


@pytest.mark.parametrize(
    ("pixel_format", "expected"),
    [("yuv420p", False), ("yuv420p10le", True), ("yuv422p12le", True)],
)
def test_source_bit_depth_is_read_from_structured_ffprobe_output(
    tmp_path, monkeypatch, pixel_format, expected,
):
    source = tmp_path / "sequence.mp4"
    source.write_bytes(b"sequence")
    monkeypatch.setattr(
        "src.services.sequence_video_service.shutil.which",
        lambda _name: "/usr/bin/ffprobe",
    )

    def fake_run(command, **_kwargs):
        assert command[command.index("-of") + 1] == "json"
        return type(
            "Result",
            (),
            {"stdout": '{"streams":[{"pix_fmt":"%s"}]}' % pixel_format},
        )()

    monkeypatch.setattr("src.services.sequence_video_service.subprocess.run", fake_run)
    assert _source_is_high_bit_depth(source) is expected


def test_sequence_split_preserves_provider_chroma_sampling(tmp_path, monkeypatch):
    source = tmp_path / "sequence.mov"
    source.write_bytes(b"sequence")
    output = tmp_path / "scene.mov"
    monkeypatch.setattr("src.services.sequence_video_service.shutil.which", lambda _name: "/usr/bin/ffmpeg")
    monkeypatch.setattr(
        "src.services.sequence_video_service._source_pixel_format",
        lambda _path: "yuv444p",
    )
    monkeypatch.setattr(
        "src.services.sequence_video_service._source_is_high_bit_depth",
        lambda _path: False,
    )
    monkeypatch.setattr("src.services.sequence_video_service._probe_stream_types", lambda _path: {"video"})
    monkeypatch.setattr("src.services.sequence_video_service._probe_duration", lambda _path: 2.0)
    commands = []

    def fake_run(command, **_kwargs):
        commands.append(command)
        if command[0] == "ffmpeg":
            Path(command[-1]).write_bytes(b"segment")

    monkeypatch.setattr("src.services.sequence_video_service.subprocess.run", fake_run)

    split_sequence_video(source, [SequenceSegment(1, 0.0, 2.0)], [output])

    ffmpeg_command = next(command for command in commands if command[0] == "ffmpeg")
    assert ffmpeg_command[ffmpeg_command.index("-pix_fmt") + 1] == "yuv444p"


def test_split_sequence_video_writes_atomic_segments(tmp_path, monkeypatch):
    source = tmp_path / "sequence.mp4"
    source.write_bytes(b"sequence")
    segments = [
        SequenceSegment(1, 0.0, 2.0),
        SequenceSegment(2, 2.0, 5.0),
    ]
    outputs = [tmp_path / "scene_1.mp4", tmp_path / "scene_2.mp4"]
    calls = []

    monkeypatch.setattr("src.services.sequence_video_service.shutil.which", lambda name: "/usr/bin/ffmpeg")

    def fake_run(command, **_kwargs):
        calls.append(command)
        if command[0] == "ffprobe":
            path = str(command[-1])
            duration = "2.0" if "scene_1" in path else "3.0"
            if "/sequence.mp4" in path:
                duration = "5.0"
            return type("Result", (), {"stdout": f"{duration}\n"})()
        Path(command[-1]).write_bytes(b"segment")

    monkeypatch.setattr("src.services.sequence_video_service.subprocess.run", fake_run)

    result = split_sequence_video(source, segments, outputs)

    assert result == [str(path) for path in outputs]
    assert all(path.read_bytes() == b"segment" for path in outputs)
    ffmpeg_calls = [command for command in calls if command[0] == "ffmpeg"]
    assert ffmpeg_calls[0][ffmpeg_calls[0].index("-ss") + 1] == "0.000"
    assert ffmpeg_calls[1][ffmpeg_calls[1].index("-t") + 1] == "3.000"
    assert ffmpeg_calls[0].index("-ss") > ffmpeg_calls[0].index("-i")
    assert ffmpeg_calls[0][ffmpeg_calls[0].index("-c:v") + 1] == "libx264"


def test_split_sequence_video_rejects_overlapping_segments(tmp_path, monkeypatch):
    source = tmp_path / "sequence.mp4"
    source.write_bytes(b"sequence")
    monkeypatch.setattr("src.services.sequence_video_service.shutil.which", lambda name: "/usr/bin/ffmpeg")

    with pytest.raises(SequenceVideoError, match="ordered and non-overlapping"):
        split_sequence_video(
            source,
            [SequenceSegment(1, 0.0, 2.0), SequenceSegment(2, 1.5, 3.0)],
            [tmp_path / "one.mp4", tmp_path / "two.mp4"],
        )


def test_split_sequence_video_rejects_segments_beyond_source_duration(tmp_path, monkeypatch):
    source = tmp_path / "sequence.mp4"
    source.write_bytes(b"video")
    monkeypatch.setattr("src.services.sequence_video_service.shutil.which", lambda name: "/usr/bin/ffmpeg")
    monkeypatch.setattr("src.services.sequence_video_service._probe_duration", lambda _path: 1.0)

    with pytest.raises(SequenceVideoError, match="beyond the generated source duration"):
        split_sequence_video(
            source,
            [SequenceSegment(1, 0.0, 2.0)],
            [tmp_path / "scene.mp4"],
        )


def test_split_sequence_video_requires_ffprobe_for_quality_validation(tmp_path, monkeypatch):
    source = tmp_path / "sequence.mp4"
    source.write_bytes(b"video")
    monkeypatch.setattr("src.services.sequence_video_service.shutil.which", lambda name: "/usr/bin/ffmpeg" if name == "ffmpeg" else None)

    with pytest.raises(SequenceVideoError, match="ffprobe is required"):
        split_sequence_video(
            source,
            [SequenceSegment(1, 0.0, 2.0)],
            [tmp_path / "scene.mp4"],
        )


def test_split_sequence_video_rejects_overlong_segment_output(tmp_path, monkeypatch):
    source = tmp_path / "sequence.mp4"
    source.write_bytes(b"video")
    output = tmp_path / "scene.mp4"
    monkeypatch.setattr("src.services.sequence_video_service.shutil.which", lambda _name: "/usr/bin/ffmpeg")

    def fake_run(command, **_kwargs):
        if command[0] == "ffprobe":
            return type("Result", (), {"stdout": "3.0\n"})()
        Path(command[-1]).write_bytes(b"segment")

    monkeypatch.setattr("src.services.sequence_video_service.subprocess.run", fake_run)

    with pytest.raises(SequenceVideoError, match="duration-drifted"):
        split_sequence_video(
            source,
            [SequenceSegment(1, 0.0, 2.0)],
            [output],
        )
    assert not output.exists()


def test_split_sequence_video_does_not_publish_partial_batch(tmp_path, monkeypatch):
    source = tmp_path / "sequence.mp4"
    source.write_bytes(b"sequence")
    outputs = [tmp_path / "scene_1.mp4", tmp_path / "scene_2.mp4"]
    monkeypatch.setattr("src.services.sequence_video_service.shutil.which", lambda name: "/usr/bin/ffmpeg")
    calls = {"ffmpeg": 0}

    def fake_run(command, **_kwargs):
        if command[0] == "ffprobe":
            path = str(command[-1])
            duration = "2.0" if ".scene_1.part" in path else "4.0"
            return type("Result", (), {"stdout": f"{duration}\n"})()
        calls["ffmpeg"] += 1
        if calls["ffmpeg"] == 2:
            raise RuntimeError("ffmpeg failed")
        Path(command[-1]).write_bytes(b"segment")

    monkeypatch.setattr("src.services.sequence_video_service.subprocess.run", fake_run)

    with pytest.raises(SequenceVideoError, match="Could not split scene 2"):
        split_sequence_video(
            source,
            [SequenceSegment(1, 0.0, 2.0), SequenceSegment(2, 2.0, 4.0)],
            outputs,
        )

    assert not any(path.exists() for path in outputs)
    assert not any(".part" in path.name for path in tmp_path.iterdir())


def test_split_sequence_video_rolls_back_when_batch_publish_fails(tmp_path, monkeypatch):
    source = tmp_path / "sequence.mp4"
    source.write_bytes(b"sequence")
    outputs = [tmp_path / "scene_1.mp4", tmp_path / "scene_2.mp4"]
    outputs[0].write_bytes(b"old-scene-1")
    outputs[1].write_bytes(b"old-scene-2")
    monkeypatch.setattr("src.services.sequence_video_service.shutil.which", lambda name: "/usr/bin/ffmpeg")

    def fake_run(command, **_kwargs):
        if command[0] == "ffprobe":
            path = str(command[-1])
            duration = "2.0" if "scene_1" in path else "3.0"
            if str(source) in path:
                duration = "5.0"
            return type("Result", (), {"stdout": f"{duration}\n"})()
        Path(command[-1]).write_bytes(b"new-scene")

    monkeypatch.setattr("src.services.sequence_video_service.subprocess.run", fake_run)
    original_replace = Path.replace

    def fail_second_publish(self, target):
        if target == outputs[1] and ".scene_2.part" in self.name:
            raise OSError("simulated publish failure")
        return original_replace(self, target)

    monkeypatch.setattr(Path, "replace", fail_second_publish)

    with pytest.raises(SequenceVideoError, match="Could not publish the complete sequence batch"):
        split_sequence_video(
            source,
            [SequenceSegment(1, 0.0, 2.0), SequenceSegment(2, 2.0, 5.0)],
            outputs,
        )

    assert outputs[0].read_bytes() == b"old-scene-1"
    assert outputs[1].read_bytes() == b"old-scene-2"
    assert not any(path.name.endswith(".bak") for path in tmp_path.iterdir())


def test_split_sequence_video_rejects_dropped_source_audio(tmp_path, monkeypatch):
    source = tmp_path / "sequence.mp4"
    source.write_bytes(b"sequence")
    output = tmp_path / "scene_1.mp4"
    monkeypatch.setattr("src.services.sequence_video_service.shutil.which", lambda _name: "/usr/bin/ffprobe")

    def fake_run(command, **_kwargs):
        if "stream=codec_type" in command:
            if str(source) in command:
                return type("Result", (), {"stdout": "video\naudio\n"})()
            return type("Result", (), {"stdout": "video\n"})()
        return type("Result", (), {"stdout": "2.0\n"})()

    monkeypatch.setattr("src.services.sequence_video_service.subprocess.run", fake_run)

    # The fake ffmpeg invocation must still publish a non-empty temp file.
    def fake_run_with_output(command, **kwargs):
        result = fake_run(command, **kwargs)
        if command[0] == "ffmpeg":
            Path(command[-1]).write_bytes(b"segment")
        return result

    monkeypatch.setattr("src.services.sequence_video_service.subprocess.run", fake_run_with_output)

    with pytest.raises(SequenceVideoError, match="dropped the source audio"):
        split_sequence_video(source, [SequenceSegment(1, 0.0, 2.0)], [output])
    assert not output.exists()


def test_split_sequence_video_rejects_unknown_source_streams(tmp_path, monkeypatch):
    source = tmp_path / "sequence.mp4"
    source.write_bytes(b"sequence")
    monkeypatch.setattr("src.services.sequence_video_service.shutil.which", lambda _name: "/usr/bin/ffprobe")
    monkeypatch.setattr("src.services.sequence_video_service._probe_duration", lambda _path: 2.0)
    monkeypatch.setattr("src.services.sequence_video_service._probe_stream_types", lambda _path: None)

    with pytest.raises(SequenceVideoError, match="audio continuity evidence"):
        split_sequence_video(
            source,
            [SequenceSegment(1, 0.0, 2.0)],
            [tmp_path / "scene.mp4"],
        )
