from dataclasses import replace

from src.services.generation_provider import VideoGenerationRequest
from src.tasks.video_tasks import _bounded_multi_shot_plan, _video_request_contract


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
    assert contract["provider_request_version"] == 2
    assert contract["model"] == "doubao-seedance-2-5-260628"
    assert contract["sequence_level_multi_shot"] is True
    assert contract["reference_video_count"] == 1
    assert {item["role"] for item in contract["reference_assets"]} >= {
        "reference_image", "reference_video", "reference_audio",
    }
    assert len(contract["contract_hash"]) == 64


def test_video_request_contract_binds_local_reference_content(tmp_path):
    reference = tmp_path / "character.png"
    reference.write_bytes(b"reference-v1")
    request = VideoGenerationRequest(
        prompt="shot", output_path=str(tmp_path / "shot.mp4"), reference_image=str(reference),
    )
    first = _video_request_contract(request, request_mode="reference", sequence_level=False)
    reference.write_bytes(b"reference-v2")
    second = _video_request_contract(request, request_mode="reference", sequence_level=False)

    assert first["reference_assets"][0]["kind"] == "local_file"
    assert first["reference_assets"][0]["sha256"] != second["reference_assets"][0]["sha256"]
    assert first["contract_hash"] != second["contract_hash"]


def test_video_request_contract_hash_changes_when_a_quality_control_changes():
    base = VideoGenerationRequest(prompt="shot", output_path="/tmp/shot.mp4", request_mode="reference", duration_seconds=4.0)
    first = _video_request_contract(base, request_mode="reference", sequence_level=False)
    changed = replace(base, return_last_frame=True)
    second = _video_request_contract(changed, request_mode="reference", sequence_level=False)
    assert first["contract_hash"] != second["contract_hash"]


def test_video_request_contract_fingerprints_prompt_and_shot_plan():
    request = VideoGenerationRequest(
        prompt="hero turns toward the window",
        negative_prompt="frozen pose",
        output_path="/tmp/shot.mp4",
        shot_plan={"shot_role": "reaction", "director_prompt": "turn slowly"},
    )
    first = _video_request_contract(request, request_mode="reference", sequence_level=False)
    changed = replace(request, prompt="hero runs toward the window")
    second = _video_request_contract(changed, request_mode="reference", sequence_level=False)

    assert first["prompt_fingerprint"]
    assert first["negative_prompt_fingerprint"]
    assert first["shot_plan_fingerprint"]
    assert first["prompt_fingerprint"] != second["prompt_fingerprint"]
    assert first["contract_hash"] != second["contract_hash"]


def test_video_request_contract_binds_dialogue_and_audio_mode(tmp_path):
    audio = tmp_path / "dialogue.wav"
    audio.write_bytes(b"audio")
    request = VideoGenerationRequest(
        prompt="shot",
        output_path=str(tmp_path / "shot.mp4"),
        audio_path=str(audio),
        shot_plan={"dialogue": "你为什么骗我"},
    )
    reference = _video_request_contract(request, request_mode="reference", sequence_level=False)
    changed = replace(request, shot_plan={"dialogue": "我没有骗你"})
    changed_contract = _video_request_contract(changed, request_mode="reference", sequence_level=False)

    assert reference["audio_binding_mode"] == "reference_audio"
    assert reference["dialogue_fingerprint"]
    assert reference["dialogue_fingerprint"] != changed_contract["dialogue_fingerprint"]
    assert reference["contract_hash"] != changed_contract["contract_hash"]


def test_video_request_contract_records_multicharacter_reference_bindings():
    request = VideoGenerationRequest(
        prompt="two characters confront each other",
        output_path="/tmp/shot.mp4",
        shot_plan={
            "character_reference_bindings": [
                {"image_index": 2, "character_name": "Alice", "view": "front", "expected_features": {"hair": "black"}},
                {"image_index": 3, "character_name": "Bob", "view": "profile"},
            ],
        },
    )

    contract = _video_request_contract(request, request_mode="reference", sequence_level=False)

    assert contract["character_reference_binding_count"] == 2
    assert contract["character_reference_bindings"] == [
        {"image_index": 2, "character_name": "Alice", "view": "front"},
        {"image_index": 3, "character_name": "Bob", "view": "profile"},
    ]


def test_video_request_contract_binds_frozen_spatial_asset_pack():
    request = VideoGenerationRequest(
        prompt="shot",
        output_path="/tmp/shot.mp4",
        shot_plan={
            "spatial_asset_pack": {
                "planner_contract_version": "spatial-director-v2",
                "project_signature": "project-hash",
                "scene_contract_hash": "scene-hash",
            },
        },
    )

    contract = _video_request_contract(request, request_mode="reference", sequence_level=False)

    assert contract["spatial_asset_pack"]["scene_contract_hash"] == "scene-hash"


def test_bounded_multi_shot_plan_carries_each_frozen_spatial_contract():
    shots = _bounded_multi_shot_plan({
        "sequence_shots": [
            {"scene_number": 1, "visual_summary": "entrance"},
            {"scene_number": 2, "visual_summary": "confrontation"},
        ],
        "spatial_contracts": {
            "1": {"scene_contract_hash": "scene-1"},
            "2": {"scene_contract_hash": "scene-2"},
        },
    })

    assert [shot["spatial_asset_pack"]["scene_contract_hash"] for shot in shots] == [
        "scene-1", "scene-2",
    ]


def test_video_request_contract_records_sequence_spatial_contract_hashes():
    request = VideoGenerationRequest(
        prompt="sequence",
        output_path="/tmp/sequence.mp4",
        multi_shot=True,
        shot_plan={
            "shots": [
                {"scene_number": 1, "spatial_asset_pack": {"scene_contract_hash": "scene-1"}},
                {"scene_number": 2, "spatial_asset_pack": {"scene_contract_hash": "scene-2"}},
            ],
        },
    )

    contract = _video_request_contract(request, request_mode="multi_shot", sequence_level=True)

    assert contract["sequence_shot_contracts"] == [
        {"scene_number": 1, "scene_contract_hash": "scene-1"},
        {"scene_number": 2, "scene_contract_hash": "scene-2"},
    ]
