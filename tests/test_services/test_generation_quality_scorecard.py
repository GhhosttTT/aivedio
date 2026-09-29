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
