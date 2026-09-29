"""Production scorecard for generated short-drama assets."""

from __future__ import annotations

from typing import Any


DIMENSION_LABELS = {
    "identity": "Character identity and role separation",
    "platform_aesthetic": "Mobile short-drama surface quality",
    "temporal_motion": "Video motion and temporal stability",
    "acting_performance": "Acting, emotion, and dialogue reaction",
    "technical_integrity": "Rendering and visual integrity",
    "story_atomicity": "Atomic shot design",
    "spatial_continuity": "Shot continuity and screen direction",
    "workflow_assets": "Production setup and control assets",
    "episode_style_consistency": "Episode visual style continuity",
    "final_composition_finish": "Final episode finishing polish",
}

ACTION_DIMENSIONS = {
    "regenerate_keyframe_with_identity_lock": "identity",
    "regenerate_character_identity": "identity",
    "regenerate_turnaround_album": "identity",
    "refine_prompt_composition": "platform_aesthetic",
    "refine_face_aesthetic_detail": "platform_aesthetic",
    "refine_project_style_consistency": "episode_style_consistency",
    "regenerate_keyframe_with_prop_constraints": "technical_integrity",
    "lower_motion_and_regenerate_video": "temporal_motion",
    "increase_motion_and_regenerate_video": "temporal_motion",
    "regenerate_video_with_performance_direction": "acting_performance",
    "split_scene": "story_atomicity",
    "fix_workflow_profile": "workflow_assets",
    "refreeze_spatial_plan": "spatial_continuity",
    "refine_final_composition_finish": "final_composition_finish",
    "start_local_reviewer": "workflow_assets",
    "manual_review": "technical_integrity",
}

SCORE_DIMENSIONS = {
    "facial_identity": "identity",
    "identity_consistency": "identity",
    "aesthetic_quality": "platform_aesthetic",
    "composition": "platform_aesthetic",
    "prompt_alignment": "story_atomicity",
    "story_match": "story_atomicity",
    "visual_integrity": "technical_integrity",
    "temporal_consistency": "temporal_motion",
    "video_performance_scores": "acting_performance",
}

FEATURE_DIMENSIONS = {
    "skin_texture": "platform_aesthetic",
    "skin_texture_stability": "platform_aesthetic",
    "lighting_quality": "platform_aesthetic",
    "lighting_consistency": "platform_aesthetic",
    "color_grade": "platform_aesthetic",
    "color_grade_consistency": "platform_aesthetic",
    "phone_readability": "platform_aesthetic",
    "background_separation": "platform_aesthetic",
    "background_stability": "temporal_motion",
    "production_polish": "platform_aesthetic",
    "style_consistency": "episode_style_consistency",
    "repair_artifacts_absent": "technical_integrity",
    "artifact_absence": "technical_integrity",
    "motion_smoothness": "temporal_motion",
    "emotion_readability": "acting_performance",
    "gaze_intent": "acting_performance",
    "dialogue_reaction": "acting_performance",
    "body_language": "acting_performance",
    "action_intent": "acting_performance",
    "scene_order_coherence": "spatial_continuity",
    "screen_direction_continuity": "spatial_continuity",
    "character_position_continuity": "spatial_continuity",
    "prop_continuity": "spatial_continuity",
    "cut_smoothness": "spatial_continuity",
    "exposure_uniformity": "final_composition_finish",
    "skin_tone_uniformity": "final_composition_finish",
    "color_grade_uniformity": "final_composition_finish",
    "sharpness_uniformity": "final_composition_finish",
    "subtitle_visual_integration": "final_composition_finish",
    "overall_finish_polish": "final_composition_finish",
}


