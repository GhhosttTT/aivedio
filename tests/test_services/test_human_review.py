import json

from src.services.human_review import HumanReviewStore


def test_human_decision_is_applied_only_to_the_same_report_version(monkeypatch, tmp_path):
    from src.utils.storage import storage_manager
    monkeypatch.setattr(storage_manager, "base_path", tmp_path)
    store = HumanReviewStore(1)
    report = {"status": "needs_review", "average": 3.2}
    entry = store.record("generation", "approved", "looks acceptable", report, user_id=9)

    reports = {"generation": dict(report)}
    active = store.apply(reports)
    assert active["generation"]["decision"] == "approved"
    assert reports["generation"]["human_decision"]["note"] == "looks acceptable"

    changed = {"generation": {**report, "average": 2.8}}
    store.apply(changed)
    assert changed["generation"]["human_decision"]["decision"] == "stale"
    assert json.loads(store.path.read_text())["decisions"]["generation"]["report_signature"] == entry["report_signature"]
