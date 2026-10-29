from src.services.repair_budget import RepairBudget


def test_preview_does_not_consume_budget_or_change_existing_reservations(monkeypatch, tmp_path):
    from src.utils.storage import storage_manager
    monkeypatch.setattr(storage_manager, "base_path", tmp_path)
    budget = RepairBudget(1, max_attempts=2, max_total_attempts=2)
    item = {"scene_number": 1, "stage": "video", "action": "repair", "reason": "flicker"}

    for _ in range(3):
        accepted, exhausted = budget.filter([item, item, item], reserve=False)
        assert len(accepted) == 2
        assert len(exhausted) == 1
        assert not budget.path.exists()

    budget.filter([item])
    original = budget.path.read_bytes()
    for _ in range(3):
        accepted, exhausted = budget.filter([item, item], reserve=False)
        assert len(accepted) == 1
        assert accepted[0]["retry_attempts"] == 1
        assert len(exhausted) == 1
        assert budget.path.read_bytes() == original

    accepted, exhausted = budget.filter([item])
    assert len(accepted) == 1 and not exhausted


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


def test_repair_budget_enforces_project_wide_retry_cap(monkeypatch, tmp_path):
    from src.utils.storage import storage_manager
    monkeypatch.setattr(storage_manager, "base_path", tmp_path)
    budget = RepairBudget(1, max_attempts=2, max_total_attempts=2)
    first = {"scene_number": 1, "stage": "video", "action": "repair-a", "reason": "first"}
    second = {"scene_number": 2, "stage": "video", "action": "repair-b", "reason": "second"}

    accepted, exhausted = budget.filter([first, second])
    assert [item["action"] for item in accepted] == ["repair-a", "repair-b"]
    assert not exhausted
    budget.record(accepted)

    accepted, exhausted = budget.filter([{
        "scene_number": 3,
        "stage": "video",
        "action": "repair-c",
        "reason": "new evidence text",
    }])
    assert accepted == []
    assert exhausted[0]["reason"] == "project automatic repair retry budget exhausted"
    assert exhausted[0]["project_retry_attempts"] == 2


def test_repair_budget_migrates_legacy_attempt_file(monkeypatch, tmp_path):
    from src.utils.storage import storage_manager
    monkeypatch.setattr(storage_manager, "base_path", tmp_path)
    project_path = storage_manager.get_project_path(1)
    (project_path / "repair_attempts.json").write_text(
        '{"version": 1, "attempts": {"legacy": {"count": 3}}}\n',
        encoding="utf-8",
    )
    budget = RepairBudget(1, max_attempts=2, max_total_attempts=3)

    accepted, exhausted = budget.filter([{
        "scene_number": 1,
        "stage": "video",
        "action": "repair",
        "reason": "new evidence",
    }])

    assert accepted == []
    assert exhausted[0]["project_retry_attempts"] == 3


def test_repair_budget_reserves_concurrent_filters_until_commit(monkeypatch, tmp_path):
    from src.utils.storage import storage_manager
    monkeypatch.setattr(storage_manager, "base_path", tmp_path)
    budget = RepairBudget(1, max_attempts=1, max_total_attempts=1)
    item = {"scene_number": 1, "stage": "video", "action": "repair", "reason": "flicker"}

    accepted, exhausted = budget.filter([item])
    assert len(accepted) == 1 and not exhausted

    second_accepted, second_exhausted = budget.filter([item])
    assert second_accepted == []
    assert second_exhausted[0]["retry_attempts"] == 1

    budget.release(accepted)
    accepted_after_release, exhausted_after_release = budget.filter([item])
    assert len(accepted_after_release) == 1 and not exhausted_after_release
    budget.record(accepted_after_release)

    _, exhausted_after_commit = budget.filter([item])
    assert exhausted_after_commit[0]["project_retry_attempts"] == 1
