from pathlib import Path

import pytest
from PIL import Image

from src.services.generation_review import ReviewError
from src.services.image_quality_service import (
    IMAGE_REVIEW_RUBRIC,
    PLATFORM_AESTHETIC_FEATURES,
    ImageQualitySelector,
    candidate_output_path,
    platform_aesthetic_gate,
)
from src.services.turnaround_quality import TURNAROUND_FEATURES


def make_image(path: Path, color: tuple[int, int, int]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (512, 512), color).save(path)


def passed_platform_aesthetic_scores(score: int = 5) -> dict:
    return {
        feature: {"score": score, "evidence": "passes short-drama still-image aesthetic gate"}
        for feature in PLATFORM_AESTHETIC_FEATURES
    }


def test_candidate_output_path_keeps_final_extension():
    assert candidate_output_path("scene.png", 3) == "scene.candidate_03.png"


def test_image_review_rubric_checks_mobile_short_drama_aesthetics():
    assert "mobile short-drama platform" in IMAGE_REVIEW_RUBRIC
    assert "readable face on a phone screen" in IMAGE_REVIEW_RUBRIC
    assert "same-face characters" in IMAGE_REVIEW_RUBRIC
    assert "platform_aesthetic_scores" in IMAGE_REVIEW_RUBRIC


def test_platform_aesthetic_gate_quantifies_short_drama_surface_quality(monkeypatch):
    monkeypatch.setattr("src.services.image_quality_service.settings.GENERATION_IMAGE_AESTHETIC_FEATURE_MIN_SCORE", 4.0)
    candidate = {
        "platform_score": 4.8,
        "review": {
            "platform_aesthetic_scores": {
                "skin_texture": {"score": 2, "evidence": "plastic skin"},
                "lighting_quality": {"score": 2, "evidence": "muddy lighting"},
                "color_grade": {"score": 4, "evidence": "usable color"},
                "phone_readability": {"score": 5, "evidence": "face readable"},
                "background_separation": {"score": 4, "evidence": "clean separation"},
                "production_polish": {"score": 3, "evidence": "looks cheap"},
                "repair_artifacts_absent": {"score": 5, "evidence": "no repair scar"},
            }
        },
    }

    gate = platform_aesthetic_gate(candidate)

    assert gate["status"] == "needs_review"
    assert set(gate["low"]) == {"skin_texture", "lighting_quality", "production_polish"}


def test_select_best_promotes_best_candidate(tmp_path):
    first = tmp_path / "first.png"
    second = tmp_path / "second.png"
    final = tmp_path / "final.png"
    make_image(first, (80, 80, 80))
    make_image(second, (120, 120, 120))

    selector = ImageQualitySelector(reviewer=object())
    report = selector.select_best([
        {"index": 1, "path": str(first), "average": 2.5, "status": "technical_only"},
        {"index": 2, "path": str(second), "average": 4.2, "status": "passed"},
    ], final, tmp_path / "quality.json", min_average=4.0, require_vlm=False)

    assert report["best_index"] == 2
    assert final.read_bytes() == second.read_bytes()


def test_select_best_prefers_identity_safe_candidate_over_higher_average(tmp_path):
    first = tmp_path / "first.png"
    second = tmp_path / "second.png"
    final = tmp_path / "final.png"
    make_image(first, (80, 80, 80))
    make_image(second, (120, 120, 120))

    selector = ImageQualitySelector(reviewer=object())
    report = selector.select_best([
        {
            "index": 1,
            "path": str(first),
            "average": 4.8,
            "status": "passed",
            "review": {
                "composition": {"score": 4, "evidence": "usable framing"},
                "aesthetic_quality": {"score": 5, "evidence": "commercial lighting"},
                "visual_integrity": {"score": 4, "evidence": "no broken anatomy"},
                "facial_identity": {"score": 2, "evidence": "face drift"},
                "identity_consistency": {"score": 5, "evidence": "wardrobe stable"},
                "platform_aesthetic_scores": passed_platform_aesthetic_scores(),
            },
        },
        {
            "index": 2,
            "path": str(second),
            "average": 4.2,
            "status": "passed",
            "review": {
                "composition": {"score": 5, "evidence": "strong framing"},
                "aesthetic_quality": {"score": 5, "evidence": "commercial lighting"},
                "visual_integrity": {"score": 5, "evidence": "clean render"},
                "facial_identity": {"score": 4, "evidence": "face matches"},
                "identity_consistency": {"score": 4, "evidence": "wardrobe stable"},
                "platform_aesthetic_scores": passed_platform_aesthetic_scores(),
            },
        },
    ], final, tmp_path / "quality.json", min_average=4.0, min_identity_score=4.0)

    assert report["best_index"] == 2
    assert report["best_identity_scores"] == {"facial_identity": 4.0, "identity_consistency": 4.0}
    assert final.read_bytes() == second.read_bytes()


