import json
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from fastapi import HTTPException

from src.api.routes.projects import _generation_review_summary, get_generation_review
from src.services.generation_review import write_report


@pytest.mark.asyncio
async def test_review_requires_owned_project():
    db = Mock()
    db.query.return_value.filter.return_value.first.return_value = None
    with pytest.raises(HTTPException) as exc:
        await get_generation_review(1, SimpleNamespace(id=2), db)
    assert exc.value.status_code == 404
    conditions = db.query.return_value.filter.call_args.args
    assert len(conditions) == 2


@pytest.mark.asyncio
async def test_review_api_returns_score_evidence(tmp_path, monkeypatch):
    from src.utils.storage import storage_manager
    monkeypatch.setattr(storage_manager, "base_path", tmp_path)
    root = storage_manager.get_project_path(1) / "reviews"
    write_report(root / "story.json", {"status": "needs_review", "average": 2.5, "reason": "prop continuity"})
    db = Mock()
    db.query.return_value.filter.return_value.first.return_value = SimpleNamespace(id=1)
    result = await get_generation_review(1, SimpleNamespace(id=2), db)
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
        "shot_complexity": {"status": "passed", "summary": {"needs_split": 0, "warn": 0}},
    })

    assert summary["status"] == "ready"
    assert summary["action_items"] == []
