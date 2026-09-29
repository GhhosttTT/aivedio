from src.services.generation_quality_scorecard import build_generation_quality_scorecard


def test_generation_quality_scorecard_prioritizes_weakest_production_dimension():
    reports = {
        "quality_images_scene_1": {
            "status": "needs_review",
            "repair_queue": [{
                "scene_number": 1,
                "action": "regenerate_keyframe_with_identity_lock",
                "execution": "auto",
                "reason": "same-face characters and face drift",
            }],
            "candidates": [{
                "scene": {"scene_number": 1},
                "review": {
                    "facial_identity": {"score": 1, "evidence": "changed face shape"},
                    "aesthetic_quality": {"score": 4, "evidence": "commercial lighting"},
                },
            }],
        },
        "quality_video_scene_2": {
            "status": "needs_review",
            "repair_queue": [{
                "scene_number": 2,
                "action": "lower_motion_and_regenerate_video",
                "execution": "auto",
                "reason": "motion stutter and face drift across frames",
            }],
            "candidates": [{
                "scene": {"scene_number": 2},
                "video_aesthetic_gate": {
                    "low": {
                        "motion_smoothness": {"score": 2, "evidence": "visible stutter"},
                    }
                },
            }],
        },
    }

    scorecard = build_generation_quality_scorecard(reports)

    assert scorecard["status"] == "needs_repair"
    assert scorecard["repair_queue_total"] == 2
    assert scorecard["dimensions"]["identity"]["status"] == "needs_repair"
    assert scorecard["dimensions"]["identity"]["scenes"] == [1]
    assert scorecard["dimensions"]["temporal_motion"]["scenes"] == [2]
    assert scorecard["next_focus"]["dimension"] == "identity"
    assert scorecard["next_focus"]["suggested_action"] == "regenerate_keyframe_with_identity_lock"


def test_generation_quality_scorecard_is_clean_without_failed_reports():
    scorecard = build_generation_quality_scorecard({
        "generation": {"status": "passed"},
        "seed_dance_baseline_comparison": {"status": "passed"},
    })

    assert scorecard["status"] == "clean"
    assert scorecard["repair_queue_total"] == 0
    assert scorecard["weakest_dimensions"] == []


def test_generation_quality_scorecard_counts_platform_reference_gate_without_repair_queue():
    scorecard = build_generation_quality_scorecard({
        "image_review": {
            "status": "needs_review",
            "cases": [{
                "scene": {"scene_number": 5},
                "platform_reference_gate": {
                    "status": "needs_review",
                    "low": {
                        "seed_dance_gap": {
                            "score": 2,
                            "evidence": "large gap against premium short-drama reference",
                        },
                        "premium_casting": {
                            "score": 3,
                            "evidence": "face and styling read like a generic generated portrait",
                        },
                    },
                    "missing": [],
                },
            }],
        },
    })

    assert scorecard["status"] == "needs_repair"
    assert scorecard["candidate_count"] == 1
    assert scorecard["repair_queue_total"] == 0
    assert scorecard["dimensions"]["platform_aesthetic"]["status"] == "needs_repair"
    assert scorecard["dimensions"]["platform_aesthetic"]["scenes"] == [5]
    assert scorecard["next_focus"]["dimension"] == "platform_aesthetic"
    assert scorecard["next_focus"]["suggested_action"] == "refine_prompt_composition"


def test_generation_quality_scorecard_routes_video_platform_reference_to_video_aesthetic_repair():
    scorecard = build_generation_quality_scorecard({
        "video_review": {
            "status": "needs_review",
            "batches": [{
                "scene": {"scene_number": 6},
                "platform_reference_gate": {
                    "status": "needs_review",
                    "low": {
                        "seed_dance_gap": {
                            "score": 2,
                            "evidence": "large visible gap versus Seed Dance contact sheet",
                        },
                        "viewer_scroll_stop_appeal": {
                            "score": 3,
                            "evidence": "opening impression is weak",
                        },
                    },
                    "missing": [],
                },
            }],
        },
    })

    assert scorecard["status"] == "needs_repair"
    assert scorecard["repair_queue_total"] == 0
    assert scorecard["dimensions"]["platform_aesthetic"]["status"] == "needs_repair"
    assert scorecard["dimensions"]["platform_aesthetic"]["scenes"] == [6]
    assert scorecard["next_focus"]["dimension"] == "platform_aesthetic"
    assert scorecard["next_focus"]["suggested_action"] == "refine_video_commercial_aesthetic"


