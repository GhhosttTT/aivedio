from src.services.shot_complexity_service import ShotComplexityService, infer_shot_execution_contract


def test_simple_shot_is_ok():
    report = ShotComplexityService().diagnose(
        "Alice holds a red letter in an office doorway, medium shot",
        ["Alice"],
    )

    assert report.status == "ok"
    assert report.score < 3
    assert "one frozen instant" in report.prompt_constraint


def test_group_sequential_camera_move_needs_split():
    report = ShotComplexityService().diagnose(
        "Alice enters the room and then sits down while Bob and Cara fight as the camera pans around them",
        ["Alice", "Bob", "Cara"],
    )

    assert report.status == "needs_split"
    assert any("visible characters" in reason for reason in report.reasons)
    assert any("sequential" in reason for reason in report.reasons)
    assert any("camera movement" in reason for reason in report.reasons)
    assert len(report.suggested_atomic_shots) >= 2
    assert report.suggested_atomic_shots[0]["order"] == 1
    assert report.suggested_atomic_shots[0]["visible_characters"] == ["Alice"]
    assert "static" in report.suggested_atomic_shots[0]["camera"]
    assert "continuity" in report.suggested_atomic_shots[0]["continuity_note"].lower()


def test_warning_shot_gets_atomic_simplification_hint():
    report = ShotComplexityService().diagnose(
        "Alice opens the letter then turns toward Bob",
        ["Alice", "Bob"],
    )

    assert report.status == "warn"
    assert report.suggested_atomic_shots
    assert report.suggested_atomic_shots[0]["primary_action"]


def test_two_character_dialogue_gets_short_drama_coverage_plan():
    report = ShotComplexityService().diagnose(
        "Alice confronts Bob across a desk in the same office",
        ["Alice", "Bob"],
        "Alice: You knew the truth all along.",
    )

    assert report.status == "warn"
    assert [shot["shot_role"] for shot in report.suggested_atomic_shots] == [
        "establishing", "dialogue_reaction", "emotion_reaction",
    ]
    assert report.suggested_atomic_shots[0]["visible_characters"] == ["Alice", "Bob"]
    assert report.suggested_atomic_shots[1]["visible_characters"] == ["Alice"]
    assert report.suggested_atomic_shots[1]["dialogue"] == "Alice: You knew the truth all along."
    assert report.suggested_atomic_shots[2]["visible_characters"] == ["Bob"]
    assert report.suggested_atomic_shots[0]["required_engine_capabilities"] == [
        "identity_reference", "multi_character",
    ]
    assert report.suggested_atomic_shots[1]["required_engine_capabilities"] == [
        "identity_reference", "performance_control",
    ]
    assert report.suggested_atomic_shots[0]["screen_positions"] == {
        "Alice": "frame left", "Bob": "frame right",
    }
    assert report.suggested_atomic_shots[1]["eyeline_directions"] == {
        "Alice": "screen right",
    }
    assert report.suggested_atomic_shots[2]["eyeline_directions"] == {
        "Bob": "screen left",
    }
    assert "180-degree" in report.suggested_atomic_shots[0]["camera_axis"]


def test_no_dialogue_marker_does_not_force_dialogue_coverage():
    report = ShotComplexityService().diagnose(
        "Alice and Bob hold a static pose in the office",
        ["Alice", "Bob"],
        "无对白",
    )

    assert report.status == "ok"
    assert report.suggested_atomic_shots == []


def test_execution_contract_recognizes_inflected_english_action_before_prop():
    for description in (
        "Alice runs toward the locked door",
        "Alice is running toward the locked door",
        "Alice fought beside the locked door",
        "Alice chased him past the locked door",
    ):
        contract = infer_shot_execution_contract(description, "", ["Alice"])
        assert contract["shot_role"] == "action"
        assert contract["action_intensity"] == "high"
        assert contract["required_engine_capabilities"] == [
            "identity_reference", "motion_control",
        ]
