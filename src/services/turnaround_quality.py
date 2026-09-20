"""Feature-level quality gates for character turnaround albums."""

from __future__ import annotations

from typing import Any


TURNAROUND_FEATURES: dict[str, tuple[str, ...]] = {
    "front": (
        "view_angle",
        "face_shape",
        "eyes",
        "nose",
        "mouth",
        "hair",
        "distinctive_features",
        "body_proportion",
        "wardrobe_front",
    ),
    "side": (
        "view_angle",
        "nose_silhouette",
        "hair_outline",
        "body_proportion",
        "wardrobe_side",
        "no_three_quarter",
    ),
    "back": (
        "view_angle",
        "hair_back_shape",
        "body_proportion",
        "outfit_back_silhouette",
        "no_face_visible",
    ),
}


def turnaround_expected_features(view: str, character_data: dict[str, Any]) -> dict[str, str]:
    identity = {
        "face_shape": character_data.get("face_shape", ""),
        "eyes": character_data.get("eyes", ""),
        "nose": character_data.get("nose", ""),
        "mouth": character_data.get("mouth", ""),
        "hair": character_data.get("hair", ""),
        "distinctive_features": character_data.get("distinctive_features", ""),
        "body_proportion": ", ".join(
            str(item).strip()
            for item in (character_data.get("body_type"), character_data.get("height"))
            if str(item or "").strip()
        ),
        "wardrobe_front": character_data.get("outfit_details", ""),
        "wardrobe_side": character_data.get("outfit_details", ""),
        "outfit_back_silhouette": character_data.get("outfit_details", ""),
        "nose_silhouette": character_data.get("nose", ""),
        "hair_outline": character_data.get("hair", ""),
        "hair_back_shape": character_data.get("hair", ""),
    }
    view_requirements = {
        "front": {"view_angle": "strict front view, shoulders square to camera"},
        "side": {"view_angle": "strict 90 degree side profile", "no_three_quarter": "not a three-quarter view"},
        "back": {"view_angle": "strict rear view", "no_face_visible": "no visible face or front-facing pose"},
    }
    expected = {key: identity.get(key, "") for key in TURNAROUND_FEATURES[view]}
    expected.update(view_requirements.get(view, {}))
    return {key: str(value).strip() for key, value in expected.items()}


def attach_turnaround_quality_gate(
    candidate: dict[str, Any],
    view: str,
    character_data: dict[str, Any],
    min_score: float,
) -> dict[str, Any]:
    """Attach feature-level turnaround scores to a candidate report.

    The preferred source is the VLM field `turnaround_feature_scores`. When it is
    missing, the gate is marked as needs_review instead of pretending generic
    facial identity scores prove exact front/side/back consistency.
    """
    expected = turnaround_expected_features(view, character_data)
    review = candidate.get("review") if isinstance(candidate.get("review"), dict) else {}
    supplied = review.get("turnaround_feature_scores")
    if not isinstance(supplied, dict):
        supplied = candidate.get("turnaround_feature_scores") if isinstance(candidate.get("turnaround_feature_scores"), dict) else {}
    feature_scores = {}
    missing = []
    for feature in TURNAROUND_FEATURES[view]:
        score_item = supplied.get(feature) if isinstance(supplied, dict) else None
        score = score_item.get("score") if isinstance(score_item, dict) else None
        evidence = score_item.get("evidence") if isinstance(score_item, dict) else ""
        if isinstance(score, (int, float)):
            feature_scores[feature] = {
                "score": round(max(0.0, min(5.0, float(score))), 2),
                "evidence": str(evidence or "feature reviewed"),
                "expected": expected.get(feature, ""),
            }
        else:
            missing.append(feature)
            feature_scores[feature] = {
                "score": 0.0,
                "evidence": "turnaround feature was not reviewed by the local VLM",
                "expected": expected.get(feature, ""),
            }
    average = round(sum(item["score"] for item in feature_scores.values()) / len(feature_scores), 2)
    low = {
        feature: item
        for feature, item in feature_scores.items()
        if item["score"] < min_score
    }
    status = "passed" if not missing and not low else "needs_review"
    gate = {
        "status": status,
        "view": view,
        "min_score": min_score,
        "average": average,
        "scores": feature_scores,
        "missing": missing,
        "low": low,
    }
    candidate["turnaround_gate"] = gate
    candidate["turnaround_gate_score"] = average if status == "passed" else 0.0
    current_platform = candidate.get("platform_score")
    if isinstance(current_platform, (int, float)):
        candidate["platform_score"] = min(float(current_platform), candidate["turnaround_gate_score"])
    else:
        candidate["platform_score"] = candidate["turnaround_gate_score"]
    return candidate
