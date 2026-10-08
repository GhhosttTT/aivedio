import json
import base64
import io
from PIL import Image
from unittest.mock import Mock

import httpx
import pytest

from src.services.generation_review import (
    CHARACTER_DISTINCTIVENESS_FEATURES,
    EPISODE_CONTINUITY_FEATURES,
    FINAL_COMPOSITION_FINISHING_FEATURES,
    FrameReview,
    StoryReview,
    GenerationReviewService,
    LlamaCppReviewer,
    ReviewError,
    PLATFORM_REFERENCE_FEATURES,
    VIDEO_AESTHETIC_FEATURES,
    VIDEO_PERFORMANCE_FEATURES,
    decision,
    final_composition_finishing_gate,
    platform_reference_gate,
    require_passed,
    video_aesthetic_gate,
    video_character_distinctiveness_gate,
    episode_continuity_gate,
    video_performance_gate,
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


def test_platform_reference_gate_quantifies_seed_dance_gap(monkeypatch):
    monkeypatch.setattr("src.services.generation_review.settings.GENERATION_VIDEO_AESTHETIC_FEATURE_MIN_SCORE", 4.0)
    review = {
        "platform_reference_scores": {
            "seed_dance_gap": {"score": 2, "evidence": "large visible gap versus contact sheet"},
            "premium_casting": {"score": 3, "evidence": "face feels generic and low-end"},
            "mobile_frame_value": {"score": 4, "evidence": "frame reads on phone"},
            "production_design": {"score": 2, "evidence": "set dressing looks cheap"},
            "viewer_scroll_stop_appeal": {"score": 3, "evidence": "opening impression is weak"},
        }
    }

    gate = platform_reference_gate(review)

    assert gate["status"] == "needs_review"
    assert set(gate["low"]) == {
        "seed_dance_gap",
        "premium_casting",
        "production_design",
        "viewer_scroll_stop_appeal",
    }


def test_video_character_distinctiveness_gate_quantifies_same_face_risk(monkeypatch):
    monkeypatch.setattr("src.services.generation_review.settings.GENERATION_VIDEO_CHARACTER_DISTINCTIVENESS_MIN_SCORE", 4.0)
    review = {
        "character_distinctiveness_scores": {
            "face_geometry_separation": {"score": 2, "evidence": "copied facial geometry"},
            "hair_separation": {"score": 4, "evidence": "hair is distinct"},
            "wardrobe_separation": {"score": 4, "evidence": "wardrobe is distinct"},
            "role_readability": {"score": 3, "evidence": "roles are unclear in motion"},
            "no_same_face_casting": {"score": 2, "evidence": "same-face casting appears across frames"},
        }
    }

    gate = video_character_distinctiveness_gate(review, {
        "visible_characters": [
            {"name": "Alice", "appearance": "sharp eyes"},
            {"name": "Bob", "appearance": "round eyes"},
        ],
    })

    assert gate["status"] == "needs_review"
    assert set(gate["low"]) == {
        "face_geometry_separation",
        "role_readability",
        "no_same_face_casting",
    }


def test_video_performance_gate_quantifies_flat_short_drama_acting(monkeypatch):
    monkeypatch.setattr("src.services.generation_review.settings.GENERATION_VIDEO_PERFORMANCE_MIN_SCORE", 4.0)
    review = {
        "video_performance_scores": {
            "emotion_readability": {"score": 2, "evidence": "emotion is unreadable on phone"},
            "gaze_intent": {"score": 3, "evidence": "dead eyes with no target"},
            "dialogue_reaction": {"score": 2, "evidence": "no reaction to the line"},
            "body_language": {"score": 4, "evidence": "posture supports conflict"},
            "action_intent": {"score": 4, "evidence": "gesture is readable"},
        }
    }

    gate = video_performance_gate(review, {
        "scene_number": 1,
        "dialogue": "你为什么骗我",
        "shot_plan": {"shot_role": "dialogue_reaction"},
    })

    assert gate["status"] == "needs_review"
    assert set(gate["low"]) == {
        "emotion_readability",
        "gaze_intent",
        "dialogue_reaction",
    }


def test_episode_continuity_gate_quantifies_final_composition_jump_cuts(monkeypatch):
    monkeypatch.setattr("src.services.generation_review.settings.GENERATION_VIDEO_PERFORMANCE_MIN_SCORE", 4.0)
    review = {
        "episode_continuity_scores": {
            "scene_order_coherence": {"score": 4, "evidence": "scene order is coherent"},
            "screen_direction_continuity": {"score": 2, "evidence": "screen direction flips across the cut"},
            "character_position_continuity": {"score": 3, "evidence": "actor jumps from left to right"},
            "prop_continuity": {"score": 2, "evidence": "contract disappears after the cut"},
            "cut_smoothness": {"score": 4, "evidence": "cuts are mostly smooth"},
        }
    }

    gate = episode_continuity_gate(review, {
        "shot_plan": {"shot_role": "final_composed_short_drama"},
    })

    assert gate["status"] == "needs_review"
    assert set(gate["low"]) == {
        "screen_direction_continuity",
        "character_position_continuity",
        "prop_continuity",
    }


def test_final_composition_finishing_gate_quantifies_mixed_clip_finish(monkeypatch):
    monkeypatch.setattr("src.services.generation_review.settings.GENERATION_VIDEO_AESTHETIC_FEATURE_MIN_SCORE", 4.0)
    review = {
        "final_composition_finishing_scores": {
            "exposure_uniformity": {"score": 2, "evidence": "exposure jumps between cuts"},
            "skin_tone_uniformity": {"score": 3, "evidence": "skin tone shifts after concat"},
            "color_grade_uniformity": {"score": 2, "evidence": "mixed color grade looks like different clips"},
            "sharpness_uniformity": {"score": 4, "evidence": "detail mostly stable"},
            "subtitle_visual_integration": {"score": 4, "evidence": "subtitles avoid faces"},
            "overall_finish_polish": {"score": 3, "evidence": "episode lacks one unified finishing pass"},
        }
    }

    gate = final_composition_finishing_gate(review, {
        "shot_plan": {"shot_role": "final_composed_short_drama"},
    })

    assert gate["status"] == "needs_review"
    assert set(gate["low"]) == {
        "exposure_uniformity",
        "skin_tone_uniformity",
        "color_grade_uniformity",
        "overall_finish_polish",
    }


def test_frame_review_accepts_video_aesthetic_scores(tmp_path, monkeypatch):
    video = tmp_path / "clip.mp4"
    video.write_bytes(b"test video bytes")
    frames = [{"index": i, "timestamp": i, "path": str(tmp_path / f"{i}.jpg")} for i in range(3)]
    monkeypatch.setattr(GenerationReviewService, "sample_frames", lambda *args: frames)
    data = {key: {"score": 4, "evidence": "visible subject matches the keyframe"} for key in (
        "story_match", "composition", "aesthetic_quality", "visual_integrity", "facial_identity", "identity_consistency", "temporal_consistency")}
    data["video_aesthetic_scores"] = {
        feature: {"score": 4, "evidence": "visible sampled frames pass this feature"}
        for feature in VIDEO_AESTHETIC_FEATURES
    }
    reviewer = Mock()
    reviewer.evaluate.return_value = FrameReview(**data, reviewed_frames=[0, 1, 2], issues=[])

    result = GenerationReviewService(reviewer).review_video(
        str(video),
        {
            "scene_number": 1,
            "platform_aesthetic_contract": {
                "video_features": list(VIDEO_AESTHETIC_FEATURES),
                "review_instruction": "score platform polish",
            },
        },
        tmp_path / "frames.json",
    )

    assert result["status"] == "passed"
    assert result["batches"][0]["video_aesthetic_gate"]["status"] == "passed"
    assert result["batches"][0]["review"]["video_aesthetic_scores"]["motion_smoothness"]["score"] == 4
    assert "scene.platform_aesthetic_contract" in reviewer.evaluate.call_args.args[0]
    assert "profile_prompt" in reviewer.evaluate.call_args.args[0]
    assert "profile_negative_prompt" in reviewer.evaluate.call_args.args[0]


def test_video_aesthetic_gate_rejects_short_generic_evidence(monkeypatch):
    monkeypatch.setattr("src.services.generation_review.settings.GENERATION_VIDEO_AESTHETIC_FEATURE_MIN_SCORE", 4.0)
    review = {
        "video_aesthetic_scores": {
            feature: {"score": 4, "evidence": "passes"}
            for feature in VIDEO_AESTHETIC_FEATURES
        }
    }

    gate = video_aesthetic_gate(review)

    assert gate["status"] == "needs_review"
    assert gate["missing"] == [f"{feature}.evidence" for feature in VIDEO_AESTHETIC_FEATURES]
    assert gate["scores"]["motion_smoothness"]["score"] == 0.0


def test_frame_review_accepts_platform_reference_scores(tmp_path, monkeypatch):
    video = tmp_path / "clip.mp4"
    video.write_bytes(b"test video bytes")
    frames = [{"index": i, "timestamp": i, "path": str(tmp_path / f"{i}.jpg")} for i in range(3)]
    monkeypatch.setattr(GenerationReviewService, "sample_frames", lambda *args: frames)
    data = {key: {"score": 4, "evidence": "visible subject matches the keyframe"} for key in (
        "story_match", "composition", "aesthetic_quality", "visual_integrity", "facial_identity", "identity_consistency", "temporal_consistency")}
    data["platform_reference_scores"] = {
        feature: {"score": 4, "evidence": "passes platform reference comparison"}
        for feature in PLATFORM_REFERENCE_FEATURES
    }
    reviewer = Mock()
    reviewer.evaluate.return_value = FrameReview(**data, reviewed_frames=[0, 1, 2], issues=[])

    result = GenerationReviewService(reviewer).review_video(
        str(video),
        {"scene_number": 1},
        tmp_path / "frames.json",
    )

    assert result["status"] == "passed"
    assert result["batches"][0]["platform_reference_gate"]["status"] == "passed"
    assert result["batches"][0]["review"]["platform_reference_scores"]["seed_dance_gap"]["score"] == 4
    assert "platform_reference_scores" in reviewer.evaluate.call_args.args[0]


def test_frame_review_accepts_character_distinctiveness_scores(tmp_path, monkeypatch):
    video = tmp_path / "clip.mp4"
    video.write_bytes(b"test video bytes")
    frames = [{"index": i, "timestamp": i, "path": str(tmp_path / f"{i}.jpg")} for i in range(3)]
    monkeypatch.setattr(GenerationReviewService, "sample_frames", lambda *args: frames)
    data = {key: {"score": 4, "evidence": "visible subject matches the keyframe"} for key in (
        "story_match", "composition", "aesthetic_quality", "visual_integrity", "facial_identity", "identity_consistency", "temporal_consistency")}
    data["character_distinctiveness_scores"] = {
        feature: {"score": 4, "evidence": "characters stay visually distinct"}
        for feature in CHARACTER_DISTINCTIVENESS_FEATURES
    }
    reviewer = Mock()
    reviewer.evaluate.return_value = FrameReview(**data, reviewed_frames=[0, 1, 2], issues=[])

    result = GenerationReviewService(reviewer).review_video(
        str(video),
        {
            "scene_number": 1,
            "visible_characters": [
                {"name": "Alice", "appearance": "sharp eyes and black bob"},
                {"name": "Bob", "appearance": "round eyes and short crop"},
            ],
        },
        tmp_path / "frames.json",
    )

    assert result["status"] == "passed"
    assert result["batches"][0]["character_distinctiveness_gate"]["status"] == "passed"
    assert result["batches"][0]["review"]["character_distinctiveness_scores"]["no_same_face_casting"]["score"] == 4
    assert "character_distinctiveness_scores" in reviewer.evaluate.call_args.args[0]


def test_frame_review_accepts_video_performance_scores(tmp_path, monkeypatch):
    video = tmp_path / "clip.mp4"
    video.write_bytes(b"test video bytes")
    frames = [{"index": i, "timestamp": i, "path": str(tmp_path / f"{i}.jpg")} for i in range(3)]
    monkeypatch.setattr(GenerationReviewService, "sample_frames", lambda *args: frames)
    data = {key: {"score": 4, "evidence": "visible subject matches the keyframe"} for key in (
        "story_match", "composition", "aesthetic_quality", "visual_integrity", "facial_identity", "identity_consistency", "temporal_consistency")}
    data["video_performance_scores"] = {
        feature: {"score": 4, "evidence": "acting reads clearly"}
        for feature in VIDEO_PERFORMANCE_FEATURES
    }
    reviewer = Mock()
    reviewer.evaluate.return_value = FrameReview(**data, reviewed_frames=[0, 1, 2], issues=[])

    result = GenerationReviewService(reviewer).review_video(
        str(video),
        {
            "scene_number": 1,
            "dialogue": "你为什么骗我",
            "shot_plan": {"shot_role": "dialogue_reaction"},
        },
        tmp_path / "frames.json",
    )

    assert result["status"] == "passed"
    assert result["batches"][0]["video_performance_gate"]["status"] == "passed"
    assert result["batches"][0]["review"]["video_performance_scores"]["gaze_intent"]["score"] == 4
    assert "video_performance_scores" in reviewer.evaluate.call_args.args[0]


def test_frame_review_accepts_episode_continuity_scores_for_final_composition(tmp_path, monkeypatch):
    video = tmp_path / "clip.mp4"
    video.write_bytes(b"test video bytes")
    frames = [{"index": i, "timestamp": i, "path": str(tmp_path / f"{i}.jpg")} for i in range(3)]
    monkeypatch.setattr(GenerationReviewService, "sample_frames", lambda *args: frames)
    data = {key: {"score": 4, "evidence": "visible subject matches the keyframe"} for key in (
        "story_match", "composition", "aesthetic_quality", "visual_integrity", "facial_identity", "identity_consistency", "temporal_consistency")}
    data["video_performance_scores"] = {
        feature: {"score": 4, "evidence": "acting reads clearly"}
        for feature in VIDEO_PERFORMANCE_FEATURES
    }
    data["episode_continuity_scores"] = {
        feature: {"score": 4, "evidence": "episode continuity holds"}
        for feature in EPISODE_CONTINUITY_FEATURES
    }
    reviewer = Mock()
    reviewer.evaluate.return_value = FrameReview(**data, reviewed_frames=[0, 1, 2], issues=[])

    result = GenerationReviewService(reviewer).review_video(
        str(video),
        {
            "scene_number": "final_composition",
            "shot_plan": {"shot_role": "final_composed_short_drama"},
        },
        tmp_path / "frames.json",
    )

    assert result["status"] == "passed"
    assert result["batches"][0]["episode_continuity_gate"]["status"] == "passed"
    assert result["batches"][0]["review"]["episode_continuity_scores"]["cut_smoothness"]["score"] == 4
    assert "episode_continuity_scores" in reviewer.evaluate.call_args.args[0]


def test_frame_review_accepts_final_composition_finishing_scores(tmp_path, monkeypatch):
    video = tmp_path / "final.mp4"
    video.write_bytes(b"test video bytes")
    frames = [{"index": i, "timestamp": i, "path": str(tmp_path / f"{i}.jpg")} for i in range(3)]
    monkeypatch.setattr(GenerationReviewService, "sample_frames", lambda *args: frames)
    data = {key: {"score": 4, "evidence": "visible subject matches the keyframe"} for key in (
        "story_match", "composition", "aesthetic_quality", "visual_integrity", "facial_identity", "identity_consistency", "temporal_consistency")}
    data["episode_continuity_scores"] = {
        feature: {"score": 4, "evidence": "continuity passes"}
        for feature in EPISODE_CONTINUITY_FEATURES
    }
    data["final_composition_finishing_scores"] = {
        feature: {"score": 4, "evidence": "finish passes"}
        for feature in FINAL_COMPOSITION_FINISHING_FEATURES
    }
    reviewer = Mock()
    reviewer.evaluate.return_value = FrameReview(**data, reviewed_frames=[0, 1, 2], issues=[])

    result = GenerationReviewService(reviewer).review_video(
        str(video),
        {
            "scene_number": "final_composition",
            "shot_plan": {"shot_role": "final_composed_short_drama"},
        },
        tmp_path / "final_review.json",
    )

    assert result["status"] == "passed"
    assert result["batches"][0]["final_composition_finishing_gate"]["status"] == "passed"
    assert result["batches"][0]["review"]["final_composition_finishing_scores"]["skin_tone_uniformity"]["score"] == 4
    assert "final_composition_finishing_scores" in reviewer.evaluate.call_args.args[0]


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
    assert "at least 12 characters" in body["messages"][0]["content"]
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
