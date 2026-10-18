"""Structured market and audience brief used to stabilize story generation."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from src.utils.storage import storage_manager


TOPIC_BRIEF_FIELDS = (
    "audience",
    "platform",
    "genre",
    "hook_type",
    "region",
    "policy_notes",
)
REQUIRED_TOPIC_BRIEF_FIELDS = TOPIC_BRIEF_FIELDS[:5]


class TopicBriefService:
    def path(self, project_id: int) -> Path:
        return storage_manager.get_project_path(project_id) / "topic_brief.json"

    def normalize(self, payload: dict) -> dict:
        if not isinstance(payload, dict):
            raise ValueError("Topic brief must be an object")
        normalized = {field: str(payload.get(field) or "").strip() for field in TOPIC_BRIEF_FIELDS}
        missing = [field for field in REQUIRED_TOPIC_BRIEF_FIELDS if not normalized[field]]
        if missing:
            raise ValueError("Missing topic brief fields: " + ", ".join(missing))
        if any(len(normalized[field]) > 240 for field in TOPIC_BRIEF_FIELDS):
            raise ValueError("Topic brief fields must be 240 characters or fewer")
        return normalized

    def save(self, project_id: int, payload: dict) -> dict:
        normalized = self.normalize(payload)
        result = {
            **normalized,
            "status": "ready",
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        path = self.path(project_id)
        path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return result

    def load(self, project_id: int) -> dict | None:
        path = self.path(project_id)
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        return payload if isinstance(payload, dict) else None

    def check(self, project_id: int) -> dict:
        payload = self.load(project_id)
        if payload is None:
            return {"status": "missing", "missing": list(REQUIRED_TOPIC_BRIEF_FIELDS), "brief": {}}
        missing = [field for field in REQUIRED_TOPIC_BRIEF_FIELDS if not str(payload.get(field) or "").strip()]
        return {
            "status": "ready" if not missing else "incomplete",
            "missing": missing,
            "brief": payload,
            "path": str(self.path(project_id)),
        }

    def prompt_fragment(self, project_id: int) -> str:
        report = self.check(project_id)
        if report["status"] != "ready":
            return ""
        brief = report["brief"]
        return (
            "\nMARKET AND AUDIENCE LOCK:\n"
            f"Target audience: {brief['audience']}\n"
            f"Platform: {brief['platform']}\n"
            f"Genre: {brief['genre']}\n"
            f"Opening hook type: {brief['hook_type']}\n"
            f"Region/language: {brief['region']}\n"
            f"Policy and brand constraints: {brief.get('policy_notes') or 'none specified'}\n"
            "Keep the hook, visual tone, dialogue density, and ending payoff aligned with this lock."
        )
