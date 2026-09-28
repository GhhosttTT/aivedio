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


PROFILE_BUDGETS = {
    "high_quality": {"candidate_multiplier": 1.25, "extra_refinement_passes": 0},
    "ultra": {"candidate_multiplier": 1.5, "extra_refinement_passes": 1},
    "seed_dance_reference": {"candidate_multiplier": 2.0, "extra_refinement_passes": 2},
}


ACTION_BUDGETS = {
    "image": {
        "regenerate_keyframe_with_identity_lock": {
            "candidate_multiplier": 1.6,
            "extra_refinement_passes": 1,
            "min_candidates": 5,
            "profile": "identity_lock",
        },
        "refine_prompt_composition": {
            "candidate_multiplier": 1.4,
            "extra_refinement_passes": 1,
            "min_candidates": 4,
            "profile": "composition_polish",
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
