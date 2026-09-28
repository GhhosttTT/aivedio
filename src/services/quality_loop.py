"""Plan automatic quality-repair cycles from generation review reports."""

from __future__ import annotations

from typing import Any


def scene_number_from_repair_item(item: dict[str, Any]) -> int | None:
    value = item.get("scene_number")
    if value is None:
        return None
    try:
        scene_number = int(value)
    except (TypeError, ValueError):
        return None
    return scene_number if scene_number > 0 else None


def auto_repair_candidates(repair_queue: dict[str, Any], max_actions: int) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Select executable repair actions for one quality loop iteration.

    One scene is repaired at most once per iteration. Image/keyframe repairs are
    selected before video repairs because accepted video depends on the keyframe.
    """
    priority_rank = {"high": 0, "medium": 1, "low": 2}
    stage_rank = {"image": 0, "keyframe": 0, "video": 1}
    items = [
        dict(item)
        for item in repair_queue.get("items", [])
        if isinstance(item, dict) and item.get("execution") == "auto"
    ]
    items.sort(
        key=lambda item: (
            priority_rank.get(item.get("priority"), 9),
            stage_rank.get(item.get("stage"), 5),
            item.get("source_report") or "",
            item.get("action") or "",
        )
    )

    selected: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    seen_scenes = set()
    seen_actions = set()
    for item in items:
        scene_number = scene_number_from_repair_item(item)
        action = item.get("action")
        item["scene_number"] = scene_number
        if scene_number is None:
            skipped.append({**item, "reason": "missing_scene_number"})
            continue
        if not action:
            skipped.append({**item, "reason": "missing_action"})
            continue
        if scene_number in seen_scenes:
            skipped.append({**item, "reason": "scene_already_selected"})
            continue
        key = (scene_number, action)
        if key in seen_actions:
            skipped.append({**item, "reason": "duplicate_action"})
            continue
        if len(selected) >= max_actions:
            skipped.append({**item, "reason": "max_actions_reached"})
            continue
        selected.append(item)
        seen_scenes.add(scene_number)
        seen_actions.add(key)
    return selected, skipped


def build_quality_loop_plan(summary: dict[str, Any], max_actions: int) -> dict[str, Any]:
    repair_queue = summary.get("repair_queue", {}) if isinstance(summary.get("repair_queue"), dict) else {}
    selected, skipped = auto_repair_candidates(repair_queue, max_actions)
    setup_required = repair_queue.get("setup_required", []) if isinstance(repair_queue.get("setup_required"), list) else []
    manual_actions = repair_queue.get("manual_actions", []) if isinstance(repair_queue.get("manual_actions"), list) else []
    if selected:
        status = "can_auto_repair"
    elif setup_required:
        status = "setup_required"
    elif manual_actions:
        status = "manual_review_required"
    elif summary.get("status") == "ready":
        status = "ready"
    else:
        status = "blocked"
    return {
        "status": status,
        "selected": selected,
        "skipped": skipped,
        "setup_required": setup_required,
        "manual_actions": manual_actions,
        "next_step": _next_step(status),
    }


def _next_step(status: str) -> str:
    if status == "can_auto_repair":
        return "Submit selected automatic repair tasks, rerun generation review, then rebuild this plan."
    if status == "setup_required":
        return "Complete required asset, workflow, or reviewer setup before submitting repairs."
    if status == "manual_review_required":
        return "Review manual actions and choose a concrete repair before the next generation cycle."
    if status == "ready":
        return "Proceed to final composition and human sample review."
    return "Resolve blocking review items before the next production attempt."
