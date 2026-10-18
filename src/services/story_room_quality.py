"""Heuristic story-room quality gates for short-drama production."""

from __future__ import annotations

import re
from dataclasses import dataclass

from src.database.models import Project, Scene
from src.services.repair_queue import build_repair_queue
from src.services.topic_brief import TopicBriefService


@dataclass(frozen=True)
class StoryRoomQualityReport:
    status: str
    score: int
    signals: dict
    missing: list[str]
    rewrite_actions: list[str]
    scene_notes: list[dict]
    repair_queue: list[dict]

    def to_dict(self) -> dict:
        return {
            "status": self.status,
            "score": self.score,
            "signals": self.signals,
            "missing": self.missing,
            "rewrite_actions": self.rewrite_actions,
            "scene_notes": self.scene_notes,
            "repair_queue": self.repair_queue,
        }


class StoryRoomQualityService:
    """Approximate the pre-generation story-room gate used by stronger platforms.

    This is intentionally deterministic. Local LLM review can refine the script,
    but production readiness needs a cheap first-pass gate before GPU work starts.
    """

    HOOK_TERMS = [
        "秘密", "背叛", "离婚", "复仇", "重生", "陷害", "真相", "危机", "威胁", "怀孕",
        "证据", "身份", "破产", "失踪", " betrayal", "secret", "revenge", "divorce",
        "truth", "threat", "crisis", "evidence", "identity",
    ]
    ESCALATION_TERMS = [
        "争吵", "质问", "拒绝", "威胁", "冲突", "崩溃", "揭穿", "逼迫", "哭", "怒",
        "报警", "抢走", "摔", "跪", "argue", "confront", "refuse", "threaten",
        "fight", "breakdown", "expose",
    ]
    REVERSAL_TERMS = [
        "反转", "突然", "没想到", "竟然", "原来", "发现", "揭露", "身份", "证据",
        "误会", "亲子", "遗嘱", "suddenly", "reveals", "discovers", "evidence",
        "identity", "twist",
    ]
    ENDING_TERMS = [
        "未完", "待续", "门被推开", "电话响", "真相", "证据", "出现", "转身",
        "下一集", "cliffhanger", "to be continued", "phone rings", "truth",
        "evidence", "appears",
    ]
    PAYOFF_TERMS = [
        "承认", "解决", "成功", "赢", "胜利", "救出", "带走", "离开", "撕掉", "签下",
        "回归", "兑现", "揭开", "付出代价", "payoff", "resolved", "wins", "victory",
        "rescued", "leaves", "admits", "consequence",
    ]
    MARKET_TERMS = [
        "受众", "平台", "竖屏", "女性", "男性", "都市", "甜宠", "逆袭", "复仇", "悬疑",
        "目标", "海外", "douyin", "tiktok", "reels", "audience", "platform",
        "genre", "market",
    ]
    MULTI_ACTION_TERMS = [
        "然后", "接着", "同时", "随后", "并且", "一边", "又", "再", "转身走向",
        "拿起", "递给", "打开", "阅读", "站起", "坐下", "走进", "离开",
        "then", "while", "and then",
    ]
    EMOTION_TERMS = [
        "震惊", "愤怒", "崩溃", "委屈", "冷笑", "害怕", "犹豫", "坚定", "心虚",
        "失望", "惊讶", "哭", "怒", "shock", "angry", "afraid", "hesitate",
        "determined",
    ]
    GOAL_TERMS = [
        "想要", "必须", "选择", "保护", "证明", "拿到", "夺回", "逃离", "留下",
        "赢回", "救", "查清", "复仇", "逆袭", "want", "must", "choose", "protect",
        "prove", "escape", "win", "save", "find", "revenge",
    ]
    STAKES_TERMS = [
        "失去", "毁掉", "破产", "坐牢", "曝光", "名声", "孩子", "遗产", "婚姻",
        "生命", "家族", "lose", "ruin", "bankrupt", "jail", "expose", "reputation",
        "child", "inheritance", "marriage", "life", "family",
    ]

    def evaluate(self, project: Project, scenes: list[Scene], script_scenes: dict[int, dict] | None = None) -> StoryRoomQualityReport:
        script_scenes = script_scenes or {}
        ordered = sorted(scenes, key=lambda scene: scene.scene_number)
        scene_texts = [self._scene_text(scene, script_scenes.get(scene.scene_number, {})) for scene in ordered]
        full_text = " ".join(scene_texts)
        early_text = " ".join(scene_texts[:2])
        middle_text = " ".join(scene_texts[max(0, len(scene_texts) // 3):])
        ending_text = " ".join(scene_texts[-2:])
        topic_brief = {}
        project_id = getattr(project, "id", None)
        if project_id is not None:
            topic_brief = TopicBriefService().load(project_id) or {}
        brief_text = " ".join(filter(None, [
            getattr(project, "theme", "") or "",
            getattr(project, "outline", "") or "",
            getattr(project, "description", "") or "",
            *(str(topic_brief.get(field) or "") for field in (
                "audience", "platform", "genre", "hook_type", "region", "policy_notes",
            )),
        ]))

        dialogue_count = sum(1 for scene in ordered if (scene.dialogue or "").strip())
        dialogue_density = round(dialogue_count / max(len(ordered), 1), 3)
        overloaded = self._overloaded_scene_notes(ordered, script_scenes)
        conflict_count = self._count_terms(full_text, self.ESCALATION_TERMS)
        emotion_count = self._count_terms(full_text, self.EMOTION_TERMS)
        hook_count = self._count_terms(early_text, self.HOOK_TERMS) + len(re.findall(r"[!?！？]", early_text))
        reversal_count = self._count_terms(middle_text, self.REVERSAL_TERMS)
        ending_count = self._count_terms(ending_text, self.ENDING_TERMS) + len(re.findall(r"[!?！？]", ending_text))
        payoff_count = self._count_terms(ending_text, self.PAYOFF_TERMS)
        escalation_windows = self._escalation_windows(scene_texts)
        goal_count = self._count_terms(full_text, self.GOAL_TERMS)
        stakes_count = self._count_terms(full_text, self.STAKES_TERMS)
        hook_scenes = self._scene_numbers_with_terms(scene_texts[:2], self.HOOK_TERMS)
        middle_start = max(0, len(scene_texts) // 3)
        middle_end = min(len(scene_texts), max(middle_start + 1, len(scene_texts) * 2 // 3 + 1))
        reversal_scenes = self._scene_numbers_with_terms(
            scene_texts[middle_start:middle_end], self.REVERSAL_TERMS, offset=middle_start
        )
        ending_start = max(0, len(scene_texts) - 2)
        payoff_scenes = self._scene_numbers_with_terms(
            scene_texts[ending_start:], self.PAYOFF_TERMS, offset=ending_start
        )
        ending_hook_scenes = self._scene_numbers_with_terms(
            scene_texts[ending_start:], self.ENDING_TERMS, offset=ending_start
        )
        beat_order_valid = bool(
            hook_scenes
            and reversal_scenes
            and (payoff_scenes or ending_hook_scenes)
            and min(hook_scenes) < min(reversal_scenes)
            and min(reversal_scenes) < min(payoff_scenes or ending_hook_scenes)
        )

        signals = {
            "has_market_brief": len(brief_text.strip()) >= 20 and self._count_terms(brief_text, self.MARKET_TERMS) > 0,
            "early_hook": hook_count > 0,
            "character_goal_conflict": goal_count > 0 and conflict_count > 0 and stakes_count > 0,
            "goal_signals": goal_count,
            "stakes_signals": stakes_count,
            "dialogue_density": dialogue_density,
            "escalation_windows": escalation_windows,
            "has_reversal": reversal_count > 0,
            "has_payoff": payoff_count > 0,
            "ending_hook": ending_count > 0,
            "hook_scenes": hook_scenes,
            "reversal_scenes": reversal_scenes,
            "payoff_scenes": payoff_scenes,
            "ending_hook_scenes": ending_hook_scenes,
            "beat_order_valid": beat_order_valid,
            "emotion_signals": emotion_count,
            "overloaded_scene_count": len(overloaded),
        }

        beat_evidence = {
            "hook": {
                "scene_range": [1, min(2, len(ordered))],
                "detected": bool(signals["early_hook"]),
                "signal_count": hook_count,
            },
            "escalation": {
                "window_count": escalation_windows,
                "required_windows": max(1, len(ordered) // 4),
                "detected": escalation_windows >= max(1, len(ordered) // 4),
            },
            "reversal": {
                "scene_range": [max(1, len(ordered) // 3 + 1), max(1, len(ordered) * 2 // 3)],
                "detected": bool(signals["has_reversal"]),
                "signal_count": reversal_count,
            },
            "payoff": {
                "scene_range": [max(1, len(ordered) - 1), len(ordered)],
                "detected": bool(signals["has_payoff"]),
                "signal_count": payoff_count,
            },
            "cliffhanger": {
                "scene_range": [max(1, len(ordered) - 1), len(ordered)],
                "detected": bool(signals["ending_hook"]),
                "signal_count": ending_count,
            },
            "ordered_progression": {
                "detected": beat_order_valid,
                "hook_scenes": hook_scenes,
                "reversal_scenes": reversal_scenes,
                "payoff_or_cliffhanger_scenes": payoff_scenes or ending_hook_scenes,
            },
        }
        signals["beat_contract"] = beat_evidence

        missing = []
        if not signals["has_market_brief"]:
            missing.append("market_brief")
        if not signals["early_hook"]:
            missing.append("early_hook")
        if not signals["character_goal_conflict"]:
            missing.append("character_goal_conflict")
        if dialogue_density < 0.5:
            missing.append("dialogue_or_reaction_drive")
        if escalation_windows < max(1, len(ordered) // 4):
            missing.append("escalation_cadence")
        if not signals["has_reversal"]:
            missing.append("reversal")
        if not signals["has_payoff"]:
            missing.append("payoff")
        if not signals["ending_hook"]:
            missing.append("ending_hook")
        if not beat_order_valid:
            missing.append("beat_order")
        if emotion_count < max(2, len(ordered) // 4):
            missing.append("emotional_progression")
        if overloaded:
            missing.append("atomic_shots")

        score = max(0, 9 - len(missing))
        status = "passed" if score >= 8 else ("warn" if score >= 5 else "weak")
        rewrite_actions = self._rewrite_actions(missing, overloaded)
        repair_queue = build_repair_queue({
            "status": status,
            "kind": "story_room_quality",
            "story_room_quality_gate": {
                "status": "passed" if status == "passed" else "needs_review",
                "missing": missing,
                "low": {
                    item["scene_number"]: {
                        "score": 0,
                        "evidence": "too_many_actions_or_beats",
                        "scene_number": item["scene_number"],
                    }
                    for item in overloaded
                },
            },
            "rewrite_actions": rewrite_actions,
        }, "script")
        return StoryRoomQualityReport(
            status=status,
            score=score,
            signals=signals,
            missing=missing,
            rewrite_actions=rewrite_actions,
            scene_notes=overloaded,
            repair_queue=repair_queue,
        )

    def _scene_text(self, scene: Scene, script_scene: dict) -> str:
        parts = [
            scene.visual_description or "",
            scene.dialogue or "",
            str(script_scene.get("story_beat") or ""),
            str(script_scene.get("emotion") or script_scene.get("情感") or ""),
        ]
        return " ".join(part for part in parts if part)

    def _count_terms(self, text: str, terms: list[str]) -> int:
        lowered = text.lower()
        return sum(lowered.count(term.lower()) for term in terms)

    def _scene_numbers_with_terms(
        self,
        scene_texts: list[str],
        terms: list[str],
        *,
        offset: int = 0,
    ) -> list[int]:
        """Return one-based positions so beat evidence proves placement, not only presence."""
        return [
            index + offset + 1
            for index, text in enumerate(scene_texts)
            if self._count_terms(text, terms) > 0
        ]

    def _escalation_windows(self, scene_texts: list[str]) -> int:
        count = 0
        for start in range(0, len(scene_texts), 4):
            window = " ".join(scene_texts[start:start + 4])
            if self._count_terms(window, self.ESCALATION_TERMS) > 0:
                count += 1
        return count

    def _overloaded_scene_notes(self, scenes: list[Scene], script_scenes: dict[int, dict]) -> list[dict]:
        notes = []
        for scene in scenes:
            text = self._scene_text(scene, script_scenes.get(scene.scene_number, {}))
            hits = sorted({term for term in self.MULTI_ACTION_TERMS if term.lower() in text.lower()})
            comma_count = len(re.findall(r"[，,；;]", text))
            if len(hits) >= 3 or comma_count >= 7:
                notes.append({
                    "scene_number": scene.scene_number,
                    "reason": "too_many_actions_or_beats",
                    "signals": hits[:6],
                })
        return notes

    def _rewrite_actions(self, missing: list[str], overloaded: list[dict]) -> list[str]:
        actions = []
        if "market_brief" in missing:
            actions.append("Add a topic brief with target audience, platform, genre, hook type, and risk notes.")
        if "early_hook" in missing:
            actions.append("Rewrite scenes 1-2 around a visible secret, threat, crisis, evidence, or irreversible choice.")
        if "character_goal_conflict" in missing:
            actions.append("Clarify the protagonist's visible goal, the opposing force, and what is lost if they fail.")
        if "dialogue_or_reaction_drive" in missing:
            actions.append("Make at least half of the shots dialogue-driven or reaction-driven.")
        if "escalation_cadence" in missing:
            actions.append("Add confrontation, refusal, exposed evidence, or higher stakes every 3-4 shots.")
        if "reversal" in missing:
            actions.append("Add one clear mid-episode reversal that changes the audience's understanding.")
        if "payoff" in missing:
            actions.append("Give the protagonist a visible short-term payoff or consequence before the final hook.")
        if "ending_hook" in missing:
            actions.append("End with a payoff or next-episode hook visible in the final two shots.")
        if "beat_order" in missing:
            actions.append("Place the hook early, a reversal in the middle, and a payoff or cliffhanger after the reversal.")
        if "emotional_progression" in missing:
            actions.append("Assign visible emotions to beats so reactions escalate across the episode.")
        if overloaded:
            numbers = ", ".join(str(item["scene_number"]) for item in overloaded[:8])
            actions.append(f"Split overloaded shots into atomic visual beats: {numbers}.")
        return actions
