import json
import base64
import io
from PIL import Image
from unittest.mock import Mock

import httpx
import pytest

from src.services.generation_review import (
    FrameReview, StoryReview, GenerationReviewService, LlamaCppReviewer,
    ReviewError, VIDEO_AESTHETIC_FEATURES, decision, require_passed, video_aesthetic_gate,
)


def story_review(**changes):
    data = {key: {"score": 4, "evidence": "scene 1 establishes the cause"} for key in (
        "causal_logic", "character_motivation", "continuity", "filmability")}
    data.update(reviewed_scenes=[1, 2], issues=[])
    data.update(changes)
    return StoryReview(**data)


def script():
    return {"scenes": [{"scene_number": 1, "description": "She finds a letter"},
                       {"scene_number": 2, "description": "Her shocked reaction"}]}


def test_major_issue_blocks_even_perfect_average():
    review = story_review(issues=[{"severity": "major", "reason": "prop continuity breaks", "scene_number": 2}])
    assert decision(review)[0] == "needs_review"


def test_low_dimension_cannot_be_hidden_by_average():
    review = story_review(continuity={"score": 2, "evidence": "The letter changes owners without cause"})
    assert decision(review)[0] == "needs_review"


def test_unavailable_reviewer_writes_error_not_pass(tmp_path):
    reviewer = Mock()
    reviewer.evaluate.side_effect = httpx.ConnectError("not running")
    path = tmp_path / "story.json"
    result = GenerationReviewService(reviewer).review_story(script(), path)
    assert result["status"] == "error"
    assert json.loads(path.read_text())["error"] == "not running"
    with pytest.raises(ReviewError):
        require_passed(result)


@pytest.mark.parametrize("numbers", [[1], [1, 1, 2], [1, 2, 3]])
def test_all_scenes_must_be_reviewed_exactly_once(tmp_path, numbers):
    reviewer = Mock()
    reviewer.evaluate.return_value = story_review(reviewed_scenes=numbers)
    result = GenerationReviewService(reviewer).review_story(script(), tmp_path / "review.json")
    assert result["status"] == "error"


def test_story_success_records_input_and_scores(tmp_path):
    reviewer = Mock()
    reviewer.evaluate.return_value = story_review()
    result = GenerationReviewService(reviewer).review_story(script(), tmp_path / "review.json")
    assert result["status"] == "passed"
    assert result["average"] == 4
    assert len(result["input_hash"]) == 64


def test_empty_or_numbering_errors_block_before_model(tmp_path):
    reviewer = Mock()
    result = GenerationReviewService(reviewer).review_story({"scenes": []}, tmp_path / "review.json")
    assert result["status"] == "error"
    reviewer.evaluate.assert_not_called()


def test_frame_coverage_and_video_hash(tmp_path, monkeypatch):
    video = tmp_path / "clip.mp4"
    video.write_bytes(b"test video bytes")
    frames = [{"index": i, "timestamp": i, "path": str(tmp_path / f"{i}.jpg")} for i in range(3)]
    monkeypatch.setattr(GenerationReviewService, "sample_frames", lambda *args: frames)
    data = {key: {"score": 4, "evidence": "visible subject matches the keyframe"} for key in (
        "story_match", "composition", "aesthetic_quality", "visual_integrity", "facial_identity", "identity_consistency", "temporal_consistency")}
    reviewer = Mock()
    reviewer.evaluate.return_value = FrameReview(**data, reviewed_frames=[0, 1, 2], issues=[])
    service = GenerationReviewService(reviewer)
    result = service.review_video(str(video), {"scene_number": 1}, tmp_path / "frames.json")
    assert result["status"] == "passed"
    assert len(result["video_sha256"]) == 64
    assert result["batches"][0]["platform_score"] == 4.0
    reviewer.evaluate.return_value = FrameReview(**data, reviewed_frames=[0, 2], issues=[])
    result = service.review_video(str(video), {"scene_number": 1}, tmp_path / "frames.json")
    assert result["status"] == "error"


def test_video_aesthetic_gate_quantifies_short_drama_motion_surface(monkeypatch):
    monkeypatch.setattr("src.services.generation_review.settings.GENERATION_VIDEO_AESTHETIC_FEATURE_MIN_SCORE", 4.0)
    review = {
        "video_aesthetic_scores": {
            "skin_texture_stability": {"score": 2, "evidence": "skin flickers"},
            "lighting_consistency": {"score": 2, "evidence": "light jumps between frames"},
            "color_grade_consistency": {"score": 4, "evidence": "color mostly stable"},
            "phone_readability": {"score": 5, "evidence": "face readable"},
            "motion_smoothness": {"score": 3, "evidence": "small stutter"},
            "background_stability": {"score": 4, "evidence": "room stays stable"},
            "artifact_absence": {"score": 2, "evidence": "repair scar flickers"},
        }
    }

    gate = video_aesthetic_gate(review)

    assert gate["status"] == "needs_review"
    assert set(gate["low"]) == {
        "skin_texture_stability",
        "lighting_consistency",
        "motion_smoothness",
        "artifact_absence",
    }


