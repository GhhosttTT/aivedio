"""Version-bound human review decisions for generation reports."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone

from src.utils.atomic_json import write_json_atomic
from src.utils.storage import storage_manager


class HumanReviewStore:
    def __init__(self, project_id: int):
        self.path = storage_manager.get_project_path(project_id) / "reviews" / "human_decisions.json"

    @staticmethod
    def report_signature(report: dict) -> str:
        payload = {key: value for key, value in report.items() if key != "human_decision"}
        encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(encoded.encode("utf-8")).hexdigest()

    def _read(self) -> dict:
        try:
            value = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {"version": 1, "decisions": {}}
        return value if isinstance(value, dict) and isinstance(value.get("decisions"), dict) else {"version": 1, "decisions": {}}

    def record(self, report_key: str, decision: str, note: str, report: dict, user_id: int | None = None) -> dict:
        if decision not in {"approved", "rejected"}:
            raise ValueError("Human review decision must be approved or rejected")
        if not str(report_key).strip():
            raise ValueError("Report key is required")
        if len(note) > 1000:
            raise ValueError("Human review note must be 1000 characters or fewer")
        payload = self._read()
        entry = {
            "report_key": report_key,
            "decision": decision,
            "note": note.strip(),
            "report_signature": self.report_signature(report),
            "reviewed_by": user_id,
            "reviewed_at": datetime.now(timezone.utc).isoformat(),
        }
        payload["decisions"][report_key] = entry
        write_json_atomic(self.path, payload)
        return entry

    def apply(self, reports: dict[str, dict]) -> dict[str, dict]:
        decisions = self._read().get("decisions", {})
        active: dict[str, dict] = {}
        for key, report in reports.items():
            if not isinstance(report, dict):
                continue
            entry = decisions.get(key)
            if not isinstance(entry, dict):
                continue
            if entry.get("report_signature") == self.report_signature(report):
                report["human_decision"] = dict(entry)
                active[key] = dict(entry)
            else:
                report["human_decision"] = {
                    "decision": "stale",
                    "report_key": key,
                    "reviewed_at": entry.get("reviewed_at"),
                }
        return active

    def active(self, report_key: str, report: dict) -> dict | None:
        """Return a decision only when it still matches the supplied report."""
        entry = self._read().get("decisions", {}).get(report_key)
        if not isinstance(entry, dict):
            return None
        if entry.get("report_signature") != self.report_signature(report):
            return {"decision": "stale", "report_key": report_key, "reviewed_at": entry.get("reviewed_at")}
        return dict(entry)
