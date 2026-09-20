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
    compare_seed_dance_baseline,
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


def test_generation_review_summary_blocks_complex_shots():
    summary = _generation_review_summary({
        "production_story": {"status": "passed"},
        "generation": {"status": "passed"},
        "shot_complexity": {"status": "needs_split", "summary": {"needs_split": 2, "warn": 1}},
    })

    assert summary["status"] == "blocked"
    assert summary["shot_complexity"]["needs_split"] == 2
    assert any("Split or simplify" in item for item in summary["action_items"])


def test_generation_review_summary_ready_when_reviews_pass():
    summary = _generation_review_summary({
        "production_story": {"status": "passed"},
        "generation": {"status": "passed"},
        "seed_dance_baseline_comparison": {"status": "passed"},
        "shot_complexity": {"status": "passed", "summary": {"needs_split": 0, "warn": 0}},
    })

    assert summary["status"] == "ready"
    assert summary["action_items"] == []


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
