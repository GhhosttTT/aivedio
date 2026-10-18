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
KNOWN_PLATFORMS = ("抖音", "快手", "视频号", "小红书", "tiktok", "reels", "shorts", "youtube")
HOOK_SIGNALS = (
    "秘密", "证据", "背叛", "危机", "威胁", "身份", "反转", "失踪", "离婚", "曝光",
    "复仇", "重生", "secret", "evidence", "betrayal", "threat", "identity", "twist",
)
RISK_TERMS = ("未成年人", "暴力", "血腥", "自残", "色情", "赌博", "仇恨", "minor", "violence", "gambling")


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
        result = {
            "status": "ready" if not missing else "incomplete",
            "missing": missing,
            "brief": payload,
            "path": str(self.path(project_id)),
        }
        if not missing:
            result.update(self._score(payload))
        return result

    def _score(self, brief: dict) -> dict:
        """Score commercial specificity without pretending to predict virality.

        The score is an explainable preflight: it measures whether the brief is
        specific enough to drive script, visual, and platform decisions. It is
        deliberately separate from popularity or revenue forecasting.
        """
        audience = str(brief.get("audience") or "").strip()
        platform = str(brief.get("platform") or "").strip().lower()
        genre = str(brief.get("genre") or "").strip()
        hook = str(brief.get("hook_type") or "").strip().lower()
        region = str(brief.get("region") or "").strip()
        policy = str(brief.get("policy_notes") or "").strip()
        sensitive_text = hook + " " + genre
        sensitive_theme = any(term in sensitive_text for term in RISK_TERMS)
        policy_addresses_risk = any(term in policy for term in RISK_TERMS) or "无" in policy.lower() or "none" in policy.lower()
        signals = {
            "audience_specific": len(audience) >= 4 and bool(
                any(token in audience for token in ("岁", "年龄", "女性", "男性", "受众", "viewers", "audience"))
                or any(char.isdigit() for char in audience)
            ),
            "platform_specific": any(token in platform for token in KNOWN_PLATFORMS),
            "genre_specific": len(genre) >= 2,
            "hook_specific": len(hook) >= 2 and any(token.lower() in hook for token in HOOK_SIGNALS),
            "region_specific": len(region) >= 2,
            "policy_reviewed": bool(policy),
            "risk_disclosed": not sensitive_theme or policy_addresses_risk,
        }
        points = {
            "audience_specific": 2,
            "platform_specific": 2,
            "genre_specific": 1,
            "hook_specific": 2,
            "region_specific": 1,
            "policy_reviewed": 1,
            "risk_disclosed": 1,
        }
        score = sum(points[name] for name, passed in signals.items() if passed)
        missing = [name for name, passed in signals.items() if not passed]
        recommendations = {
            "audience_specific": "Specify audience age/identity and viewing motivation.",
            "platform_specific": "Name the target platform and vertical/landscape delivery context.",
            "genre_specific": "Use a concrete commercial genre rather than a broad theme.",
            "hook_specific": "Describe a visible first-minute hook: secret, threat, evidence, identity, or reversal.",
            "region_specific": "Lock region and language for casting, dialogue, and compliance.",
            "policy_reviewed": "Record brand and policy constraints, or explicitly write 'none'.",
            "risk_disclosed": "Review sensitive themes and document the mitigation in policy notes.",
        }
        return {
            "score": score,
            "score_max": sum(points.values()),
            "score_status": "passed" if score >= 8 else ("warn" if score >= 5 else "weak"),
            "signals": signals,
            "score_missing": missing,
            "recommendations": [recommendations[item] for item in missing],
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
