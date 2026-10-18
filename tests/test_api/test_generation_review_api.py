import json
import asyncio
from io import BytesIO
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from fastapi import HTTPException
from starlette.datastructures import UploadFile

from src.api.routes.projects import (
    SeedDanceBaselineRequest,
    _generation_review_summary,
    record_human_review,
    compare_seed_dance_baseline,
    create_delivery_package,
    get_generation_review,
    upload_seed_dance_baseline,
)
from src.services.generation_review import write_report


def test_review_requires_owned_project():
    db = Mock()
    db.query.return_value.filter.return_value.first.return_value = None
    with pytest.raises(HTTPException) as exc:
        asyncio.run(get_generation_review(1, SimpleNamespace(id=2), db))
    assert exc.value.status_code == 404
    conditions = db.query.return_value.filter.call_args.args
    assert len(conditions) == 2


def test_review_api_returns_score_evidence(tmp_path, monkeypatch):
    from src.utils.storage import storage_manager
    monkeypatch.setattr(storage_manager, "base_path", tmp_path)
    root = storage_manager.get_project_path(1) / "reviews"
    write_report(root / "story.json", {"status": "needs_review", "average": 2.5, "reason": "prop continuity"})
    db = Mock()
    db.query.return_value.filter.return_value.first.return_value = SimpleNamespace(id=1)
    result = asyncio.run(get_generation_review(1, SimpleNamespace(id=2), db))
    assert result["reports"]["story"]["status"] == "needs_review"
    assert result["reports"]["story"]["average"] == 2.5
    assert result["summary"]["status"] == "blocked"


def test_review_api_includes_final_composition_report(tmp_path, monkeypatch):
    from src.utils.storage import storage_manager
    monkeypatch.setattr(storage_manager, "base_path", tmp_path)
    project_root = storage_manager.get_project_path(1)
    final_video = project_root / "final.mp4"
    final_video.write_bytes(b"video")
    final_video.with_suffix(".composition_review.json").write_text(
        json.dumps({"status": "needs_review", "average": 3.1, "error": "audio drift"}),
        encoding="utf-8",
    )
    db = Mock()
    db.query.return_value.filter.return_value.first.return_value = SimpleNamespace(
        id=1, final_video_path=str(final_video), scenes=[],
    )

    result = asyncio.run(get_generation_review(1, SimpleNamespace(id=2), db))

    assert result["reports"]["final_composition"]["average"] == 3.1
    assert result["summary"]["status"] == "blocked"
    assert any("final composition quality gate" in item for item in result["summary"]["action_items"])


def test_review_api_blocks_final_video_without_composition_evidence(tmp_path, monkeypatch):
    from src.utils.storage import storage_manager
    monkeypatch.setattr(storage_manager, "base_path", tmp_path)
    project_root = storage_manager.get_project_path(1)
    final_video = project_root / "final.mp4"
    final_video.write_bytes(b"video")
    db = Mock()
    db.query.return_value.filter.return_value.first.return_value = SimpleNamespace(
        id=1, final_video_path=str(final_video), scenes=[],
    )

    result = asyncio.run(get_generation_review(1, SimpleNamespace(id=2), db))

    assert result["reports"]["final_composition"]["status"] == "needs_review"
    assert result["summary"]["status"] == "blocked"
    assert result["summary"]["human_final_review_required"] is True
    assert any("final composition quality gate" in item for item in result["summary"]["action_items"])


