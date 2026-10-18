import asyncio
import json
from types import SimpleNamespace

from src.api.routes.localization import record_localization_quality_review


def test_localization_quality_review_records_operator(tmp_path):
    report_path = tmp_path / "moderation_report.json"
    report_path.write_text(json.dumps({"status": "passed", "score": 0.9}), encoding="utf-8")
    job = SimpleNamespace(id=4, moderation_report_path=str(report_path))
    query = SimpleNamespace(filter=lambda *_args: query, first=lambda: job)
    db = SimpleNamespace(query=lambda *_args: query, commit=lambda: None)

    result = asyncio.run(record_localization_quality_review(
        4,
        SimpleNamespace(decision="approved", note="人工确认"),
        SimpleNamespace(id=12),
        db,
    ))

    assert result["human_review"]["reviewed_by"] == 12
    assert job.status.value == "completed"
    saved = json.loads((tmp_path / "human_review.json").read_text(encoding="utf-8"))
    assert saved["decision"]["reviewed_by"] == 12


def test_localization_human_approval_cannot_bypass_failed_qa(tmp_path):
    report_path = tmp_path / "moderation_report.json"
    report_path.write_text(json.dumps({"status": "needs_review", "score": 0.61}), encoding="utf-8")
    job = SimpleNamespace(id=5, moderation_report_path=str(report_path))
    query = SimpleNamespace(filter=lambda *_args: query, first=lambda: job)
    db = SimpleNamespace(query=lambda *_args: query, commit=lambda: None)

    asyncio.run(record_localization_quality_review(
        5,
        SimpleNamespace(decision="approved", note="人工认为可接受"),
        SimpleNamespace(id=12),
        db,
    ))

    assert job.status.value == "needs_review"
    assert "不能覆盖" in job.error_message
