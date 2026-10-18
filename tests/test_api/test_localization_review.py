import asyncio
import json
from types import SimpleNamespace

from src.api.routes.localization import record_localization_quality_review


def test_localization_quality_review_records_operator(tmp_path):
    report_path = tmp_path / "moderation_report.json"
    report_path.write_text(json.dumps({"status": "passed", "score": 0.9}), encoding="utf-8")
    job = SimpleNamespace(id=4, moderation_report_path=str(report_path))
    query = SimpleNamespace(filter=lambda *_args: query, first=lambda: job)
    db = SimpleNamespace(query=lambda *_args: query)

    result = asyncio.run(record_localization_quality_review(
        4,
        SimpleNamespace(decision="approved", note="人工确认"),
        SimpleNamespace(id=12),
        db,
    ))

    assert result["human_review"]["reviewed_by"] == 12
    saved = json.loads((tmp_path / "human_review.json").read_text(encoding="utf-8"))
    assert saved["decision"]["reviewed_by"] == 12
