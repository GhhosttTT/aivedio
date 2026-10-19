"""Deterministic adjacent-shot continuity evidence for short-drama projects."""

from __future__ import annotations

import json
from dataclasses import dataclass

from src.services.video_director_service import VideoDirectorService


@dataclass(frozen=True)
class ContinuityAuditReport:
    status: str
    pair_count: int
    issues: list[dict]
    pairs: list[dict]

    def to_dict(self) -> dict:
        return {
            "kind": "continuity_audit",
            "status": self.status,
            "pair_count": self.pair_count,
            "issue_count": len(self.issues),
            "issues": self.issues,
            "pairs": self.pairs,
        }


class ContinuityAuditService:
    """Compare adjacent director contracts without requiring a VLM call."""

    def audit(self, project, scenes: list) -> ContinuityAuditReport:
        ordered = sorted(scenes, key=lambda scene: scene.scene_number)
        if len(ordered) < 2:
            return ContinuityAuditReport("not_applicable", 0, [], [])
        script_map = self._script_scene_map(project)
        director = VideoDirectorService()
        plans = {}
        for scene in ordered:
            try:
                visible = self._visible_characters(scene, script_map.get(scene.scene_number, {}))
                plans[scene.scene_number] = director.plan_scene(
                    scene,
                    getattr(project, "id", None),
                    [{"name": name} for name in visible],
                ).as_dict()
            except (OSError, TypeError, ValueError):
                plans[scene.scene_number] = {}

        issues: list[dict] = []
        pairs: list[dict] = []
        for previous, current in zip(ordered, ordered[1:]):
            previous_plan = plans.get(previous.scene_number, {})
            current_plan = plans.get(current.scene_number, {})
            previous_spatial = previous_plan.get("spatial_plan") or {}
            current_spatial = current_plan.get("spatial_plan") or {}
            pair = {
                "from_scene": previous.scene_number,
                "to_scene": current.scene_number,
                "from_role": previous_plan.get("shot_role"),
                "to_role": current_plan.get("shot_role"),
                "from_characters": self._visible_characters(previous, script_map.get(previous.scene_number, {})),
                "to_characters": self._visible_characters(current, script_map.get(current.scene_number, {})),
                "from_positions": previous_spatial.get("character_positions") or {},
                "to_positions": current_spatial.get("character_positions") or {},
                "from_prop": previous_spatial.get("prop_focus") or None,
                "to_prop": current_spatial.get("prop_focus") or None,
            }
            pairs.append(pair)
            if not previous_plan or not current_plan or not previous_spatial or not current_spatial:
                missing_scenes = [
                    scene_number for scene_number, plan, spatial in (
                        (previous.scene_number, previous_plan, previous_spatial),
                        (current.scene_number, current_plan, current_spatial),
                    )
                    if not plan or not spatial
                ]
                issues.append({
                    "severity": "high",
                    "code": "missing_continuity_evidence",
                    "from_scene": previous.scene_number,
                    "to_scene": current.scene_number,
                    "missing_scenes": missing_scenes,
                    "evidence": (
                        "Director spatial plan is unavailable for scene(s) "
                        + ", ".join(str(number) for number in missing_scenes)
                    ),
                    "recommendation": "Rebuild the director shot plan before evaluating adjacent-shot continuity.",
                })
                continue
            previous_axis = previous_spatial.get("camera_axis") or previous_spatial.get("axis")
            current_axis = current_spatial.get("camera_axis") or current_spatial.get("axis")
            if previous_axis and current_axis and previous_axis != current_axis:
                issues.append({
                    "severity": "high",
                    "code": "screen_direction_jump",
                    "from_scene": previous.scene_number,
                    "to_scene": current.scene_number,
                    "evidence": f"camera axis changed from {previous_axis} to {current_axis}",
                    "recommendation": "Freeze the 180-degree axis or add an explicit establishing/reorientation shot.",
                })
            if (
                pair["from_prop"] and pair["to_prop"]
                and pair["from_prop"] != pair["to_prop"]
                and current_plan.get("shot_role") != "establishing"
            ):
                issues.append({
                    "severity": "warning",
                    "code": "prop_focus_change",
                    "from_scene": previous.scene_number,
                    "to_scene": current.scene_number,
                    "evidence": f"prop focus changed from {pair['from_prop']} to {pair['to_prop']}",
                    "recommendation": "Keep the prior prop state visible or use an establishing shot before changing focus.",
                })
            previous_location = self._location(previous, script_map.get(previous.scene_number, {}))
            current_location = self._location(current, script_map.get(current.scene_number, {}))
            if previous_location and current_location and previous_location != current_location and current_plan.get("shot_role") != "establishing":
                issues.append({
                    "severity": "warning",
                    "code": "location_change_without_establishing",
                    "from_scene": previous.scene_number,
                    "to_scene": current.scene_number,
                    "evidence": f"location changed from {previous_location} to {current_location}",
                    "recommendation": "Add an establishing frame or make the location transition explicit in the shot plan.",
                })
        status = "needs_review" if any(issue["severity"] == "high" for issue in issues) else ("warn" if issues else "passed")
        return ContinuityAuditReport(status, len(pairs), issues, pairs)

    def _script_scene_map(self, project) -> dict[int, dict]:
        try:
            payload = json.loads(project.script or "{}")
        except (TypeError, ValueError):
            return {}
        return {
            item["scene_number"]: item
            for item in payload.get("scenes", [])
            if isinstance(item, dict) and isinstance(item.get("scene_number"), int)
        } if isinstance(payload, dict) else {}

    def _visible_characters(self, scene, script_scene: dict) -> list[str]:
        values = script_scene.get("characters")
        if isinstance(values, str):
            values = [values]
        if not isinstance(values, list):
            values = [getattr(scene, "character_name", None)]
        return list(dict.fromkeys(str(value).strip() for value in values if str(value or "").strip()))

    def _location(self, scene, script_scene: dict) -> str:
        return str(
            getattr(scene, "location", None)
            or script_scene.get("environment")
            or ""
        ).strip()
