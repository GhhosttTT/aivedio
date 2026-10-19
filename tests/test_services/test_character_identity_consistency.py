from types import SimpleNamespace

from src.services.character_identity_consistency import CharacterIdentityConsistencyService


def _scene(number, character="Alice"):
    return SimpleNamespace(scene_number=number, character_name=character)


def test_character_identity_consistency_passes_stable_review_scores():
    reports = {
        "generation": {
            "cases": [
                {"scene_number": 1, "character_name": "Alice", "review": {"identity_consistency": {"score": 5, "evidence": "same face"}}},
                {"scene_number": 2, "character_name": "Alice", "review": {"identity_consistency": {"score": 4, "evidence": "stable identity"}}},
            ]
        }
    }

    report = CharacterIdentityConsistencyService().audit([_scene(1), _scene(2)], reports)

    assert report.status == "passed"
    assert report.character_count == 1
    assert report.observation_count == 2


def test_character_identity_consistency_flags_low_score_and_drift():
    reports = {
        "generation": {
            "cases": [
                {"scene_number": 1, "character_name": "Alice", "review": {"identity_consistency": {"score": 5}}},
                {"scene_number": 2, "character_name": "Alice", "review": {"identity_consistency": {"score": 2}}},
            ]
        }
    }

    report = CharacterIdentityConsistencyService().audit([_scene(1), _scene(2)], reports)

    assert report.status == "needs_review"
    assert {issue["code"] for issue in report.issues} == {
        "identity_score_below_threshold",
        "identity_score_drift",
    }
    assert report.to_dict()["repair_queue"][0]["action"] == "regenerate_character_identity"


def test_character_identity_consistency_uses_scene_character_when_candidate_omits_name():
    reports = {
        "generation": {
            "cases": [
                {"scene_number": 1, "review": {"facial_identity": {"score": 4}}},
                {"scene_number": 2, "review": {"facial_identity": {"score": 4}}},
            ]
        }
    }

    report = CharacterIdentityConsistencyService().audit([_scene(1), _scene(2)], reports)

    assert report.status == "passed"
    assert {item["character"] for item in report.observations} == {"Alice"}


def test_character_identity_consistency_uses_configured_project_floor(monkeypatch):
    monkeypatch.setattr(
        "src.services.character_identity_consistency.settings.GENERATION_CHARACTER_IDENTITY_MIN_SCORE",
        4.5,
    )
    reports = {
        "generation": {
            "cases": [
                {
                    "scene_number": 1,
                    "character_name": "Alice",
                    "review": {"identity_consistency": {"score": 4.2}},
                },
            ]
        }
    }

    report = CharacterIdentityConsistencyService().audit([_scene(1)], reports)

    assert report.status == "needs_review"
    assert report.issues[0]["code"] == "identity_score_below_threshold"


def test_character_identity_consistency_requires_cross_shot_evidence_for_repeated_character():
    reports = {
        "generation": {
            "cases": [
                {"scene_number": 1, "character_name": "Alice", "review": {"identity_consistency": {"score": 5}}},
            ]
        }
    }

    report = CharacterIdentityConsistencyService().audit([_scene(1), _scene(2)], reports)

    assert report.status == "needs_review"
    assert report.issues[0]["code"] == "identity_evidence_insufficient"


def test_character_identity_consistency_does_not_require_two_observations_for_single_scene_character():
    reports = {
        "generation": {
            "cases": [
                {"scene_number": 1, "character_name": "Alice", "review": {"identity_consistency": {"score": 5}}},
            ]
        }
    }

    report = CharacterIdentityConsistencyService().audit([_scene(1)], reports)

    assert report.status == "passed"


def test_character_identity_consistency_requires_every_repeated_scene_observation():
    reports = {
        "generation": {
            "cases": [
                {"scene_number": 1, "character_name": "Alice", "review": {"identity_consistency": {"score": 5}}},
                {"scene_number": 2, "character_name": "Alice", "review": {"identity_consistency": {"score": 5}}},
            ]
        }
    }

    report = CharacterIdentityConsistencyService().audit(
        [_scene(1), _scene(2), _scene(3)], reports,
    )

    assert report.status == "needs_review"
    assert report.issues[0]["code"] == "identity_evidence_insufficient"
    assert report.issues[0]["required_observations"] == 3
