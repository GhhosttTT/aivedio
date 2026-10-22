"""Structured market and audience brief used to stabilize story generation."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from src.utils.atomic_json import write_json_atomic
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
MARKET_SIGNAL_FIELDS = ("comparables", "differentiation", "success_metric", "notes")


class TopicBriefService:
    def path(self, project_id: int) -> Path:
        return storage_manager.get_project_path(project_id) / "topic_brief.json"

    def market_signal_path(self, project_id: int) -> Path:
        return storage_manager.get_project_path(project_id) / "market_signals.json"

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
        write_json_atomic(path, result)
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
            result["market_fit"] = self.market_score(project_id)
        return result

    def normalize_market_signals(self, payload: dict) -> dict:
        if not isinstance(payload, dict):
            raise ValueError("Market signals must be an object")
        comparables = payload.get("comparables") or []
        if not isinstance(comparables, list):
            raise ValueError("comparables must be a list")
        normalized = []
        for item in comparables[:12]:
            if isinstance(item, str):
                title = item.strip()
                item = {"title": title}
            if not isinstance(item, dict):
                raise ValueError("Each comparable must be an object or title")
            comparable = {
                "title": str(item.get("title") or "").strip(),
                "platform": str(item.get("platform") or "").strip(),
                "genre": str(item.get("genre") or "").strip(),
                "hook": str(item.get("hook") or "").strip(),
                "audience": str(item.get("audience") or "").strip(),
                "signal": str(item.get("signal") or "").strip(),
            }
            if not comparable["title"]:
                raise ValueError("Each comparable must have a title")
            if any(len(value) > 240 for value in comparable.values()):
                raise ValueError("Comparable fields must be 240 characters or fewer")
            normalized.append(comparable)
        result = {
            "comparables": normalized,
            "differentiation": str(payload.get("differentiation") or "").strip(),
            "success_metric": str(payload.get("success_metric") or "").strip(),
            "notes": str(payload.get("notes") or "").strip(),
        }
        if any(len(result[field]) > 500 for field in ("differentiation", "success_metric", "notes")):
            raise ValueError("Market signal notes must be 500 characters or fewer")
        if not normalized:
            raise ValueError("At least one comparable is required")
        return result

    def save_market_signals(self, project_id: int, payload: dict) -> dict:
        normalized = self.normalize_market_signals(payload)
        result = {**normalized, "updated_at": datetime.now(timezone.utc).isoformat()}
        write_json_atomic(self.market_signal_path(project_id), result)
        return result

    def load_market_signals(self, project_id: int) -> dict | None:
        try:
            payload = json.loads(self.market_signal_path(project_id).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        return payload if isinstance(payload, dict) else None

    def market_score(self, project_id: int) -> dict:
        evidence = self.load_market_signals(project_id)
        if evidence is None:
            return {"status": "missing", "score": 0, "score_max": 5, "missing": list(MARKET_SIGNAL_FIELDS)}
        comparables = [item for item in evidence.get("comparables", []) if isinstance(item, dict)]
        signals = {
            "comparable_library": len(comparables) >= 2,
            "platform_or_genre_match": any(
                item.get("platform") or item.get("genre") for item in comparables
            ),
            "performance_signal": any(item.get("signal") for item in comparables),
            "differentiation": len(str(evidence.get("differentiation") or "")) >= 20,
            "success_metric": len(str(evidence.get("success_metric") or "")) >= 6,
        }
        missing = [name for name, passed in signals.items() if not passed]
        score = sum(signals.values())
        recommendations = {
            "comparable_library": "Add at least two comparable short dramas.",
            "platform_or_genre_match": "Record the comparable platform or commercial genre.",
            "performance_signal": "Capture a concrete comparable signal such as completion, comments, or retention.",
            "differentiation": "Explain the visible premise or emotional difference from the comparables.",
            "success_metric": "Define a measurable success metric for the first release batch.",
        }
        return {
            "status": "passed" if score >= 4 else ("warn" if score >= 2 else "weak"),
            "score": score,
            "score_max": len(signals),
            "signals": signals,
            "missing": missing,
            "recommendations": [recommendations[item] for item in missing],
            "evidence": evidence,
            "path": str(self.market_signal_path(project_id)),
        }

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
        market_fit = report.get("market_fit") or {}
        evidence_hint = ""
        if market_fit.get("status") == "passed":
            evidence_hint = (
                "\nMARKET EVIDENCE LOCK:\n"
                f"Comparable titles: {', '.join(item.get('title', '') for item in market_fit.get('evidence', {}).get('comparables', []))}\n"
                f"Differentiation: {market_fit.get('evidence', {}).get('differentiation', '')}\n"
                f"Success metric: {market_fit.get('evidence', {}).get('success_metric', '')}\n"
            )
        return (
            "\nMARKET AND AUDIENCE LOCK:\n"
            f"Target audience: {brief['audience']}\n"
            f"Platform: {brief['platform']}\n"
            f"Genre: {brief['genre']}\n"
            f"Opening hook type: {brief['hook_type']}\n"
            f"Region/language: {brief['region']}\n"
            f"Policy and brand constraints: {brief.get('policy_notes') or 'none specified'}\n"
            "Keep the hook, visual tone, dialogue density, and ending payoff aligned with this lock."
            + evidence_hint
        )
