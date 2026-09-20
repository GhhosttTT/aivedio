from pathlib import Path

import pytest
from PIL import Image

from src.services.generation_review import ReviewError
from src.services.image_quality_service import IMAGE_REVIEW_RUBRIC, ImageQualitySelector, candidate_output_path


def make_image(path: Path, color: tuple[int, int, int]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (512, 512), color).save(path)


def test_candidate_output_path_keeps_final_extension():
    assert candidate_output_path("scene.png", 3) == "scene.candidate_03.png"


def test_image_review_rubric_checks_mobile_short_drama_aesthetics():
    assert "mobile short-drama platform" in IMAGE_REVIEW_RUBRIC
    assert "readable face on a phone screen" in IMAGE_REVIEW_RUBRIC
    assert "same-face characters" in IMAGE_REVIEW_RUBRIC


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


def test_select_best_rejects_when_vlm_is_required_but_missing(tmp_path):
    image = tmp_path / "candidate.png"
    make_image(image, (120, 120, 120))
    selector = ImageQualitySelector(reviewer=object())

    with pytest.raises(ReviewError, match="No local VLM"):
        selector.select_best([
            {"index": 1, "path": str(image), "average": 5.0, "status": "technical_only"},
        ], tmp_path / "final.png", tmp_path / "quality.json", require_vlm=True)


def test_select_best_promotes_technical_candidate_when_vlm_is_optional(tmp_path):
    image = tmp_path / "candidate.png"
    final = tmp_path / "final.png"
    make_image(image, (120, 120, 120))

    selector = ImageQualitySelector(reviewer=object())
    report = selector.select_best([
        {"index": 1, "path": str(image), "average": 3.2, "status": "technical_only"},
    ], final, tmp_path / "quality.json", min_average=4.0, require_vlm=False)

    assert report["status"] == "needs_review"
    assert final.read_bytes() == image.read_bytes()


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
