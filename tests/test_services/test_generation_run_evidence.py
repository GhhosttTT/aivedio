from src.services.generation_run_evidence import (
    build_generation_run_evidence,
    build_video_generation_evidence,
    collect_gpu_evidence,
)


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

    assert evidence["schema_version"] == 2
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


def test_build_video_generation_evidence_tracks_attempts_and_provider_contracts():
    evidence = build_video_generation_evidence(
        {
            "status": "passed",
            "selected_path": "clip.candidate_02.mp4",
            "promoted_path": "clip.mp4",
            "video_sha256": "c" * 64,
            "quality_budget": {"candidate_count": 2},
            "candidates": [
                {
                    "path": "clip.candidate_01.mp4",
                    "status": "needs_review",
                    "elapsed_seconds": 3.4,
                    "provider_metadata": {
                        "provider_name": "seedance_api",
                        "provider_task_id": "task-1",
                        "video_sha256": "a" * 64,
                        "request_contract_hash": "hash-a",
                        "request_contract": {"spatial_asset_pack": {
                            "scene_contract_hash": "scene-a", "project_signature": "project-a",
                        }},
                    },
                },
                {
                    "path": "clip.candidate_02.mp4",
                    "status": "passed",
                    "elapsed_seconds": 4.6,
                    "provider_metadata": {
                        "provider_name": "seedance_api",
                        "provider_task_id": "task-2",
                        "video_sha256": "b" * 64,
                        "request_contract_hash": "hash-b",
                        "request_contract": {"spatial_asset_pack": {
                            "scene_contract_hash": "scene-b", "project_signature": "project-a",
                        }},
                    },
                },
                {"path": "clip.candidate_03.mp4", "status": "error", "elapsed_seconds": 0.2},
            ],
        },
        generated_at=456,
    )

    assert evidence["generated_at"] == 456
    assert evidence["schema_version"] == 2
    assert evidence["attempts"] == {
        "candidate_count": 3,
        "generated_count": 2,
        "passed_count": 1,
        "error_count": 1,
        "elapsed_seconds_sum": 8.2,
        "elapsed_seconds_max": 4.6,
        "pass_rate": 0.5,
    }
    assert evidence["providers"] == ["seedance_api"]
    assert evidence["provider_task_ids"] == ["task-1", "task-2"]
    assert evidence["request_contract_hashes"] == ["hash-a", "hash-b"]
    assert evidence["video_sha256s"] == ["a" * 64, "b" * 64]
    assert evidence["selected_video_sha256"] == "b" * 64
    assert evidence["accepted_video_sha256"] == "c" * 64
    assert evidence["spatial_scene_contract_hashes"] == ["scene-a", "scene-b"]
    assert evidence["spatial_project_signatures"] == ["project-a"]


def test_generation_run_evidence_ignores_non_finite_elapsed_values():
    evidence = build_generation_run_evidence(
        {
            "status": "rendered_pending_human_review",
            "cases": [
                {"image": "one.png", "elapsed_seconds": float("nan")},
                {"image": "two.png", "elapsed_seconds": float("inf")},
                {"image": "three.png", "elapsed_seconds": 2.5},
            ],
        },
        gpu_evidence={"status": "unavailable", "devices": []},
    )

    assert evidence["runtime"]["elapsed_seconds_sum"] == 2.5
    assert evidence["runtime"]["elapsed_seconds_max"] == 2.5


def test_generation_run_evidence_ignores_non_finite_gpu_numbers(monkeypatch):
    class Result:
        stdout = "GPU, nan, inf, 10, 20\n"

    monkeypatch.setattr(
        "src.services.generation_run_evidence.subprocess.run",
        lambda *args, **kwargs: Result(),
    )

    evidence = collect_gpu_evidence()

    assert evidence["status"] == "available"
    assert evidence["devices"][0]["memory_total_mb"] is None
    assert evidence["devices"][0]["memory_used_mb"] is None