def test_frame_review_accepts_video_aesthetic_scores(tmp_path, monkeypatch):
    video = tmp_path / "clip.mp4"
    video.write_bytes(b"test video bytes")
    frames = [{"index": i, "timestamp": i, "path": str(tmp_path / f"{i}.jpg")} for i in range(3)]
    monkeypatch.setattr(GenerationReviewService, "sample_frames", lambda *args: frames)
    data = {key: {"score": 4, "evidence": "visible subject matches the keyframe"} for key in (
        "story_match", "composition", "aesthetic_quality", "visual_integrity", "facial_identity", "identity_consistency", "temporal_consistency")}
    data["video_aesthetic_scores"] = {
        feature: {"score": 4, "evidence": "passes"}
        for feature in VIDEO_AESTHETIC_FEATURES
    }
    reviewer = Mock()
    reviewer.evaluate.return_value = FrameReview(**data, reviewed_frames=[0, 1, 2], issues=[])

    result = GenerationReviewService(reviewer).review_video(str(video), {"scene_number": 1}, tmp_path / "frames.json")

    assert result["status"] == "passed"
    assert result["batches"][0]["video_aesthetic_gate"]["status"] == "passed"
    assert result["batches"][0]["review"]["video_aesthetic_scores"]["motion_smoothness"]["score"] == 4


def test_temporal_inconsistency_blocks_video_review(tmp_path, monkeypatch):
    video = tmp_path / "clip.mp4"
    video.write_bytes(b"test video bytes")
    frames = [{"index": i, "timestamp": i, "path": str(tmp_path / f"{i}.jpg")} for i in range(3)]
    monkeypatch.setattr(GenerationReviewService, "sample_frames", lambda *args: frames)
    data = {key: {"score": 4, "evidence": "visible subject matches the keyframe"} for key in (
        "story_match", "composition", "aesthetic_quality", "visual_integrity", "facial_identity", "identity_consistency", "temporal_consistency")}
    data["temporal_consistency"] = {
        "score": 2,
        "evidence": "the lead character face and wardrobe drift between sampled frames",
    }
    reviewer = Mock()
    reviewer.evaluate.return_value = FrameReview(**data, reviewed_frames=[0, 1, 2], issues=[])
    result = GenerationReviewService(reviewer).review_video(
        str(video), {"scene_number": 1}, tmp_path / "frames.json",
    )
    assert result["status"] == "needs_review"
    assert result["batches"][0]["review"]["temporal_consistency"]["score"] == 2


def test_facial_identity_blocks_video_review(tmp_path, monkeypatch):
    video = tmp_path / "clip.mp4"
    video.write_bytes(b"test video bytes")
    frames = [{"index": i, "timestamp": i, "path": str(tmp_path / f"{i}.jpg")} for i in range(3)]
    monkeypatch.setattr(GenerationReviewService, "sample_frames", lambda *args: frames)
    data = {key: {"score": 4, "evidence": "visible subject matches the keyframe"} for key in (
        "story_match", "composition", "aesthetic_quality", "visual_integrity", "facial_identity", "identity_consistency", "temporal_consistency")}
    data["facial_identity"] = {
        "score": 2,
        "evidence": "the nose, mouth, and hairstyle drift from the Alice identity anchor",
    }
    reviewer = Mock()
    reviewer.evaluate.return_value = FrameReview(**data, reviewed_frames=[0, 1, 2], issues=[])
    result = GenerationReviewService(reviewer).review_video(
        str(video),
        {"scene_number": 1, "visible_characters": [{"name": "Alice", "appearance": "woman, short black hair"}]},
        tmp_path / "frames.json",
    )

    assert result["status"] == "needs_review"
    assert result["batches"][0]["review"]["facial_identity"]["score"] == 2


def test_llama_cpp_reviewer_sends_openai_compatible_images(tmp_path, monkeypatch):
    frame = tmp_path / "frame.jpg"
    Image.new("RGB", (1024, 1024), "red").save(frame)
    client = Mock()
    client.__enter__ = Mock(return_value=client)
    client.__exit__ = Mock(return_value=False)
    client.post.return_value.json.return_value = {
        "choices": [{"finish_reason": "stop", "message": {"content": story_review().model_dump_json()}}]
    }
    monkeypatch.setattr("src.services.generation_review.httpx.Client", Mock(return_value=client))
    monkeypatch.setattr("src.services.generation_review.settings.LOCAL_REVIEW_BASE_URL", "http://127.0.0.1:8080/v1")
    monkeypatch.setattr("src.services.generation_review.settings.LOCAL_REVIEW_MODEL", "local-vlm")
    LlamaCppReviewer().evaluate("review", script(), StoryReview, [frame])
    assert client.post.call_args.args[0] == "http://127.0.0.1:8080/v1/chat/completions"
    body = client.post.call_args.kwargs["json"]
    assert body["stream"] is False
    assert body["response_format"]["type"] == "json_object"
    assert "JSON must satisfy this schema" in body["messages"][0]["content"]
    image_url = body["messages"][1]["content"][1]["image_url"]["url"]
    assert image_url.startswith("data:image/jpeg;base64,")
    with Image.open(io.BytesIO(base64.b64decode(image_url.split(",", 1)[1]))) as decoded:
        assert decoded.size == (768, 768)


def test_llama_cpp_reviewer_sends_plain_text_for_text_only(monkeypatch):
    client = Mock()
    client.__enter__ = Mock(return_value=client)
    client.__exit__ = Mock(return_value=False)
    client.post.return_value.json.return_value = {
        "choices": [{"finish_reason": "stop", "message": {"content": story_review().model_dump_json()}}]
    }
    monkeypatch.setattr("src.services.generation_review.httpx.Client", Mock(return_value=client))
    monkeypatch.setattr("src.services.generation_review.settings.LOCAL_REVIEW_BASE_URL", "http://127.0.0.1:8080/v1")
    monkeypatch.setattr("src.services.generation_review.settings.LOCAL_REVIEW_MODEL", "local-vlm")
    LlamaCppReviewer().evaluate("review", script(), StoryReview)
    body = client.post.call_args.kwargs["json"]
    assert isinstance(body["messages"][1]["content"], str)
