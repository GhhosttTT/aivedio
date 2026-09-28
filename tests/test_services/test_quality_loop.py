from src.services.quality_loop import build_quality_loop_plan


def test_quality_loop_selects_image_before_video_and_one_action_per_scene():
    summary = {
        "repair_queue": {
            "items": [
                {
                    "scene_number": 1,
                    "priority": "high",
                    "stage": "video",
                    "action": "lower_motion_and_regenerate_video",
                    "execution": "auto",
                },
                {
                    "scene_number": 1,
                    "priority": "high",
                    "stage": "image",
                    "action": "regenerate_keyframe_with_identity_lock",
                    "execution": "auto",
                },
                {
                    "scene_number": 2,
                    "priority": "medium",
                    "stage": "image",
                    "action": "refine_prompt_composition",
                    "execution": "auto",
                },
            ]
        }
    }

    plan = build_quality_loop_plan(summary, max_actions=5)

    assert plan["status"] == "can_auto_repair"
    assert [item["action"] for item in plan["selected"]] == [
        "regenerate_keyframe_with_identity_lock",
        "refine_prompt_composition",
    ]
    assert any(item["reason"] == "scene_already_selected" for item in plan["skipped"])


def test_quality_loop_reports_setup_required_when_no_auto_actions():
    summary = {
        "repair_queue": {
            "items": [],
            "setup_required": [{"action": "fix_workflow_profile"}],
            "manual_actions": [],
        }
    }

    plan = build_quality_loop_plan(summary, max_actions=5)

    assert plan["status"] == "setup_required"
    assert "setup" in plan["next_step"].lower()


def test_quality_loop_reports_ready_after_clean_summary():
    plan = build_quality_loop_plan({"status": "ready", "repair_queue": {"items": []}}, max_actions=5)

    assert plan["status"] == "ready"
    assert plan["selected"] == []
