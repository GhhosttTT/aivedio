import json
import base64
import io
from PIL import Image
from unittest.mock import Mock

import httpx
import pytest

from src.services.generation_review import (
    FrameReview, StoryReview, GenerationReviewService, LocalReviewer,
    ReviewError, decision, require_passed,
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
        "story_match", "composition", "visual_integrity", "identity_consistency")}
    reviewer = Mock()
    reviewer.evaluate.return_value = FrameReview(**data, reviewed_frames=[0, 1, 2], issues=[])
    service = GenerationReviewService(reviewer)
    result = service.review_video(str(video), {"scene_number": 1}, tmp_path / "frames.json")
    assert result["status"] == "passed"
    assert len(result["video_sha256"]) == 64
    reviewer.evaluate.return_value = FrameReview(**data, reviewed_frames=[0, 2], issues=[])
    result = service.review_video(str(video), {"scene_number": 1}, tmp_path / "frames.json")
    assert result["status"] == "error"


def test_ollama_receives_real_images_and_unloads_model(tmp_path, monkeypatch):
    frame = tmp_path / "frame.jpg"
    Image.new("RGB", (1024, 1024), "red").save(frame)
    client = Mock()
    client.__enter__ = Mock(return_value=client)
    client.__exit__ = Mock(return_value=False)
    client.post.return_value.json.return_value = {"done": True, "message": {"content": story_review().model_dump_json()}}
    monkeypatch.setattr("src.services.generation_review.httpx.Client", Mock(return_value=client))
    LocalReviewer().evaluate("review", script(), StoryReview, [frame])
    body = client.post.call_args.kwargs["json"]
    assert body["keep_alive"] == 0
    assert body["stream"] is False
    data = body["messages"][1]["images"]
    with Image.open(io.BytesIO(base64.b64decode(data[0]))) as decoded:
        assert decoded.size == (768, 768)
    assert body["format"]["type"] == "object"