def test_generation_quality_scorecard_counts_final_video_review_regressions():
    scorecard = build_generation_quality_scorecard({
        "quality_scene_3": {
            "status": "needs_review",
            "final_video_review": {
                "status": "needs_review",
                "scene": {"scene_number": 3},
                "video_aesthetic_gate": {
                    "low": {
                        "motion_smoothness": {"score": 2, "evidence": "normalized clip stutters"},
                        "background_stability": {"score": 3, "evidence": "background jumps after padding"},
                    }
                },
                "gate_scores": {
                    "temporal_consistency": 2,
                    "identity_consistency": 5,
                    "facial_identity": 5,
                },
            },
            "repair_queue": [{
                "scene_number": 3,
                "action": "lower_motion_and_regenerate_video",
                "execution": "auto",
                "reason": "normalized clip stutters",
            }],
        },
    })

    assert scorecard["status"] == "needs_repair"
    assert scorecard["candidate_count"] == 1
    assert scorecard["dimensions"]["temporal_motion"]["status"] == "needs_repair"
    assert scorecard["dimensions"]["temporal_motion"]["scenes"] == [3]
    assert scorecard["next_focus"]["dimension"] == "temporal_motion"


def test_generation_quality_scorecard_counts_video_performance_regressions():
    scorecard = build_generation_quality_scorecard({
        "quality_scene_4": {
            "status": "needs_review",
            "final_video_review": {
                "status": "needs_review",
                "scene": {"scene_number": 4},
                "video_performance_gate": {
                    "low": {
                        "emotion_readability": {"score": 2, "evidence": "flat acting"},
                        "dialogue_reaction": {"score": 2, "evidence": "no reaction to dialogue"},
                    }
                },
            },
            "repair_queue": [{
                "scene_number": 4,
                "action": "regenerate_video_with_performance_direction",
                "execution": "auto",
                "reason": "flat acting and unreadable emotion",
            }],
        },
    })

    assert scorecard["status"] == "needs_repair"
    assert scorecard["dimensions"]["acting_performance"]["status"] == "needs_repair"
    assert scorecard["dimensions"]["acting_performance"]["scenes"] == [4]
    assert scorecard["next_focus"]["dimension"] == "acting_performance"
    assert scorecard["next_focus"]["suggested_action"] == "regenerate_video_with_performance_direction"


def test_generation_quality_scorecard_maps_video_commercial_repair_to_platform_aesthetic():
    scorecard = build_generation_quality_scorecard({
        "quality_video_scene_6": {
            "status": "needs_review",
            "repair_queue": [{
                "scene_number": 6,
                "action": "refine_video_commercial_aesthetic",
                "execution": "auto",
                "reason": "video commercial aesthetic and production polish below platform threshold",
            }],
        },
    })

    assert scorecard["status"] == "needs_repair"
    assert scorecard["dimensions"]["platform_aesthetic"]["status"] == "needs_repair"
    assert scorecard["dimensions"]["platform_aesthetic"]["scenes"] == [6]
    assert scorecard["dimensions"]["technical_integrity"]["status"] == "passed"
    assert scorecard["next_focus"]["dimension"] == "platform_aesthetic"
    assert scorecard["next_focus"]["suggested_action"] == "refine_video_commercial_aesthetic"


def test_generation_quality_scorecard_maps_role_separation_to_identity():
    scorecard = build_generation_quality_scorecard({
        "quality_images_scene_7": {
            "status": "needs_review",
            "repair_queue": [{
                "scene_number": 7,
                "action": "regenerate_keyframe_with_role_separation",
                "execution": "auto",
                "reason": "same-face casting and copied facial geometry between two named roles",
            }],
        },
    })

    assert scorecard["status"] == "needs_repair"
    assert scorecard["dimensions"]["identity"]["status"] == "needs_repair"
    assert scorecard["dimensions"]["identity"]["scenes"] == [7]
    assert scorecard["dimensions"]["technical_integrity"]["status"] == "passed"
    assert scorecard["next_focus"]["dimension"] == "identity"
    assert scorecard["next_focus"]["suggested_action"] == "regenerate_keyframe_with_role_separation"


