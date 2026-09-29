"""Production quality budgets for local generation and repair passes."""

from __future__ import annotations

import math
from dataclasses import dataclass

from src.config import settings


@dataclass(frozen=True)
class QualityBudget:
    candidate_count: int
    refinement_passes: int
    max_candidates: int
    profile: str
    repair_action: str | None = None
    reason: str = "base_generation"
    action_profile: str | None = None

    def as_dict(self) -> dict:
        return {
            "candidate_count": self.candidate_count,
            "refinement_passes": self.refinement_passes,
            "max_candidates": self.max_candidates,
            "profile": self.profile,
            "repair_action": self.repair_action,
            "reason": self.reason,
            "action_profile": self.action_profile,
        }


@dataclass(frozen=True)
class QualityPipeline:
    stages: list[str]
    prompt_directive: str
    negative_directive: str
    required_capabilities: list[str]
    shot_profile_id: str | None = None
    repair_action: str | None = None

    def as_dict(self) -> dict:
        return {
            "stages": list(self.stages),
            "prompt_directive": self.prompt_directive,
            "negative_directive": self.negative_directive,
            "required_capabilities": list(self.required_capabilities),
            "shot_profile_id": self.shot_profile_id,
            "repair_action": self.repair_action,
        }


PROFILE_BUDGETS = {
    "high_quality": {"candidate_multiplier": 1.25, "extra_refinement_passes": 0},
    "ultra": {"candidate_multiplier": 1.5, "extra_refinement_passes": 1},
    "seed_dance_reference": {"candidate_multiplier": 2.0, "extra_refinement_passes": 2},
}


SHOT_PIPELINE_STAGES = {
    "close_up": {
        "stages": ["identity_reference", "face_detail", "skin_texture_pass", "upscale", "final_vlm_review"],
        "prompt": "production pipeline: face detail pass, natural skin texture pass, clean catchlight preservation, final VLM review",
        "negative": "waxy face after detailer, over-sharpened pores, face repair scar, plastic close-up",
        "capabilities": ["character_identity", "face_repair", "upscale", "candidate_review"],
    },
    "reaction": {
        "stages": ["identity_reference", "expression_polish", "face_detail", "upscale", "final_vlm_review"],
        "prompt": "production pipeline: expression polish pass, face detail pass, emotion readability check, final VLM review",
        "negative": "flat acting, dead eyes, overdone expression repair, waxy emotion close-up",
        "capabilities": ["character_identity", "face_repair", "upscale", "candidate_review"],
    },
    "two_shot": {
        "stages": ["identity_reference", "spatial_control", "role_separation", "upscale", "final_vlm_review"],
        "prompt": "production pipeline: spatial control pass, role separation pass, both faces readable, final VLM review",
        "negative": "same-face casting after upscale, merged bodies, hidden second actor, copied wardrobe silhouette",
        "capabilities": ["character_identity", "spatial_control", "upscale", "candidate_review"],
    },
    "full_body": {
        "stages": ["pose_control", "body_integrity", "wardrobe_silhouette", "upscale", "final_vlm_review"],
        "prompt": "production pipeline: pose control pass, full-body proportion check, wardrobe silhouette preservation, final VLM review",
        "negative": "floating feet, broken full-body pose, cropped shoes, distorted body after upscale",
        "capabilities": ["pose_control", "spatial_control", "upscale", "candidate_review"],
    },
    "prop_interaction": {
        "stages": ["pose_control", "hand_prop_integrity", "face_detail", "upscale", "final_vlm_review"],
        "prompt": "production pipeline: hand-prop integrity pass, readable fingers, stable prop contact, face detail pass, final VLM review",
        "negative": "broken fingers after detail pass, disappearing prop, floating prop, unclear hand-object contact",
        "capabilities": ["pose_control", "face_repair", "upscale", "candidate_review"],
    },
    "establishing": {
        "stages": ["spatial_control", "set_dressing_polish", "color_grade_lock", "upscale", "final_vlm_review"],
        "prompt": "production pipeline: set dressing polish pass, color grade lock, subject readability check, final VLM review",
        "negative": "generic empty set, low-budget background, dirty clutter after upscale, washed-out color grade",
        "capabilities": ["spatial_control", "upscale", "candidate_review"],
    },
}

