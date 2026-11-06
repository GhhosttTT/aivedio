"""Conservative cross-shot checks for explicit character state contracts."""

from __future__ import annotations

import re
from collections.abc import Iterable


_HAND_SIDE = re.compile(r"(?:\b(?P<english>left|right)\s+hand\b|(?P<chinese>左手|右手))", re.IGNORECASE)
_EXPLICIT_HANDOFF = re.compile(r"换手|交接|递给|移交|handoff|hand\s*over|switch(?:ed|ing)?\s+hands?", re.IGNORECASE)


def _hand_sides(text: str) -> set[str]:
    sides: set[str] = set()
    for match in _HAND_SIDE.finditer(text or ""):
        token = (match.group("english") or match.group("chinese") or "").lower()
        sides.add("left" if token in {"left", "左手"} else "right")
    return sides


def _state_map(scene: dict) -> dict[str, dict]:
    specification = scene.get("shot_spec")
    if not isinstance(specification, dict):
        return {}
    states = specification.get("character_states")
    if not isinstance(states, list):
        return {}
    result = {}
    for state in states:
        if isinstance(state, dict) and isinstance(state.get("character_name"), str):
            result[state["character_name"]] = state
    return result


def _asset_map(scene: dict) -> dict[str, dict]:
    specification = scene.get("shot_spec")
    if not isinstance(specification, dict):
        return {}
    assets = specification.get("continuity_assets")
    if not isinstance(assets, list):
        return {}
    return {
        asset["asset_id"]: asset
        for asset in assets
        if isinstance(asset, dict) and isinstance(asset.get("asset_id"), str) and asset["asset_id"].strip()
    }


class ShotStateContinuityService:
    """Report only deterministic hand-side conflicts across adjacent shots.

    Free-form state descriptions cannot reliably prove semantic equivalence.
    The service therefore exposes coverage and flags only an explicit hand-side
    flip without a declared handoff, leaving all other transitions to review.
    """

    def assess(self, script_scenes: Iterable[dict]) -> dict:
        scenes = sorted(
            (scene for scene in script_scenes if isinstance(scene, dict) and isinstance(scene.get("scene_number"), int)),
            key=lambda scene: scene["scene_number"],
        )
        transitions = []
        conflicts = []
        asset_transitions = []
        asset_conflicts = []
        previous_states: dict[str, tuple[int, dict, str]] = {}
        previous_assets: dict[str, tuple[int, dict]] = {}

        for scene in scenes:
            scene_number = scene["scene_number"]
            for character_name, current in _state_map(scene).items():
                start_state = str(current.get("start_state") or "")
                previous = previous_states.get(character_name)
                if previous and start_state and previous[0] == scene_number - 1:
                    previous_scene, previous_state, end_state = previous
                    transition = {
                        "character_name": character_name,
                        "from_scene": previous_scene,
                        "to_scene": scene_number,
                        "has_end_state": bool(end_state),
                        "has_start_state": True,
                    }
                    transitions.append(transition)
                    previous_sides = _hand_sides(end_state)
                    current_sides = _hand_sides(start_state)
                    handoff_declared = bool(_EXPLICIT_HANDOFF.search(f"{end_state}\n{start_state}"))
                    if previous_sides and current_sides and previous_sides.isdisjoint(current_sides) and not handoff_declared:
                        conflicts.append({
                            **transition,
                            "type": "hand_side_conflict",
                            "previous_sides": sorted(previous_sides),
                            "current_sides": sorted(current_sides),
                            "message": (
                                f"{character_name} 在分镜 {previous_scene} 到 {scene_number} 的手部状态从 "
                                f"{', '.join(sorted(previous_sides))} 变为 {', '.join(sorted(current_sides))}，"
                                "但未声明换手或交接。"
                            ),
                        })
                end_state = str(current.get("end_state") or "")
                if end_state or start_state:
                    previous_states[character_name] = (scene_number, current, end_state)

            for asset_id, current in _asset_map(scene).items():
                previous = previous_assets.get(asset_id)
                if previous and previous[0] == scene_number - 1:
                    previous_scene, previous_asset = previous
                    previous_end = previous_asset.get("end_state") or {}
                    current_start = current.get("start_state") or {}
                    if not isinstance(previous_end, dict):
                        previous_end = {}
                    if not isinstance(current_start, dict):
                        current_start = {}
                    transition = {
                        "asset_id": asset_id,
                        "kind": current.get("kind") or previous_asset.get("kind") or "other",
                        "from_scene": previous_scene,
                        "to_scene": scene_number,
                        "inherits_previous": bool(current.get("inherits_previous", True)),
                        "has_transition_note": bool(str(current.get("transition_note") or "").strip()),
                        "compared_attributes": sorted(set(previous_end).intersection(current_start)),
                    }
                    asset_transitions.append(transition)
                    if transition["inherits_previous"] and not transition["has_transition_note"]:
                        mismatches = {
                            key: {"previous": previous_end[key], "current": current_start[key]}
                            for key in transition["compared_attributes"]
                            if previous_end[key] != current_start[key]
                        }
                        if mismatches:
                            asset_conflicts.append({
                                **transition,
                                "type": "asset_attribute_conflict",
                                "mismatches": mismatches,
                                "message": (
                                    f"{asset_id} 在分镜 {previous_scene} 到 {scene_number} 的状态发生变化，"
                                    "但未声明转场原因。"
                                ),
                            })
                previous_assets[asset_id] = (scene_number, current)

        return {
            "status": "needs_review" if conflicts or asset_conflicts else (
                "documented" if transitions or asset_transitions else "not_configured"
            ),
            "summary": {
                "tracked_transitions": len(transitions),
                "asset_transitions": len(asset_transitions),
                "conflicts": len(conflicts) + len(asset_conflicts),
            },
            "transitions": transitions,
            "conflicts": conflicts,
            "asset_transitions": asset_transitions,
            "asset_conflicts": asset_conflicts,
        }
