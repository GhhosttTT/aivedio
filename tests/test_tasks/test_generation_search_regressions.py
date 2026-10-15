import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from PIL import Image

from src.config import settings
from src.services.generation_provider import GenerationProviderError, GenerationResult, ImageGenerationRequest
from src.services.generation_quality_policy import QualityBudget
from src.services.generation_review import ReviewError, review_reference_images
from src.services.image_quality_service import (
    ImageQualitySelector, ImageReview, PLATFORM_AESTHETIC_FEATURES, PLATFORM_REFERENCE_FEATURES,
)
from src.tasks.image_tasks import _generate_quality_candidates
from src.tasks.video_tasks import _ComfyVideoGenerator, _select_best_video_candidate


def features(names, score=5):
    return {name: {"score": score, "evidence": "visible facial detail and controlled scene lighting"} for name in names}


def image_report(index, image_path, *, identity=5, average=4.6):
    review = features(("prompt_alignment", "composition", "aesthetic_quality", "visual_integrity", "facial_identity", "identity_consistency"))
    review["facial_identity"]["score"] = identity
    review["platform_aesthetic_scores"] = features(PLATFORM_AESTHETIC_FEATURES)
    review["platform_reference_scores"] = features(PLATFORM_REFERENCE_FEATURES)
    review["issues"] = []
    return {"index": index, "path": str(image_path), "status": "passed", "average": average,
            "review": review, "metrics": {"technical_score": 4.6}}


class ImageProvider:
    def __init__(self):
        self.requests = []
        self.releases = 0

    def generate_image(self, request):
        self.requests.append(request)
        Image.new("RGB", (512, 512), (80 + len(self.requests), 100, 120)).save(request.output_path)
        return GenerationResult("local_comfyui", request.output_path, "image", {})

    def release_generation_resources(self):
        self.releases += 1


@pytest.fixture
def search(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "GENERATION_REQUIRE_IMAGE_REVIEW", True)
    monkeypatch.setattr(settings, "GENERATION_REQUIRE_IMAGE_POSTPROCESS", False)
    monkeypatch.setattr(settings, "GENERATION_IMAGE_POSTPROCESS_COMMAND", "")
    monkeypatch.setattr("src.tasks.image_tasks.image_quality_budget", lambda _action=None: QualityBudget(1, 1, 4, "hongguo_reference"))
    request = ImageGenerationRequest("an actor waiting at the doorway", str(tmp_path / "scene.png"), width=512, height=512, seed=42)
    return ImageProvider(), request


def test_high_average_with_bad_face_does_not_end_candidate_search(search, monkeypatch):
    provider, request = search

    def review(_self, index, image_path, *_args):
        assert provider.releases == len(provider.requests)
        return image_report(index, image_path, identity=2 if index == 1 else 5, average=4.9 if index == 1 else 4.5)

    monkeypatch.setattr(ImageQualitySelector, "review_candidate", review)
    path, result = _generate_quality_candidates(provider, request, {"scene_number": 1}, None)
    assert len(provider.requests) == 2
    assert result["best_index"] == 2
    assert Path(path).read_bytes() == Path(result["candidates"][0]["path"]).read_bytes()


def test_seed_reference_profile_searches_beyond_first_passing_batch(search, monkeypatch):
    provider, request = search
    monkeypatch.setattr(settings, "GENERATION_MIN_QUALITY_PASSES", 2)
    monkeypatch.setattr("src.tasks.image_tasks.image_quality_budget", lambda _action=None: QualityBudget(1, 2, 4, "seed_dance_reference"))
    monkeypatch.setattr(ImageQualitySelector, "review_candidate", lambda _self, index, path, *_args: image_report(index, path, average=4.3 + index / 10))
    _, result = _generate_quality_candidates(provider, request, {"scene_number": 1}, None)
    assert len(provider.requests) == 2
    assert result["best_index"] == 2
    assert result["search"]["completed_passes"] == 2


def test_one_generation_failure_does_not_discard_later_good_candidate(search, monkeypatch):
    provider, request = search
    original = provider.generate_image

    def generate(item):
        if not provider.requests:
            provider.requests.append(item)
            raise GenerationProviderError("one transient candidate failed")
        return original(item)

    provider.generate_image = generate
    monkeypatch.setattr("src.tasks.image_tasks.image_quality_budget", lambda _action=None: QualityBudget(2, 0, 4, "hongguo_reference"))
    monkeypatch.setattr(ImageQualitySelector, "review_candidate", lambda _self, index, path, *_args: image_report(index, path))
    _, result = _generate_quality_candidates(provider, request, {"scene_number": 1}, None)
    assert result["best_index"] == 2
    assert result["search"]["failed_generations"] == 1


def test_postprocess_failure_restores_accepted_pixels(search, monkeypatch):
    provider, request = search

    def review(_self, index, path, *_args):
        return image_report(index, path, identity=1 if index == 0 else 5)

    def postprocess(_self, path, **kwargs):
        Image.new("RGB", (512, 512), (255, 0, 0)).save(path)
        return {"status": "passed"}

    monkeypatch.setattr(ImageQualitySelector, "review_candidate", review)
    monkeypatch.setattr("src.tasks.image_tasks.ImagePostprocessor.process", postprocess)
    with pytest.raises(ReviewError, match="Postprocessed image failed"):
        _generate_quality_candidates(provider, request, {"scene_number": 1}, None)
    report = json.loads(Path(request.output_path).with_suffix(".quality.json").read_text(encoding="utf-8"))
    assert report["restored_selected_candidate"] is True
    assert Path(request.output_path).read_bytes() == Path(report["candidates"][0]["path"]).read_bytes()


