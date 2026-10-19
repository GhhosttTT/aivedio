"""Aggregate locked-keyframe to generated-video first-frame evidence."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from src.config import settings


@dataclass(frozen=True)
class FirstFrameConsistencyAuditReport:
    status: str
    checked_scene_count: int
    scenes: list[dict[str, Any]]
    issues: list[dict[str, Any]]

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": "first_frame_consistency_audit",
            "status": self.status,
            "checked_scene_count": self.checked_scene_count,
            "scenes": self.scenes,
            "issues": self.issues,
            "issue_count": len(self.issues),
            "repair_queue": [
                {
                    "priority": "high",
                    "stage": "video",
                    "action": issue.get("action", "regenerate_video_with_performance_direction"),
                    "execution": "auto",
                    "scene_number": issue.get("scene_number"),
                    "reason": issue.get("message") or issue.get("code"),
                    "recommendation": "Regenerate the clip with the locked keyframe as the opening-frame reference, then rerun the reference gate.",
                }
                for issue in self.issues
            ],
        }


class FirstFrameConsistencyAuditService:
    """Fail closed when a reference-backed shot lacks usable opening-frame evidence."""

    def audit(self, scenes: list) -> FirstFrameConsistencyAuditReport:
        observations = []
        for scene in sorted(scenes or [], key=lambda item: item.scene_number):
            video_path = getattr(scene, "video_path", None)
            reference_image = getattr(scene, "image_path", None)
            if not video_path or not reference_image:
                continue
            metrics = self._load_metrics(Path(str(video_path)))
            if not metrics:
                continue
            evidence = metrics.get("start_frame_reference")
            item = {
                "scene_number": scene.scene_number,
                "video_path": str(video_path),
                "reference_image": str(reference_image),
                "status": evidence.get("status") if isinstance(evidence, dict) else "missing",
                "score": evidence.get("score") if isinstance(evidence, dict) else None,
                "brightness_delta": evidence.get("brightness_delta") if isinstance(evidence, dict) else None,
                "pixel_delta": evidence.get("pixel_delta") if isinstance(evidence, dict) else None,
                "histogram_distance": evidence.get("histogram_distance") if isinstance(evidence, dict) else None,
            }
            observations.append(item)
        if not observations:
            return FirstFrameConsistencyAuditReport("not_applicable", 0, [], [])

        issues = []
        minimum = float(settings.GENERATION_VIDEO_START_FRAME_REFERENCE_MIN_SCORE)
        for item in observations:
            score = item.get("score")
            if item["status"] == "missing":
                issues.append(self._issue(item["scene_number"], "missing_reference_evidence", "opening-frame reference evidence is missing"))
            elif item["status"] != "available":
                issues.append(self._issue(item["scene_number"], "reference_evidence_unavailable", "opening-frame reference could not be measured"))
            elif not isinstance(score, (int, float)):
                issues.append(self._issue(item["scene_number"], "reference_score_missing", "opening-frame reference score is missing"))
            elif score < minimum:
                issues.append(self._issue(item["scene_number"], "opening_frame_drift", f"opening-frame reference score {score:.2f} is below the production floor {minimum:.2f}"))
        status = "needs_review" if issues else "passed"
        return FirstFrameConsistencyAuditReport(status, len(observations), observations, issues)

    def _load_metrics(self, video_path: Path) -> dict[str, Any] | None:
        try:
            payload = json.loads(video_path.with_suffix(".quality.json").read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError):
            return None
        if not isinstance(payload, dict):
            return None
        legacy_metrics = payload.get("metrics")
        if isinstance(legacy_metrics, dict):
            return legacy_metrics

        # Final normalized clips keep their measurable evidence under the
        # final-review envelope. Candidate-selection reports keep it under the
        # candidate matching the published video path.
        containers: list[dict[str, Any]] = []
        final_review = payload.get("final_video_review")
        if isinstance(final_review, dict):
            containers.append(final_review)
        candidates = payload.get("candidates")
        if isinstance(candidates, list):
            video_path_text = str(video_path)
            containers.extend(
                candidate
                for candidate in candidates
                if isinstance(candidate, dict)
                and str(candidate.get("path") or "") == video_path_text
            )
        containers.append(payload)
        for container in containers:
            metrics = container.get("technical_metrics")
            if isinstance(metrics, dict):
                return metrics
        return None

    def _issue(self, scene_number: int, code: str, message: str) -> dict[str, Any]:
        return {
            "severity": "high",
            "code": code,
            "scene_number": scene_number,
            "message": message,
            "action": "regenerate_video_with_performance_direction",
            "recommendation": "Lock the keyframe as the first frame and regenerate the atomic clip.",
        }
