"""Heuristic shot complexity checks before image/video generation."""

from __future__ import annotations

import re
from dataclasses import dataclass, asdict


SEQUENTIAL_RE = re.compile(
    r"\b(and then|then|afterwards|subsequently|while|as she|as he|camera pans|camera zooms|tracking shot)\b"
    r"|然后|接着|随后|同时|一边|镜头推进|镜头拉远|镜头跟随|转身后|走进.*坐下",
    re.I,
)
ACTION_RE = re.compile(
    r"\b(run|walk|turn|fight|chase|dance|grab|throw|fall|enter|sit|stand|open|close|hand|pass|hug|kiss)\b"
    r"|奔跑|走|转身|打斗|追逐|跳舞|抓|扔|摔倒|进入|坐下|站起|打开|递|拥抱|亲吻"
)
CAMERA_RE = re.compile(r"\bpan|zoom|dolly|tracking|handheld|orbit\b|推镜|拉镜|摇镜|跟拍|环绕", re.I)


@dataclass
class ShotComplexityReport:
    status: str
    score: int
    visible_characters: list[str]
    reasons: list[str]
    recommendations: list[str]
    prompt_constraint: str

    def to_dict(self) -> dict:
        return asdict(self)


class ShotComplexityService:
    """Estimate whether a shot is suitable for one stable keyframe/video clip."""

    def diagnose(self, description: str, visible_characters: list[str] | None = None, dialogue: str | None = None) -> ShotComplexityReport:
        visible_characters = visible_characters or []
        text = " ".join(part for part in (description or "", dialogue or "") if part)
        words = re.findall(r"[\w\u3400-\u9fff]+", text)
        action_count = len(ACTION_RE.findall(text))
        reasons: list[str] = []
        recommendations: list[str] = []
        score = 0

        if len(visible_characters) > 2:
            score += 3
            reasons.append(f"{len(visible_characters)} visible characters in one shot")
            recommendations.append("Split group interaction into singles, two-shots, and reaction shots.")
        elif len(visible_characters) == 2:
            score += 1

        if SEQUENTIAL_RE.search(text):
            score += 3
            reasons.append("sequential action or multiple time moments")
            recommendations.append("Keep one frozen instant; move before/after actions into adjacent scenes.")

        if CAMERA_RE.search(text):
            score += 2
            reasons.append("camera movement requested")
            recommendations.append("Use a static composition for the keyframe, then add motion in the video workflow.")

        if action_count >= 4:
            score += 2
            reasons.append(f"{action_count} action cues")
            recommendations.append("Reduce to one primary action and one readable prop or expression.")

        if len(words) > 90:
            score += 2
            reasons.append(f"{len(words)} descriptive tokens")
            recommendations.append("Shorten the visual description to subject, action, setting, framing, and light.")

        if not reasons:
            reasons.append("single-shot complexity is acceptable")

        status = "ok"
        if score >= 5:
            status = "needs_split"
        elif score >= 3:
            status = "warn"

        prompt_constraint = (
            "Shot complexity constraint: one frozen instant, one primary action, static camera, "
            "no before-after sequence, no extra people."
        )
        return ShotComplexityReport(
            status=status,
            score=score,
            visible_characters=visible_characters,
            reasons=reasons,
            recommendations=recommendations,
            prompt_constraint=prompt_constraint,
        )
