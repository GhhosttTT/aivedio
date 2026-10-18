"""Deterministic episode-level rhythm and timing audit."""

from __future__ import annotations

import math
from dataclasses import dataclass

from src.services.video_director_service import VideoDirectorService


@dataclass(frozen=True)
class RhythmAuditReport:
    status: str
    scene_count: int
    total_duration_seconds: float
    issues: list[dict]
    timeline: list[dict]
    repair_queue: list[dict]
    editing_plan: list[dict] | None = None

    def to_dict(self) -> dict:
        return {
            "kind": "rhythm_audit",
            "status": self.status,
            "scene_count": self.scene_count,
            "total_duration_seconds": self.total_duration_seconds,
            "issues": self.issues,
            "timeline": self.timeline,
            "repair_queue": self.repair_queue,
            "editing_plan": list(self.editing_plan or []),
        }


class RhythmAuditService:
    """Catch pacing failures before expensive final composition.

    This is intentionally model-agnostic: it uses measured dialogue audio when
    available and the same director plan that drives video generation otherwise.
    """

    MIN_SHOT_SECONDS = 1.2
    MAX_SILENT_SHOT_SECONDS = 6.0
    MAX_DIALOGUE_MARGIN_SECONDS = 0.30
    SAME_ROLE_WARNING_RUN = 3

    def audit(self, project, scenes) -> RhythmAuditReport:
        ordered = sorted(list(scenes or []), key=lambda scene: scene.scene_number)
        if not ordered:
            return RhythmAuditReport("not_applicable", 0, 0.0, [], [], [], [])

        director = VideoDirectorService()
        timeline = []
        issues = []
        cursor = 0.0
        for scene in ordered:
            plan = director.plan_scene(scene, project_id=getattr(project, "id", None))
            duration = self._duration(scene, plan)
            dialogue = str(getattr(scene, "dialogue", "") or "").strip()
            audio_duration = self._positive_number(getattr(scene, "audio_duration", None))
            item = {
                "scene_number": scene.scene_number,
                "shot_role": plan.shot_role,
                "duration_seconds": round(duration, 3),
                "start_seconds": round(cursor, 3),
                "end_seconds": round(cursor + duration, 3),
                "has_dialogue": bool(dialogue),
                "audio_duration_seconds": round(audio_duration, 3) if audio_duration else None,
                "action_intensity": getattr(plan, "action_intensity", None),
            }
            timeline.append(item)
            if duration < self.MIN_SHOT_SECONDS:
                issues.append(self._issue(
                    "short_shot", "high", scene.scene_number,
                    f"Shot duration {duration:.2f}s leaves too little time for a readable cut and reaction.",
                    "split_scene",
                ))
            if not dialogue and duration > self.MAX_SILENT_SHOT_SECONDS:
                issues.append(self._issue(
                    "long_silent_shot", "warn", scene.scene_number,
                    f"Silent shot lasts {duration:.2f}s; add motion, a reaction beat, or split the shot.",
                    "split_scene",
                ))
            if dialogue and audio_duration and duration - audio_duration <= self.MAX_DIALOGUE_MARGIN_SECONDS + 1e-6:
                issues.append(self._issue(
                    "dialogue_reaction_margin", "high", scene.scene_number,
                    f"Dialogue has only {max(0.0, duration - audio_duration):.2f}s of reaction room.",
                    "refine_dialogue_audio_delivery",
                ))
            cursor += duration

        self._add_role_run_issues(timeline, issues)
        status = "needs_review" if any(item["severity"] == "high" for item in issues) else ("warn" if issues else "passed")
        repair_queue = [
            {
                "action": item["action"],
                "stage": "script" if item["action"] == "split_scene" else "audio",
                "scene_number": item["scene_number"],
                "reason": item["message"],
                "recommendation": item["message"],
            }
            for item in issues
        ]
        editing_plan = self._editing_plan(timeline)
        return RhythmAuditReport(
            status=status,
            scene_count=len(ordered),
            total_duration_seconds=round(cursor, 3),
            issues=issues,
            timeline=timeline,
            repair_queue=repair_queue,
            editing_plan=editing_plan,
        )

    @staticmethod
    def _editing_plan(timeline: list[dict]) -> list[dict]:
        """Turn shot roles into an explicit, reviewable editorial blueprint."""
        plan = []
        previous_role = None
        for index, item in enumerate(timeline):
            role = str(item.get("shot_role") or "story_shot")
            if index == 0:
                cut_type = "opening_hold"
                reason = "Open on the first readable story beat; do not spend the hook on a transition."
                audio_strategy = "start_at_zero"
            elif role == "emotion_reaction":
                cut_type = "reaction_cut"
                reason = "Cut to the emotional response after the preceding beat lands."
                audio_strategy = "hold_room_tone_then_dialogue"
            elif role == "prop_interaction":
                cut_type = "match_cut_prop"
                reason = "Cut on the prop result so the audience can read the cause and effect."
                audio_strategy = "action_cut_with_short_crossfade"
            elif role == "action" or item.get("action_intensity") == "high":
                cut_type = "hard_cut_action"
                reason = "Cut on a readable physical action while preserving screen direction."
                audio_strategy = "cut_on_action"
            elif role == "dialogue_reaction" and previous_role == "dialogue_reaction":
                cut_type = "eyeline_cut"
                reason = "Alternate dialogue coverage while keeping the established eyeline."
                audio_strategy = "dialogue_pre_lap"
            elif role == "establishing":
                cut_type = "location_cut"
                reason = "Use a clean location reset only when the story changes visual space."
                audio_strategy = "room_tone_bridge"
            else:
                cut_type = "motivated_hard_cut"
                reason = "Use a direct cut at the next settled story beat."
                audio_strategy = "short_crossfade"
            transition = RhythmAuditService._transition_contract(
                cut_type, audio_strategy, index == 0
            )
            plan.append({
                "scene_number": item.get("scene_number"),
                "start_seconds": item.get("start_seconds"),
                "end_seconds": item.get("end_seconds"),
                "cut_type": cut_type,
                "reason": reason,
                "audio_strategy": audio_strategy,
                "transition": transition,
                "shot_role": role,
            })
            previous_role = role
        return plan

    @staticmethod
    def _transition_contract(cut_type: str, audio_strategy: str, is_opening: bool) -> dict:
        """Describe the safe transition a renderer must apply at a cut.

        The contract deliberately defaults to hard cuts. Short-drama dialogue
        should not be softened with arbitrary dissolves, while action and
        location changes may use a tightly bounded visual blend. Keeping this
        decision explicit lets the final reviewer detect a renderer that
        ignored the editorial intent instead of treating all boundaries alike.
        """
        if is_opening:
            return {"video": "none", "duration_seconds": 0.0, "dialogue_protected": True}
        if cut_type in {"reaction_cut", "hard_cut_action", "eyeline_cut", "match_cut_prop"}:
            return {"video": "hard_cut", "duration_seconds": 0.0, "dialogue_protected": True}
        if cut_type == "location_cut":
            return {"video": "crossfade", "duration_seconds": 0.12, "dialogue_protected": True}
        return {
            "video": "hard_cut" if audio_strategy == "dialogue_pre_lap" else "crossfade",
            "duration_seconds": 0.08 if audio_strategy != "dialogue_pre_lap" else 0.0,
            "dialogue_protected": audio_strategy != "start_at_zero",
        }

    def _duration(self, scene, plan) -> float:
        audio_duration = self._positive_number(getattr(scene, "audio_duration", None))
        value = self._positive_number(getattr(plan, "target_duration_seconds", None))
        required = audio_duration + 0.3 if audio_duration else 0.0
        return max(0.1, value, required)

    def _add_role_run_issues(self, timeline: list[dict], issues: list[dict]) -> None:
        if len(timeline) < self.SAME_ROLE_WARNING_RUN:
            return
        start = 0
        while start < len(timeline):
            role = timeline[start]["shot_role"]
            end = start + 1
            while end < len(timeline) and timeline[end]["shot_role"] == role:
                end += 1
            if end - start >= self.SAME_ROLE_WARNING_RUN:
                issues.append(self._issue(
                    "repeated_shot_role", "warn", timeline[start]["scene_number"],
                    f"{end - start} consecutive shots use the {role} role; vary coverage or add a reaction cut.",
                    "refine_video_commercial_aesthetic",
                    scene_numbers=[item["scene_number"] for item in timeline[start:end]],
                ))
            start = end

    @staticmethod
    def _positive_number(value) -> float:
        try:
            number = float(value)
        except (TypeError, ValueError):
            return 0.0
        return number if math.isfinite(number) and number > 0 else 0.0

    @staticmethod
    def _issue(code: str, severity: str, scene_number: int, message: str, action: str, **extra) -> dict:
        return {
            "code": code,
            "severity": severity,
            "scene_number": scene_number,
            "message": message,
            "action": action,
            **extra,
        }