def test_select_best_rejects_when_identity_scores_are_low(tmp_path):
    image = tmp_path / "candidate.png"
    make_image(image, (120, 120, 120))
    selector = ImageQualitySelector(reviewer=object())

    with pytest.raises(ReviewError, match="identity score"):
        selector.select_best([
            {
                "index": 1,
                "path": str(image),
                "average": 4.8,
                "status": "passed",
                "review": {
                    "facial_identity": {"score": 3, "evidence": "face drift"},
                    "identity_consistency": {"score": 3, "evidence": "same-face issue"},
                },
            },
        ], tmp_path / "final.png", tmp_path / "quality.json", min_average=4.0, min_identity_score=4.0)


def test_select_best_rejects_low_platform_score(tmp_path, monkeypatch):
    image = tmp_path / "candidate.png"
    make_image(image, (120, 120, 120))
    selector = ImageQualitySelector(reviewer=object())
    monkeypatch.setattr("src.services.image_quality_service.settings.GENERATION_IMAGE_PLATFORM_MIN_SCORE", 4.1)

    with pytest.raises(ReviewError, match="platform score"):
        selector.select_best([
            {
                "index": 1,
                "path": str(image),
                "average": 4.5,
                "status": "passed",
                "review": {
                    "composition": {"score": 4, "evidence": "usable framing"},
                    "aesthetic_quality": {"score": 2, "evidence": "cheap filter look and dull lighting"},
                    "visual_integrity": {"score": 4, "evidence": "no broken anatomy"},
                    "facial_identity": {"score": 5, "evidence": "face matches"},
                    "identity_consistency": {"score": 5, "evidence": "wardrobe stable"},
                },
            },
        ], tmp_path / "final.png", tmp_path / "quality.json", min_average=4.0, min_identity_score=4.0)

    report = (tmp_path / "quality.json").read_text(encoding="utf-8")
    assert "refine_prompt_composition" in report


def test_select_best_requires_aesthetic_breakdown_when_vlm_required(tmp_path):
    image = tmp_path / "candidate.png"
    make_image(image, (120, 120, 120))
    selector = ImageQualitySelector(reviewer=object())

    with pytest.raises(ReviewError, match="platform aesthetic feature scores"):
        selector.select_best([
            {
                "index": 1,
                "path": str(image),
                "average": 4.6,
                "status": "passed",
                "review": {
                    "composition": {"score": 5, "evidence": "strong framing"},
                    "aesthetic_quality": {"score": 5, "evidence": "commercial lighting"},
                    "visual_integrity": {"score": 5, "evidence": "clean render"},
                    "facial_identity": {"score": 5, "evidence": "face matches"},
                    "identity_consistency": {"score": 5, "evidence": "wardrobe stable"},
                },
            },
        ], tmp_path / "final.png", tmp_path / "quality.json", min_average=4.0, min_identity_score=4.0, require_vlm=True)


def test_select_best_uses_platform_aesthetic_breakdown(tmp_path, monkeypatch):
    first = tmp_path / "first.png"
    second = tmp_path / "second.png"
    final = tmp_path / "final.png"
    make_image(first, (90, 90, 90))
    make_image(second, (130, 130, 130))
    monkeypatch.setattr("src.services.image_quality_service.settings.GENERATION_IMAGE_AESTHETIC_FEATURE_MIN_SCORE", 4.0)
    monkeypatch.setattr("src.services.image_quality_service.settings.GENERATION_IMAGE_PLATFORM_MIN_SCORE", 4.0)

    low_breakdown = {
        feature: {"score": 4, "evidence": "ok"}
        for feature in PLATFORM_AESTHETIC_FEATURES
    }
    low_breakdown["skin_texture"] = {"score": 1, "evidence": "plastic skin"}
    high_breakdown = {
        feature: {"score": 4, "evidence": "passes"}
        for feature in PLATFORM_AESTHETIC_FEATURES
    }
    selector = ImageQualitySelector(reviewer=object())
    report = selector.select_best([
        {
            "index": 1,
            "path": str(first),
            "average": 4.8,
            "status": "passed",
            "review": {
                "composition": {"score": 5, "evidence": "strong framing"},
                "aesthetic_quality": {"score": 5, "evidence": "commercial lighting"},
                "visual_integrity": {"score": 5, "evidence": "clean render"},
                "facial_identity": {"score": 5, "evidence": "face matches"},
                "identity_consistency": {"score": 5, "evidence": "wardrobe stable"},
                "platform_aesthetic_scores": low_breakdown,
            },
        },
        {
            "index": 2,
            "path": str(second),
            "average": 4.2,
            "status": "passed",
            "review": {
                "composition": {"score": 4, "evidence": "usable framing"},
                "aesthetic_quality": {"score": 4, "evidence": "commercial lighting"},
                "visual_integrity": {"score": 4, "evidence": "clean render"},
                "facial_identity": {"score": 4, "evidence": "face matches"},
                "identity_consistency": {"score": 4, "evidence": "wardrobe stable"},
                "platform_aesthetic_scores": high_breakdown,
            },
        },
    ], final, tmp_path / "quality.json", min_average=4.0, min_identity_score=4.0)

    assert report["best_index"] == 2
    assert report["candidates"][1]["platform_aesthetic_gate"]["status"] == "needs_review"
    assert final.read_bytes() == second.read_bytes()


