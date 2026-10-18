from src.services.repair_budget import RepairBudget


def test_repair_budget_accepts_then_exhausts_repeated_evidence(monkeypatch, tmp_path):
    from src.utils.storage import storage_manager
    monkeypatch.setattr(storage_manager, "base_path", tmp_path)
    budget = RepairBudget(1, max_attempts=2)
    item = {
        "scene_number": 3,
        "stage": "video",
        "action": "lower_motion_and_regenerate_video",
        "source_report": "scene_3.video.json",
        "reason": "prolonged frozen-frame run",
    }

    accepted, exhausted = budget.filter([item])
    assert len(accepted) == 1 and not exhausted
    budget.record(accepted)
    accepted, exhausted = budget.filter([item])
    assert accepted[0]["retry_attempts"] == 1
    budget.record(accepted)
    accepted, exhausted = budget.filter([item])

    assert not accepted
    assert exhausted[0]["retry_attempts"] == 2
    assert exhausted[0]["execution"] == "manual"


def test_repair_budget_treats_changed_evidence_as_a_new_attempt(monkeypatch, tmp_path):
    from src.utils.storage import storage_manager
    monkeypatch.setattr(storage_manager, "base_path", tmp_path)
    budget = RepairBudget(1, max_attempts=1)
    original = {"scene_number": 1, "stage": "image", "action": "refine_prompt_composition", "reason": "bad crop"}
    changed = {**original, "reason": "face cropped"}
    budget.record([original])

    accepted, exhausted = budget.filter([changed])

    assert len(accepted) == 1
    assert not exhausted
