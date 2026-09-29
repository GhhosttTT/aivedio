from src.services.generation_quality_policy import image_quality_budget, image_quality_pipeline, video_quality_budget


def test_repair_image_budget_increases_candidates_and_refinement(monkeypatch):
    monkeypatch.setattr("src.services.generation_quality_policy.settings.GENERATION_QUALITY_PROFILE", "hongguo_reference")
    monkeypatch.setattr("src.services.generation_quality_policy.settings.GENERATION_IMAGE_CANDIDATES", 4)
    monkeypatch.setattr("src.services.generation_quality_policy.settings.GENERATION_IMAGE_REFINEMENT_PASSES", 1)
    monkeypatch.setattr("src.services.generation_quality_policy.settings.GENERATION_MAX_IMAGE_CANDIDATES", 8)
    monkeypatch.setattr("src.services.generation_quality_policy.settings.GENERATION_REPAIR_IMAGE_CANDIDATE_MULTIPLIER", 1.5)
    monkeypatch.setattr("src.services.generation_quality_policy.settings.GENERATION_REPAIR_EXTRA_REFINEMENT_PASSES", 1)

    budget = image_quality_budget("regenerate_keyframe_with_identity_lock")

    assert budget.candidate_count == 8
    assert budget.refinement_passes == 3
    assert budget.reason == "repair_generation_budget"
    assert budget.action_profile == "identity_lock"


def test_role_separation_image_budget_uses_heavier_multi_character_profile(monkeypatch):
    monkeypatch.setattr("src.services.generation_quality_policy.settings.GENERATION_QUALITY_PROFILE", "hongguo_reference")
    monkeypatch.setattr("src.services.generation_quality_policy.settings.GENERATION_IMAGE_CANDIDATES", 2)
    monkeypatch.setattr("src.services.generation_quality_policy.settings.GENERATION_IMAGE_REFINEMENT_PASSES", 1)
    monkeypatch.setattr("src.services.generation_quality_policy.settings.GENERATION_MAX_IMAGE_CANDIDATES", 8)
    monkeypatch.setattr("src.services.generation_quality_policy.settings.GENERATION_REPAIR_IMAGE_CANDIDATE_MULTIPLIER", 1.5)
    monkeypatch.setattr("src.services.generation_quality_policy.settings.GENERATION_REPAIR_EXTRA_REFINEMENT_PASSES", 1)

    budget = image_quality_budget("regenerate_keyframe_with_role_separation")
    pipeline = image_quality_pipeline({"id": "two_shot"}, "regenerate_keyframe_with_role_separation")

    assert budget.candidate_count == 6
    assert budget.refinement_passes == 4
    assert budget.action_profile == "multi_character_role_separation"
    assert "role_separation" in pipeline.stages
    assert "distinctiveness_vlm_review" in pipeline.stages
    assert "spatial_control" in pipeline.required_capabilities


def test_style_consistency_image_budget_and_pipeline_lock_project_look(monkeypatch):
    monkeypatch.setattr("src.services.generation_quality_policy.settings.GENERATION_QUALITY_PROFILE", "hongguo_reference")
    monkeypatch.setattr("src.services.generation_quality_policy.settings.GENERATION_IMAGE_CANDIDATES", 2)
    monkeypatch.setattr("src.services.generation_quality_policy.settings.GENERATION_IMAGE_REFINEMENT_PASSES", 1)
    monkeypatch.setattr("src.services.generation_quality_policy.settings.GENERATION_MAX_IMAGE_CANDIDATES", 8)
    monkeypatch.setattr("src.services.generation_quality_policy.settings.GENERATION_REPAIR_IMAGE_CANDIDATE_MULTIPLIER", 1.5)
    monkeypatch.setattr("src.services.generation_quality_policy.settings.GENERATION_REPAIR_EXTRA_REFINEMENT_PASSES", 1)

    budget = image_quality_budget("refine_project_style_consistency")
    pipeline = image_quality_pipeline({"id": "establishing"}, "refine_project_style_consistency")

    assert budget.candidate_count == 6
    assert budget.refinement_passes == 4
    assert budget.action_profile == "project_style_consistency"
    assert "project_style_bible" in pipeline.stages
    assert "color_grade_lock" in pipeline.stages
    assert "style_vlm_review" in pipeline.stages
    assert "candidate_review" in pipeline.required_capabilities


def test_video_budget_respects_max_candidate_cap(monkeypatch):
    monkeypatch.setattr("src.services.generation_quality_policy.settings.GENERATION_QUALITY_PROFILE", "hongguo_reference")
    monkeypatch.setattr("src.services.generation_quality_policy.settings.GENERATION_VIDEO_CANDIDATES", 6)
    monkeypatch.setattr("src.services.generation_quality_policy.settings.GENERATION_VIDEO_REFINEMENT_PASSES", 2)
    monkeypatch.setattr("src.services.generation_quality_policy.settings.GENERATION_MAX_VIDEO_CANDIDATES", 8)
    monkeypatch.setattr("src.services.generation_quality_policy.settings.GENERATION_REPAIR_VIDEO_CANDIDATE_MULTIPLIER", 2.0)
    monkeypatch.setattr("src.services.generation_quality_policy.settings.GENERATION_REPAIR_EXTRA_REFINEMENT_PASSES", 1)

    budget = video_quality_budget("lower_motion_and_regenerate_video")

    assert budget.candidate_count == 8
    assert budget.refinement_passes == 5
    assert budget.max_candidates == 8
    assert budget.action_profile == "temporal_identity_stabilization"


