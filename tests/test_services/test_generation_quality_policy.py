from src.services.generation_quality_policy import image_quality_budget, video_quality_budget


def test_repair_image_budget_increases_candidates_and_refinement(monkeypatch):
    monkeypatch.setattr("src.services.generation_quality_policy.settings.GENERATION_IMAGE_CANDIDATES", 4)
    monkeypatch.setattr("src.services.generation_quality_policy.settings.GENERATION_IMAGE_REFINEMENT_PASSES", 1)
    monkeypatch.setattr("src.services.generation_quality_policy.settings.GENERATION_MAX_IMAGE_CANDIDATES", 8)
    monkeypatch.setattr("src.services.generation_quality_policy.settings.GENERATION_REPAIR_IMAGE_CANDIDATE_MULTIPLIER", 1.5)
    monkeypatch.setattr("src.services.generation_quality_policy.settings.GENERATION_REPAIR_EXTRA_REFINEMENT_PASSES", 1)

    budget = image_quality_budget("regenerate_keyframe_with_identity_lock")

    assert budget.candidate_count == 6
    assert budget.refinement_passes == 2
    assert budget.reason == "repair_generation_budget"


def test_video_budget_respects_max_candidate_cap(monkeypatch):
    monkeypatch.setattr("src.services.generation_quality_policy.settings.GENERATION_VIDEO_CANDIDATES", 6)
    monkeypatch.setattr("src.services.generation_quality_policy.settings.GENERATION_VIDEO_REFINEMENT_PASSES", 2)
    monkeypatch.setattr("src.services.generation_quality_policy.settings.GENERATION_MAX_VIDEO_CANDIDATES", 8)
    monkeypatch.setattr("src.services.generation_quality_policy.settings.GENERATION_REPAIR_VIDEO_CANDIDATE_MULTIPLIER", 2.0)
    monkeypatch.setattr("src.services.generation_quality_policy.settings.GENERATION_REPAIR_EXTRA_REFINEMENT_PASSES", 1)

    budget = video_quality_budget("lower_motion_and_regenerate_video")

    assert budget.candidate_count == 8
    assert budget.refinement_passes == 3
    assert budget.max_candidates == 8


def test_base_generation_budget_keeps_configured_values(monkeypatch):
    monkeypatch.setattr("src.services.generation_quality_policy.settings.GENERATION_IMAGE_CANDIDATES", 5)
    monkeypatch.setattr("src.services.generation_quality_policy.settings.GENERATION_IMAGE_REFINEMENT_PASSES", 2)
    monkeypatch.setattr("src.services.generation_quality_policy.settings.GENERATION_MAX_IMAGE_CANDIDATES", 12)

    budget = image_quality_budget()

    assert budget.candidate_count == 5
    assert budget.refinement_passes == 2
    assert budget.reason == "base_generation_budget"
