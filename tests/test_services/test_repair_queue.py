from src.services.repair_queue import build_repair_queue


def test_repair_queue_classifies_identity_and_composition_failures():
    report = {
        "status": "needs_review",
        "candidates": [
            {
                "index": 1,
                "average": 2.2,
                "review": {
                    "issues": [
                        {"severity": "major", "reason": "same-face characters and face drift", "scene_number": 3},
                        {"severity": "major", "reason": "bad crop on the main actor", "scene_number": 3},
                    ],
                    "composition": {"score": 2, "evidence": "bad crop and muddy lighting"},
                    "facial_identity": {"score": 1, "evidence": "changed face shape"},
                },
            }
        ],
    }

    queue = build_repair_queue(report, "image")

    assert {item["action"] for item in queue} >= {
        "regenerate_character_identity",
        "refine_prompt_composition",
    }
    assert any(item["scene_number"] == 3 for item in queue)
    assert {item["execution"] for item in queue} >= {"auto", "setup_required"}


def test_repair_queue_classifies_video_motion_failures():
    report = {
        "status": "needs_review",
        "candidates": [
            {
                "index": 2,
                "average": 2.5,
                "review": {
                    "issues": [
                        {"severity": "critical", "reason": "temporal flicker and random camera jump", "scene_number": 1}
                    ],
                    "temporal_consistency": {"score": 1, "evidence": "motion breaks and body melts"},
                },
            }
        ],
    }

    queue = build_repair_queue(report, "video")

    assert queue[0]["action"] == "lower_motion_and_regenerate_video"
    assert queue[0]["stage"] == "video"
    assert queue[0]["priority"] == "high"
    assert queue[0]["execution"] == "auto"


def test_repair_queue_handles_review_unavailable():
    report = {"status": "review_unavailable", "error": "No local VLM review unavailable", "candidates": []}

    queue = build_repair_queue(report, "video")

    assert queue[0]["action"] == "start_local_reviewer"
    assert queue[0]["execution"] == "setup_required"


def test_repair_queue_classifies_asset_and_workflow_setup_failures():
    report = {
        "status": "needs_review",
        "candidates": [
            {
                "index": 1,
                "review": {
                    "issues": [
                        {"severity": "major", "reason": "side view is not a profile view and body proportion changed", "scene_number": 2},
                        {"severity": "major", "reason": "left/right screen direction changed; camera axis flipped", "scene_number": 2},
                        {"severity": "major", "reason": "workflow profile missing depth control and face repair capability", "scene_number": 2},
                    ]
                },
            }
        ],
    }

    queue = build_repair_queue(report, "image")

    assert {item["action"] for item in queue} >= {
        "regenerate_turnaround_album",
        "refreeze_spatial_plan",
        "fix_workflow_profile",
    }
    assert all(item["execution"] == "setup_required" for item in queue)
