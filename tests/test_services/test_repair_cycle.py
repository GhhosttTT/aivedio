import json

from src.services.repair_cycle import RepairCycleStore


def test_repair_cycle_store_records_bounded_auditable_entries(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "src.services.repair_cycle.storage_manager.get_project_path",
        lambda _project_id: tmp_path,
    )
    store = RepairCycleStore(7)
    entry = store.record(
        status="submitted",
        considered=[{"scene_number": 1, "action": "refine_prompt_composition"}],
        submitted=[{"scene_number": 1, "action": "refine_prompt_composition", "task_id": "task-1", "provider_secret": "redact"}],
        skipped=[{"scene_number": 2, "action": "manual_review", "reason": "needs human"}],
    )

    assert entry["cycle_id"]
    assert store.recent(1)[0]["submitted"][0] == {
        "scene_number": 1,
        "action": "refine_prompt_composition",
        "task_id": "task-1",
    }
    payload = json.loads((tmp_path / "reviews" / "repair_cycles.json").read_text(encoding="utf-8"))
    assert payload["schema_version"] == 1
    assert payload["cycles"][0]["skipped_count"] == 1


def test_repair_cycle_store_keeps_only_recent_cycles(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "src.services.repair_cycle.storage_manager.get_project_path",
        lambda _project_id: tmp_path,
    )
    store = RepairCycleStore(7)
    for index in range(store.MAX_CYCLES + 3):
        store.record(status=f"cycle-{index}", submitted=[], skipped=[], considered=[])

    recent = store.recent(50)
    assert len(recent) == store.MAX_CYCLES
    assert recent[0]["status"] == "cycle-22"
    assert recent[-1]["status"] == "cycle-3"
