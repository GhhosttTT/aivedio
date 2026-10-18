"""Persistent audit trail for automatic quality-repair cycles."""

from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime, timezone
from uuid import uuid4

from src.utils.storage import storage_manager


class RepairCycleStore:
    """Keep a bounded, project-local history of submitted repair cycles."""

    MAX_CYCLES = 20

    def __init__(self, project_id: int):
        self.path = storage_manager.get_project_path(project_id) / "reviews" / "repair_cycles.json"

    def _read(self) -> dict:
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, TypeError, ValueError):
            return {"schema_version": 1, "cycles": []}
        if not isinstance(payload, dict) or not isinstance(payload.get("cycles"), list):
            return {"schema_version": 1, "cycles": []}
        return payload

    def _write(self, payload: dict) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, temporary_name = tempfile.mkstemp(
            prefix=f".{self.path.name}.", suffix=".tmp", dir=self.path.parent,
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                json.dump(payload, stream, ensure_ascii=False, indent=2)
                stream.write("\n")
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary_name, self.path)
        finally:
            if os.path.exists(temporary_name):
                os.unlink(temporary_name)

    def record(
        self,
        *,
        status: str,
        submitted: list[dict],
        skipped: list[dict],
        considered: list[dict],
    ) -> dict:
        entry = {
            "cycle_id": uuid4().hex,
            "status": str(status),
            "created_at": datetime.now(timezone.utc).isoformat(),
            "considered_count": len(considered),
            "submitted_count": len(submitted),
            "skipped_count": len(skipped),
            "submitted": [self._compact(item) for item in submitted],
            "skipped": [self._compact(item) for item in skipped],
        }
        payload = self._read()
        cycles = [item for item in payload["cycles"] if isinstance(item, dict)]
        payload["cycles"] = (cycles + [entry])[-self.MAX_CYCLES:]
        self._write(payload)
        return entry

    def recent(self, limit: int = 5) -> list[dict]:
        try:
            bounded_limit = max(1, min(int(limit), self.MAX_CYCLES))
        except (TypeError, ValueError):
            bounded_limit = 5
        cycles = [item for item in self._read()["cycles"] if isinstance(item, dict)]
        return list(reversed(cycles[-bounded_limit:]))

    @staticmethod
    def _compact(item: dict) -> dict:
        """Persist stable audit fields, not provider or path internals."""
        return {
            key: item.get(key)
            for key in ("scene_number", "stage", "action", "task_id", "reason")
            if item.get(key) is not None
        }
