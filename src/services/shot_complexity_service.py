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
    suggested_atomic_shots: list[dict]

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
            suggested_atomic_shots=_suggest_atomic_shots(text, visible_characters) if status in {"warn", "needs_split"} else [],
        )


def _suggest_atomic_shots(text: str, visible_characters: list[str]) -> list[dict]:
    """Return deterministic split hints for overloaded short-drama shots."""
    clean_text = " ".join(str(text or "").split())
    if not clean_text:
        return []
    parts = [
        part.strip(" ,.;，。；")
        for part in re.split(
            r"\b(?:and then|then|afterwards|subsequently|while)\b|然后|接着|随后|同时|一边",
            clean_text,
            flags=re.I,
        )
        if part.strip(" ,.;，。；")
    ]
    if len(parts) <= 1:
        parts = [clean_text]
    shots = []
    for index, part in enumerate(parts[:4], start=1):
        primary_action = _primary_action(part)
        characters = _characters_in_text(part, visible_characters) or visible_characters[:2]
        shots.append({
            "order": index,
            "visual_description": _atomic_visual_description(part),
            "primary_action": primary_action,
            "visible_characters": characters,
            "camera": "static medium shot or close-up; no pan, zoom, orbit, or tracking move",
            "continuity_note": "Continuity: keep wardrobe, prop state, screen direction, and emotional beat consistent with adjacent atomic shots.",
        })
    return shots


def _primary_action(text: str) -> str:
    matches = ACTION_RE.findall(text or "")
    if not matches:
        return "hold one readable emotional beat"
    first = matches[0]
    if isinstance(first, tuple):
        first = next((item for item in first if item), "")
    return str(first or "hold one readable emotional beat")


def _characters_in_text(text: str, visible_characters: list[str]) -> list[str]:
    lowered = (text or "").lower()
    found = [name for name in visible_characters if name and name.lower() in lowered]
    return found


def _atomic_visual_description(text: str) -> str:
    text = re.sub(CAMERA_RE, "static camera", text or "")
    text = re.sub(r"\b(camera pans|camera zooms|tracking shot)\b|镜头推进|镜头拉远|镜头跟随|推镜|拉镜|摇镜|跟拍|环绕", "static camera", text, flags=re.I)
    text = " ".join(text.split())
    if len(text) > 180:
        text = text[:177].rstrip() + "..."
    return text