def test_generation_quality_scorecard_routes_character_distinctiveness_gate_to_role_separation():
    scorecard = build_generation_quality_scorecard({
        "video_review": {
            "status": "needs_review",
            "batches": [{
                "scene": {"scene_number": 9},
                "character_distinctiveness_gate": {
                    "status": "needs_review",
                    "low": {
                        "no_same_face_casting": {
                            "score": 2,
                            "evidence": "two roles share copied facial geometry",
                        },
                        "role_readability": {
                            "score": 3,
                            "evidence": "lead and antagonist are hard to separate on phone",
                        },
                    },
                    "missing": [],
                },
            }],
        },
    })

    assert scorecard["status"] == "needs_repair"
    assert scorecard["repair_queue_total"] == 0
    assert scorecard["dimensions"]["identity"]["status"] == "needs_repair"
    assert scorecard["dimensions"]["identity"]["scenes"] == [9]
    assert scorecard["dimensions"]["technical_integrity"]["status"] == "passed"
    assert scorecard["next_focus"]["dimension"] == "identity"
    assert scorecard["next_focus"]["suggested_action"] == "regenerate_keyframe_with_role_separation"


def test_generation_quality_scorecard_routes_visual_integrity_to_prop_constraints():
    scorecard = build_generation_quality_scorecard({
        "image_review": {
            "status": "needs_review",
            "cases": [{
                "scene": {"scene_number": 10},
                "review": {
                    "visual_integrity": {
                        "score": 2,
                        "evidence": "broken fingers and unreadable hand-object contact",
                    },
                },
            }],
        },
    })

    assert scorecard["status"] == "needs_repair"
    assert scorecard["dimensions"]["technical_integrity"]["status"] == "needs_repair"
    assert scorecard["dimensions"]["technical_integrity"]["scenes"] == [10]
    assert scorecard["next_focus"]["dimension"] == "technical_integrity"
    assert scorecard["next_focus"]["suggested_action"] == "regenerate_keyframe_with_prop_constraints"


def test_generation_quality_scorecard_routes_image_artifact_gate_to_prop_constraints():
    scorecard = build_generation_quality_scorecard({
        "image_review": {
            "status": "needs_review",
            "cases": [{
                "scene": {"scene_number": 11},
                "platform_aesthetic_gate": {
                    "status": "needs_review",
                    "low": {
                        "repair_artifacts_absent": {
                            "score": 2,
                            "evidence": "visible face repair scar around hand detail pass",
                        },
                    },
                },
            }],
        },
    })

    assert scorecard["status"] == "needs_repair"
    assert scorecard["dimensions"]["technical_integrity"]["status"] == "needs_repair"
    assert scorecard["dimensions"]["technical_integrity"]["scenes"] == [11]
    assert scorecard["next_focus"]["dimension"] == "technical_integrity"
    assert scorecard["next_focus"]["suggested_action"] == "regenerate_keyframe_with_prop_constraints"


def test_generation_quality_scorecard_routes_video_artifact_gate_to_motion_repair():
    scorecard = build_generation_quality_scorecard({
        "video_review": {
            "status": "needs_review",
            "batches": [{
                "scene": {"scene_number": 12},
                "video_aesthetic_gate": {
                    "status": "needs_review",
                    "low": {
                        "artifact_absence": {
                            "score": 2,
                            "evidence": "repair scar flickers around hands",
                        },
                    },
                },
            }],
        },
    })

    assert scorecard["status"] == "needs_repair"
    assert scorecard["dimensions"]["technical_integrity"]["status"] == "needs_repair"
    assert scorecard["dimensions"]["technical_integrity"]["scenes"] == [12]
    assert scorecard["next_focus"]["dimension"] == "technical_integrity"
    assert scorecard["next_focus"]["suggested_action"] == "lower_motion_and_regenerate_video"


def test_generation_quality_scorecard_counts_episode_style_consistency_regressions():
    scorecard = build_generation_quality_scorecard({
        "final_composition": {
            "status": "needs_review",
            "episode_style_consistency_gate": {
                "status": "needs_review",
                "low": {
                    "scene_2_style_consistency": {
                        "score": 2,
                        "evidence": "style drift scene 2: random color grade",
                    },
                },
            },
            "repair_queue": [{
                "scene_number": 2,
                "action": "refine_project_style_consistency",
                "execution": "auto",
                "reason": "style drift scene 2: random color grade",
            }],
        },
    })

    assert scorecard["status"] == "needs_repair"
    assert scorecard["dimensions"]["episode_style_consistency"]["status"] == "needs_repair"
    assert scorecard["dimensions"]["episode_style_consistency"]["scenes"] == [2]
    assert scorecard["next_focus"]["dimension"] == "episode_style_consistency"
    assert scorecard["next_focus"]["suggested_action"] == "refine_project_style_consistency"