def test_review_api_persists_version_bound_project_audits(tmp_path, monkeypatch):
    from src.utils.storage import storage_manager
    monkeypatch.setattr(storage_manager, "base_path", tmp_path)
    scenes = [
        SimpleNamespace(
            scene_number=1, visual_description="A room", dialogue="Hello", character_name="A",
            location="room", audio_duration=1.5, image_path=None, video_path=None,
        ),
        SimpleNamespace(
            scene_number=2, visual_description="A room", dialogue="Bye", character_name="A",
            location="room", audio_duration=1.5, image_path=None, video_path=None,
        ),
    ]
    monkeypatch.setattr(
        "src.api.routes.projects.ContinuityAuditService.audit",
        lambda self, project, scenes: SimpleNamespace(
            to_dict=lambda: {"kind": "continuity_audit", "status": "passed", "pair_count": 1}
        ),
    )
    monkeypatch.setattr(
        "src.api.routes.projects.RhythmAuditService.audit",
        lambda self, project, scenes: SimpleNamespace(
            to_dict=lambda: {"kind": "rhythm_audit", "status": "passed", "scene_count": 2}
        ),
    )
    db = Mock()
    db.query.return_value.filter.return_value.first.return_value = SimpleNamespace(
        id=1, user_id=2, script="{}", scenes=scenes, final_video_path=None,
    )

    result = asyncio.run(get_generation_review(1, SimpleNamespace(id=2), db))

    assert result["reports"]["continuity_audit"]["evidence_schema_version"] == 1
    assert result["reports"]["rhythm_audit"]["input_hash"]
    assert (storage_manager.get_project_path(1) / "reviews" / "continuity_audit.json").is_file()
    assert (storage_manager.get_project_path(1) / "reviews" / "rhythm_audit.json").is_file()


def test_review_api_marks_final_composition_stale_after_video_changes(tmp_path, monkeypatch):
    from src.utils.storage import storage_manager
    monkeypatch.setattr(storage_manager, "base_path", tmp_path)
    project_root = storage_manager.get_project_path(1)
    final_video = project_root / "final.mp4"
    final_video.write_bytes(b"new-final-video")
    final_video.with_suffix(".composition_review.json").write_text(
        json.dumps({
            "status": "passed",
            "video_path": str(final_video),
            "video_signature": "old-final-version",
        }),
        encoding="utf-8",
    )
    db = Mock()
    db.query.return_value.filter.return_value.first.return_value = SimpleNamespace(
        id=1, final_video_path=str(final_video), scenes=[],
    )

    result = asyncio.run(get_generation_review(1, SimpleNamespace(id=2), db))

    assert result["reports"]["final_composition"]["status"] == "stale"
    assert any("final composition quality gate" in item for item in result["summary"]["action_items"])


def test_human_review_endpoint_records_decision_for_owned_report(tmp_path, monkeypatch):
    from src.utils.storage import storage_manager
    monkeypatch.setattr(storage_manager, "base_path", tmp_path)
    root = storage_manager.get_project_path(1) / "reviews"
    write_report(root / "generation.json", {"status": "needs_review", "average": 3.0})
    db = Mock()
    db.query.return_value.filter.return_value.first.return_value = SimpleNamespace(
        id=1, user_id=2, final_video_path=None, scenes=[],
    )

    result = asyncio.run(record_human_review(
        1,
        SimpleNamespace(report_key="generation", decision="approved", note="人工通过"),
        SimpleNamespace(id=2),
        db,
    ))

    assert result["decision"]["decision"] == "approved"
    review = asyncio.run(get_generation_review(1, SimpleNamespace(id=2), db))
    assert review["human_decisions"]["generation"]["note"] == "人工通过"


def test_generation_review_summary_honors_current_human_approval():
    summary = _generation_review_summary({
        "production_story": {"status": "passed"},
        "generation": {
            "status": "needs_review",
            "human_decision": {"decision": "approved"},
        },
        "seed_dance_baseline_comparison": {"status": "passed"},
    })

    assert summary["status"] == "ready"
    assert "generation" in summary["human_approved_reports"]


def test_delivery_package_endpoint_exports_approved_project(tmp_path, monkeypatch):
    from src.utils.storage import storage_manager
    monkeypatch.setattr(storage_manager, "base_path", tmp_path)
    project_root = storage_manager.get_project_path(1)
    final_video = project_root / "final.mp4"
    final_video.write_bytes(b"approved-video")
    db = Mock()
    db.query.return_value.filter.return_value.first.return_value = SimpleNamespace(
        id=1, user_id=2, name="Pilot", theme="悬疑", outline="outline", script="{}",
        final_video_path=str(final_video), scenes=[],
    )
    async def approved_review(*_args, **_kwargs):
        return {
            "reports": {"generation": {"status": "passed"}},
            "summary": {"status": "ready"},
        }

    monkeypatch.setattr("src.api.routes.projects.get_generation_review", approved_review)

    result = asyncio.run(create_delivery_package(1, SimpleNamespace(id=2), db))

    assert result["status"] == "ready"
    assert (project_root / "delivery" / "delivery_package.zip").is_file()