def test_increase_motion_video_budget_uses_motion_floor_profile(monkeypatch):
    monkeypatch.setattr("src.services.generation_quality_policy.settings.GENERATION_QUALITY_PROFILE", "hongguo_reference")
    monkeypatch.setattr("src.services.generation_quality_policy.settings.GENERATION_VIDEO_CANDIDATES", 2)
    monkeypatch.setattr("src.services.generation_quality_policy.settings.GENERATION_VIDEO_REFINEMENT_PASSES", 1)
    monkeypatch.setattr("src.services.generation_quality_policy.settings.GENERATION_MAX_VIDEO_CANDIDATES", 8)
    monkeypatch.setattr("src.services.generation_quality_policy.settings.GENERATION_REPAIR_VIDEO_CANDIDATE_MULTIPLIER", 1.5)
    monkeypatch.setattr("src.services.generation_quality_policy.settings.GENERATION_REPAIR_EXTRA_REFINEMENT_PASSES", 1)

    budget = video_quality_budget("increase_motion_and_regenerate_video")

    assert budget.candidate_count == 5
    assert budget.refinement_passes == 3
    assert budget.action_profile == "motion_floor_recovery"


def test_performance_video_budget_uses_performance_direction_profile(monkeypatch):
    monkeypatch.setattr("src.services.generation_quality_policy.settings.GENERATION_QUALITY_PROFILE", "hongguo_reference")
    monkeypatch.setattr("src.services.generation_quality_policy.settings.GENERATION_VIDEO_CANDIDATES", 2)
    monkeypatch.setattr("src.services.generation_quality_policy.settings.GENERATION_VIDEO_REFINEMENT_PASSES", 1)
    monkeypatch.setattr("src.services.generation_quality_policy.settings.GENERATION_MAX_VIDEO_CANDIDATES", 8)
    monkeypatch.setattr("src.services.generation_quality_policy.settings.GENERATION_REPAIR_VIDEO_CANDIDATE_MULTIPLIER", 1.5)
    monkeypatch.setattr("src.services.generation_quality_policy.settings.GENERATION_REPAIR_EXTRA_REFINEMENT_PASSES", 1)

    budget = video_quality_budget("regenerate_video_with_performance_direction")

    assert budget.candidate_count == 5
    assert budget.refinement_passes == 4
    assert budget.action_profile == "performance_direction_recovery"


def test_commercial_aesthetic_video_budget_uses_heavier_video_polish_profile(monkeypatch):
    monkeypatch.setattr("src.services.generation_quality_policy.settings.GENERATION_QUALITY_PROFILE", "hongguo_reference")
    monkeypatch.setattr("src.services.generation_quality_policy.settings.GENERATION_VIDEO_CANDIDATES", 2)
    monkeypatch.setattr("src.services.generation_quality_policy.settings.GENERATION_VIDEO_REFINEMENT_PASSES", 1)
    monkeypatch.setattr("src.services.generation_quality_policy.settings.GENERATION_MAX_VIDEO_CANDIDATES", 8)
    monkeypatch.setattr("src.services.generation_quality_policy.settings.GENERATION_REPAIR_VIDEO_CANDIDATE_MULTIPLIER", 1.5)
    monkeypatch.setattr("src.services.generation_quality_policy.settings.GENERATION_REPAIR_EXTRA_REFINEMENT_PASSES", 1)

    budget = video_quality_budget("refine_video_commercial_aesthetic")

    assert budget.candidate_count == 6
    assert budget.refinement_passes == 4
    assert budget.action_profile == "video_commercial_aesthetic_recovery"


def test_final_composition_finish_video_budget_uses_heavy_finishing_profile(monkeypatch):
    monkeypatch.setattr("src.services.generation_quality_policy.settings.GENERATION_QUALITY_PROFILE", "hongguo_reference")
    monkeypatch.setattr("src.services.generation_quality_policy.settings.GENERATION_VIDEO_CANDIDATES", 2)
    monkeypatch.setattr("src.services.generation_quality_policy.settings.GENERATION_VIDEO_REFINEMENT_PASSES", 1)
    monkeypatch.setattr("src.services.generation_quality_policy.settings.GENERATION_MAX_VIDEO_CANDIDATES", 8)
    monkeypatch.setattr("src.services.generation_quality_policy.settings.GENERATION_REPAIR_VIDEO_CANDIDATE_MULTIPLIER", 1.5)
    monkeypatch.setattr("src.services.generation_quality_policy.settings.GENERATION_REPAIR_EXTRA_REFINEMENT_PASSES", 1)

    budget = video_quality_budget("refine_final_composition_finish")

    assert budget.candidate_count == 6
    assert budget.refinement_passes == 4
    assert budget.action_profile == "final_composition_finishing_recovery"


