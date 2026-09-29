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


def test_quality_loop_selects_face_aesthetic_detail_repair():
    plan = build_quality_loop_plan({
        "repair_queue": {
            "items": [{
                "scene_number": 3,
                "priority": "high",
                "stage": "image",
                "action": "refine_face_aesthetic_detail",
                "execution": "auto",
            }]
        }
    }, max_actions=5)

    assert plan["status"] == "can_auto_repair"
    assert plan["selected"][0]["action"] == "refine_face_aesthetic_detail"


def test_quality_loop_accepts_flat_validation_repair_queue():
    summary = {
        "status": "partial_needs_review",
        "repair_queue": [
            {
                "scene_number": 4,
                "priority": "high",
                "stage": "image",
                "action": "refine_face_aesthetic_detail",
                "execution": "auto",
                "source_report": "image_review.json",
            },
            {
                "scene_number": 5,
                "priority": "high",
                "stage": "workflow",
                "action": "fix_workflow_profile",
                "execution": "setup_required",
            },
            {
                "scene_number": 6,
                "priority": "medium",
                "stage": "review",
                "action": "manual_review",
                "execution": "manual",
            },
        ],
    }

    plan = build_quality_loop_plan(summary, max_actions=2)

    assert plan["status"] == "can_auto_repair"
    assert plan["selected"][0]["action"] == "refine_face_aesthetic_detail"
    assert plan["selected"][0]["source_report"] == "image_review.json"
    assert plan["setup_required"][0]["action"] == "fix_workflow_profile"
    assert plan["manual_actions"][0]["action"] == "manual_review"


def test_quality_loop_treats_seed_dance_candidate_summary_as_ready():
    plan = build_quality_loop_plan({"status": "ready_for_seed_dance_candidate", "repair_queue": []}, max_actions=5)

    assert plan["status"] == "ready"
    assert plan["next_step"] == "Proceed to final composition and human sample review."
