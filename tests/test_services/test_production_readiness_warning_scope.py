from unittest.mock import Mock

from src.services.production_readiness import ProductionReadinessService, ReadinessIssue
from types import SimpleNamespace


def test_non_sample_warnings_do_not_create_sample_validation_blocker(monkeypatch):
    service = ProductionReadinessService(Mock())
    project = Mock(id=1)
    monkeypatch.setattr(service.db.query.return_value.filter.return_value, "first", lambda: project)
    monkeypatch.setattr(service.db.query.return_value.filter.return_value.order_by.return_value, "all", lambda: [])
    monkeypatch.setattr(service, "_script_check", lambda *_: {"status": "passed"})
    monkeypatch.setattr(service, "_story_rhythm_check", lambda *_: {"status": "passed"})
    monkeypatch.setattr(service, "_story_room_check", lambda *_: {"status": "passed"})
    monkeypatch.setattr(service, "_episode_rhythm_check", lambda *_: {"status": "passed"})
    monkeypatch.setattr(service, "_topic_brief_check", lambda _project, warnings: warnings.append(ReadinessIssue("ordinary_warning", "ordinary", "warning")) or {"status": "warn"})
    for method in (
        "_content_safety_check", "_visual_format_check", "_draft_media_fallback_check", "_image_postprocess_check",
        "_video_postprocess_check", "_character_check", "_shot_complexity_check", "_shot_state_continuity_check",
        "_spatial_continuity_check", "_visual_style_check", "_workflow_profile_check", "_regional_identity_check",
        "_reviewer_check", "_project_generation_quality_check",
    ):
        monkeypatch.setattr(service, method, lambda *args, **kwargs: {"status": "passed"})
    monkeypatch.setattr(service, "_sample_validation_check", lambda warnings: {"status": "passed"})

    report = service.build_report(1, include_engine_preflight=False)

    assert report["status"] == "needs_review"
    assert [issue["code"] for issue in report["warnings"]] == ["ordinary_warning"]
    assert not any(issue["code"] == "sample_validation_not_production_ready" for issue in report["blockers"])


def test_shot_readiness_blocks_missing_execution_contract(monkeypatch):
    service = ProductionReadinessService(None)
    service._script_scene_map = lambda _project: {
        1: {"scene_number": 1, "characters": ["Alice"], "shot_spec": {}},
    }
    service._visible_character_names = lambda *_args: ["Alice"]
    blockers = []
    warnings = []

    report = service._shot_complexity_check(
        SimpleNamespace(id=1),
        [SimpleNamespace(
            scene_number=1,
            visual_description="Alice runs toward the door",
            dialogue="",
        )],
        blockers,
        warnings,
    )

    assert report["status"] == "invalid_contract"
    assert report["invalid_contracts"][0]["scene_number"] == 1
    assert blockers[0].code == "invalid_shot_execution_contract"
    assert "motion_control" in blockers[0].message


def test_shot_readiness_promotes_two_character_dialogue_to_split_blocker(monkeypatch):
    service = ProductionReadinessService(None)
    service._script_scene_map = lambda _project: {
        1: {
            "scene_number": 1,
            "characters": ["Alice", "Bob"],
            "shot_spec": {
                "shot_role": "dialogue_reaction",
                "required_engine_capabilities": [
                    "identity_reference", "performance_control", "multi_character",
                ],
            },
        },
    }
    service._visible_character_names = lambda *_args: ["Alice", "Bob"]
    blockers = []
    warnings = []

    report = service._shot_complexity_check(
        SimpleNamespace(id=1),
        [SimpleNamespace(
            scene_number=1,
            visual_description="Alice confronts Bob across the desk",
            dialogue="Alice: You knew the truth.",
        )],
        blockers,
        warnings,
    )

    assert report["status"] == "needs_split"
    assert blockers[0].code == "overloaded_shots"
    assert not warnings
