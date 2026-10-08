from src.services.turnaround_quality import attach_turnaround_quality_gate, turnaround_expected_features


def character_data():
    return {
        "face_shape": "oval face",
        "eyes": "almond brown eyes",
        "nose": "straight nose bridge",
        "mouth": "medium lips",
        "hair": "short black hair",
        "body_type": "slender",
        "height": "168cm",
        "outfit_details": "green jacket",
        "distinctive_features": "small mole under left eye",
    }


def test_turnaround_expected_features_are_view_specific():
    front = turnaround_expected_features("front", character_data())
    side = turnaround_expected_features("side", character_data())
    back = turnaround_expected_features("back", character_data())

    assert "almond brown eyes" in front["eyes"]
    assert side["view_angle"] == "strict 90 degree side profile"
    assert side["no_three_quarter"] == "not a three-quarter view"
    assert back["no_face_visible"] == "no visible face or front-facing pose"


def test_turnaround_gate_quantifies_feature_mismatch():
    candidate = {
        "review": {
            "turnaround_feature_scores": {
                "view_angle": {"score": 5, "evidence": "strict front view is visible"},
                "face_shape": {"score": 5, "evidence": "oval face shape matches identity"},
                "eyes": {"score": 5, "evidence": "almond brown eyes match identity"},
                "nose": {"score": 2, "evidence": "nose bridge changed"},
                "mouth": {"score": 5, "evidence": "medium lip shape matches identity"},
                "hair": {"score": 5, "evidence": "short black hair"},
                "distinctive_features": {"score": 1, "evidence": "mole missing"},
                "body_proportion": {"score": 4, "evidence": "slender body proportion matches"},
                "wardrobe_front": {"score": 4, "evidence": "green jacket is visible"},
            }
        },
        "platform_score": 4.5,
    }

    attach_turnaround_quality_gate(candidate, "front", character_data(), min_score=4.0)

    gate = candidate["turnaround_gate"]
    assert gate["status"] == "needs_review"
    assert gate["scores"]["nose"]["score"] == 2
    assert gate["scores"]["distinctive_features"]["score"] == 1
    assert set(gate["low"]) == {"nose", "distinctive_features"}
    assert candidate["platform_score"] == 0.0


def test_turnaround_gate_passes_when_all_features_are_scored():
    scores = {
        feature: {"score": 4, "evidence": f"{feature} visibly matches expected character sheet"}
        for feature in turnaround_expected_features("back", character_data())
    }
    candidate = {"review": {"turnaround_feature_scores": scores}, "platform_score": 4.5}

    attach_turnaround_quality_gate(candidate, "back", character_data(), min_score=4.0)

    assert candidate["turnaround_gate"]["status"] == "passed"
    assert candidate["turnaround_gate"]["missing"] == []
    assert candidate["platform_score"] == 4.0


def test_turnaround_gate_rejects_short_generic_evidence():
    scores = {
        feature: {"score": 4, "evidence": "matches"}
        for feature in turnaround_expected_features("back", character_data())
    }
    candidate = {"review": {"turnaround_feature_scores": scores}, "platform_score": 4.5}

    attach_turnaround_quality_gate(candidate, "back", character_data(), min_score=4.0)

    gate = candidate["turnaround_gate"]
    assert gate["status"] == "needs_review"
    assert gate["missing"] == [f"{feature}.evidence" for feature in turnaround_expected_features("back", character_data())]
    assert candidate["platform_score"] == 0.0
