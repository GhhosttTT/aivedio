from types import SimpleNamespace

import pytest

from src.services.sequence_plan import build_sequence_context, build_sequence_timeline


def _scene(number, character, visual, *, image=True, video=False):
    return SimpleNamespace(
        scene_number=number,
        character_name=character,
        visual_description=visual,
        dialogue=f"line {number}",
        audio_duration=2.0,
        image_path=f"scene_{number}.png" if image else None,
        video_path=f"scene_{number}.mp4" if video else None,
    )


def test_sequence_context_binds_adjacent_shots_and_continuity_contract():
    context = build_sequence_context(
        [
            _scene(1, "Alice", "Alice enters", video=True),
            _scene(2, "Alice", "Alice looks at the door"),
            _scene(3, "Victor", "Victor opens the door"),
        ],
        current_scene_number=2,
        sequence_id="project-7",
    )

    payload = context.as_dict()
    assert payload["sequence_id"] == "project-7"
    assert payload["previous"]["scene_number"] == 1
    assert payload["current"]["scene_number"] == 2
    assert payload["next"]["scene_number"] == 3
    assert any("motion and pacing" in item for item in payload["continuity_contract"])
    assert any("screen direction" in item for item in payload["continuity_contract"])
    assert [shot["scene_number"] for shot in payload["sequence_shots"]] == [1, 2, 3]


def test_sequence_context_rejects_missing_scene():
    with pytest.raises(ValueError, match="not present"):
        build_sequence_context([_scene(1, "Alice", "entrance")], current_scene_number=2)


def test_sequence_timeline_uses_dialogue_duration_and_stays_within_provider_limit():
    timeline = build_sequence_timeline(
        [_scene(1, "Alice", "entrance"), _scene(2, "Alice", "reaction"), _scene(3, "Victor", "door")],
        max_duration_seconds=5.0,
    )

    assert [item.scene_number for item in timeline] == [1, 2, 3]
    assert timeline[0].start_seconds == 0.0
    assert timeline[-1].end_seconds <= 5.0
    assert all(item.duration_seconds >= 1.0 for item in timeline)
    assert timeline[0].as_dict()["duration_seconds"] == timeline[0].duration_seconds
