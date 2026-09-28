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
