"""Feature-level quality gates for character turnaround albums."""

from __future__ import annotations

from typing import Any

from src.services.generation_review import MIN_REVIEW_EVIDENCE_CHARS


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
    "three_quarter_left": (
        "view_angle",
        "face_shape",
        "eyes",
        "nose_bridge",
        "mouth",
        "hair_volume",
        "distinctive_features",
        "wardrobe_left",
        "not_front_clone",
    ),
    "three_quarter_right": (
        "view_angle",
        "face_shape",
        "eyes",
        "nose_bridge",
        "mouth",
        "hair_volume",
        "distinctive_features",
        "wardrobe_right",
        "not_front_clone",
    ),
    "full_body": (
        "view_angle",
        "body_proportion",
        "height_impression",
        "wardrobe_full",
        "shoe_or_hemline",
        "face_readability",
        "same_scale",
    ),
    "expression_neutral": (
        "view_angle",
        "face_shape",
        "eyes",
        "mouth",
        "neutral_expression",
        "hair",
        "distinctive_features",
    ),
    "expression_intense": (
        "view_angle",
        "face_shape",
        "eyes",
        "mouth",
        "dramatic_expression",
        "hair",
        "distinctive_features",
        "no_identity_drift",
    ),
}


def turnaround_expected_features(view: str, character_data: dict[str, Any]) -> dict[str, str]:
    supplied = {
        feature: str(character_data.get(feature) or "").strip()
        for feature in TURNAROUND_FEATURES[view]
        if str(character_data.get(feature) or "").strip()
    }
    if supplied:
        view_requirements = {
            "front": {"view_angle": "strict front view, shoulders square to camera"},
            "side": {"view_angle": "strict 90 degree side profile", "no_three_quarter": "not a three-quarter view"},
            "back": {"view_angle": "strict rear view", "no_face_visible": "no visible face or front-facing pose"},
            "three_quarter_left": {
                "view_angle": "strict 45 degree left three-quarter view",
                "not_front_clone": "not a duplicated front view",
            },
            "three_quarter_right": {
                "view_angle": "strict 45 degree right three-quarter view",
                "not_front_clone": "not a duplicated front view",
            },
            "full_body": {
                "view_angle": "front full-body model-sheet view",
                "same_scale": "same height scale as turnaround views",
            },
            "expression_neutral": {
                "view_angle": "front close-up expression reference",
                "neutral_expression": "relaxed neutral face without smile or drama",
            },
            "expression_intense": {
                "view_angle": "front close-up expression reference",
                "dramatic_expression": "short-drama emotional intensity while preserving identity",
                "no_identity_drift": "same facial geometry as identity bible",
            },
        }
        merged = {key: supplied.get(key, "") for key in TURNAROUND_FEATURES[view]}
        merged.update({key: value for key, value in view_requirements.get(view, {}).items() if not merged.get(key)})
        return merged
    wardrobe = character_data.get("outfit_details") or character_data.get("wardrobe") or ""
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
        "wardrobe_front": wardrobe,
        "wardrobe_side": wardrobe,
        "wardrobe_left": wardrobe,
        "wardrobe_right": wardrobe,
        "wardrobe_full": wardrobe,
        "shoe_or_hemline": wardrobe,
        "outfit_back_silhouette": wardrobe,
        "nose_silhouette": character_data.get("nose", ""),
        "nose_bridge": character_data.get("nose", ""),
        "hair_outline": character_data.get("hair", ""),
        "hair_back_shape": character_data.get("hair", ""),
        "hair_volume": character_data.get("hair", ""),
        "height_impression": character_data.get("height", ""),
        "face_readability": character_data.get("face_shape", ""),
        "neutral_expression": "relaxed neutral face without smile or drama",
        "dramatic_expression": "short-drama emotional intensity while preserving identity",
        "not_front_clone": "45 degree view, not a duplicated front view",
        "same_scale": "same height scale as turnaround views",
        "no_identity_drift": "same facial geometry as identity bible",
    }
    view_requirements = {
        "front": {"view_angle": "strict front view, shoulders square to camera"},
        "side": {"view_angle": "strict 90 degree side profile", "no_three_quarter": "not a three-quarter view"},
        "back": {"view_angle": "strict rear view", "no_face_visible": "no visible face or front-facing pose"},
        "three_quarter_left": {
            "view_angle": "strict 45 degree left three-quarter view",
            "not_front_clone": "not a duplicated front view",
        },
        "three_quarter_right": {
            "view_angle": "strict 45 degree right three-quarter view",
            "not_front_clone": "not a duplicated front view",
        },
        "full_body": {
            "view_angle": "front full-body model-sheet view",
            "same_scale": "same height scale as turnaround views",
        },
        "expression_neutral": {
            "view_angle": "front close-up expression reference",
            "neutral_expression": "relaxed neutral face without smile or drama",
        },
        "expression_intense": {
            "view_angle": "front close-up expression reference",
            "dramatic_expression": "short-drama emotional intensity while preserving identity",
            "no_identity_drift": "same facial geometry as identity bible",
        },
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
    facial identity scores prove exact production character-sheet consistency.
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
        evidence = str(score_item.get("evidence") or "").strip() if isinstance(score_item, dict) else ""
        if isinstance(score, (int, float)):
            if len(evidence) < MIN_REVIEW_EVIDENCE_CHARS:
                missing.append(f"{feature}.evidence")
                feature_scores[feature] = {
                    "score": 0.0,
                    "evidence": f"specific visual evidence shorter than {MIN_REVIEW_EVIDENCE_CHARS} characters",
                    "expected": expected.get(feature, ""),
                }
            else:
                feature_scores[feature] = {
                    "score": round(max(0.0, min(5.0, float(score))), 2),
                    "evidence": evidence,
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
