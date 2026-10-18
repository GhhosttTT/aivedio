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


def test_repair_queue_maps_style_drift_to_project_style_consistency_repair():
    report = {
        "status": "needs_review",
        "candidates": [{
            "index": 1,
            "scene": {"scene_number": 6},
            "platform_aesthetic_gate": {
                "status": "needs_review",
                "low": {
                    "style_consistency": {
                        "score": 2,
                        "evidence": "style drift between shots with random color grade and inconsistent lighting",
                    }
                },
            },
        }],
    }

    queue = build_repair_queue(report, "image")

    assert queue[0]["action"] == "refine_project_style_consistency"
    assert queue[0]["stage"] == "image"
    assert queue[0]["scene_number"] == 6
    assert queue[0]["execution"] == "auto"


def test_repair_queue_maps_temporal_instability_to_motion_repair():
    report = {
        "status": "needs_review",
        "candidates": [{
            "index": 1,
            "scene": {"scene_number": 2},
            "average": 3.0,
            "technical_metrics": {
                "technical_score": 2.8,
                "brightness_step_p95": 58.0,
                "motion_jitter_ratio": 1.8,
            },
        }],
    }

    queue = build_repair_queue(report, "video")

    temporal_items = [item for item in queue if "temporal exposure jumps" in item["reason"]]
    assert temporal_items
    assert temporal_items[0]["action"] == "lower_motion_and_regenerate_video"


def test_repair_queue_maps_temporal_visual_resets_to_targeted_motion_repair():
    report = {
        "status": "needs_review",
        "candidates": [{
            "index": 1,
            "scene": {"scene_number": 3},
            "average": 4.1,
            "technical_metrics": {
                "technical_score": 4.1,
                "temporal_jump_ratio": 0.5,
            },
        }],
    }

    queue = build_repair_queue(report, "video")

    reset_items = [item for item in queue if "temporal visual resets" in item["reason"]]
    assert reset_items
    assert reset_items[0]["action"] == "lower_motion_and_regenerate_video"
    assert "repeated scene resets" in reset_items[0]["recommendation"]


def test_repair_queue_maps_extreme_temporal_resets_to_targeted_motion_repair():
    report = {
        "status": "needs_review",
        "candidates": [{
            "index": 1,
            "scene": {"scene_number": 7},
            "average": 4.1,
            "technical_metrics": {
                "technical_score": 4.1,
                "temporal_jump_ratio": 0.01,
                "temporal_jump_p95": 0.9,
            },
        }],
    }

    queue = build_repair_queue(report, "video")

    reset_items = [item for item in queue if "extreme temporal visual reset" in item["reason"]]
    assert reset_items
    assert reset_items[0]["action"] == "lower_motion_and_regenerate_video"
    assert "extreme single-frame resets" in reset_items[0]["recommendation"]


def test_repair_queue_uses_configured_temporal_reset_threshold(monkeypatch):
    monkeypatch.setattr(
        "src.services.repair_queue.settings.GENERATION_VIDEO_MAX_TEMPORAL_JUMP_P95",
        0.95,
    )
    report = {
        "status": "needs_review",
        "candidates": [{
            "index": 1,
            "technical_metrics": {
                "technical_score": 4.1,
                "temporal_jump_p95": 0.9,
            },
        }],
    }

    queue = build_repair_queue(report, "video")

    assert not any("extreme temporal visual reset" in item["reason"] for item in queue)


def test_repair_queue_maps_sequence_fps_mismatch_to_output_contract_repair():
    report = {
        "status": "needs_review",
        "candidates": [{
            "index": 1,
            "scene": {"scene_number": 4},
            "average": 3.0,
            "error": "Sequence boundary quality gate failed: fps_mismatches=1",
        }],
    }

    queue = build_repair_queue(report, "video")

    assert queue[0]["action"] == "fix_video_output_contract"


def test_repair_queue_maps_pixel_format_mismatch_to_output_contract_repair():
    report = {
        "status": "needs_review",
        "candidates": [{
            "index": 1,
            "scene": {"scene_number": 5},
            "average": 3.0,
            "error": "Sequence boundary quality gate failed: pixel_format_mismatches=1",
        }],
    }

    queue = build_repair_queue(report, "video")

    assert queue[0]["action"] == "fix_video_output_contract"


def test_repair_queue_expands_top_level_episode_style_gate_by_scene():
    report = {
        "status": "needs_review",
        "episode_style_consistency_gate": {
            "status": "needs_review",
            "low": {
                "scene_2_style_consistency": {
                    "score": 2,
                    "evidence": "style drift scene 2: random color grade",
                    "scene_number": 2,
                },
            },
        },
    }

    queue = build_repair_queue(report, "video")

    assert queue[0]["action"] == "refine_project_style_consistency"
    assert queue[0]["stage"] == "image"
    assert queue[0]["scene_number"] == 2
    assert queue[0]["execution"] == "auto"


def test_repair_queue_maps_episode_continuity_gate_to_spatial_plan_setup():
    report = {
        "status": "needs_review",
        "batches": [{
            "status": "needs_review",
            "episode_continuity_gate": {
                "status": "needs_review",
                "low": {
                    "screen_direction_continuity": {
                        "score": 2,
                        "evidence": "screen_direction_continuity failed: jarring cut flips camera axis",
                    },
                    "prop_continuity": {
                        "score": 2,
                        "evidence": "prop_continuity failed: contract disappears after the cut",
                    },
                },
            },
        }],
    }

    queue = build_repair_queue(report, "video")

    assert queue[0]["action"] == "refreeze_spatial_plan"
    assert queue[0]["stage"] == "spatial"
    assert queue[0]["execution"] == "setup_required"


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


