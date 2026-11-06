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
    r"\b(?:run(?:s|ning)?|ran|walk(?:s|ed|ing)?|turn(?:s|ed|ing)?|fight(?:s|ing)?|fought|"
    r"chase(?:s|d|ing)?|dance(?:s|d|ing)?|grab(?:s|bed|bing)?|throw(?:s|ing)?|threw|"
    r"fall(?:s|ing)?|fell|enter(?:s|ed|ing)?|sit(?:s|ting)?|sat|stand(?:s|ing)?|stood|"
    r"open(?:s|ed|ing)?|close(?:s|d|ing)?|hand(?:s|ed|ing)?|pass(?:es|ed|ing)?|"
    r"hug(?:s|ged|ging)?|kiss(?:es|ed|ing)?)\b"
    r"|奔跑|走|转身|打斗|追逐|跳舞|抓|扔|摔倒|进入|坐下|站起|打开|递|拥抱|亲吻"
)
CAMERA_RE = re.compile(r"\bpan|zoom|dolly|tracking|handheld|orbit\b|推镜|拉镜|摇镜|跟拍|环绕", re.I)
NO_DIALOGUE_MARKERS = {"", "无", "无对白", "没有对白", "none", "null", "n/a", "na", "-"}
PROP_RE = re.compile(
    r"\b(phone|letter|note|door|cup|knife|key|photo|weapon)\b"
    r"|手机|信|纸条|门|杯|咖啡|刀|钥匙|照片|武器",
    re.I,
)
EMOTION_RE = re.compile(
    r"\b(smile|cry|stare|hesitate|shock|angry|embarrassed|reaction|listening)\b"
    r"|哭|笑|愣|惊|怒|尴尬|羞|沉默|凝视|反应",
    re.I,
)
HIGH_ACTION_RE = re.compile(
    r"\b(?:run(?:s|ning)?|ran|fight(?:s|ing)?|fought|chase(?:s|d|ing)?|"
    r"throw(?:s|ing)?|threw|fall(?:s|ing)?|fell)\b|奔跑|追逐|打斗|击打|殴打|扔|摔倒",
    re.I,
)


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
            if str(dialogue or "").strip().lower() not in NO_DIALOGUE_MARKERS:
                score += 2
                reasons.append("two-character dialogue needs coverage rather than one generated interaction")
                recommendations.append(
                    "Use a relationship two-shot, speaker close-up, and listener reaction close-up."
                )

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
            suggested_atomic_shots=(
                _suggest_atomic_shots(description or "", dialogue or "", visible_characters)
                if status in {"warn", "needs_split"}
                else []
            ),
        )


def infer_shot_execution_contract(
    description: str,
    dialogue: str | None,
    visible_characters: list[str] | None,
) -> dict:
    """Compile the minimum model-routing contract from observable scene facts."""
    text = " ".join(part for part in (description or "", dialogue or "") if part)
    visible = list(dict.fromkeys(
        str(name).strip() for name in (visible_characters or []) if str(name).strip()
    ))
    has_dialogue = str(dialogue or "").strip().lower() not in NO_DIALOGUE_MARKERS
    if ACTION_RE.search(text):
        role = "action"
    elif PROP_RE.search(text):
        role = "prop_interaction"
    elif EMOTION_RE.search(text):
        role = "emotion_reaction"
    elif has_dialogue:
        role = "dialogue_reaction"
    else:
        role = "establishing"

    capabilities = []
    if visible:
        capabilities.append("identity_reference")
    if has_dialogue or role in {"dialogue_reaction", "emotion_reaction"}:
        capabilities.append("performance_control")
    if role in {"action", "prop_interaction"}:
        capabilities.append("motion_control")
    if len(visible) > 1:
        capabilities.append("multi_character")

    action_intensity = "low"
    if HIGH_ACTION_RE.search(text):
        action_intensity = "high"
    elif ACTION_RE.search(text):
        action_intensity = "medium"
    return {
        "shot_role": role,
        "required_engine_capabilities": capabilities,
        "action_intensity": action_intensity,
    }
