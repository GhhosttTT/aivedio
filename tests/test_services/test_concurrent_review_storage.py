"""Concurrent successful review requests must retain every distinct record."""

import json
import time
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest

from src.services.baseline_comparison_history import BaselineComparisonHistoryStore
from src.services.human_review import HumanReviewStore
from src.services.localization_review import LocalizationReviewStore
from src.utils.storage import storage_manager


@pytest.mark.parametrize("kind", ["human", "baseline", "localization"])
def test_concurrent_review_records_are_not_lost(kind, tmp_path, monkeypatch):
    monkeypatch.setattr(storage_manager, "base_path", tmp_path)
    classes = {
        "human": HumanReviewStore,
        "baseline": BaselineComparisonHistoryStore,
        "localization": LocalizationReviewStore,
    }
    store_class = classes[kind]
    original_read = store_class._read

    def slow_read(self):
        payload = original_read(self)
        # Widen the vulnerable interval between reading and publishing so an
        # unlocked implementation reliably loses updates under contention.
        time.sleep(0.02)
        return payload

    monkeypatch.setattr(store_class, "_read", slow_read)
    start = Barrier(6)

    def record(index):
        store = store_class(tmp_path / "report.json" if kind == "localization" else 1)
        start.wait(timeout=10)
        if kind == "human":
            store.record(f"scene_{index}", "approved", str(index), {"index": index})
        elif kind == "baseline":
            store.record({"candidate_sha256": str(index), "baseline_sha256": "baseline", "score": 4})
        else:
            store.record("approved", str(index), {"index": index})
        return store.path

    with ThreadPoolExecutor(max_workers=6) as pool:
        paths = list(pool.map(record, range(6)))
    payload = json.loads(paths[0].read_text(encoding="utf-8"))
    if kind == "human":
        assert set(payload["decisions"]) == {f"scene_{index}" for index in range(6)}
    elif kind == "baseline":
        assert {entry["candidate_sha256"] for entry in payload["entries"]} == {str(index) for index in range(6)}
    else:
        assert {entry["note"] for entry in payload["history"]} == {str(index) for index in range(6)}
        assert payload["decision"] == payload["history"][-1]
