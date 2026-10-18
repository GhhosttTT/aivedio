from dataclasses import replace

from src.services.generation_provider import VideoGenerationRequest
from src.tasks.video_tasks import _video_request_contract


def test_video_request_contract_captures_effective_generation_controls():
    request = VideoGenerationRequest(
        prompt="a dramatic close-up",
        output_path="/tmp/shot.mp4",
        negative_prompt="blur",
        reference_image="/tmp/character.png",
        reference_videos=["/tmp/previous.mp4"],
        reference_audios=["/tmp/dialogue.wav"],
        model="doubao-seedance-2-5-260628",
        resolution="1080p",
        output_format="mp4",
        request_mode="multi_shot",
        multi_shot=True,
        generate_audio=True,
        return_last_frame=True,
        duration_seconds=5.0,
        aspect_ratio="9:16",
        fps=24,
    )
    contract = _video_request_contract(request, request_mode="multi_shot", sequence_level=True)
    assert contract["model"] == "doubao-seedance-2-5-260628"
    assert contract["sequence_level_multi_shot"] is True
    assert contract["reference_video_count"] == 1
    assert len(contract["contract_hash"]) == 64


def test_video_request_contract_hash_changes_when_a_quality_control_changes():
    base = VideoGenerationRequest(prompt="shot", output_path="/tmp/shot.mp4", request_mode="reference", duration_seconds=4.0)
    first = _video_request_contract(base, request_mode="reference", sequence_level=False)
    changed = replace(base, return_last_frame=True)
    second = _video_request_contract(changed, request_mode="reference", sequence_level=False)
    assert first["contract_hash"] != second["contract_hash"]
