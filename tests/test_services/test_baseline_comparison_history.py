from src.services.baseline_comparison_history import BaselineComparisonHistoryStore


def _report(candidate, score, status="passed"):
    return {
        "status": status,
        "score": score,
        "min_score": 0.7,
        "candidate_video_path": candidate,
        "baseline_video_path": "/tmp/baseline.mp4",
        "candidate_sha256": candidate,
        "baseline_sha256": "baseline-hash",
        "gates": {"motion_not_static": status == "passed"},
        "differences": {"motion_energy_ratio": score},
    }


def test_baseline_history_tracks_regression_and_best_score(monkeypatch, tmp_path):
    from src.utils.storage import storage_manager

    monkeypatch.setattr(storage_manager, "base_path", tmp_path)
    store = BaselineComparisonHistoryStore(1)
    first = store.record(_report("candidate-a", 0.92))
    second = store.record(_report("candidate-b", 0.81))

    assert first["count"] == 1
    assert second["count"] == 2
    assert second["previous_score"] == 0.92
    assert second["current_score"] == 0.81
    assert second["best_score"] == 0.92
    assert second["score_delta"] == -0.11
    assert second["regression"] is True


def test_baseline_history_deduplicates_same_media_versions(monkeypatch, tmp_path):
    from src.utils.storage import storage_manager

    monkeypatch.setattr(storage_manager, "base_path", tmp_path)
    store = BaselineComparisonHistoryStore(1)
    store.record(_report("candidate-a", 0.8))
    summary = store.record(_report("candidate-a", 0.9))

    assert summary["count"] == 1
    assert summary["current_score"] == 0.9
