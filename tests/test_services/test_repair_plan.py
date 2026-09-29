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
    assert any("render-images" in command for command in plan["rerun_validation_commands"])
    assert any("--repair-action regenerate_keyframe_with_identity_lock" in command for command in plan["rerun_validation_commands"])
    assert any("--scene-number 3" in command for command in plan["rerun_validation_commands"])


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
    assert any("--repair-action refine_face_aesthetic_detail" in command for command in plan["rerun_validation_commands"])


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