def test_select_best_rejects_when_vlm_is_required_but_missing(tmp_path):
    image = tmp_path / "candidate.png"
    make_image(image, (120, 120, 120))
    selector = ImageQualitySelector(reviewer=object())

    with pytest.raises(ReviewError, match="No local VLM"):
        selector.select_best([
            {"index": 1, "path": str(image), "average": 5.0, "status": "technical_only"},
        ], tmp_path / "final.png", tmp_path / "quality.json", require_vlm=True)


def test_select_best_rejects_technical_candidate_even_when_vlm_is_optional(tmp_path):
    image = tmp_path / "candidate.png"
    final = tmp_path / "final.png"
    make_image(image, (120, 120, 120))

    selector = ImageQualitySelector(reviewer=object())

    with pytest.raises(ReviewError, match="No local VLM"):
        selector.select_best([
            {"index": 1, "path": str(image), "average": 3.2, "status": "technical_only"},
        ], final, tmp_path / "quality.json", min_average=4.0, require_vlm=False)

    assert not final.exists()
    assert '"status": "review_unavailable"' in (tmp_path / "quality.json").read_text(encoding="utf-8")


def test_review_candidate_records_facial_identity_score(tmp_path):
    image = tmp_path / "candidate.png"
    make_image(image, (120, 120, 120))

    class FakeReviewer:
        def evaluate(self, _instruction, payload, schema, images=()):
            assert payload["scene"]["visible_characters"][0]["appearance"] == "woman, short black hair, green jacket"
            assert len(images) == 1
            return schema.model_validate({
                "prompt_alignment": {"score": 4, "evidence": "matches the office doorway scene"},
                "composition": {"score": 4, "evidence": "single readable subject"},
                "aesthetic_quality": {"score": 4, "evidence": "clean lighting"},
                "visual_integrity": {"score": 4, "evidence": "no obvious anatomy defects"},
                "facial_identity": {"score": 5, "evidence": "short black hair and facial traits match Alice"},
                "identity_consistency": {"score": 4, "evidence": "wardrobe and body shape match"},
                "reviewed_images": [1],
                "issues": [],
            })

    report = ImageQualitySelector(reviewer=FakeReviewer()).review_candidate(
        1,
        image,
        {
            "scene_number": 1,
            "visual_description": "Alice stands in the office doorway",
            "visible_characters": [
                {"name": "Alice", "appearance": "woman, short black hair, green jacket"},
            ],
        },
        "Alice in an office doorway",
    )

    assert report["status"] == "passed"
    assert report["review"]["facial_identity"]["score"] == 5
    assert report["platform_score"] >= 4.0


