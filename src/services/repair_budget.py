"""Bounded retry bookkeeping for automatic quality repairs."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

from src.utils.storage import storage_manager


class RepairBudget:
    """Persist a small per-project budget so auto-repair cannot loop forever."""

    MAX_ATTEMPTS = 2
    MAX_TOTAL_ATTEMPTS = 8

    def __init__(
        self,
        project_id: int,
        max_attempts: int | None = None,
        max_total_attempts: int | None = None,
    ):
        self.path = storage_manager.get_project_path(project_id) / "repair_attempts.json"
        self.max_attempts = max(1, int(max_attempts or self.MAX_ATTEMPTS))
        self.max_total_attempts = max(
            self.max_attempts,
            int(max_total_attempts or self.MAX_TOTAL_ATTEMPTS),
        )

    @staticmethod
    def key(item: dict) -> str:
        material = "|".join(str(item.get(name) or "") for name in (
            "scene_number", "stage", "action", "source_report", "reason",
        ))
        return hashlib.sha256(material.encode("utf-8")).hexdigest()[:24]

    def _read(self) -> dict:
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {"version": 2, "attempts": {}, "total_attempts": 0}
        if not isinstance(payload, dict) or not isinstance(payload.get("attempts"), dict):
            return {"version": 2, "attempts": {}, "total_attempts": 0}
        # Version 1 files did not persist a project-wide count. Derive it so
        # an upgrade cannot silently reset an already-used retry budget.
        if not isinstance(payload.get("total_attempts"), int):
            payload["total_attempts"] = sum(
                max(0, int(item.get("count", 0)))
                for item in payload["attempts"].values()
                if isinstance(item, dict)
            )
        payload["version"] = max(2, int(payload.get("version", 1) or 1))
        return payload

    def _write(self, payload: dict) -> None:
        self.path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    def filter(self, items: list[dict]) -> tuple[list[dict], list[dict]]:
        payload = self._read()
        accepted, exhausted = [], []
        total_attempts = max(0, int(payload.get("total_attempts", 0)))
        for item in items:
            key = self.key(item)
            attempts = int(payload["attempts"].get(key, {}).get("count", 0))
            if total_attempts >= self.max_total_attempts:
                exhausted.append({
                    **item,
                    "execution": "manual",
                    "reason": "project automatic repair retry budget exhausted",
                    "retry_attempts": attempts,
                    "retry_budget": self.max_attempts,
                    "project_retry_attempts": total_attempts,
                    "project_retry_budget": self.max_total_attempts,
                })
            elif attempts >= self.max_attempts:
                exhausted.append({
                    **item,
                    "execution": "manual",
                    "reason": "automatic repair retry budget exhausted",
                    "retry_attempts": attempts,
                    "retry_budget": self.max_attempts,
                    "project_retry_attempts": total_attempts,
                    "project_retry_budget": self.max_total_attempts,
                })
            else:
                accepted.append({
                    **item,
                    "retry_attempts": attempts,
                    "retry_budget": self.max_attempts,
                    "project_retry_attempts": total_attempts,
                    "project_retry_budget": self.max_total_attempts,
                })
                total_attempts += 1
        return accepted, exhausted

    def record(self, items: list[dict]) -> None:
        payload = self._read()
        now = datetime.now(timezone.utc).isoformat()
        payload["total_attempts"] = max(0, int(payload.get("total_attempts", 0)))
        for item in items:
            key = self.key(item)
            current = payload["attempts"].setdefault(key, {"count": 0})
            current["count"] = int(current.get("count", 0)) + 1
            payload["total_attempts"] += 1
            current.update({
                "action": item.get("action"),
                "scene_number": item.get("scene_number"),
                "last_reason": item.get("reason"),
                "updated_at": now,
            })
        self._write(payload)

    def reset(self) -> None:
        self.path.unlink(missing_ok=True)
