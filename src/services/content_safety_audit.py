"""Deterministic pre-generation content-safety audit for story projects."""

from __future__ import annotations

import hashlib
import json
from typing import Any

from src.services.topic_brief import TopicBriefService


RISK_CATEGORIES: dict[str, tuple[str, ...]] = {
    "minors": ("未成年人", "未成年", "儿童色情", "minor", "underage"),
    "violence": ("暴力", "血腥", "虐待", "肢解", "violence", "violent", "blood", "assault", "gore", "torture"),
    "self_harm": ("自残", "自杀", "轻生", "self-harm", "suicide"),
    "sexual": ("色情", "强奸", "性侵", "sexual", "porn", "rape"),
    "gambling": ("赌博", "博彩", "gambling", "casino"),
    "hate": ("仇恨", "种族歧视", "极端主义", "hate", "extremism"),
    "criminal_instruction": ("制毒", "炸弹制作", "诈骗教程", "入侵教程", "drug-making", "bomb-making"),
}


class ContentSafetyAuditService:
    """Scan the actual script/storyboard and route flagged projects to review.

    This is a conservative preflight, not a classifier or legal opinion. It
    reports evidence and never claims that a keyword alone proves a violation.
    """

    def audit(self, project: Any, scenes: list[Any]) -> dict:
        policy = self._policy_notes(project)
        hits: list[dict] = []
        scene_categories: dict[str, dict[str, list[str]]] = {}
        for scene in sorted(list(scenes or []), key=lambda item: getattr(item, "scene_number", 0)):
            fields = {
                "visual_description": str(getattr(scene, "visual_description", "") or ""),
                "dialogue": str(getattr(scene, "dialogue", "") or ""),
            }
            found_in_scene: set[str] = set()
            for field, text in fields.items():
                lowered = text.lower()
                for category, terms in RISK_CATEGORIES.items():
                    matched = [term for term in terms if term.lower() in lowered]
                    if not matched:
                        continue
                    found_in_scene.add(category)
                    hits.append({
                        "scene_number": getattr(scene, "scene_number", None),
                        "field": field,
                        "category": category,
                        "terms": matched,
                    })
            if found_in_scene:
                scene_categories[str(getattr(scene, "scene_number", "unknown"))] = {
                    "categories": sorted(found_in_scene),
                }

        found_categories = sorted({item["category"] for item in hits})
        policy_categories = self._policy_categories(policy)
        uncovered = [category for category in found_categories if category not in policy_categories]
        if not hits:
            status = "passed"
            message = "No configured high-risk content terms were found in the project script or storyboard."
        elif uncovered:
            status = "blocked"
            message = "High-risk content requires explicit policy coverage before production: " + ", ".join(uncovered)
        else:
            status = "needs_review"
            message = "High-risk content is disclosed in policy notes but still requires human safety review before production."
        return {
            "kind": "content_safety_audit",
            "input_hash": self._input_hash(project, scenes, policy),
            "status": status,
            "message": message,
            "policy_notes_present": bool(policy),
            "policy_categories": policy_categories,
            "categories": found_categories,
            "uncovered_categories": uncovered,
            "hit_count": len(hits),
            "hits": hits,
            "scenes": scene_categories,
        }

    @staticmethod
    def _policy_notes(project: Any) -> str:
        project_id = getattr(project, "id", None)
        if project_id is None:
            return ""
        brief = TopicBriefService().load(project_id) or {}
        return str(brief.get("policy_notes") or "").strip()

    @staticmethod
    def _policy_categories(policy: str) -> list[str]:
        lowered = policy.lower()
        return sorted(
            category
            for category, terms in RISK_CATEGORIES.items()
            if any(term.lower() in lowered for term in terms)
        )

    @staticmethod
    def _input_hash(project: Any, scenes: list[Any], policy: str) -> str:
        payload = {
            "project_id": getattr(project, "id", None),
            "policy_notes": policy,
            "scenes": [
                {
                    "scene_number": getattr(scene, "scene_number", None),
                    "visual_description": str(getattr(scene, "visual_description", "") or ""),
                    "dialogue": str(getattr(scene, "dialogue", "") or ""),
                }
                for scene in sorted(list(scenes or []), key=lambda item: getattr(item, "scene_number", 0))
            ],
        }
        return hashlib.sha256(
            json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
