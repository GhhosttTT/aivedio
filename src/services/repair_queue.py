"""Convert generation review failures into targeted repair actions."""

from __future__ import annotations

from typing import Any


ACTION_RULES = [
    (
        ("turnaround", "front view", "side view", "back view", "profile view", "body proportion", "wardrobe silhouette", "hair silhouette"),
        "regenerate_turnaround_album",
        "Generate and freeze a front/side/back turnaround album before regenerating this character.",
        "character",
    ),
    (
        ("identity", "facial", "face drift", "same-face", "same face", "changed face"),
        "regenerate_character_identity",
        "Refresh character identity bible, three-view album, and reference image before regenerating this shot.",
        "character",
    ),
    (
        ("spatial", "position", "left/right", "screen direction", "camera axis", "blocking", "stage map", "relative position"),
        "refreeze_spatial_plan",
        "Review and freeze the spatial plan before regenerating the affected shots.",
        "spatial",
    ),
    (
        ("workflow profile", "workflow", "controlnet", "openpose", "depth", "face repair", "upscale", "missing capability"),
        "fix_workflow_profile",
        "Fix and approve the ComfyUI production workflow profile before rerunning generation.",
        "workflow",
    ),
    (
        ("hand", "finger", "prop", "disappear", "letter", "phone", "cup", "object"),
        "regenerate_keyframe_with_prop_constraints",
        "Regenerate the keyframe with stricter hand and prop continuity constraints.",
        "image",
    ),
    (
        ("crop", "composition", "lighting", "muddy", "blur", "sharpness", "exposure"),
        "refine_prompt_composition",
        "Tighten composition, lighting, crop, and visual clarity before regenerating candidates.",
        "image",
    ),
    (
        ("flicker", "temporal", "motion", "camera jump", "warped body", "melting", "first frame", "last frame"),
        "lower_motion_and_regenerate_video",
        "Lower motion strength/noise and regenerate the video clip from the accepted keyframe.",
        "video",
    ),
    (
        ("unreadable action", "too complex", "multi-action", "needs_split", "split"),
        "split_scene",
        "Split this scene into simpler atomic shots before running production generation.",
        "script",
    ),
    (
        ("review unavailable", "no local vlm", "technical_only", "review failed"),
        "start_local_reviewer",
        "Start llama.cpp VLM review and rerun candidate selection before accepting output.",
        "review",
    ),
]


def build_repair_queue(report: dict[str, Any], media_type: str) -> list[dict[str, Any]]:
    """Return deduplicated repair actions for a quality report."""

    actions: list[dict[str, Any]] = []
    for candidate in report.get("candidates", []) or []:
        evidence_items = _candidate_evidence(candidate)
        for evidence in evidence_items:
            action = _classify_evidence(str(evidence), media_type, candidate)
            if action:
                actions.append(action)
    if report.get("error"):
        action = _classify_evidence(str(report["error"]), media_type, report)
        if action:
            actions.append(action)
    if report.get("status") in {"needs_review", "review_unavailable"} and not actions:
        actions.append({
            "priority": "high",
            "stage": media_type,
            "action": "manual_review",
            "reason": "Quality report needs review but did not expose a specific repair reason.",
        })
    return _dedupe(actions)


def attach_repair_queue(report: dict[str, Any], media_type: str) -> dict[str, Any]:
    report["repair_queue"] = build_repair_queue(report, media_type)
    return report


def _candidate_evidence(candidate: dict[str, Any]) -> list[str]:
    evidence = []
    if candidate.get("error"):
        evidence.append(str(candidate["error"]))
    if candidate.get("status"):
        evidence.append(str(candidate["status"]))
    review = candidate.get("review") if isinstance(candidate.get("review"), dict) else {}
    for issue in review.get("issues", []) or []:
        if isinstance(issue, dict):
            evidence.append(str(issue.get("reason") or ""))
    for key, value in review.items():
        if isinstance(value, dict) and value.get("score", 5) <= 3:
            evidence.append(str(value.get("evidence") or key))
            evidence.append(str(key))
    metrics = candidate.get("metrics") if isinstance(candidate.get("metrics"), dict) else {}
    if metrics.get("technical_score", 5) < 3:
        evidence.append("low technical image score: exposure sharpness composition")
    return [item for item in evidence if item]


def _classify_evidence(evidence: str, media_type: str, candidate: dict[str, Any]) -> dict[str, Any] | None:
    text = evidence.lower()
    for keywords, action, message, stage in ACTION_RULES:
        if any(keyword in text for keyword in keywords):
            return {
                "priority": _priority(text),
                "stage": stage if media_type == "video" or stage != "video" else media_type,
                "action": action,
                "execution": _execution_mode(action),
                "reason": evidence[:240],
                "recommendation": message,
                "candidate_index": candidate.get("index"),
                "scene_number": _scene_number(candidate),
            }
    return None


def _execution_mode(action: str) -> str:
    if action in {"regenerate_keyframe_with_prop_constraints", "refine_prompt_composition", "lower_motion_and_regenerate_video"}:
        return "auto"
    if action in {"regenerate_turnaround_album", "regenerate_character_identity", "refreeze_spatial_plan", "fix_workflow_profile", "start_local_reviewer"}:
        return "setup_required"
    return "manual"


def _priority(text: str) -> str:
    if any(term in text for term in ("critical", "major", "failed", "below", "unavailable")):
        return "high"
    if any(term in text for term in ("warning", "minor")):
        return "medium"
    return "high"


def _scene_number(candidate: dict[str, Any]) -> int | None:
    review = candidate.get("review") if isinstance(candidate.get("review"), dict) else {}
    issues = review.get("issues", []) if isinstance(review, dict) else []
    for issue in issues:
        if isinstance(issue, dict) and isinstance(issue.get("scene_number"), int):
            return issue["scene_number"]
    scene = candidate.get("scene") if isinstance(candidate.get("scene"), dict) else {}
    return scene.get("scene_number") if isinstance(scene.get("scene_number"), int) else None


def _dedupe(actions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result = []
    seen = set()
    for action in actions:
        key = (action.get("action"), action.get("stage"), action.get("scene_number"))
        if key in seen:
            continue
        seen.add(key)
        result.append(action)
    return result[:8]