REPAIR_PIPELINE_STAGES = {
    "regenerate_keyframe_with_identity_lock": {
        "stages": ["identity_reference", "face_detail", "identity_vlm_review"],
        "prompt": "repair pipeline: stricter identity reference lock and identity VLM review before acceptance",
        "negative": "identity drift after repair, same-face cast, changed wardrobe after identity lock",
        "capabilities": ["character_identity", "face_repair", "candidate_review"],
    },
    "regenerate_keyframe_with_role_separation": {
        "stages": ["identity_reference", "spatial_control", "role_separation", "face_detail", "distinctiveness_vlm_review"],
        "prompt": "repair pipeline: enforce identity contrast matrix, role separation, and character distinctiveness VLM review before acceptance",
        "negative": "same-face casting after repair, copied facial geometry, merged visual identity, hidden second actor",
        "capabilities": ["character_identity", "spatial_control", "face_repair", "candidate_review"],
    },
    "refine_project_style_consistency": {
        "stages": ["project_style_bible", "color_grade_lock", "lighting_continuity", "wardrobe_continuity", "style_vlm_review"],
        "prompt": "repair pipeline: lock project visual bible, color grade, lighting continuity, wardrobe continuity, and set dressing continuity before acceptance",
        "negative": "style drift after repair, random color grade, mismatched lighting, wardrobe drift, inconsistent set dressing",
        "capabilities": ["spatial_control", "upscale", "candidate_review"],
    },
    "refine_face_aesthetic_detail": {
        "stages": ["face_detail", "skin_texture_pass", "upscale", "artifact_vlm_review"],
        "prompt": "repair pipeline: high quality face detail pass, skin texture artifact check, upscale artifact review",
        "negative": "face repair scar, wax museum skin, over-smoothed detailer result, noisy upscale face",
        "capabilities": ["face_repair", "upscale", "candidate_review"],
    },
    "refine_prompt_composition": {
        "stages": ["spatial_control", "composition_vlm_review"],
        "prompt": "repair pipeline: composition control pass and phone-frame composition review",
        "negative": "bad crop after composition repair, unreadable face, cluttered layout",
        "capabilities": ["spatial_control", "candidate_review"],
    },
    "regenerate_keyframe_with_prop_constraints": {
        "stages": ["pose_control", "hand_prop_integrity", "prop_vlm_review"],
        "prompt": "repair pipeline: hand and prop constraint pass with prop VLM review",
        "negative": "changed prop after repair, fused fingers, disappearing object",
        "capabilities": ["pose_control", "candidate_review"],
    },
}


ACTION_BUDGETS = {
    "image": {
        "regenerate_keyframe_with_identity_lock": {
            "candidate_multiplier": 1.6,
            "extra_refinement_passes": 1,
            "min_candidates": 5,
            "profile": "identity_lock",
        },
        "regenerate_keyframe_with_role_separation": {
            "candidate_multiplier": 2.0,
            "extra_refinement_passes": 2,
            "min_candidates": 6,
            "profile": "multi_character_role_separation",
        },
        "refine_prompt_composition": {
            "candidate_multiplier": 1.4,
            "extra_refinement_passes": 1,
            "min_candidates": 4,
            "profile": "composition_polish",
        },
        "refine_project_style_consistency": {
            "candidate_multiplier": 1.7,
            "extra_refinement_passes": 2,
            "min_candidates": 5,
            "profile": "project_style_consistency",
        },
        "refine_face_aesthetic_detail": {
            "candidate_multiplier": 2.0,
            "extra_refinement_passes": 2,
            "min_candidates": 6,
            "profile": "face_aesthetic_micro_detail",
        },
        "regenerate_keyframe_with_prop_constraints": {
            "candidate_multiplier": 1.35,
            "extra_refinement_passes": 1,
            "min_candidates": 4,
            "profile": "prop_hand_constraints",
        },
    },
    "video": {
        "lower_motion_and_regenerate_video": {
            "candidate_multiplier": 1.7,
            "extra_refinement_passes": 2,
            "min_candidates": 4,
            "profile": "temporal_identity_stabilization",
        },
        "increase_motion_and_regenerate_video": {
            "candidate_multiplier": 1.5,
            "extra_refinement_passes": 1,
            "min_candidates": 4,
            "profile": "motion_floor_recovery",
        },
        "regenerate_video_with_performance_direction": {
            "candidate_multiplier": 1.6,
            "extra_refinement_passes": 2,
            "min_candidates": 4,
            "profile": "performance_direction_recovery",
        },
        "refine_video_commercial_aesthetic": {
            "candidate_multiplier": 1.8,
            "extra_refinement_passes": 2,
            "min_candidates": 5,
            "profile": "video_commercial_aesthetic_recovery",
        },
    },
}


