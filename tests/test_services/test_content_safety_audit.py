from types import SimpleNamespace

from src.services.content_safety_audit import ContentSafetyAuditService
from src.services.production_readiness import ProductionReadinessService


def _scene(number, visual="", dialogue=""):
    return SimpleNamespace(scene_number=number, visual_description=visual, dialogue=dialogue)


def test_content_safety_audit_passes_clean_story(monkeypatch):
    monkeypatch.setattr(
        "src.services.content_safety_audit.TopicBriefService.load",
        lambda _self, _project_id: {"policy_notes": "无"},
    )

    report = ContentSafetyAuditService().audit(
        SimpleNamespace(id=1), [_scene(1, "A woman opens a letter.", "你终于来了。")]
    )

    assert report["status"] == "passed"
    assert report["hit_count"] == 0


def test_content_safety_audit_blocks_uncovered_risk_with_scene_evidence(monkeypatch):
    monkeypatch.setattr(
        "src.services.content_safety_audit.TopicBriefService.load",
        lambda _self, _project_id: {"policy_notes": "品牌安全要求待复核"},
    )

    report = ContentSafetyAuditService().audit(
        SimpleNamespace(id=1), [_scene(3, "A violent assault leaves blood on the floor.")]
    )

    assert report["status"] == "blocked"
    assert report["uncovered_categories"] == ["violence"]
    assert report["hits"][0]["scene_number"] == 3
    assert report["hits"][0]["field"] == "visual_description"


def test_content_safety_audit_routes_disclosed_risk_to_human_review(monkeypatch):
    monkeypatch.setattr(
        "src.services.content_safety_audit.TopicBriefService.load",
        lambda _self, _project_id: {"policy_notes": "允许剧情化暴力，但需人工审核尺度"},
    )

    report = ContentSafetyAuditService().audit(
        SimpleNamespace(id=1), [_scene(2, "A stylized violence beat, no gore.")]
    )

    assert report["status"] == "needs_review"
    assert report["policy_categories"] == ["violence"]
    assert report["uncovered_categories"] == []


def test_production_readiness_exposes_content_safety_blocker(monkeypatch):
    monkeypatch.setattr(
        "src.services.content_safety_audit.TopicBriefService.load",
        lambda _self, _project_id: {"policy_notes": "待复核"},
    )
    blockers = []

    report = ProductionReadinessService(None)._content_safety_check(
        SimpleNamespace(id=1), [_scene(4, "A violent confrontation")], blockers
    )

    assert report["status"] == "blocked"
    assert blockers[0].code == "content_safety_review_required"
