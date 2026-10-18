"""Version-bound human decisions for localization QA reports."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path


class LocalizationReviewStore:
    def __init__(self, report_path: str | Path):
        report = Path(report_path)
        self.path = report.with_name("human_review.json")

    @staticmethod
    def report_signature(report: dict) -> str:
        encoded = json.dumps(report, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(encoded.encode("utf-8")).hexdigest()

    def _read(self) -> dict:
        try:
            value = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {"version": 1, "decision": None}
        return value if isinstance(value, dict) else {"version": 1, "decision": None}

    def record(self, decision: str, note: str, report: dict, user_id: int | None = None) -> dict:
        if decision not in {"approved", "rejected"}:
            raise ValueError("Localization review decision must be approved or rejected")
        if len(note) > 1000:
            raise ValueError("Localization review note must be 1000 characters or fewer")
        entry = {
            "decision": decision,
            "note": note.strip(),
            "report_signature": self.report_signature(report),
            "reviewed_by": user_id,
            "reviewed_at": datetime.now(timezone.utc).isoformat(),
        }
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps({"version": 1, "decision": entry}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return entry

    def apply(self, report: dict) -> dict:
        entry = self._read().get("decision")
        if not isinstance(entry, dict):
            return {"decision": "missing"}
        if entry.get("report_signature") != self.report_signature(report):
            return {"decision": "stale", "reviewed_at": entry.get("reviewed_at")}
        return dict(entry)
