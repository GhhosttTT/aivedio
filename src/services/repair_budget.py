"""Bounded retry bookkeeping for automatic quality repairs."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
import time
from contextlib import contextmanager
from datetime import datetime, timezone

from src.utils.storage import storage_manager

try:
    import fcntl
except ImportError:  # pragma: no cover - Windows uses the atomic write fallback.
    fcntl = None


class RepairBudget:
    """Persist a small per-project budget so auto-repair cannot loop forever."""

    MAX_ATTEMPTS = 2
    MAX_TOTAL_ATTEMPTS = 8
    RESERVATION_TTL_SECONDS = 3600

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
            return {"version": 3, "attempts": {}, "total_attempts": 0, "reservations": {}}
        if not isinstance(payload, dict) or not isinstance(payload.get("attempts"), dict):
            return {"version": 3, "attempts": {}, "total_attempts": 0, "reservations": {}}
        # Version 1 files did not persist a project-wide count. Derive it so
        # an upgrade cannot silently reset an already-used retry budget.
        if not isinstance(payload.get("total_attempts"), int):
            payload["total_attempts"] = sum(
                max(0, int(item.get("count", 0)))
                for item in payload["attempts"].values()
                if isinstance(item, dict)
            )
        payload["version"] = max(3, int(payload.get("version", 1) or 1))
        if not isinstance(payload.get("reservations"), dict):
            payload["reservations"] = {}
        return payload

    def _write(self, payload: dict) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{self.path.name}.", suffix=".tmp", dir=self.path.parent,
        )
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
                json.dump(payload, stream, ensure_ascii=False, indent=2)
                stream.write("\n")
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary_name, self.path)
        finally:
            if os.path.exists(temporary_name):
                os.unlink(temporary_name)

    @contextmanager
    def _locked(self):
        lock_path = self.path.with_name(f".{self.path.name}.lock")
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        with lock_path.open("a+", encoding="utf-8") as stream:
            if fcntl is not None:
                fcntl.flock(stream.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                if fcntl is not None:
                    fcntl.flock(stream.fileno(), fcntl.LOCK_UN)

    def _prune_reservations(self, payload: dict) -> None:
        now = time.time()
        reservations = payload.get("reservations")
        if not isinstance(reservations, dict):
            payload["reservations"] = {}
            return
        for key, item in list(reservations.items()):
            if not isinstance(item, dict):
                reservations.pop(key, None)
                continue
            try:
                updated = float(item.get("updated_at", 0))
                count = int(item.get("count", 0))
            except (TypeError, ValueError):
                reservations.pop(key, None)
                continue
            if count <= 0 or now - updated > self.RESERVATION_TTL_SECONDS:
                reservations.pop(key, None)

    @staticmethod
    def _reserved_count(payload: dict, key: str) -> int:
        item = (payload.get("reservations") or {}).get(key, {})
        return max(0, int(item.get("count", 0))) if isinstance(item, dict) else 0

    def _reserve(self, payload: dict, key: str) -> None:
        reservations = payload.setdefault("reservations", {})
        item = reservations.setdefault(key, {"count": 0, "updated_at": 0})
        item["count"] = max(0, int(item.get("count", 0))) + 1
        item["updated_at"] = time.time()

    def filter(self, items: list[dict]) -> tuple[list[dict], list[dict]]:
        with self._locked():
            payload = self._read()
            self._prune_reservations(payload)
            accepted, exhausted = [], []
            committed_total = max(0, int(payload.get("total_attempts", 0)))
            reserved_total = sum(
                self._reserved_count(payload, key)
                for key in payload.get("reservations", {})
            )
            total_attempts = committed_total + reserved_total
            for item in items:
                key = self.key(item)
                committed = int(payload["attempts"].get(key, {}).get("count", 0))
                reserved = self._reserved_count(payload, key)
                attempts = committed + reserved
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
                    self._reserve(payload, key)
                    total_attempts += 1
            self._write(payload)
            return accepted, exhausted

    def record(self, items: list[dict]) -> None:
        with self._locked():
            payload = self._read()
            self._prune_reservations(payload)
            now = datetime.now(timezone.utc).isoformat()
            payload["total_attempts"] = max(0, int(payload.get("total_attempts", 0)))
            for item in items:
                key = self.key(item)
                reservation = self._reserved_count(payload, key)
                if reservation:
                    reservation_entry = payload["reservations"][key]
                    reservation_entry["count"] = reservation - 1
                    if reservation_entry["count"] <= 0:
                        payload["reservations"].pop(key, None)
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

    def release(self, items: list[dict]) -> None:
        """Release reservations when task submission fails before recording."""
        with self._locked():
            payload = self._read()
            for item in items:
                key = self.key(item)
                reservation = self._reserved_count(payload, key)
                if reservation <= 1:
                    payload.get("reservations", {}).pop(key, None)
                else:
                    payload["reservations"][key]["count"] = reservation - 1
            self._write(payload)

    def reset(self) -> None:
        with self._locked():
            self.path.unlink(missing_ok=True)