def build_generation_quality_scorecard(reports: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """Summarize failed generation quality by production dimension.

    The scorecard is intentionally derived from authoritative review reports and
    repair queues. It does not claim visual quality; it points at the weakest
    dimensions that still need another generation or review cycle.
    """

    dimensions = {_name: _empty_dimension(_name) for _name in DIMENSION_LABELS}
    report_count = 0
    candidate_count = 0
    passed_reports = 0
    repair_queue_total = 0
    report_statuses: dict[str, str] = {}

    for report_name, report in reports.items():
        if not isinstance(report, dict):
            continue
        report_count += 1
        status = str(report.get("status") or "unknown")
        report_statuses[report_name] = status
        if status == "passed":
            passed_reports += 1
        for item in report.get("repair_queue") or []:
            if isinstance(item, dict):
                repair_queue_total += 1
                _add_repair_item(dimensions, item, report_name)
        _add_candidate_findings(dimensions, report, report_name)
        for candidate in report.get("candidates") or []:
            if isinstance(candidate, dict):
                candidate_count += 1
                _add_candidate_findings(dimensions, candidate, report_name)
        final_video_review = report.get("final_video_review")
        if isinstance(final_video_review, dict):
            candidate_count += 1
            _add_candidate_findings(dimensions, final_video_review, report_name)
        for batch in report.get("batches") or []:
            if isinstance(batch, dict):
                candidate_count += 1
                _add_candidate_findings(dimensions, batch, report_name)

    dimension_list = [_finalize_dimension(item) for item in dimensions.values()]
    failing = [item for item in dimension_list if item["issue_count"] > 0]
    failing.sort(key=lambda item: (item["score"], -item["issue_count"], item["dimension"]))
    production_score = _production_score(dimension_list, report_count, passed_reports, repair_queue_total)
    return {
        "status": "needs_repair" if failing or repair_queue_total else "clean",
        "production_score": production_score,
        "report_count": report_count,
        "candidate_count": candidate_count,
        "repair_queue_total": repair_queue_total,
        "report_statuses": report_statuses,
        "weakest_dimensions": failing[:5],
        "dimensions": {item["dimension"]: item for item in dimension_list},
        "next_focus": _next_focus(failing),
    }


def _empty_dimension(name: str) -> dict[str, Any]:
    return {
        "dimension": name,
        "label": DIMENSION_LABELS[name],
        "issue_count": 0,
        "worst_score": None,
        "scenes": set(),
        "actions": {},
        "evidence": [],
        "source_reports": set(),
    }


def _add_repair_item(dimensions: dict[str, dict[str, Any]], item: dict[str, Any], report_name: str) -> None:
    action = str(item.get("action") or "manual_review")
    dimension = ACTION_DIMENSIONS.get(action, "technical_integrity")
    target = dimensions[dimension]
    target["issue_count"] += 1
    target["actions"][action] = target["actions"].get(action, 0) + 1
    target["source_reports"].add(report_name)
    scene_number = _scene_number(item)
    if scene_number is not None:
        target["scenes"].add(scene_number)
    reason = str(item.get("reason") or item.get("recommendation") or action).strip()
    if reason:
        _append_evidence(target, reason)


def _add_candidate_findings(dimensions: dict[str, dict[str, Any]], candidate: dict[str, Any], report_name: str) -> None:
    review = candidate.get("review") if isinstance(candidate.get("review"), dict) else {}
    for key, value in review.items():
        if isinstance(value, dict) and isinstance(value.get("score"), (int, float)) and value["score"] <= 3:
            _add_score_finding(dimensions, SCORE_DIMENSIONS.get(key, "technical_integrity"), candidate, report_name, key, value)
        elif isinstance(value, dict):
            for nested_key, nested_value in value.items():
                if isinstance(nested_value, dict) and isinstance(nested_value.get("score"), (int, float)) and nested_value["score"] <= 3:
                    dimension = FEATURE_DIMENSIONS.get(nested_key, SCORE_DIMENSIONS.get(key, "technical_integrity"))
                    _add_score_finding(dimensions, dimension, candidate, report_name, nested_key, nested_value)
    for gate_name in (
        "platform_aesthetic_gate",
        "video_aesthetic_gate",
        "episode_style_consistency_gate",
        "episode_continuity_gate",
        "final_composition_finishing_gate",
        "turnaround_gate",
        "character_distinctiveness_gate",
        "video_performance_gate",
    ):
        gate = candidate.get(gate_name) if isinstance(candidate.get(gate_name), dict) else {}
        _add_gate_findings(dimensions, gate, candidate, report_name)


def _add_score_finding(
    dimensions: dict[str, dict[str, Any]],
    dimension: str,
    candidate: dict[str, Any],
    report_name: str,
    key: str,
    value: dict[str, Any],
) -> None:
    target = dimensions[dimension]
    score = float(value["score"])
    target["issue_count"] += 1
    target["worst_score"] = score if target["worst_score"] is None else min(target["worst_score"], score)
    target["source_reports"].add(report_name)
    scene_number = _scene_number(candidate)
    if scene_number is not None:
        target["scenes"].add(scene_number)
    evidence = str(value.get("evidence") or key).strip()
    _append_evidence(target, f"{key}: {evidence}")


def _add_gate_findings(
    dimensions: dict[str, dict[str, Any]],
    gate: dict[str, Any],
    candidate: dict[str, Any],
    report_name: str,
) -> None:
    if not gate:
        return
    for bucket in ("low", "missing"):
        values = gate.get(bucket)
        if isinstance(values, dict):
            iterator = values.items()
        elif isinstance(values, list):
            iterator = ((str(item), {}) for item in values)
        else:
            continue
        for feature, payload in iterator:
            dimension = _feature_dimension(str(feature))
            target = dimensions[dimension]
            target["issue_count"] += 1
            target["source_reports"].add(report_name)
            scene_number = _scene_number(candidate)
            if scene_number is not None:
                target["scenes"].add(scene_number)
            if isinstance(payload, dict) and isinstance(payload.get("score"), (int, float)):
                score = float(payload["score"])
                target["worst_score"] = score if target["worst_score"] is None else min(target["worst_score"], score)
                evidence = str(payload.get("evidence") or feature)
            else:
                evidence = str(feature)
            _append_evidence(target, f"{feature}: {evidence}")


def _feature_dimension(feature: str) -> str:
    if feature in FEATURE_DIMENSIONS:
        return FEATURE_DIMENSIONS[feature]
    if feature in {
        "scene_order_coherence",
        "screen_direction_continuity",
        "character_position_continuity",
        "prop_continuity",
        "cut_smoothness",
    }:
        return "spatial_continuity"
    if "style_consistency" in feature or "color_grade" in feature or "lighting" in feature:
        return "episode_style_consistency"
    return "technical_integrity"


def _append_evidence(target: dict[str, Any], evidence: str) -> None:
    evidence = " ".join(evidence.split())[:180]
    if evidence and evidence not in target["evidence"]:
        target["evidence"].append(evidence)


def _scene_number(item: dict[str, Any]) -> int | None:
    value = item.get("scene_number")
    if value is None and isinstance(item.get("scene"), dict):
        value = item["scene"].get("scene_number")
    try:
        scene_number = int(value)
    except (TypeError, ValueError):
        return None
    return scene_number if scene_number > 0 else None


def _finalize_dimension(item: dict[str, Any]) -> dict[str, Any]:
    worst_score = item["worst_score"]
    if worst_score is None:
        score = 5.0 if item["issue_count"] == 0 else 3.0
    else:
        score = max(0.0, min(5.0, worst_score))
    if item["issue_count"] > 0:
        score = max(0.0, score - min(1.5, item["issue_count"] * 0.15))
    return {
        "dimension": item["dimension"],
        "label": item["label"],
        "status": "passed" if item["issue_count"] == 0 else "needs_repair",
        "score": round(score, 2),
        "issue_count": item["issue_count"],
        "worst_score": worst_score,
        "scenes": sorted(item["scenes"]),
        "actions": dict(sorted(item["actions"].items())),
        "evidence": item["evidence"][:5],
        "source_reports": sorted(item["source_reports"]),
    }


def _production_score(dimensions: list[dict[str, Any]], report_count: int, passed_reports: int, repair_queue_total: int) -> float:
    if report_count == 0:
        return 0.0
    average_dimension = sum(item["score"] for item in dimensions) / len(dimensions)
    report_pass_ratio = passed_reports / report_count
    penalty = min(1.5, repair_queue_total * 0.12)
    return round(max(0.0, min(5.0, average_dimension * 0.75 + report_pass_ratio * 1.25 - penalty)), 2)


def _next_focus(failing: list[dict[str, Any]]) -> dict[str, Any] | None:
    if not failing:
        return None
    first = failing[0]
    actions = sorted(first["actions"].items(), key=lambda item: (-item[1], item[0]))
    return {
        "dimension": first["dimension"],
        "label": first["label"],
        "suggested_action": actions[0][0] if actions else None,
        "scenes": first["scenes"][:5],
        "evidence": first["evidence"][:3],
    }
