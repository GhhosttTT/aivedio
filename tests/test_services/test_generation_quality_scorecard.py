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