def test_vlm_rejection_cannot_outrank_a_passing_image(tmp_path):
    rejected = tmp_path / "rejected.png"
    accepted = tmp_path / "accepted.png"
    Image.new("RGB", (512, 512), "red").save(rejected)
    Image.new("RGB", (512, 512), "green").save(accepted)
    first = image_report(1, rejected, average=5)
    first["status"] = "needs_review"
    second = image_report(2, accepted, average=4.5)
    result = ImageQualitySelector(reviewer=object()).select_best([first, second], tmp_path / "final.png", tmp_path / "quality.json")
    assert result["best_index"] == 2


def test_references_are_labelled_individually_and_deduplicated(tmp_path):
    alice = str(tmp_path / "alice.png")
    bob = str(tmp_path / "bob.png")
    paths, metadata = review_reference_images({"character_sheet_references": [
        {"name": "Alice", "path": alice}, {"name": "Bob", "path": bob},
    ]}, alice)
    assert paths == [alice, bob]
    assert [(item["name"], item["image_position"]) for item in metadata] == [
        ("primary reference", 0), ("Alice", 0), ("Bob", 1),
    ]


def test_local_image_reviewer_receives_all_cast_images(tmp_path):
    reference_a = str(tmp_path / "alice.png")
    reference_b = str(tmp_path / "bob.png")
    candidate = tmp_path / "candidate.png"
    Image.new("RGB", (512, 512), "gray").save(candidate)
    reviewer = Mock()
    response = image_report(9, candidate)["review"]
    response["reviewed_images"] = [9]
    reviewer.evaluate.return_value = ImageReview.model_validate(response)
    ImageQualitySelector(reviewer).review_candidate(9, candidate, {"character_sheet_references": [
        {"name": "Alice", "path": reference_a}, {"name": "Bob", "path": reference_b},
    ]}, "two actors")
    assert reviewer.evaluate.call_args.args[3] == [reference_a, reference_b, str(candidate)]
    assert reviewer.evaluate.call_args.args[1]["candidate_image_position"] == 2


def test_image_review_cannot_score_reference_positions_as_candidate_ids(tmp_path):
    candidate = tmp_path / "candidate.png"
    Image.new("RGB", (512, 512), "gray").save(candidate)
    response = image_report(9, candidate)["review"]
    response["reviewed_images"] = [0, 9]
    reviewer = Mock(evaluate=Mock(return_value=ImageReview.model_validate(response)))
    report = ImageQualitySelector(reviewer).review_candidate(9, candidate, {}, "an actor")
    assert report["status"] == "technical_only"
    assert "exactly the candidate index" in report["error"]


def test_rear_identity_review_records_unobservable_facial_geometry(tmp_path):
    from src.services.turnaround_quality import TURNAROUND_FEATURES

    candidate = tmp_path / "back.png"
    Image.new("RGB", (512, 512), "gray").save(candidate)
    response = image_report(9, candidate)["review"]
    response.update(facial_identity=None, reviewed_images=[9], turnaround_feature_scores={
        feature: {"score": 5, "evidence": "The visible rear-view feature matches the casting reference"}
        for feature in TURNAROUND_FEATURES["back"]
    })
    reviewer = Mock(evaluate=Mock(return_value=ImageReview.model_validate(response)))
    report = ImageQualitySelector(reviewer).review_candidate(9, candidate, {"turnaround_view": "back"}, "rear view")
    assert report["status"] == "passed"
    assert report["unobservable_metrics"] == ["facial_identity"]
    assert report["review"]["facial_identity"] is None


def test_front_identity_review_cannot_omit_facial_geometry(tmp_path):
    candidate = tmp_path / "front.png"
    Image.new("RGB", (512, 512), "gray").save(candidate)
    response = image_report(9, candidate)["review"]
    response.update(facial_identity=None, reviewed_images=[9])
    reviewer = Mock(evaluate=Mock(return_value=ImageReview.model_validate(response)))
    report = ImageQualitySelector(reviewer).review_candidate(9, candidate, {}, "front view")
    assert report["status"] == "technical_only"
    assert "not reviewed" in report["error"]


def test_failed_video_review_never_outvotes_a_usable_candidate(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "GENERATION_REQUIRE_VIDEO_REVIEW", False)
    paths = [tmp_path / "bad.mp4", tmp_path / "good.mp4"]
    for path in paths:
        path.write_bytes(path.name.encode())
    candidates = [
        {"index": 1, "status": "error", "average": 5, "platform_score": 5, "path": str(paths[0]),
         "technical_metrics": {"status": "available"}, "gate_scores": {"facial_identity": 5, "temporal_consistency": 5}},
        {"index": 2, "status": "passed", "average": 4.5, "platform_score": 4.5, "path": str(paths[1]),
         "technical_metrics": {"status": "available"}, "gate_scores": {"facial_identity": 4.5, "temporal_consistency": 4.5}},
    ]
    final, result = _select_best_video_candidate(candidates, str(tmp_path / "final.mp4"), tmp_path / "quality.json")
    assert result["selected_path"] == str(paths[1])
    assert Path(final).read_bytes() == paths[1].read_bytes()


def test_video_seed_is_independent_of_output_directory(tmp_path):
    scene = SimpleNamespace(id=7, image_prompt="actor turns toward the doorway", visual_description="actor turns")
    provider = Mock()
    provider.generate_video.side_effect = lambda request: GenerationResult("local_comfyui", request.output_path, "video", {})
    generator = _ComfyVideoGenerator(scene, provider=provider)
    seeds = []
    for parent in (tmp_path / "first_run", tmp_path / "second_run"):
        generator.generate_video("ref.png", str(parent / "scene.candidate_01.mp4"), 32, 8, 127, 0.02)
        seeds.append(provider.generate_video.call_args.args[0].seed)
    assert seeds[0] == seeds[1] >= 0