def test_review_candidate_accepts_turnaround_feature_scores(tmp_path):
    image = tmp_path / "candidate.png"
    make_image(image, (120, 120, 120))

    class FakeReviewer:
        def evaluate(self, _instruction, payload, schema, images=()):
            assert payload["scene"]["turnaround_view"] == "side"
            return schema.model_validate({
                "prompt_alignment": {"score": 4, "evidence": "side profile prompt"},
                "composition": {"score": 4, "evidence": "full body side view"},
                "aesthetic_quality": {"score": 4, "evidence": "clean lighting"},
                "visual_integrity": {"score": 4, "evidence": "no obvious anatomy defects"},
                "facial_identity": {"score": 4, "evidence": "face profile matches"},
                "identity_consistency": {"score": 4, "evidence": "wardrobe and body shape match"},
                "turnaround_feature_scores": {
                    "view_angle": {"score": 5, "evidence": "strict 90 degree side profile"},
                    "nose_silhouette": {"score": 4, "evidence": "nose bridge readable"},
                },
                "reviewed_images": [1],
                "issues": [],
            })

    report = ImageQualitySelector(reviewer=FakeReviewer()).review_candidate(
        1,
        image,
        {
            "scene_number": 1,
            "visual_description": "side character turnaround reference",
            "turnaround_view": "side",
            "visible_characters": [
                {"name": "Alice", "appearance": "woman, short black hair, green jacket"},
            ],
        },
        "strict side profile",
    )

    assert report["status"] == "passed"
    assert report["review"]["turnaround_feature_scores"]["view_angle"]["score"] == 5


def test_review_candidate_promotes_visible_character_turnaround_contract(tmp_path, monkeypatch):
    image = tmp_path / "candidate.png"
    reference = tmp_path / "side_reference.png"
    make_image(image, (120, 120, 120))
    make_image(reference, (80, 140, 80))
    monkeypatch.setattr("src.services.image_quality_service.settings.GENERATION_TURNAROUND_FEATURE_MIN_SCORE", 4.0)
    expected = {
        feature: f"expected {feature}"
        for feature in TURNAROUND_FEATURES["side"]
    }

    class FakeReviewer:
        def evaluate(self, _instruction, payload, schema, images=()):
            assert payload["scene"]["turnaround_view"] == "side"
            assert payload["scene"]["turnaround_expected_features"]["nose_silhouette"] == "expected nose_silhouette"
            assert "match frozen side character turnaround reference" in payload["scene"]["reference_requirements"]
            assert len(images) == 2
            return schema.model_validate({
                "prompt_alignment": {"score": 4, "evidence": "matches side shot"},
                "composition": {"score": 4, "evidence": "readable side composition"},
                "aesthetic_quality": {"score": 4, "evidence": "commercial lighting"},
                "visual_integrity": {"score": 4, "evidence": "clean render"},
                "facial_identity": {"score": 4, "evidence": "profile matches reference"},
                "identity_consistency": {"score": 4, "evidence": "wardrobe and body shape match"},
                "turnaround_feature_scores": {
                    feature: {"score": 4, "evidence": f"{feature} matches"}
                    for feature in TURNAROUND_FEATURES["side"]
                },
                "reviewed_images": [1],
                "issues": [],
            })

    report = ImageQualitySelector(reviewer=FakeReviewer()).review_candidate(
        1,
        image,
        {
            "scene_number": 1,
            "visual_description": "Alice side profile in a premium office scene",
            "visible_characters": [{
                "name": "Alice",
                "appearance": "Alice identity",
                "turnaround_reference": {
                    "view": "side",
                    "path": str(reference),
                    "expected_features": expected,
                    "control_prompt": "strict side profile reference",
                },
            }],
        },
        "Alice side profile in office",
        str(reference),
    )

    assert report["status"] == "passed"
    assert report["turnaround_gate"]["status"] == "passed"
    assert report["platform_score"] >= 4.0


def test_review_candidate_accepts_platform_aesthetic_scores(tmp_path):
    image = tmp_path / "candidate.png"
    make_image(image, (120, 120, 120))

    class FakeReviewer:
        def evaluate(self, _instruction, _payload, schema, images=()):
            return schema.model_validate({
                "prompt_alignment": {"score": 4, "evidence": "matches"},
                "composition": {"score": 4, "evidence": "single readable subject"},
                "aesthetic_quality": {"score": 4, "evidence": "commercial look"},
                "visual_integrity": {"score": 4, "evidence": "clean render"},
                "facial_identity": {"score": 4, "evidence": "face matches"},
                "identity_consistency": {"score": 4, "evidence": "wardrobe stable"},
                "platform_aesthetic_scores": {
                    feature: {"score": 4, "evidence": "passes"}
                    for feature in PLATFORM_AESTHETIC_FEATURES
                },
                "reviewed_images": [1],
                "issues": [],
            })

    report = ImageQualitySelector(reviewer=FakeReviewer()).review_candidate(
        1,
        image,
        {"scene_number": 1, "visual_description": "Alice stands in the office doorway"},
        "Alice in an office doorway",
    )

    assert report["status"] == "passed"
    assert report["platform_aesthetic_gate"]["status"] == "passed"
    assert report["review"]["platform_aesthetic_scores"]["skin_texture"]["score"] == 4