def test_repair_queue_maps_keyframe_divergence_to_identity_preserving_video_repair():
    report = {
        "status": "needs_review",
        "candidates": [{
            "index": 4,
            "scene": {"scene_number": 9},
            "technical_metrics": {
                "technical_score": 4.2,
                "start_frame_reference": {
                    "status": "available",
                    "score": 1.8,
                },
            },
        }],
    }

    queue = build_repair_queue(report, "video")

    assert queue[0]["action"] == "regenerate_video_with_performance_direction"
    assert "locked scene keyframe" in queue[0]["recommendation"]


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


def test_repair_queue_maps_final_composition_finish_to_episode_polish_repair():
    report = {
        "status": "needs_review",
        "stage": "final_composition",
        "batches": [{
            "status": "needs_review",
            "final_composition_finishing_gate": {
                "status": "needs_review",
                "low": {
                    "exposure_uniformity": {
                        "score": 2,
                        "evidence": "final_composition_finishing exposure_uniformity failed: exposure jumps between cuts",
                    },
                    "color_grade_uniformity": {
                        "score": 2,
                        "evidence": "color_grade_uniformity failed: mixed generated clips with inconsistent color grade",
                    },
                },
                "missing": [],
            },
        }],
    }

    queue = build_repair_queue(report, "video")

    assert queue[0]["action"] == "refine_final_composition_finish"
    assert queue[0]["stage"] == "video"
    assert queue[0]["execution"] == "auto"


def test_repair_queue_maps_style_boundary_jump_to_episode_polish_repair():
    report = {
        "status": "needs_review",
        "stage": "final_composition",
        "error": "final composed video has severe color-grade/contrast transitions across 1 shot boundary(s)",
    }

    queue = build_repair_queue(report, "video")

    assert queue[0]["action"] == "refine_final_composition_finish"
    assert queue[0]["stage"] == "video"


def test_repair_queue_maps_dialogue_audio_gate_to_audio_repair():
    report = {
        "status": "needs_review",
        "dialogue_audio_quality_gate": {
            "status": "needs_review",
            "low": {
                "tts_emotion_match": {
                    "score": 2,
                    "evidence": "dialogue audio tts_emotion_match is neutral on an emotional short-drama line",
                    "scene_number": 3,
                },
                "speech_pacing": {
                    "score": 2,
                    "evidence": "dialogue audio speech_pacing out of range",
                    "scene_number": 3,
                },
            },
            "missing": [],
        },
    }

    queue = build_repair_queue(report, "audio")

    assert queue[0]["action"] == "refine_dialogue_audio_delivery"
    assert queue[0]["stage"] == "audio"
    assert queue[0]["execution"] == "auto"
    assert queue[0]["scene_number"] == 3


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


def test_repair_queue_maps_frozen_static_gate_to_motion_repair():
    report = {
        "status": "needs_review",
        "error": "Final normalized video contains a frozen/static run of 2.4s with motion_energy=0.1",
        "candidates": [{"index": 1, "scene": {"scene_number": 2}}],
    }

    queue = build_repair_queue(report, "video")

    assert queue[0]["action"] == "increase_motion_and_regenerate_video"
    assert queue[0]["execution"] == "auto"


def test_repair_queue_maps_near_silent_audio_to_dialogue_repair():
    report = {
        "status": "needs_review",
        "candidates": [{
            "index": 1,
            "scene": {"scene_number": 5},
            "technical_metrics": {
                "audio_expected": True,
                "audio_signal_status": "near_silent",
            },
        }],
    }

    queue = build_repair_queue(report, "video")

    assert queue[0]["action"] == "refine_dialogue_audio_delivery"
    assert queue[0]["stage"] == "audio"
    assert queue[0]["execution"] == "auto"


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


def test_repair_queue_maps_image_platform_reference_gap_to_composition_repair():
    report = {
        "status": "needs_review",
        "candidates": [{
            "index": 2,
            "scene": {"scene_number": 9},
            "platform_reference_gate": {
                "status": "needs_review",
                "low": {
                    "seed_dance_gap": {
                        "score": 2,
                        "evidence": "large Seed Dance gap with weak premium casting and low mobile frame value",
                    },
                    "viewer_scroll_stop_appeal": {
                        "score": 2,
                        "evidence": "first frame lacks scroll stop appeal",
                    },
                },
            },
        }],
    }

    queue = build_repair_queue(report, "image")

    assert queue[0]["action"] == "refine_prompt_composition"
    assert queue[0]["execution"] == "auto"
    assert queue[0]["scene_number"] == 9


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


def test_repair_queue_maps_story_room_quality_gate_to_script_rewrite():
    report = {
        "status": "weak",
        "kind": "story_room_quality",
        "story_room_quality_gate": {
            "status": "needs_review",
            "missing": ["early_hook", "escalation_cadence", "reversal", "ending_hook"],
            "low": {
                3: {
                    "score": 0,
                    "evidence": "too_many_actions_or_beats",
                    "scene_number": 3,
                },
            },
        },
    }

    queue = build_repair_queue(report, "script")

    assert queue[0]["action"] == "rewrite_short_drama_story_rhythm"
    assert queue[0]["stage"] == "script"
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