def test_review_api_marks_old_seedance_baseline_stale_after_candidate_changes(tmp_path, monkeypatch):
    from src.utils.storage import storage_manager
    monkeypatch.setattr(storage_manager, "base_path", tmp_path)
    project_root = storage_manager.get_project_path(1)
    candidate = project_root / "final.mp4"
    candidate.write_bytes(b"new-candidate")
    write_report(project_root / "reviews" / "seed_dance_baseline_comparison.json", {
        "kind": "seed_dance_baseline_comparison",
        "status": "passed",
        "candidate_video_path": str(candidate),
        "candidate_signature": "old-version",
        "baseline_video_path": str(project_root / "baseline.mp4"),
        "baseline_signature": "old-baseline-version",
    })
    db = Mock()
    db.query.return_value.filter.return_value.first.return_value = SimpleNamespace(
        id=1, final_video_path=str(candidate), scenes=[],
    )

    result = asyncio.run(get_generation_review(1, SimpleNamespace(id=2), db))

    assert result["reports"]["seed_dance_baseline_comparison"]["status"] == "stale"
    assert any("Seed Dance baseline comparison" in item for item in result["summary"]["action_items"])


def test_review_api_marks_baseline_stale_when_project_has_no_current_candidate(tmp_path, monkeypatch):
    from src.utils.storage import storage_manager
    monkeypatch.setattr(storage_manager, "base_path", tmp_path)
    project_root = storage_manager.get_project_path(1)
    candidate = project_root / "old-final.mp4"
    baseline = project_root / "baseline.mp4"
    candidate.write_bytes(b"old-candidate")
    baseline.write_bytes(b"baseline")
    write_report(project_root / "reviews" / "seed_dance_baseline_comparison.json", {
        "kind": "seed_dance_baseline_comparison",
        "status": "passed",
        "candidate_video_path": str(candidate),
        "baseline_video_path": str(baseline),
        "candidate_signature": "old-version",
        "baseline_signature": "old-baseline",
    })
    db = Mock()
    db.query.return_value.filter.return_value.first.return_value = SimpleNamespace(
        id=1, final_video_path=None, scenes=[],
    )

    result = asyncio.run(get_generation_review(1, SimpleNamespace(id=2), db))

    assert result["reports"]["seed_dance_baseline_comparison"]["status"] == "stale"


def test_review_api_summarizes_repair_queue_from_quality_reports(tmp_path, monkeypatch):
    from src.utils.storage import storage_manager
    monkeypatch.setattr(storage_manager, "base_path", tmp_path)
    project_root = storage_manager.get_project_path(1)
    quality_path = project_root / "images" / "scene_1.quality.json"
    write_report(quality_path, {
        "kind": "image_candidate_selection",
        "status": "needs_review",
        "repair_queue": [
            {
                "priority": "high",
                "stage": "image",
                "action": "refine_prompt_composition",
                "reason": "bad crop",
                "recommendation": "Tighten composition",
            }
        ],
    })
    db = Mock()
    db.query.return_value.filter.return_value.first.return_value = SimpleNamespace(id=1)

    result = asyncio.run(get_generation_review(1, SimpleNamespace(id=2), db))

    assert result["summary"]["repair_queue"]["total"] == 1
    assert result["summary"]["repair_queue"]["actions"] == {"refine_prompt_composition": 1}
    assert result["summary"]["repair_queue"]["items"][0]["source_report"].startswith("quality_images_scene_1")
    plan = result["summary"]["repair_execution_plan"]
    assert plan["manual"][0]["action"] == "refine_prompt_composition"
    assert any("review-images" in command for command in plan["rerun_validation_commands"])
    assert any(str(project_root / "reviews") in command for command in plan["rerun_validation_commands"])
    assert any("Repair queue has 1" in item for item in result["summary"]["action_items"])


def test_generation_review_summary_blocks_complex_shots():
    summary = _generation_review_summary({
        "production_story": {"status": "passed"},
        "generation": {"status": "passed"},
        "shot_complexity": {"status": "needs_split", "summary": {"needs_split": 2, "warn": 1}},
    })

    assert summary["status"] == "blocked"
    assert summary["shot_complexity"]["needs_split"] == 2
    assert any("Split or simplify" in item for item in summary["action_items"])


