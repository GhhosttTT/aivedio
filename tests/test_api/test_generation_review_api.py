import json
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from fastapi import HTTPException

from src.api.routes.projects import get_generation_review
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
