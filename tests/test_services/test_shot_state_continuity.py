from src.services.shot_state_continuity import ShotStateContinuityService


def _scene(number, character, start="", end=""):
    return {
        "scene_number": number,
        "shot_spec": {"character_states": [{
            "character_name": character,
            "start_state": start,
            "end_state": end,
        }]},
    }


def _asset_scene(number, asset):
    return {"scene_number": number, "shot_spec": {"continuity_assets": [asset]}}


def test_reports_explicit_hand_side_flip_without_handoff():
    report = ShotStateContinuityService().assess([
        _scene(1, "Alice", end="right hand holds the letter"),
        _scene(2, "Alice", start="left hand holds the letter"),
    ])

    assert report["status"] == "needs_review"
    assert report["summary"] == {"tracked_transitions": 1, "asset_transitions": 0, "conflicts": 1}
    assert report["conflicts"][0]["type"] == "hand_side_conflict"


def test_allows_explicit_handoff_and_ignores_unstructured_state_changes():
    report = ShotStateContinuityService().assess([
        _scene(1, "Alice", end="right hand holds the letter, then handoff to Bob"),
        _scene(2, "Alice", start="left hand is now free"),
        _scene(3, "Alice", start="at the window"),
    ])

    assert report["status"] == "documented"
    assert report["summary"] == {"tracked_transitions": 2, "asset_transitions": 0, "conflicts": 0}


def test_ignores_scripts_without_explicit_state_contracts():
    report = ShotStateContinuityService().assess([{"scene_number": 1}, {"scene_number": 2}])

    assert report["status"] == "not_configured"
    assert report["summary"] == {"tracked_transitions": 0, "asset_transitions": 0, "conflicts": 0}


def test_does_not_compare_states_across_a_scene_gap():
    report = ShotStateContinuityService().assess([
        _scene(1, "Alice", end="right hand holds the letter"),
        {"scene_number": 2},
        _scene(3, "Alice", start="left hand holds the letter"),
    ])

    assert report["status"] == "not_configured"
    assert report["summary"] == {"tracked_transitions": 0, "asset_transitions": 0, "conflicts": 0}


def test_reports_structured_asset_change_without_transition_note():
    report = ShotStateContinuityService().assess([
        _asset_scene(1, {"asset_id": "prop:knife", "kind": "prop", "end_state": {"holder": "Alice", "hand": "right"}}),
        _asset_scene(2, {"asset_id": "prop:knife", "kind": "prop", "start_state": {"holder": "Alice", "hand": "left"}}),
    ])

    assert report["status"] == "needs_review"
    assert report["summary"] == {"tracked_transitions": 0, "asset_transitions": 1, "conflicts": 1}
    assert report["asset_conflicts"][0]["mismatches"]["hand"] == {"previous": "right", "current": "left"}


def test_allows_structured_asset_change_with_documented_transition():
    report = ShotStateContinuityService().assess([
        _asset_scene(1, {"asset_id": "wardrobe:coat", "kind": "wardrobe", "end_state": {"wet": "false"}}),
        _asset_scene(2, {"asset_id": "wardrobe:coat", "kind": "wardrobe", "start_state": {"wet": "true"}, "transition_note": "雨中奔跑后淋湿"}),
    ])

    assert report["status"] == "documented"
    assert report["asset_conflicts"] == []