def test_generation_review_summary_includes_repair_queue():
    summary = _generation_review_summary({
        "production_story": {"status": "passed"},
        "generation": {"status": "passed"},
        "seed_dance_baseline_comparison": {"status": "passed"},
        "shot_complexity": {"status": "passed", "summary": {"needs_split": 0, "warn": 0}},
        "quality_scene_1": {
            "status": "needs_review",
            "repair_queue": [{"priority": "high", "stage": "video", "action": "lower_motion_and_regenerate_video", "execution": "auto"}],
        },
        "quality_scene_2": {
            "status": "needs_review",
            "repair_queue": [{"priority": "high", "stage": "video", "action": "increase_motion_and_regenerate_video", "execution": "auto"}],
        },
        "quality_scene_3": {
            "status": "needs_review",
            "repair_queue": [{"priority": "high", "stage": "workflow", "action": "fix_workflow_profile", "execution": "setup_required"}],
        },
    })

    assert summary["repair_queue"]["total"] == 3
    assert summary["repair_queue"]["actions"]["lower_motion_and_regenerate_video"] == 1
    assert summary["repair_queue"]["actions"]["increase_motion_and_regenerate_video"] == 1
    assert summary["repair_queue"]["execution"]["auto"] == 2
    assert summary["repair_queue"]["execution"]["setup_required"] == 1
    assert {
        item["action"] for item in summary["repair_queue"]["auto_actions"]
    } == {"lower_motion_and_regenerate_video", "increase_motion_and_regenerate_video"}
    assert summary["repair_queue"]["setup_required"][0]["action"] == "fix_workflow_profile"
    assert {
        item["action"] for item in summary["repair_execution_plan"]["auto"]
    } == {"lower_motion_and_regenerate_video", "increase_motion_and_regenerate_video"}
    assert summary["repair_execution_plan"]["setup_required"][0]["action"] == "fix_workflow_profile"
    assert any("compare-baseline" in command for command in summary["repair_execution_plan"]["rerun_validation_commands"])


def test_generation_review_summary_ready_when_reviews_pass():
    summary = _generation_review_summary({
        "production_story": {"status": "passed"},
        "generation": {"status": "passed"},
        "seed_dance_baseline_comparison": {"status": "passed"},
        "shot_complexity": {"status": "passed", "summary": {"needs_split": 0, "warn": 0}},
    })

    assert summary["status"] == "ready"
    assert summary["action_items"] == []


def test_generation_review_summary_blocks_failed_composition():
    summary = _generation_review_summary({
        "production_story": {"status": "passed"},
        "generation": {"status": "passed"},
        "seed_dance_baseline_comparison": {"status": "passed"},
        "final_composition": {"status": "needs_review"},
    })

    assert summary["status"] == "blocked"


def test_generation_review_summary_requires_final_human_approval():
    summary = _generation_review_summary({
        "production_story": {"status": "passed"},
        "generation": {"status": "passed"},
        "seed_dance_baseline_comparison": {"status": "passed"},
        "final_composition": {"status": "passed"},
    })

    assert summary["status"] == "blocked"
    assert summary["human_final_review_required"] is True
    assert summary["human_final_review_status"] is None
    assert any("final episode human review" in item for item in summary["action_items"])


def test_generation_review_summary_accepts_approved_final_human_review():
    summary = _generation_review_summary({
        "production_story": {"status": "passed"},
        "generation": {"status": "passed"},
        "seed_dance_baseline_comparison": {"status": "passed"},
        "final_composition": {
            "status": "passed",
            "human_decision": {"decision": "approved", "note": "人工通过"},
        },
    })

    assert summary["status"] == "ready"
    assert summary["human_final_review_status"] == "approved"
    assert "final_composition" in summary["human_approved_reports"]


def test_generation_review_summary_requires_seed_dance_baseline():
    summary = _generation_review_summary({
        "production_story": {"status": "passed"},
        "generation": {"status": "passed"},
        "shot_complexity": {"status": "passed", "summary": {"needs_split": 0, "warn": 0}},
    })

    assert summary["status"] == "blocked"
    assert any("Seed Dance baseline" in item for item in summary["action_items"])


