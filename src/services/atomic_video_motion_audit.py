"""Aggregate per-shot technical video metrics before episode composition."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from src.config import settings


@dataclass(frozen=True)
class AtomicVideoMotionAuditReport:
    status: str
    checked_scene_count: int
    scenes: list[dict[str, Any]]
    issues: list[dict[str, Any]]

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": "atomic_video_motion_audit",
            "status": self.status,
            "checked_scene_count": self.checked_scene_count,
            "scenes": self.scenes,
            "issues": self.issues,
            "issue_count": len(self.issues),
            "repair_queue": self._repair_queue(),
        }

    def _repair_queue(self) -> list[dict[str, Any]]:
        queue = []
        seen = set()
        for issue in self.issues:
            action = issue.get("action") or "refine_video_commercial_aesthetic"
            if action in seen:
                continue
            seen.add(action)
            queue.append({
                "priority": "high" if issue.get("severity") == "high" else "medium",
                "stage": "video",
                "action": action,
                "execution": "auto",
                "scene_number": issue.get("scene_number"),
                "reason": issue.get("message") or issue.get("code"),
                "recommendation": "Regenerate the atomic clip and rerun technical motion validation before composition.",
            })
        return queue


class AtomicVideoMotionAuditService:
    """Use persisted technical evidence; never treat missing evidence as a pass."""

    def audit(self, scenes: list) -> AtomicVideoMotionAuditReport:
        reports = []
        for scene in sorted(scenes or [], key=lambda item: item.scene_number):
            video_path = getattr(scene, "video_path", None)
            if not video_path:
                continue
            metrics = self._load_metrics(Path(str(video_path)))
            if not metrics:
                continue
            item = {"scene_number": scene.scene_number, **self._selected_metrics(metrics)}
            reports.append(item)
        if not reports:
            return AtomicVideoMotionAuditReport("not_applicable", 0, [], [])
        issues: list[dict[str, Any]] = []
        for item in reports:
            number = item["scene_number"]
            score = item.get("technical_score")
            if isinstance(score, (int, float)) and score < float(settings.GENERATION_VIDEO_TECHNICAL_MIN_SCORE):
                issues.append(self._issue(number, "technical_score_low", f"technical score {score:.2f} is below the production floor", "refine_video_commercial_aesthetic"))
            if float(item.get("max_black_run_seconds") or 0) > float(settings.GENERATION_VIDEO_MAX_BLACK_SECONDS):
                issues.append(self._issue(number, "black_frame_run", "black-frame run exceeds the production limit", "refine_video_commercial_aesthetic"))
            if float(item.get("motion_jitter_ratio") or 0) > float(settings.GENERATION_VIDEO_MAX_MOTION_JITTER_RATIO):
                issues.append(self._issue(number, "motion_cadence_unstable", "motion cadence is unstable", "lower_motion_and_regenerate_video"))
            if float(item.get("static_transition_ratio") or 0) >= 0.75:
                issues.append(self._issue(number, "frozen_motion", "clip spends too much of its sampled timeline in near-static transitions", "increase_motion_and_regenerate_video"))
            if float(item.get("temporal_jump_ratio") or 0) >= 0.35:
                issues.append(self._issue(number, "temporal_visual_jump", "sampled frames contain repeated full-frame visual resets", "refine_video_commercial_aesthetic"))
        status = "needs_review" if any(issue["severity"] == "high" for issue in issues) else ("warn" if issues else "passed")
        return AtomicVideoMotionAuditReport(status, len(reports), reports, issues)

    def _load_metrics(self, video_path: Path) -> dict[str, Any] | None:
        sidecar = video_path.with_suffix(".quality.json")
        try:
            payload = json.loads(sidecar.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError):
            return None
        if not isinstance(payload, dict):
            return None
        metrics = payload.get("metrics") if isinstance(payload.get("metrics"), dict) else payload
        return metrics if isinstance(metrics, dict) else None

    def _selected_metrics(self, metrics: dict[str, Any]) -> dict[str, Any]:
        return {
            key: metrics.get(key)
            for key in (
                "technical_score", "motion_energy", "static_transition_ratio",
                "max_static_run_seconds", "max_black_run_seconds",
                "motion_jitter_ratio", "sharpness", "brightness",
                "temporal_jump_ratio", "temporal_jump_p95",
            )
        }

    def _issue(self, scene_number: int, code: str, message: str, action: str) -> dict[str, Any]:
        return {
            "severity": "high",
            "code": code,
            "scene_number": scene_number,
            "message": message,
            "action": action,
            "recommendation": "Regenerate the clip and rerun the technical quality gate.",
        }