def test_base_generation_budget_keeps_configured_values(monkeypatch):
    monkeypatch.setattr("src.services.generation_quality_policy.settings.GENERATION_QUALITY_PROFILE", "hongguo_reference")
    monkeypatch.setattr("src.services.generation_quality_policy.settings.GENERATION_IMAGE_CANDIDATES", 5)
    monkeypatch.setattr("src.services.generation_quality_policy.settings.GENERATION_IMAGE_REFINEMENT_PASSES", 2)
    monkeypatch.setattr("src.services.generation_quality_policy.settings.GENERATION_MAX_IMAGE_CANDIDATES", 12)

    budget = image_quality_budget()

    assert budget.candidate_count == 5
    assert budget.refinement_passes == 2
    assert budget.reason == "base_generation_budget"


def test_face_aesthetic_repair_uses_heavier_local_quality_budget(monkeypatch):
    monkeypatch.setattr("src.services.generation_quality_policy.settings.GENERATION_QUALITY_PROFILE", "hongguo_reference")
    monkeypatch.setattr("src.services.generation_quality_policy.settings.GENERATION_IMAGE_CANDIDATES", 2)
    monkeypatch.setattr("src.services.generation_quality_policy.settings.GENERATION_IMAGE_REFINEMENT_PASSES", 0)
    monkeypatch.setattr("src.services.generation_quality_policy.settings.GENERATION_MAX_IMAGE_CANDIDATES", 10)
    monkeypatch.setattr("src.services.generation_quality_policy.settings.GENERATION_REPAIR_IMAGE_CANDIDATE_MULTIPLIER", 1.5)
    monkeypatch.setattr("src.services.generation_quality_policy.settings.GENERATION_REPAIR_EXTRA_REFINEMENT_PASSES", 1)

    budget = image_quality_budget("refine_face_aesthetic_detail")

    assert budget.candidate_count == 6
    assert budget.refinement_passes == 3
    assert budget.action_profile == "face_aesthetic_micro_detail"
    assert budget.as_dict()["action_profile"] == "face_aesthetic_micro_detail"


def test_seed_dance_profile_expands_generation_budget(monkeypatch):
    monkeypatch.setattr("src.services.generation_quality_policy.settings.GENERATION_QUALITY_PROFILE", "seed_dance_reference")
    monkeypatch.setattr("src.services.generation_quality_policy.settings.GENERATION_IMAGE_CANDIDATES", 5)
    monkeypatch.setattr("src.services.generation_quality_policy.settings.GENERATION_IMAGE_REFINEMENT_PASSES", 2)
    monkeypatch.setattr("src.services.generation_quality_policy.settings.GENERATION_MAX_IMAGE_CANDIDATES", 12)

    budget = image_quality_budget()

    assert budget.candidate_count == 10
    assert budget.refinement_passes == 4
    assert budget.profile == "seed_dance_reference"
    assert budget.reason == "profile_generation_budget"


def test_seed_dance_video_budget_uses_candidate_cap(monkeypatch):
    monkeypatch.setattr("src.services.generation_quality_policy.settings.GENERATION_QUALITY_PROFILE", "seed_dance_reference")
    monkeypatch.setattr("src.services.generation_quality_policy.settings.GENERATION_VIDEO_CANDIDATES", 4)
    monkeypatch.setattr("src.services.generation_quality_policy.settings.GENERATION_VIDEO_REFINEMENT_PASSES", 2)
    monkeypatch.setattr("src.services.generation_quality_policy.settings.GENERATION_MAX_VIDEO_CANDIDATES", 8)

    budget = video_quality_budget()

    assert budget.candidate_count == 8
    assert budget.refinement_passes == 4
    assert budget.profile == "seed_dance_reference"


def test_prop_interaction_pipeline_requires_hand_prop_and_face_quality():
    pipeline = image_quality_pipeline({"id": "prop_interaction"})

    assert pipeline.shot_profile_id == "prop_interaction"
    assert "hand_prop_integrity" in pipeline.stages
    assert "face_detail" in pipeline.stages
    assert "upscale" in pipeline.stages
    assert "pose_control" in pipeline.required_capabilities
    assert "final VLM review" in pipeline.prompt_directive
    assert "disappearing prop" in pipeline.negative_directive


def test_face_repair_pipeline_adds_artifact_review():
    pipeline = image_quality_pipeline(
        {"id": "close_up"},
        repair_action="refine_face_aesthetic_detail",
    )

    assert pipeline.repair_action == "refine_face_aesthetic_detail"
    assert "skin_texture_pass" in pipeline.stages
    assert "artifact_vlm_review" in pipeline.stages
    assert pipeline.stages.count("upscale") == 1
    assert "face_repair" in pipeline.required_capabilities
    assert "face repair scar" in pipeline.negative_directive
