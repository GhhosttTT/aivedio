"""Video, audio, and subtitles share a clock without cumulative pre-laps."""

import math
from types import SimpleNamespace

import pytest

from src.config import settings
from src.services.composition_timeline import build_composition_timeline
from src.services.subtitle_quality_service import assess_subtitle_timeline
from src.tasks.composition_tasks import _merge_subtitles


def prelap_plan(count):
    return [{}] + [
        {"audio_strategy": "dialogue_pre_lap", "transition": {"video": "hard_cut"}}
        for _ in range(count - 1)
    ]


def test_plain_concat_does_not_invent_overlaps():
    timeline = build_composition_timeline([1.0, 2.0, 3.0])
    assert [item.video_start for item in timeline] == [0.0, 1.0, 3.0]
    assert [item.audio_start for item in timeline] == [0.0, 1.0, 3.0]
    assert [item.end for item in timeline] == [1.0, 3.0, 6.0]


def test_every_prelap_is_anchored_to_its_own_video_cut(monkeypatch):
    monkeypatch.setattr(settings, "GENERATION_VIDEO_DIALOGUE_PRELAP_SECONDS", 0.08)
    timeline = build_composition_timeline([1.0] * 6, prelap_plan(6))
    assert [item.video_start for item in timeline] == pytest.approx(
        [0, 0.999, 1.998, 2.997, 3.996, 4.995]
    )
    assert [item.audio_start for item in timeline] == pytest.approx(
        [0, 0.920, 1.919, 2.918, 3.917, 4.916]
    )
    assert timeline[-1].end == pytest.approx(5.995)


def test_mixed_cuts_reanchor_after_prelap_and_clamp_to_short_shots(monkeypatch):
    monkeypatch.setattr(settings, "GENERATION_VIDEO_DIALOGUE_PRELAP_SECONDS", 0.08)
    plan = prelap_plan(2) + [
        {"transition": {"video": "crossfade", "duration_seconds": 0.12}},
        {"transition": {"video": "hard_cut"}},
    ]
    timeline = build_composition_timeline([2.0, 1.5, 0.05, 2.0], plan)
    assert timeline[1].audio_start == pytest.approx(1.92)
    assert timeline[2].video_overlap == timeline[2].audio_overlap == 0.05
    assert timeline[2].video_start == timeline[2].audio_start == pytest.approx(3.449)
    assert timeline[3].audio_start == pytest.approx(3.498)
    assert timeline[-1].end == pytest.approx(5.498)


@pytest.mark.parametrize("duration", [0.0, -1.0, math.nan, math.inf])
def test_timeline_rejects_unreadable_scene_duration(duration):
    with pytest.raises(ValueError, match="finite and positive"):
        build_composition_timeline([1.0, duration], prelap_plan(2))


def test_timeline_rejects_incomplete_plan():
    with pytest.raises(ValueError, match="one entry per scene"):
        build_composition_timeline([1.0, 2.0], [{}])


@pytest.mark.parametrize("duration", [math.nan, math.inf])
def test_timeline_rejects_nonfinite_transition(duration):
    with pytest.raises(ValueError, match="transition duration must be finite"):
        build_composition_timeline(
            [1.0, 1.0], [{}, {"transition": {"video": "crossfade", "duration_seconds": duration}}]
        )


def test_subtitles_follow_each_prelapped_dialogue_not_cumulative_compression(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "GENERATION_VIDEO_DIALOGUE_PRELAP_SECONDS", 0.08)
    subtitle = tmp_path / "source.srt"
    subtitle.write_text("1\n00:00:00,200 --> 00:00:00,300\na\n", encoding="utf-8")
    scenes = [
        SimpleNamespace(
            scene_number=index + 1, video_path=None, audio_duration=1.0, subtitle_path=str(subtitle)
        )
        for index in range(6)
    ]
    output = tmp_path / "merged.srt"
    _merge_subtitles([], str(output), scenes, editing_plan=prelap_plan(6))
    entries = assess_subtitle_timeline(output.read_text(encoding="utf-8"))["entries"]
    assert [entry["start"] for entry in entries] == pytest.approx(
        [0.2, 1.12, 2.119, 3.118, 4.117, 5.116], abs=0.001
    )


def test_subtitle_offsets_use_the_renderers_clamped_crossfade(tmp_path):
    subtitle = tmp_path / "source.srt"
    subtitle.write_text("1\n00:00:00,000 --> 00:00:00,010\na\n", encoding="utf-8")
    scenes = [
        SimpleNamespace(
            scene_number=index + 1,
            video_path=None,
            audio_duration=duration,
            subtitle_path=str(subtitle),
        )
        for index, duration in enumerate([2.0, 0.05])
    ]
    output = tmp_path / "merged.srt"
    _merge_subtitles(
        [],
        str(output),
        scenes,
        editing_plan=[{}, {"transition": {"video": "crossfade", "duration_seconds": 0.12}}],
    )
    entries = assess_subtitle_timeline(output.read_text(encoding="utf-8"))["entries"]
    assert entries[1]["start"] == 1.95
