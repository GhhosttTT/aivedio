from pathlib import Path

import pytest
from PIL import Image

from src.services.generation_review import ReviewError
from src.services.image_quality_service import ImageQualitySelector, candidate_output_path


def make_image(path: Path, color: tuple[int, int, int]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (512, 512), color).save(path)


def test_candidate_output_path_keeps_final_extension():
    assert candidate_output_path("scene.png", 3) == "scene.candidate_03.png"


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