def image_quality_budget(repair_action: str | None = None) -> QualityBudget:
    return _budget(
        stage="image",
        base_candidates=settings.GENERATION_IMAGE_CANDIDATES,
        base_refinement_passes=settings.GENERATION_IMAGE_REFINEMENT_PASSES,
        max_candidates=settings.GENERATION_MAX_IMAGE_CANDIDATES,
        repair_multiplier=settings.GENERATION_REPAIR_IMAGE_CANDIDATE_MULTIPLIER,
        repair_action=repair_action,
    )


def video_quality_budget(repair_action: str | None = None) -> QualityBudget:
    return _budget(
        stage="video",
        base_candidates=settings.GENERATION_VIDEO_CANDIDATES,
        base_refinement_passes=settings.GENERATION_VIDEO_REFINEMENT_PASSES,
        max_candidates=settings.GENERATION_MAX_VIDEO_CANDIDATES,
        repair_multiplier=settings.GENERATION_REPAIR_VIDEO_CANDIDATE_MULTIPLIER,
        repair_action=repair_action,
    )


def image_quality_pipeline(
    shot_aesthetic_profile: dict | None = None,
    repair_action: str | None = None,
) -> QualityPipeline:
    profile_id = None
    if isinstance(shot_aesthetic_profile, dict):
        profile_id = str(shot_aesthetic_profile.get("id") or "").strip() or None
    base = SHOT_PIPELINE_STAGES.get(profile_id or "", SHOT_PIPELINE_STAGES["reaction"])
    stages = list(base["stages"])
    prompt_parts = [base["prompt"]]
    negative_parts = [base["negative"]]
    capabilities = set(base["capabilities"])
    if repair_action:
        repair = REPAIR_PIPELINE_STAGES.get(repair_action)
        if repair:
            stages.extend(repair["stages"])
            prompt_parts.append(repair["prompt"])
            negative_parts.append(repair["negative"])
            capabilities.update(repair["capabilities"])
    stages = list(dict.fromkeys(stages))
    return QualityPipeline(
        stages=stages,
        prompt_directive=". ".join(dict.fromkeys(part for part in prompt_parts if part)),
        negative_directive=", ".join(dict.fromkeys(part for part in negative_parts if part)),
        required_capabilities=sorted(capabilities),
        shot_profile_id=profile_id,
        repair_action=repair_action,
    )


def _budget(
    *,
    stage: str,
    base_candidates: int,
    base_refinement_passes: int,
    max_candidates: int,
    repair_multiplier: float,
    repair_action: str | None,
) -> QualityBudget:
    max_candidates = max(1, int(max_candidates))
    candidate_count = max(1, min(int(base_candidates), max_candidates))
    refinement_passes = max(0, int(base_refinement_passes))
    profile = settings.GENERATION_QUALITY_PROFILE.strip().lower()
    profile_budget = PROFILE_BUDGETS.get(profile)
    reason = "base_generation_budget"
    action_profile = None
    if profile_budget:
        candidate_count = max(
            candidate_count,
            min(max_candidates, int(math.ceil(candidate_count * profile_budget["candidate_multiplier"]))),
        )
        refinement_passes += max(0, int(profile_budget["extra_refinement_passes"]))
        reason = "profile_generation_budget"
    if repair_action:
        candidate_count = max(
            candidate_count,
            min(max_candidates, int(math.ceil(candidate_count * max(1.0, repair_multiplier)))),
        )
        refinement_passes = max(
            refinement_passes,
            refinement_passes + max(0, int(settings.GENERATION_REPAIR_EXTRA_REFINEMENT_PASSES)),
        )
        reason = "repair_generation_budget"
        action_budget = ACTION_BUDGETS.get(stage, {}).get(repair_action)
        if action_budget:
            candidate_count = max(
                candidate_count,
                min(max_candidates, int(action_budget["min_candidates"])),
                min(max_candidates, int(math.ceil(candidate_count * action_budget["candidate_multiplier"]))),
            )
            refinement_passes += max(0, int(action_budget["extra_refinement_passes"]))
            action_profile = str(action_budget["profile"])
    return QualityBudget(
        candidate_count=candidate_count,
        refinement_passes=refinement_passes,
        max_candidates=max_candidates,
        profile=profile,
        repair_action=repair_action,
        reason=reason,
        action_profile=action_profile,
    )