def test_seed_dance_baseline_endpoint_writes_project_review(tmp_path, monkeypatch):
    from src.utils.storage import storage_manager
    from scripts import compare_video_baseline

    monkeypatch.setattr(storage_manager, "base_path", tmp_path / "storage")
    candidate = tmp_path / "candidate.mp4"
    baseline = tmp_path / "baseline.mp4"
    candidate.write_bytes(b"candidate")
    baseline.write_bytes(b"baseline")
    monkeypatch.setattr(compare_video_baseline, "compare", lambda *_args, **_kwargs: {
        "kind": "seed_dance_baseline_comparison",
        "status": "passed",
        "contact_sheet_path": str(storage_manager.get_project_path(1) / "reviews" / "seed_dance_contact_sheet.png"),
        "gates": {"duration_close": True},
    })
    db = Mock()
    db.query.return_value.filter.return_value.first.return_value = SimpleNamespace(
        id=1,
        user_id=2,
        final_video_path=str(candidate),
    )

    result = asyncio.run(compare_seed_dance_baseline(
        1,
        SeedDanceBaselineRequest(baseline_path=str(baseline)),
        SimpleNamespace(id=2),
        db,
    ))

    assert result["status"] == "passed"
    assert result["candidate_video_path"] == str(candidate)
    assert result["baseline_video_path"] == str(baseline)
    assert result["candidate_signature"]
    assert result["baseline_signature"]
    assert result["contact_sheet_path"].endswith("seed_dance_contact_sheet.png")
    report = storage_manager.get_project_path(1) / "reviews" / "seed_dance_baseline_comparison.json"
    assert json.loads(report.read_text(encoding="utf-8"))["kind"] == "seed_dance_baseline_comparison"


def test_seed_dance_baseline_upload_writes_project_review(tmp_path, monkeypatch):
    from src.utils.storage import storage_manager
    from scripts import compare_video_baseline

    monkeypatch.setattr(storage_manager, "base_path", tmp_path / "storage")
    candidate = tmp_path / "candidate.mp4"
    candidate.write_bytes(b"candidate")
    monkeypatch.setattr(compare_video_baseline, "compare", lambda candidate_path, baseline_path, **_kwargs: {
        "kind": "seed_dance_baseline_comparison",
        "status": "passed",
        "candidate_seen": str(candidate_path),
        "baseline_seen": str(baseline_path),
        "contact_sheet_path": str(storage_manager.get_project_path(1) / "reviews" / "seed_dance_contact_sheet.png"),
        "gates": {"duration_close": True},
    })
    db = Mock()
    db.query.return_value.filter.return_value.first.return_value = SimpleNamespace(
        id=1,
        user_id=2,
        final_video_path=str(candidate),
    )
    upload = UploadFile(filename="baseline.mp4", file=BytesIO(b"baseline-video"))

    result = asyncio.run(upload_seed_dance_baseline(1, upload, SimpleNamespace(id=2), db))

    assert result["status"] == "passed"
    saved_baseline = storage_manager.get_project_path(1) / "reviews" / "baselines" / "seed_dance_baseline.mp4"
    assert saved_baseline.read_bytes() == b"baseline-video"
    assert result["candidate_video_path"] == str(candidate)
    assert result["baseline_video_path"] == str(saved_baseline)
    assert result["candidate_signature"]
    assert result["baseline_signature"]
    assert result["contact_sheet_path"].endswith("seed_dance_contact_sheet.png")
    report = storage_manager.get_project_path(1) / "reviews" / "seed_dance_baseline_comparison.json"
    assert json.loads(report.read_text(encoding="utf-8"))["uploaded_baseline_path"] == str(saved_baseline)


def test_seed_dance_baseline_upload_rejects_non_video(tmp_path, monkeypatch):
    from src.utils.storage import storage_manager

    monkeypatch.setattr(storage_manager, "base_path", tmp_path / "storage")
    candidate = tmp_path / "candidate.mp4"
    candidate.write_bytes(b"candidate")
    db = Mock()
    db.query.return_value.filter.return_value.first.return_value = SimpleNamespace(
        id=1,
        user_id=2,
        final_video_path=str(candidate),
    )
    upload = UploadFile(filename="baseline.txt", file=BytesIO(b"not-video"))

    with pytest.raises(HTTPException) as exc:
        asyncio.run(upload_seed_dance_baseline(1, upload, SimpleNamespace(id=2), db))

    assert exc.value.status_code == 400
