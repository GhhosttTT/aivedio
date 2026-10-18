from src.services.generation_run_evidence import build_generation_run_evidence, collect_gpu_evidence


def test_build_generation_run_evidence_summarizes_cases_and_candidates():
    evidence = build_generation_run_evidence(
        {
            "status": "rendered_pending_human_review",
            "render_profile": {"quality_mode": "ultra"},
            "cases": [
                {"image": "one.png", "elapsed_seconds": 4.25, "search": {"candidates": [{}, {}]}},
                {"image": "two.png", "elapsed_seconds": 2.0, "search": None},
            ],
        },
        {"status": "ready_for_live_test", "checks": {"local_gpu": "RTX"}},
        gpu_evidence={"status": "available", "devices": [{"name": "RTX", "memory_total_mb": 24576}]},
        generated_at=123,
    )

    assert evidence["schema_version"] == 1
    assert evidence["generated_at"] == 123
    assert evidence["runtime"] == {
        "status": "rendered_pending_human_review",
        "elapsed_seconds_sum": 6.25,
        "elapsed_seconds_max": 4.25,
        "case_count": 2,
        "candidate_count": 3,
        "accepted_count": 2,
        "acceptance_rate": 1.0,
    }
    assert evidence["gpu"]["devices"][0]["memory_total_mb"] == 24576


def test_collect_gpu_evidence_degrades_without_nvidia_smi(monkeypatch):
    def fail(*args, **kwargs):
        raise FileNotFoundError("nvidia-smi")

    monkeypatch.setattr("src.services.generation_run_evidence.subprocess.run", fail)

    evidence = collect_gpu_evidence()

    assert evidence["status"] == "unavailable"
    assert evidence["devices"] == []
    assert "nvidia-smi" in evidence["reason"]