def test_generation_quality_scorecard_counts_episode_continuity_regressions():
    scorecard = build_generation_quality_scorecard({
        "final_composition": {
            "status": "needs_review",
            "batches": [{
                "episode_continuity_gate": {
                    "status": "needs_review",
                    "low": {
                        "screen_direction_continuity": {
                            "score": 2,
                            "evidence": "screen direction flips across the cut",
                        },
                        "prop_continuity": {
                            "score": 2,
                            "evidence": "contract disappears after the cut",
                        },
                    },
                },
            }],
            "repair_queue": [{
                "action": "refreeze_spatial_plan",
                "execution": "setup_required",
                "reason": "screen direction flips across the cut",
            }],
        },
    })

    assert scorecard["status"] == "needs_repair"
    assert scorecard["dimensions"]["spatial_continuity"]["status"] == "needs_repair"
    assert scorecard["next_focus"]["dimension"] == "spatial_continuity"
    assert scorecard["next_focus"]["suggested_action"] == "refreeze_spatial_plan"


def test_generation_quality_scorecard_counts_final_composition_finish_regressions():
    scorecard = build_generation_quality_scorecard({
        "final_composition": {
            "status": "needs_review",
            "batches": [{
                "final_composition_finishing_gate": {
                    "status": "needs_review",
                    "low": {
                        "exposure_uniformity": {
                            "score": 2,
                            "evidence": "exposure jumps between cuts",
                        },
                        "skin_tone_uniformity": {
                            "score": 2,
                            "evidence": "skin tone jumps after concat",
                        },
                    },
                },
            }],
            "repair_queue": [{
                "action": "refine_final_composition_finish",
                "execution": "auto",
                "reason": "exposure jumps between cuts",
            }],
        },
    })

    assert scorecard["status"] == "needs_repair"
    assert scorecard["dimensions"]["final_composition_finish"]["status"] == "needs_repair"
    assert scorecard["next_focus"]["dimension"] == "final_composition_finish"
    assert scorecard["next_focus"]["suggested_action"] == "refine_final_composition_finish"


def test_generation_quality_scorecard_counts_dialogue_audio_regressions():
    scorecard = build_generation_quality_scorecard({
        "audio_scene_2": {
            "status": "needs_review",
            "scene": {"scene_number": 2},
            "dialogue_audio_quality_gate": {
                "status": "needs_review",
                "low": {
                    "tts_emotion_match": {
                        "score": 2,
                        "evidence": "flat tts delivery on confrontation line",
                    },
                    "speech_pacing": {
                        "score": 2,
                        "evidence": "speech timing is too rushed",
                    },
                },
            },
            "repair_queue": [{
                "scene_number": 2,
                "action": "refine_dialogue_audio_delivery",
                "execution": "auto",
                "reason": "flat tts delivery",
            }],
        },
    })

    assert scorecard["status"] == "needs_repair"
    assert scorecard["dimensions"]["dialogue_audio"]["status"] == "needs_repair"
    assert scorecard["dimensions"]["dialogue_audio"]["scenes"] == [2]
    assert scorecard["next_focus"]["dimension"] == "dialogue_audio"
    assert scorecard["next_focus"]["suggested_action"] == "refine_dialogue_audio_delivery"


def test_generation_quality_scorecard_counts_story_rhythm_regressions():
    scorecard = build_generation_quality_scorecard({
        "story_room_quality": {
            "status": "weak",
            "story_room_quality_gate": {
                "status": "needs_review",
                "missing": ["early_hook", "escalation_cadence", "ending_hook"],
            },
            "repair_queue": [{
                "action": "rewrite_short_drama_story_rhythm",
                "execution": "setup_required",
                "reason": "early_hook escalation_cadence ending_hook",
            }],
        },
    })

    assert scorecard["status"] == "needs_repair"
    assert scorecard["dimensions"]["story_rhythm"]["status"] == "needs_repair"
    assert scorecard["next_focus"]["dimension"] == "story_rhythm"
    assert scorecard["next_focus"]["suggested_action"] == "rewrite_short_drama_story_rhythm"
