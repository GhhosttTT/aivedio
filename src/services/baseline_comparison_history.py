"""Versioned history for Seed Dance baseline comparisons."""

from __future__ import annotations

import json
from datetime import datetime, timezone

from src.config import settings
from src.utils.atomic_json import json_update_lock, write_json_atomic
from src.utils.storage import storage_manager


class BaselineComparisonHistoryStore:
    MAX_ENTRIES = 50

    def __init__(self, project_id: int):
        self.path = storage_manager.get_project_path(project_id) / "reviews" / "seed_dance_baseline_history.json"

    def _read(self) -> list[dict]:
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return []
        return [item for item in payload.get("entries", []) if isinstance(item, dict)] if isinstance(payload, dict) else []

    def record(self, report: dict) -> dict:
        entry = {
            "recorded_at": datetime.now(timezone.utc).isoformat(),
            "status": report.get("status"),
            "score": report.get("score"),
            "min_score": report.get("min_score"),
            "candidate_video_path": report.get("candidate_video_path"),
            "baseline_video_path": report.get("baseline_video_path"),
            "candidate_signature": report.get("candidate_signature"),
            "baseline_signature": report.get("baseline_signature"),
            "candidate_sha256": report.get("candidate_sha256"),
            "baseline_sha256": report.get("baseline_sha256"),
            "gates": dict(report.get("gates") or {}),
            "differences": dict(report.get("differences") or {}),
        }
        identity = (entry.get("candidate_sha256"), entry.get("baseline_sha256"))
        with json_update_lock(self.path):
            entries = [
                item for item in self._read()
                if (item.get("candidate_sha256"), item.get("baseline_sha256")) != identity
            ]
            entries.append(entry)
            entries = entries[-self.MAX_ENTRIES:]
            write_json_atomic(self.path, {"version": 1, "entries": entries})
        return self.summary(entries)

    def summary(self, entries: list[dict] | None = None) -> dict:
        entries = list(entries if entries is not None else self._read())
        scored = [item for item in entries if isinstance(item.get("score"), (int, float))]
        current = scored[-1] if scored else None
        previous = scored[-2] if len(scored) > 1 else None
        current_score = current.get("score") if current else None
        previous_score = previous.get("score") if previous else None
        delta = round(float(current_score) - float(previous_score), 3) if current and previous else None
        regression_tolerance = float(settings.GENERATION_SEED_DANCE_BASELINE_REGRESSION_TOLERANCE)
        return {
            "count": len(entries),
            "passed_count": sum(1 for item in entries if item.get("status") == "passed"),
            "current_score": current_score,
            "previous_score": previous_score,
            "best_score": max((float(item["score"]) for item in scored), default=None),
            "score_delta": delta,
            "regression_tolerance": regression_tolerance,
            "regression": bool(delta is not None and delta < -regression_tolerance),
            "entries": entries[-10:],
        }
