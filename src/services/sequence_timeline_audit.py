"""Validate planned versus published durations for multi-shot sequences."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable


@dataclass(frozen=True)
class SequenceTimelineAuditReport:
    status: str
    planned_count: int
    actual_count: int
    segments: list[dict[str, Any]]
    issues: list[dict[str, Any]]

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": "sequence_timeline_audit",
            "status": self.status,
            "planned_count": self.planned_count,
            "actual_count": self.actual_count,
            "segments": self.segments,
            "issues": self.issues,
            "issue_count": len(self.issues),
            "repair_queue": self._repair_queue(),
        }

    def _repair_queue(self) -> list[dict[str, Any]]:
        if not self.issues:
            return []
        return [{
            "priority": "high",
            "stage": "workflow",
            "action": "fix_video_output_contract",
            "execution": "setup_required",
            "scene_number": None,
            "reason": "; ".join(issue["code"] for issue in self.issues[:3]),
            "recommendation": "Regenerate or re-split the sequence with the persisted timeline contract before composing.",
        }]


class SequenceTimelineAuditService:
    TOLERANCE_SECONDS = 0.12
    RELATIVE_TOLERANCE = 0.05

    def audit(self, planned: Iterable[dict], actual: Iterable[dict]) -> SequenceTimelineAuditReport:
        planned_list = [dict(item) for item in planned or [] if isinstance(item, dict)]
        actual_list = [dict(item) for item in actual or [] if isinstance(item, dict)]
        if not planned_list and not actual_list:
            return SequenceTimelineAuditReport("not_applicable", 0, 0, [], [])
        issues: list[dict[str, Any]] = []
        if len(planned_list) != len(actual_list):
            issues.append({
                "severity": "high",
                "code": "segment_count_mismatch",
                "message": f"planned {len(planned_list)} segments but published {len(actual_list)}",
            })
        segments = []
        for index, expected in enumerate(planned_list):
            observed = actual_list[index] if index < len(actual_list) else {}
            scene_number = expected.get("scene_number")
            expected_duration = self._number(expected.get("duration_seconds"))
            actual_duration = self._number(observed.get("duration_seconds"))
            item = {
                "scene_number": scene_number,
                "planned_start_seconds": expected.get("start_seconds"),
                "planned_end_seconds": expected.get("end_seconds"),
                "planned_duration_seconds": expected_duration,
                "actual_duration_seconds": actual_duration,
            }
            segments.append(item)
            if expected_duration is None or actual_duration is None:
                issues.append({
                    "severity": "high",
                    "code": "segment_duration_unavailable",
                    "scene_number": scene_number,
                    "message": "planned or published segment duration is unavailable",
                })
                continue
            tolerance = max(self.TOLERANCE_SECONDS, expected_duration * self.RELATIVE_TOLERANCE)
            if abs(actual_duration - expected_duration) > tolerance:
                issues.append({
                    "severity": "high",
                    "code": "segment_duration_drift",
                    "scene_number": scene_number,
                    "expected_seconds": round(expected_duration, 3),
                    "actual_seconds": round(actual_duration, 3),
                    "message": f"segment duration drifted by {abs(actual_duration - expected_duration):.3f}s",
                })
        status = "needs_review" if issues else "passed"
        return SequenceTimelineAuditReport(status, len(planned_list), len(actual_list), segments, issues)

    def _number(self, value) -> float | None:
        try:
            result = float(value)
        except (TypeError, ValueError):
            return None
        return result if result >= 0 else None
