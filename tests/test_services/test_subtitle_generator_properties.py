"""Property tests for the audio-file and timed-dialogue subtitle contract."""
import math
import re
import tempfile
from pathlib import Path
from unittest.mock import patch
import pytest
from hypothesis import given, strategies as st, settings
from src.services.subtitle_generator import SubtitleGenerator

DURATIONS = st.lists(st.floats(min_value=.05, max_value=60, allow_nan=False), min_size=1, max_size=20)

@given(DURATIONS)
@settings(max_examples=30, deadline=None)
def test_subtitle_timeline_alignment(durations):
    service = SubtitleGenerator()
    with patch.object(service, "_get_audio_duration", side_effect=durations):
        timings = service.calculate_timing([f"{i}.wav" for i in range(len(durations))])
    elapsed = 0
    for timing, duration in zip(timings, durations):
        assert timing["start_time"] == pytest.approx(elapsed)
        assert timing["duration"] == duration
        elapsed += duration

@given(st.integers(1, 20))
def test_subtitle_file_format_correctness(count):
    with tempfile.TemporaryDirectory() as directory:
        target = Path(directory) / "test.srt"
        SubtitleGenerator().generate_srt([{"text": f"subtitle {i}", "start_time": i * 2, "duration": 1.5} for i in range(count)], str(target))
        blocks = target.read_text(encoding="utf-8").strip().split("\n\n")
        assert len(blocks) == count
        for i, block in enumerate(blocks):
            lines = block.splitlines()
            assert lines[0] == str(i + 1)
            assert re.fullmatch(r"\d{2}:\d{2}:\d{2},\d{3} --> \d{2}:\d{2}:\d{2},\d{3}", lines[1])
            assert lines[2] == f"subtitle {i}"

@given(st.integers(1, 200), st.integers(10, 50))
def test_text_splitting_preserves_content(length, width):
    service = SubtitleGenerator(max_chars_per_line=width, max_lines=math.ceil(length / width))
    text = "测" * length
    lines = service._split_text(text)
    assert all(len(line) <= width for line in lines)
    assert "".join(lines) == text

@given(DURATIONS)
def test_timing_is_monotonic(durations):
    service = SubtitleGenerator()
    with patch.object(service, "_get_audio_duration", side_effect=durations):
        timings = service.calculate_timing(["audio"] * len(durations))
    starts = [t["start_time"] for t in timings]
    assert starts == sorted(starts)
    for previous, current in zip(timings, timings[1:]):
        assert current["start_time"] >= previous["start_time"] + previous["duration"]

@given(DURATIONS)
def test_subtitle_duration_matches_audio(durations):
    service = SubtitleGenerator()
    with patch.object(service, "_get_audio_duration", side_effect=durations):
        timings = service.calculate_timing(["audio"] * len(durations))
    assert timings[-1]["start_time"] + timings[-1]["duration"] == pytest.approx(sum(durations))