def _suggest_atomic_shots(
    description: str,
    dialogue: str,
    visible_characters: list[str],
) -> list[dict]:
    """Return deterministic split hints for overloaded short-drama shots."""
    clean_description = " ".join(str(description or "").split())
    clean_dialogue = " ".join(str(dialogue or "").split())
    clean_text = " ".join(part for part in (clean_description, clean_dialogue) if part)
    if not clean_text:
        return []
    if len(visible_characters) >= 2 and clean_dialogue:
        return _dialogue_coverage_shots(
            clean_description or clean_text,
            clean_dialogue,
            visible_characters,
        )
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
            "shot_role": "action" if primary_action != "hold one readable emotional beat" else "emotion_reaction",
            "visual_description": _atomic_visual_description(part),
            "primary_action": primary_action,
            "visible_characters": characters,
            "camera": "static medium shot or close-up; no pan, zoom, orbit, or tracking move",
            "dialogue": "",
            "required_engine_capabilities": [
                *(["identity_reference"] if characters else []),
                "motion_control" if primary_action != "hold one readable emotional beat" else "performance_control",
            ],
            "continuity_note": "Continuity: keep wardrobe, prop state, screen direction, and emotional beat consistent with adjacent atomic shots.",
        })
    return shots


def _dialogue_coverage_shots(
    description: str,
    dialogue: str,
    visible_characters: list[str],
) -> list[dict]:
    """Compile a risky group dialogue into a conventional short-drama coverage plan."""
    speaker = _dialogue_speaker(dialogue, visible_characters) or visible_characters[0]
    listeners = [name for name in visible_characters if name != speaker]
    listener = listeners[0] if listeners else visible_characters[-1]
    base = _atomic_visual_description(description)
    continuity = (
        "Continuity: preserve eyelines, screen direction, wardrobe, prop ownership, lighting, "
        "and the same dialogue beat across all coverage shots."
    )
    shots = [
        {
            "order": 1,
            "shot_role": "establishing",
            "visual_description": (
                f"{base}. Static relationship two-shot establishing {speaker} at frame left looking screen right "
                f"and {listener} at frame right looking screen left."
            ),
            "primary_action": "establish character positions and eyelines",
            "visible_characters": [speaker, listener],
            "camera": "static medium two-shot; no character crosses, orbit, pan, or zoom",
            "camera_axis": "locked 180-degree dialogue axis; never cross or mirror the axis",
            "screen_positions": {speaker: "frame left", listener: "frame right"},
            "eyeline_directions": {speaker: "screen right", listener: "screen left"},
            "dialogue": "",
            "required_engine_capabilities": ["identity_reference", "multi_character"],
            "continuity_note": continuity,
        },
        {
            "order": 2,
            "shot_role": "dialogue_reaction",
            "visual_description": (
                f"{base}. Clean close-up of {speaker} at frame left looking screen right, "
                "delivering one restrained dramatic beat."
            ),
            "primary_action": "deliver the dialogue with one readable facial performance",
            "visible_characters": [speaker],
            "camera": "locked close-up with subtle breathing motion; preserve the established eyeline",
            "camera_axis": "same locked 180-degree dialogue axis as the establishing shot",
            "screen_positions": {speaker: "frame left"},
            "eyeline_directions": {speaker: "screen right"},
            "dialogue": dialogue,
            "required_engine_capabilities": ["identity_reference", "performance_control"],
            "continuity_note": continuity,
        },
    ]
    for listener_index, reaction_character in enumerate(listeners[:2], start=3):
        shots.append({
            "order": listener_index,
            "shot_role": "emotion_reaction",
            "visual_description": (
                f"{base}. Reaction close-up of {reaction_character} at frame right looking screen left, "
                "absorbing the line before responding."
            ),
            "primary_action": "hold one readable listening reaction",
            "visible_characters": [reaction_character],
            "camera": "locked reaction close-up; preserve reverse eyeline and matching headroom",
            "camera_axis": "same locked 180-degree dialogue axis as the establishing shot",
            "screen_positions": {reaction_character: "frame right"},
            "eyeline_directions": {reaction_character: "screen left"},
            "dialogue": "",
            "required_engine_capabilities": ["identity_reference", "performance_control"],
            "continuity_note": continuity,
        })
    return shots


def _dialogue_speaker(dialogue: str, visible_characters: list[str]) -> str:
    for name in visible_characters:
        if re.search(rf"(?:^|[\n;；])\s*{re.escape(name)}\s*[：:]", dialogue, re.I):
            return name
    return ""


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
