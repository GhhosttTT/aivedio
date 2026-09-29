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
        "regenerate_keyframe_with_identity_lock",
        "refine_prompt_composition",
    }
    assert any(item["scene_number"] == 3 for item in queue)
    assert any(item["execution"] == "auto" for item in queue)


def test_repair_queue_maps_character_distinctiveness_gate_to_role_separation():
    report = {
        "status": "needs_review",
        "candidates": [{
            "index": 1,
            "scene": {"scene_number": 4},
            "character_distinctiveness_gate": {
                "status": "needs_review",
                "low": {
                    "no_same_face_casting": {
                        "score": 2,
                        "evidence": "same-face casting between two named roles",
                    }
                },
                "missing": [],
            },
        }],
    }

    queue = build_repair_queue(report, "image")

    assert queue[0]["action"] == "regenerate_keyframe_with_role_separation"
    assert queue[0]["scene_number"] == 4
    assert queue[0]["execution"] == "auto"


def test_repair_queue_maps_video_identity_drift_to_motion_repair():
    report = {
        "status": "needs_review",
        "candidates": [{
            "index": 1,
            "scene": {"scene_number": 4},
            "review": {
                "facial_identity": {"score": 2, "evidence": "identity drift and changed face across frames"},
            },
        }],
    }

    queue = build_repair_queue(report, "video")

    assert queue[0]["action"] == "lower_motion_and_regenerate_video"
    assert queue[0]["stage"] == "video"
    assert queue[0]["execution"] == "auto"
    assert queue[0]["scene_number"] == 4


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


def test_repair_queue_maps_video_performance_gate_to_performance_repair():
    report = {
        "status": "needs_review",
        "candidates": [{
            "index": 3,
            "scene": {"scene_number": 8},
            "video_performance_gate": {
                "status": "needs_review",
                "low": {
                    "emotion_readability": {"score": 2, "evidence": "flat acting and unreadable emotion"},
                    "dialogue_reaction": {"score": 2, "evidence": "no reaction to dialogue"},
                },
                "missing": [],
            },
        }],
    }

    queue = build_repair_queue(report, "video")

    assert queue[0]["action"] == "regenerate_video_with_performance_direction"
    assert queue[0]["stage"] == "video"
    assert queue[0]["execution"] == "auto"
    assert queue[0]["scene_number"] == 8


def test_repair_queue_maps_video_commercial_aesthetic_to_video_aesthetic_repair():
    report = {
        "status": "needs_review",
        "candidates": [{
            "index": 2,
            "scene": {"scene_number": 8},
            "video_aesthetic_gate": {
                "status": "needs_review",
                "low": {
                    "commercial_aesthetic": {
                        "score": 2,
                        "evidence": "commercial_aesthetic low: muddy lighting, weak platform score, and poor production value",
                    },
                },
            },
        }],
    }

    queue = build_repair_queue(report, "video")

    assert queue[0]["action"] == "refine_video_commercial_aesthetic"
    assert queue[0]["execution"] == "auto"
    assert queue[0]["stage"] == "video"
    assert queue[0]["scene_number"] == 8


def test_repair_queue_reads_final_composition_batches():
    report = {
        "status": "needs_review",
        "stage": "final_composition",
        "scene": {"scene_number": "final_composition"},
        "batches": [{
            "status": "needs_review",
            "video_performance_gate": {
                "status": "needs_review",
                "low": {
                    "emotion_readability": {
                        "score": 2,
                        "evidence": "flat acting across the composed episode",
                    },
                    "gaze_intent": {
                        "score": 2,
                        "evidence": "dead eyes in the final confrontation",
                    },
                },
            },
            "review": {
                "video_performance_scores": {
                    "dialogue_reaction": {
                        "score": 2,
                        "evidence": "no reaction to dialogue after the cut",
                    },
                },
            },
        }],
    }

    queue = build_repair_queue(report, "video")

    assert queue[0]["action"] == "regenerate_video_with_performance_direction"
    assert queue[0]["stage"] == "video"
    assert queue[0]["execution"] == "auto"
    assert queue[0]["scene_number"] is None


def test_repair_queue_maps_low_image_technical_metrics_to_composition_repair():
    report = {
        "status": "needs_review",
        "candidates": [{
            "index": 1,
            "scene": {"scene_number": 6},
            "metrics": {
                "technical_score": 2.1,
                "sharpness": 2.0,
                "mean_luma": 42.0,
                "colorfulness": 4.0,
            },
        }],
    }

    queue = build_repair_queue(report, "image")

    assert queue[0]["action"] == "refine_prompt_composition"
    assert queue[0]["execution"] == "auto"
    assert queue[0]["scene_number"] == 6


