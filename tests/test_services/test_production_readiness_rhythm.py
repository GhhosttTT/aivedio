from types import SimpleNamespace

from src.services.production_readiness import ProductionReadinessService, ReadinessIssue


def test_production_readiness_promotes_hard_rhythm_conflicts_to_blockers(monkeypatch):
    monkeypatch.setattr(
        "src.services.production_readiness.RhythmAuditService.audit",
        lambda _self, project, scenes: SimpleNamespace(
            to_dict=lambda: {
                "kind": "rhythm_audit",
                "status": "needs_review",
                "scene_count": 1,
                "total_duration_seconds": 2.0,
                "issues": [{"code": "dialogue_reaction_margin", "severity": "high"}],
                "timeline": [],
                "repair_queue": [],
            }
        ),
    )
    blockers = []
    warnings = []
    result = ProductionReadinessService(None)._episode_rhythm_check(
        SimpleNamespace(id=1), [], blockers, warnings
    )
    assert result["status"] == "needs_review"
    assert blockers[0].code == "episode_rhythm_conflict"
    assert not warnings


def test_production_readiness_keeps_soft_rhythm_findings_as_warnings(monkeypatch):
    monkeypatch.setattr(
        "src.services.production_readiness.RhythmAuditService.audit",
        lambda _self, project, scenes: SimpleNamespace(
            to_dict=lambda: {
                "kind": "rhythm_audit",
                "status": "warn",
                "scene_count": 3,
                "total_duration_seconds": 8.0,
                "issues": [{"code": "repeated_shot_role", "severity": "warn"}],
                "timeline": [],
                "repair_queue": [],
            }
        ),
    )
    blockers = []
    warnings = []
    result = ProductionReadinessService(None)._episode_rhythm_check(
        SimpleNamespace(id=1), [], blockers, warnings
    )
    assert result["status"] == "warn"
    assert warnings[0].code == "episode_rhythm_warning"
    assert not blockers


def test_production_readiness_maps_warning_findings_to_typed_repair_actions():
    service = ProductionReadinessService(None)
    actions = service._readiness_repair_actions([
        ReadinessIssue(
            "weak_spatial_continuity", "Review spatial plans", severity="warning"
        ),
        ReadinessIssue(
            "weak_story_rhythm", "Improve rhythm", severity="warning"
        ),
    ])
    assert actions == [
        {
            "action": "refreeze_spatial_plan",
            "stage": "spatial",
            "execution": "setup_required",
            "severity": "warning",
            "source_report": "production_readiness",
            "reason": "Review spatial plans",
            "recommendation": "Resolve production readiness warning: weak_spatial_continuity.",
        },
        {
            "action": "rewrite_short_drama_story_rhythm",
            "stage": "script",
            "execution": "setup_required",
            "severity": "warning",
            "source_report": "production_readiness",
            "reason": "Improve rhythm",
            "recommendation": "Resolve production readiness warning: weak_story_rhythm.",
        },
    ]
