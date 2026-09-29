"""Plan automatic quality-repair cycles from generation review reports."""

from __future__ import annotations

from typing import Any

from src.services.repair_queue import repair_execution_mode


SCORECARD_ACTION_STAGES = {
    "regenerate_keyframe_with_identity_lock": "image",
    "regenerate_character_identity": "character",
    "regenerate_turnaround_album": "character",
    "refine_prompt_composition": "image",
    "refine_face_aesthetic_detail": "image",
    "refine_project_style_consistency": "image",
    "regenerate_keyframe_with_prop_constraints": "image",
    "lower_motion_and_regenerate_video": "video",
    "increase_motion_and_regenerate_video": "video",
    "regenerate_video_with_performance_direction": "video",
    "split_scene": "script",
    "rewrite_short_drama_story_rhythm": "script",
    "fix_workflow_profile": "workflow",
    "refreeze_spatial_plan": "spatial",
    "refine_final_composition_finish": "video",
    "refine_dialogue_audio_delivery": "audio",
    "start_local_reviewer": "review",
    "manual_review": "review",
}


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
    stage_rank = {"image": 0, "keyframe": 0, "audio": 1, "video": 2}
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


def normalize_repair_queue(repair_queue: Any) -> dict[str, list[dict[str, Any]]]:
    """Accept repair queues from API summaries and validation artifacts.

    The API quality loop stores a grouped dict. The local validation CLI writes a
    flat list gathered from image, video, baseline, manual, and quality reports.
    Normalizing both shapes keeps the rerun planner usable after real sample
    validation failures.
    """

    if isinstance(repair_queue, dict):
        return {
            "items": [
                dict(item)
                for item in repair_queue.get("items", [])
                if isinstance(item, dict)
            ],
            "setup_required": [
                dict(item)
                for item in repair_queue.get("setup_required", [])
                if isinstance(item, dict)
            ],
            "manual_actions": [
                dict(item)
                for item in repair_queue.get("manual_actions", [])
                if isinstance(item, dict)
            ],
        }
    if not isinstance(repair_queue, list):
        return {"items": [], "setup_required": [], "manual_actions": []}

    normalized = {"items": [], "setup_required": [], "manual_actions": []}
    for item in repair_queue:
        if not isinstance(item, dict):
            continue
        copied = dict(item)
        execution = copied.get("execution") or "manual"
        if execution == "auto":
            normalized["items"].append(copied)
        elif execution == "setup_required":
            normalized["setup_required"].append(copied)
        else:
            normalized["manual_actions"].append(copied)
    return normalized


def augment_repair_queue_with_scorecard(
    repair_queue: dict[str, list[dict[str, Any]]],
    scorecard: dict[str, Any] | None,
) -> dict[str, list[dict[str, Any]]]:
    """Add a fallback repair item from the quality scorecard focus.

    Some validation reports expose structured weak dimensions before they expose
    a full repair_queue item. Keeping the scorecard focus in the quality loop
    lets the next generation pass act on the weakest proven defect.
    """

    if not isinstance(scorecard, dict) or scorecard.get("status") in {None, "clean"}:
        return repair_queue
    focus = scorecard.get("next_focus") if isinstance(scorecard.get("next_focus"), dict) else {}
    action = str(focus.get("suggested_action") or "").strip()
    if not action:
        return repair_queue

    existing = {
        (item.get("action"), scene_number_from_repair_item(item))
        for bucket in repair_queue.values()
        for item in bucket
        if isinstance(item, dict)
    }
    scenes = [scene for scene in focus.get("scenes", []) if isinstance(scene, int) and scene > 0]
    if not scenes:
        scenes = [None]

    for scene_number in scenes:
        key = (action, scene_number)
        if key in existing:
            continue
        item = _scorecard_focus_item(scorecard, focus, action, scene_number)
        if item["execution"] == "auto":
            repair_queue["items"].append(item)
        elif item["execution"] == "setup_required":
            repair_queue["setup_required"].append(item)
        else:
            repair_queue["manual_actions"].append(item)
        existing.add(key)
    return repair_queue


def build_quality_loop_plan(summary: dict[str, Any], max_actions: int) -> dict[str, Any]:
    repair_queue = normalize_repair_queue(summary.get("repair_queue"))
    repair_queue = augment_repair_queue_with_scorecard(
        repair_queue,
        summary.get("quality_scorecard") if isinstance(summary.get("quality_scorecard"), dict) else None,
    )
    selected, skipped = auto_repair_candidates(repair_queue, max_actions)
    setup_required = repair_queue["setup_required"]
    manual_actions = repair_queue["manual_actions"]
    if selected:
        status = "can_auto_repair"
    elif setup_required:
        status = "setup_required"
    elif manual_actions:
        status = "manual_review_required"
    elif summary.get("status") in {"ready", "ready_for_seed_dance_candidate"}:
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


def _scorecard_focus_item(
    scorecard: dict[str, Any],
    focus: dict[str, Any],
    action: str,
    scene_number: int | None,
) -> dict[str, Any]:
    execution = repair_execution_mode(action)
    if execution == "auto" and scene_number is None:
        execution = "manual"
    evidence = focus.get("evidence") if isinstance(focus.get("evidence"), list) else []
    dimension = str(focus.get("dimension") or "quality_scorecard")
    label = str(focus.get("label") or dimension)
    reason = "; ".join(str(item) for item in evidence[:3] if item) or f"{label} needs repair"
    item = {
        "priority": "high",
        "stage": SCORECARD_ACTION_STAGES.get(action, "review"),
        "action": action,
        "execution": execution,
        "reason": reason[:240],
        "recommendation": f"Repair the weakest quality scorecard dimension: {label}.",
        "source_report": "quality_scorecard",
        "dimension": dimension,
        "production_score": scorecard.get("production_score"),
    }
    if scene_number is not None:
        item["scene_number"] = scene_number
    else:
        item["missing_scope"] = "scene_number"
    return item


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
