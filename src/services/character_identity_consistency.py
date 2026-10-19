"""Cross-shot character identity evidence derived from generation reviews."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from src.config import settings


@dataclass(frozen=True)
class CharacterIdentityConsistencyReport:
    status: str
    character_count: int
    observation_count: int
    observations: list[dict[str, Any]]
    issues: list[dict[str, Any]]

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": "character_identity_consistency",
            "status": self.status,
            "character_count": self.character_count,
            "observation_count": self.observation_count,
            "observations": self.observations,
            "issues": self.issues,
            "issue_count": len(self.issues),
            "repair_queue": self._repair_queue(),
        }

    def _repair_queue(self) -> list[dict[str, Any]]:
        if not self.issues:
            return []
        drift = any(issue.get("code") == "identity_score_drift" for issue in self.issues)
        action = "regenerate_character_identity" if drift else "regenerate_keyframe_with_identity_lock"
        stage = "character" if drift else "image"
        execution = "setup_required" if drift else "auto"
        scene_numbers = sorted({
            issue["scene_number"] for issue in self.issues
            if isinstance(issue.get("scene_number"), int)
        })
        return [{
            "priority": "high",
            "stage": stage,
            "action": action,
            "execution": execution,
            "scene_number": scene_numbers[0] if len(scene_numbers) == 1 else None,
            "reason": "; ".join(issue.get("evidence", issue["code"]) for issue in self.issues[:3]),
            "recommendation": "Reapply the frozen character identity bible and regenerate affected shots before video composition.",
        }]


class CharacterIdentityConsistencyService:
    """Aggregate per-shot VLM identity scores into a fail-closed gate.

    This deliberately consumes existing review evidence instead of pretending a
    cheap pixel comparison is a face-recognition model. It catches both a low
    identity score and a large score swing for the same named role.
    """

    def audit(self, scenes: list, reports: dict[str, Any]) -> CharacterIdentityConsistencyReport:
        scene_names = {
            getattr(scene, "scene_number", None): self._scene_characters(scene)
            for scene in scenes or []
        }
        observations: list[dict[str, Any]] = []
        for report_name, report in (reports or {}).items():
            if not isinstance(report, dict):
                continue
            for candidate in self._review_candidates(report):
                scene_number = self._scene_number(candidate)
                if scene_number is None:
                    continue
                names = self._candidate_characters(candidate) or scene_names.get(scene_number, [])
                score, evidence = self._identity_score(candidate)
                if score is None or not names:
                    continue
                for name in names:
                    observations.append({
                        "character": name,
                        "scene_number": scene_number,
                        "score": round(score, 2),
                        "evidence": evidence,
                        "source_report": report_name,
                    })
        deduped = self._dedupe(observations)
        grouped: dict[str, list[dict[str, Any]]] = {}
        for item in deduped:
            grouped.setdefault(item["character"], []).append(item)
        if not deduped:
            return CharacterIdentityConsistencyReport("not_applicable", 0, 0, [], [])

        issues: list[dict[str, Any]] = []
        minimum = float(settings.GENERATION_CHARACTER_IDENTITY_MIN_SCORE)
        maximum_spread = float(settings.GENERATION_CHARACTER_IDENTITY_MAX_SCORE_SPREAD)
        for character, items in sorted(grouped.items()):
            scores = [float(item["score"]) for item in items]
            low = min(scores)
            spread = max(scores) - low
            if low < minimum:
                for item in items:
                    if item["score"] < minimum:
                        issues.append({
                            "severity": "high",
                            "code": "identity_score_below_threshold",
                            "character": character,
                            "scene_number": item["scene_number"],
                            "score": item["score"],
                            "evidence": f"{character} scene {item['scene_number']} identity score {item['score']:.1f}/5 is below {minimum:.1f}",
                            "recommendation": "Regenerate the shot with the frozen identity reference and turnaround controls.",
                        })
            if len(items) >= 2 and spread > maximum_spread:
                issues.append({
                    "severity": "high",
                    "code": "identity_score_drift",
                    "character": character,
                    "score_spread": round(spread, 2),
                    "scene_numbers": [item["scene_number"] for item in items],
                    "evidence": f"{character} identity scores drift by {spread:.1f} points across {len(items)} shots",
                    "recommendation": "Refresh the character identity bible/turnaround and regenerate the weakest shots.",
                })
        status = "needs_review" if issues else "passed"
        return CharacterIdentityConsistencyReport(status, len(grouped), len(deduped), deduped, issues)

    def _review_candidates(self, report: dict[str, Any]):
        if isinstance(report.get("review"), dict):
            yield report
        for key in ("cases", "candidates", "batches"):
            values = report.get(key)
            if isinstance(values, list):
                for item in values:
                    if isinstance(item, dict):
                        yield from self._review_candidates(item)
        for value in report.values():
            if isinstance(value, dict) and value is not report:
                if value.get("scene_number") is not None or isinstance(value.get("scene"), dict):
                    yield from self._review_candidates(value)

    def _scene_number(self, candidate: dict[str, Any]) -> int | None:
        value = candidate.get("scene_number")
        if value is None and isinstance(candidate.get("scene"), dict):
            value = candidate["scene"].get("scene_number")
        try:
            result = int(value)
        except (TypeError, ValueError):
            return None
        return result if result > 0 else None

    def _candidate_characters(self, candidate: dict[str, Any]) -> list[str]:
        values = candidate.get("character_name")
        if values is None and isinstance(candidate.get("scene"), dict):
            values = candidate["scene"].get("character_name") or candidate["scene"].get("characters")
        if isinstance(values, str):
            values = [values]
        return list(dict.fromkeys(str(value).strip() for value in (values or []) if str(value).strip()))

    def _scene_characters(self, scene) -> list[str]:
        value = getattr(scene, "character_name", None)
        if isinstance(value, str) and value.strip():
            return [value.strip()]
        return []

    def _identity_score(self, candidate: dict[str, Any]) -> tuple[float | None, str]:
        review = candidate.get("review") if isinstance(candidate.get("review"), dict) else candidate
        values = []
        evidence = []
        for key in ("identity_consistency", "facial_identity"):
            value = review.get(key)
            if isinstance(value, dict):
                score = value.get("score")
                note = value.get("evidence")
            else:
                score = value
                note = None
            if isinstance(score, (int, float)) and not isinstance(score, bool):
                values.append(float(score))
                if note:
                    evidence.append(str(note))
        if not values:
            return None, ""
        return min(values), "; ".join(evidence)[:240]

    def _dedupe(self, observations: list[dict[str, Any]]) -> list[dict[str, Any]]:
        result = {}
        for item in observations:
            key = (item["character"], item["scene_number"])
            current = result.get(key)
            if current is None or item["score"] < current["score"]:
                result[key] = item
        return sorted(result.values(), key=lambda item: (item["character"], item["scene_number"]))
