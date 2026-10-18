from pathlib import Path
from types import SimpleNamespace

from PIL import Image

from src.services.episode_style_consistency import EpisodeStyleConsistencyService


def _write_image(path: Path, color: tuple[int, int, int], size=(108, 192)):
    Image.new("RGB", size, color).save(path)


def test_episode_style_consistency_passes_matching_keyframes(tmp_path):
    first = tmp_path / "scene-1.png"
    second = tmp_path / "scene-2.png"
    _write_image(first, (92, 104, 118))
    _write_image(second, (94, 106, 120))
    scenes = [
        SimpleNamespace(scene_number=1, image_path=str(first)),
        SimpleNamespace(scene_number=2, image_path=str(second)),
    ]

    report = EpisodeStyleConsistencyService().audit(SimpleNamespace(id=1), scenes)

    assert report.status == "passed"
    assert report.sampled_count == 2
    assert report.to_dict()["repair_queue"] == []


def test_episode_style_consistency_flags_exposure_and_framing_outlier(tmp_path):
    first = tmp_path / "scene-1.png"
    second = tmp_path / "scene-2.png"
    _write_image(first, (95, 105, 115), size=(108, 192))
    _write_image(second, (245, 245, 245), size=(192, 108))
    scenes = [
        SimpleNamespace(scene_number=1, image_path=str(first)),
        SimpleNamespace(scene_number=2, image_path=str(second)),
    ]

    report = EpisodeStyleConsistencyService().audit(SimpleNamespace(id=1), scenes)

    assert report.status == "needs_review"
    assert {issue["code"] for issue in report.issues} >= {"exposure_drift", "framing_drift"}
    assert report.to_dict()["repair_queue"][0]["action"] == "refine_project_style_consistency"


def test_episode_style_consistency_is_not_applicable_without_two_rendered_keyframes(tmp_path):
    first = tmp_path / "scene-1.png"
    _write_image(first, (95, 105, 115))
    scenes = [
        SimpleNamespace(scene_number=1, image_path=str(first)),
        SimpleNamespace(scene_number=2, image_path=None),
    ]

    report = EpisodeStyleConsistencyService().audit(SimpleNamespace(id=1), scenes)

    assert report.status == "not_applicable"
    assert report.sampled_count == 1