def test_repair_queue_maps_static_video_technical_metrics_to_increase_motion_repair():
    report = {
        "status": "needs_review",
        "candidates": [{
            "index": 2,
            "scene": {"scene_number": 9},
            "technical_metrics": {
                "technical_score": 2.3,
                "motion_energy": 0.4,
                "sharpness": 3.0,
                "brightness": 48.0,
                "brightness_variance": 720.0,
            },
        }],
    }

    queue = build_repair_queue(report, "video")

    assert queue[0]["action"] == "increase_motion_and_regenerate_video"
    assert queue[0]["execution"] == "auto"
    assert queue[0]["scene_number"] == 9


def test_repair_queue_reads_nested_platform_aesthetic_gates():
    report = {
        "status": "needs_review",
        "candidates": [
            {
                "index": 1,
                "platform_aesthetic_gate": {
                    "status": "needs_review",
                    "low": {
                        "skin_texture": {"score": 2, "evidence": "plastic skin"},
                        "lighting_quality": {"score": 2, "evidence": "muddy light"},
                    },
                },
            },
            {
                "index": 2,
                "video_aesthetic_gate": {
                    "status": "needs_review",
                    "low": {
                        "motion_smoothness": {"score": 2, "evidence": "motion stutter"},
                        "artifact_absence": {"score": 2, "evidence": "repair scar flickers"},
                    },
                },
            },
        ],
    }

    image_queue = build_repair_queue({"status": "needs_review", "candidates": [report["candidates"][0]]}, "image")
    video_queue = build_repair_queue({"status": "needs_review", "candidates": [report["candidates"][1]]}, "video")

    assert image_queue[0]["action"] == "refine_face_aesthetic_detail"
    assert image_queue[0]["execution"] == "auto"
    assert video_queue[0]["action"] == "lower_motion_and_regenerate_video"
    assert video_queue[0]["execution"] == "auto"


def test_repair_queue_maps_seed_dance_profile_defects_to_aesthetic_repair():
    report = {
        "status": "needs_review",
        "candidates": [{
            "index": 1,
            "scene": {"scene_number": 5},
            "platform_aesthetic_gate": {
                "status": "needs_review",
                "low": {
                    "production_polish": {"score": 2, "evidence": "AI generated gloss and low-budget set dressing"},
                },
            },
        }],
    }

    queue = build_repair_queue(report, "image")

    assert queue[0]["action"] == "refine_face_aesthetic_detail"
    assert queue[0]["execution"] == "auto"
    assert queue[0]["scene_number"] == 5


def test_repair_queue_routes_face_repair_scars_to_workflow_setup():
    queue = build_repair_queue({
        "status": "needs_review",
        "candidates": [{
            "index": 1,
            "scene": {"scene_number": 4},
            "platform_aesthetic_gate": {
                "status": "needs_review",
                "low": {
                    "skin_texture": {"score": 2, "evidence": "plastic skin after face repair"},
                    "repair_artifacts_absent": {"score": 2, "evidence": "visible face repair scar"},
                },
            },
        }],
    }, "image")

    assert queue[0]["action"] == "fix_workflow_profile"
    assert queue[0]["execution"] == "setup_required"
    assert queue[0]["scene_number"] == 4


def test_repair_queue_reads_scene_number_from_candidate_scene_payload():
    report = {
        "status": "needs_review",
        "candidates": [
            {
                "index": 1,
                "scene": {"scene_number": 7},
                "platform_aesthetic_gate": {
                    "status": "needs_review",
                    "low": {
                        "lighting_quality": {"score": 2, "evidence": "muddy light"},
                    },
                },
            }
        ],
    }

    queue = build_repair_queue(report, "image")

    assert queue[0]["action"] == "refine_prompt_composition"
    assert queue[0]["scene_number"] == 7


def test_video_repair_queue_reads_scene_number_from_candidate_scene_payload():
    report = {
        "status": "needs_review",
        "candidates": [
            {
                "index": 2,
                "scene": {"scene_number": 8},
                "video_aesthetic_gate": {
                    "status": "needs_review",
                    "low": {
                        "motion_smoothness": {"score": 2, "evidence": "motion stutter"},
                    },
                },
            }
        ],
    }

    queue = build_repair_queue(report, "video")

    assert queue[0]["action"] == "lower_motion_and_regenerate_video"
    assert queue[0]["scene_number"] == 8


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
