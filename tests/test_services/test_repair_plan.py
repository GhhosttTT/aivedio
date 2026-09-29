from src.services.repair_plan import build_repair_execution_plan


def test_repair_execution_plan_handles_identity_lock_rerun(tmp_path):
    plan = build_repair_execution_plan(
        tmp_path,
        [{
            "action": "regenerate_keyframe_with_identity_lock",
            "execution": "auto",
            "stage": "image",
            "scene_number": 3,
            "reason": "changed face and wrong camera angle versus character sheet",
            "recommendation": "lock identity",
        }],
    )

    item = plan["auto"][0]
    assert item["action"] == "regenerate_keyframe_with_identity_lock"
    assert item["parameter_hints"]["lock_character_sheet"] is True
    assert item["parameter_hints"]["repair_action"] == "regenerate_keyframe_with_identity_lock"
    assert "identity_vlm_review" in item["quality_pipeline"]["stages"]
    assert "character_identity" in item["parameter_hints"]["required_workflow_capabilities"]
    assert any("render-images" in command for command in plan["rerun_validation_commands"])
    assert any("--repair-action regenerate_keyframe_with_identity_lock" in command for command in plan["rerun_validation_commands"])
    assert any("--scene-number 3" in command for command in plan["rerun_validation_commands"])


def test_repair_execution_plan_handles_role_separation_rerun(tmp_path):
    plan = build_repair_execution_plan(
        tmp_path,
        [{
            "action": "regenerate_keyframe_with_role_separation",
            "execution": "auto",
            "stage": "image",
            "scene_number": 4,
            "reason": "same-face casting between two named roles",
        }],
    )

    item = plan["auto"][0]
    assert item["action"] == "regenerate_keyframe_with_role_separation"
    assert item["parameter_hints"]["use_identity_contrast_matrix"] is True
    assert item["parameter_hints"]["require_role_separation"] is True
    assert "role_separation" in item["quality_pipeline"]["stages"]
    assert "distinctiveness_vlm_review" in item["quality_pipeline"]["stages"]
    assert any("--repair-action regenerate_keyframe_with_role_separation" in command for command in plan["rerun_validation_commands"])


def test_repair_execution_plan_passes_face_repair_action_to_render_images(tmp_path):
    plan = build_repair_execution_plan(
        tmp_path,
        [{
            "action": "refine_face_aesthetic_detail",
            "execution": "auto",
            "stage": "image",
            "scene_number": 2,
            "reason": "plastic skin",
        }],
    )

    assert plan["auto"][0]["parameter_hints"]["natural_face_texture_required"] is True
    assert "artifact_vlm_review" in plan["auto"][0]["quality_pipeline"]["stages"]
    assert "face_repair" in plan["auto"][0]["parameter_hints"]["required_workflow_capabilities"]
    assert any("--repair-action refine_face_aesthetic_detail" in command for command in plan["rerun_validation_commands"])


def test_repair_execution_plan_handles_project_style_consistency_rerun(tmp_path):
    plan = build_repair_execution_plan(
        tmp_path,
        [{
            "action": "refine_project_style_consistency",
            "execution": "auto",
            "stage": "image",
            "scene_number": 7,
            "reason": "style drift between shots and random color grade",
        }],
    )

    item = plan["auto"][0]
    assert item["action"] == "refine_project_style_consistency"
    assert item["parameter_hints"]["lock_project_style_bible"] is True
    assert item["parameter_hints"]["lock_color_grade"] is True
    assert item["parameter_hints"]["lock_lighting_continuity"] is True
    assert "project_style_bible" in item["quality_pipeline"]["stages"]
    assert "color_grade_lock" in item["quality_pipeline"]["stages"]
    assert any("--repair-action refine_project_style_consistency" in command for command in plan["rerun_validation_commands"])


def test_repair_execution_plan_handles_increase_motion_video_rerun(tmp_path):
    plan = build_repair_execution_plan(
        tmp_path,
        [{
            "action": "increase_motion_and_regenerate_video",
            "execution": "auto",
            "stage": "video",
            "scene_number": 4,
            "reason": "video motion too static or frozen",
        }],
    )

    item = plan["auto"][0]
    assert item["action"] == "increase_motion_and_regenerate_video"
    assert item["parameter_hints"]["raise_motion_bucket_id"] is True
    assert item["parameter_hints"]["raise_noise_aug_strength_slightly"] is True


def test_repair_execution_plan_handles_performance_video_rerun(tmp_path):
    plan = build_repair_execution_plan(
        tmp_path,
        [{
            "action": "regenerate_video_with_performance_direction",
            "execution": "auto",
            "stage": "video",
            "scene_number": 5,
            "reason": "flat acting and unreadable emotion",
        }],
    )

    item = plan["auto"][0]
    assert item["action"] == "regenerate_video_with_performance_direction"
    assert item["parameter_hints"]["strengthen_shot_plan_performance"] is True
    assert item["parameter_hints"]["preserve_identity"] is True


def test_repair_execution_plan_handles_video_commercial_aesthetic_rerun(tmp_path):
    plan = build_repair_execution_plan(
        tmp_path,
        [{
            "action": "refine_video_commercial_aesthetic",
            "execution": "auto",
            "stage": "video",
            "scene_number": 6,
            "reason": "commercial_aesthetic low with muddy lighting and poor production value",
        }],
    )

    item = plan["auto"][0]
    assert item["action"] == "refine_video_commercial_aesthetic"
    assert item["parameter_hints"]["commercial_aesthetic_required"] is True
    assert item["parameter_hints"]["stabilize_motion_for_aesthetic_polish"] is True
    assert item["parameter_hints"]["preserve_identity"] is True


def test_repair_execution_plan_handles_final_composition_finish_rerun(tmp_path):
    plan = build_repair_execution_plan(
        tmp_path,
        [{
            "action": "refine_final_composition_finish",
            "execution": "auto",
            "stage": "video",
            "reason": "exposure jumps between cuts and skin tone mismatch",
        }],
    )

    item = plan["auto"][0]
    assert item["action"] == "refine_final_composition_finish"
    assert item["parameter_hints"]["unify_exposure"] is True
    assert item["parameter_hints"]["unify_skin_tone"] is True
    assert item["parameter_hints"]["check_subtitle_safe_area"] is True
    assert any("final_or_refinished_episode.mp4" in command for command in plan["rerun_validation_commands"])
