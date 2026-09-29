import pytest

from src.services.production_workflow_profile import ProductionWorkflowProfileService


def write_production_workflows(tmp_path):
    image = tmp_path / "image_workflow.json"
    reference = tmp_path / "reference_workflow.json"
    video = tmp_path / "video_workflow.json"
    image.write_text(
        """
        {
          "1": {"class_type": "KSampler"},
          "2": {"class_type": "ControlNetApply"},
          "3": {"class_type": "OpenPosePreprocessor"},
          "4": {"class_type": "ZoeDepthPreprocessor"},
          "5": {"class_type": "FaceDetailer"},
          "6": {"class_type": "ImageUpscaleWithModel"},
          "7": {"class_type": "SaveImage"}
        }
        """,
        encoding="utf-8",
    )
    reference.write_text(
        """
        {
          "1": {"class_type": "IPAdapterFaceID"},
          "2": {"class_type": "SaveImage"}
        }
        """,
        encoding="utf-8",
    )
    video.write_text(
        """
        {
          "1": {"class_type": "LoadImage"},
          "2": {"class_type": "LoadImage"},
          "3": {"class_type": "SVD_img2vid_Conditioning"},
          "4": {"class_type": "VHS_VideoCombine"}
        }
        """,
        encoding="utf-8",
    )
    return image, reference, video


def test_workflow_profile_freezes_required_workflow_hashes(tmp_path, monkeypatch):
    image, reference, video = write_production_workflows(tmp_path)
    profile = tmp_path / "profile.json"
    monkeypatch.setattr("src.services.production_workflow_profile.settings.COMFYUI_WORKFLOW_PATH", str(image))
    monkeypatch.setattr("src.services.production_workflow_profile.settings.COMFYUI_VIDEO_WORKFLOW_PATH", str(video))
    monkeypatch.setattr("src.services.production_workflow_profile.settings.COMFYUI_REFERENCE_WORKFLOW_PATH", str(reference))

    service = ProductionWorkflowProfileService()
    manifest = service.freeze_profile(profile_path=str(profile), notes="approved local profile")

    assert manifest["status"] == "approved"
    assert set(manifest["required_workflows"]) == {"image", "reference", "video"}
    assert manifest["capabilities"]["character_identity"] is True
    assert manifest["capabilities"]["pose_control"] is True
    assert manifest["capabilities"]["depth_control"] is True
    assert manifest["capability_evidence"]["face_repair"]["matched_nodes"] == ["FaceDetailer"]
    assert service.validate_profile(profile_path=str(profile))["status"] == "valid"

    video.write_text('{"1":{"class_type":"DifferentVideoNode"}}', encoding="utf-8")
    stale = service.validate_profile(profile_path=str(profile))
    assert stale["status"] == "blocked"
    assert "video_workflow_hash" in stale["stale"]


def test_workflow_profile_requires_quality_capabilities(tmp_path, monkeypatch):
    image, reference, video = write_production_workflows(tmp_path)
    profile = tmp_path / "profile.json"
    monkeypatch.setattr("src.services.production_workflow_profile.settings.COMFYUI_WORKFLOW_PATH", str(image))
    monkeypatch.setattr("src.services.production_workflow_profile.settings.COMFYUI_VIDEO_WORKFLOW_PATH", str(video))
    monkeypatch.setattr("src.services.production_workflow_profile.settings.COMFYUI_REFERENCE_WORKFLOW_PATH", str(reference))

    service = ProductionWorkflowProfileService()
    with pytest.raises(ValueError, match="face_repair"):
        service.freeze_profile(profile_path=str(profile), capabilities={"face_repair": False})


def test_workflow_profile_rejects_workflows_without_capability_evidence(tmp_path, monkeypatch):
    image = tmp_path / "image_workflow.json"
    reference = tmp_path / "reference_workflow.json"
    video = tmp_path / "video_workflow.json"
    profile = tmp_path / "profile.json"
    image.write_text('{"1":{"class_type":"KSampler"}}', encoding="utf-8")
    reference.write_text('{"1":{"class_type":"IPAdapterFaceID"}}', encoding="utf-8")
    video.write_text('{"1":{"class_type":"VHS_VideoCombine"}}', encoding="utf-8")
    monkeypatch.setattr("src.services.production_workflow_profile.settings.COMFYUI_WORKFLOW_PATH", str(image))
    monkeypatch.setattr("src.services.production_workflow_profile.settings.COMFYUI_VIDEO_WORKFLOW_PATH", str(video))
    monkeypatch.setattr("src.services.production_workflow_profile.settings.COMFYUI_REFERENCE_WORKFLOW_PATH", str(reference))

    service = ProductionWorkflowProfileService()

    with pytest.raises(ValueError, match="workflow capabilities are missing") as exc:
        service.freeze_profile(profile_path=str(profile))

    message = str(exc.value)
    assert "face_repair" in message
    assert "upscale" in message
    assert "pose_control" in message
    assert "depth_control" in message


def test_workflow_profile_requires_reference_workflow_for_turnaround_assets(tmp_path, monkeypatch):
    image = tmp_path / "image_workflow.json"
    video = tmp_path / "video_workflow.json"
    profile = tmp_path / "profile.json"
    image.write_text("{}", encoding="utf-8")
    video.write_text("{}", encoding="utf-8")
    monkeypatch.setattr("src.services.production_workflow_profile.settings.COMFYUI_WORKFLOW_PATH", str(image))
    monkeypatch.setattr("src.services.production_workflow_profile.settings.COMFYUI_VIDEO_WORKFLOW_PATH", str(video))
    monkeypatch.setattr("src.services.production_workflow_profile.settings.COMFYUI_REFERENCE_WORKFLOW_PATH", "")

    service = ProductionWorkflowProfileService()

    with pytest.raises(ValueError, match="reference"):
        service.freeze_profile(profile_path=str(profile))

    report = service.validate_profile(profile_path=str(profile))
    assert report["status"] == "missing"


def test_workflow_profile_tracks_postprocess_command(tmp_path, monkeypatch):
    image, reference, video = write_production_workflows(tmp_path)
    profile = tmp_path / "profile.json"
    monkeypatch.setattr("src.services.production_workflow_profile.settings.COMFYUI_WORKFLOW_PATH", str(image))
    monkeypatch.setattr("src.services.production_workflow_profile.settings.COMFYUI_VIDEO_WORKFLOW_PATH", str(video))
    monkeypatch.setattr("src.services.production_workflow_profile.settings.COMFYUI_REFERENCE_WORKFLOW_PATH", str(reference))
    monkeypatch.setattr("src.services.production_workflow_profile.settings.GENERATION_IMAGE_POSTPROCESS_COMMAND", "facefix --input {input} --output {output}")
    monkeypatch.setattr("src.services.production_workflow_profile.settings.GENERATION_REQUIRE_IMAGE_POSTPROCESS", True)

    service = ProductionWorkflowProfileService()
    manifest = service.freeze_profile(profile_path=str(profile))

    assert manifest["quality_gates"]["image_postprocess_required"] is True
    assert manifest["quality_gates"]["image_postprocess_command_hash"]
    assert service.validate_profile(profile_path=str(profile))["status"] == "valid"

    monkeypatch.setattr("src.services.production_workflow_profile.settings.GENERATION_IMAGE_POSTPROCESS_COMMAND", "upscale --input {input} --output {output}")

    report = service.validate_profile(profile_path=str(profile))

    assert report["status"] == "blocked"
    assert "quality_gate_image_postprocess_command_hash" in report["stale"]


def test_workflow_profile_tracks_turnaround_feature_gate(tmp_path, monkeypatch):
    image, reference, video = write_production_workflows(tmp_path)
    profile = tmp_path / "profile.json"
    monkeypatch.setattr("src.services.production_workflow_profile.settings.COMFYUI_WORKFLOW_PATH", str(image))
    monkeypatch.setattr("src.services.production_workflow_profile.settings.COMFYUI_VIDEO_WORKFLOW_PATH", str(video))
    monkeypatch.setattr("src.services.production_workflow_profile.settings.COMFYUI_REFERENCE_WORKFLOW_PATH", str(reference))
    monkeypatch.setattr("src.services.production_workflow_profile.settings.GENERATION_TURNAROUND_FEATURE_MIN_SCORE", 4.0)

    service = ProductionWorkflowProfileService()
    manifest = service.freeze_profile(profile_path=str(profile))
    assert manifest["quality_gates"]["turnaround_feature_min_score"] == 4.0

    monkeypatch.setattr("src.services.production_workflow_profile.settings.GENERATION_TURNAROUND_FEATURE_MIN_SCORE", 4.5)
    report = service.validate_profile(profile_path=str(profile))

    assert report["status"] == "blocked"
    assert "quality_gate_turnaround_feature_min_score" in report["stale"]


def test_workflow_profile_tracks_image_aesthetic_feature_gate(tmp_path, monkeypatch):
    image, reference, video = write_production_workflows(tmp_path)
    profile = tmp_path / "profile.json"
    monkeypatch.setattr("src.services.production_workflow_profile.settings.COMFYUI_WORKFLOW_PATH", str(image))
    monkeypatch.setattr("src.services.production_workflow_profile.settings.COMFYUI_VIDEO_WORKFLOW_PATH", str(video))
    monkeypatch.setattr("src.services.production_workflow_profile.settings.COMFYUI_REFERENCE_WORKFLOW_PATH", str(reference))
    monkeypatch.setattr("src.services.production_workflow_profile.settings.GENERATION_IMAGE_AESTHETIC_FEATURE_MIN_SCORE", 4.0)

    service = ProductionWorkflowProfileService()
    manifest = service.freeze_profile(profile_path=str(profile))
    assert manifest["quality_gates"]["image_aesthetic_feature_min_score"] == 4.0

    monkeypatch.setattr("src.services.production_workflow_profile.settings.GENERATION_IMAGE_AESTHETIC_FEATURE_MIN_SCORE", 4.6)
    report = service.validate_profile(profile_path=str(profile))

    assert report["status"] == "blocked"
    assert "quality_gate_image_aesthetic_feature_min_score" in report["stale"]


def test_workflow_profile_tracks_video_aesthetic_feature_gate(tmp_path, monkeypatch):
    image, reference, video = write_production_workflows(tmp_path)
    profile = tmp_path / "profile.json"
    monkeypatch.setattr("src.services.production_workflow_profile.settings.COMFYUI_WORKFLOW_PATH", str(image))
    monkeypatch.setattr("src.services.production_workflow_profile.settings.COMFYUI_VIDEO_WORKFLOW_PATH", str(video))
    monkeypatch.setattr("src.services.production_workflow_profile.settings.COMFYUI_REFERENCE_WORKFLOW_PATH", str(reference))
    monkeypatch.setattr("src.services.production_workflow_profile.settings.GENERATION_VIDEO_AESTHETIC_FEATURE_MIN_SCORE", 4.0)

    service = ProductionWorkflowProfileService()
    manifest = service.freeze_profile(profile_path=str(profile))
    assert manifest["quality_gates"]["video_aesthetic_feature_min_score"] == 4.0

    monkeypatch.setattr("src.services.production_workflow_profile.settings.GENERATION_VIDEO_AESTHETIC_FEATURE_MIN_SCORE", 4.5)
    report = service.validate_profile(profile_path=str(profile))

    assert report["status"] == "blocked"
    assert "quality_gate_video_aesthetic_feature_min_score" in report["stale"]


def test_workflow_profile_tracks_video_character_distinctiveness_gate(tmp_path, monkeypatch):
    image, reference, video = write_production_workflows(tmp_path)
    profile = tmp_path / "profile.json"
    monkeypatch.setattr("src.services.production_workflow_profile.settings.COMFYUI_WORKFLOW_PATH", str(image))
    monkeypatch.setattr("src.services.production_workflow_profile.settings.COMFYUI_VIDEO_WORKFLOW_PATH", str(video))
    monkeypatch.setattr("src.services.production_workflow_profile.settings.COMFYUI_REFERENCE_WORKFLOW_PATH", str(reference))
    monkeypatch.setattr("src.services.production_workflow_profile.settings.GENERATION_VIDEO_CHARACTER_DISTINCTIVENESS_MIN_SCORE", 4.0)

    service = ProductionWorkflowProfileService()
    manifest = service.freeze_profile(profile_path=str(profile))
    assert manifest["quality_gates"]["video_character_distinctiveness_min_score"] == 4.0

    monkeypatch.setattr("src.services.production_workflow_profile.settings.GENERATION_VIDEO_CHARACTER_DISTINCTIVENESS_MIN_SCORE", 4.5)
    report = service.validate_profile(profile_path=str(profile))

    assert report["status"] == "blocked"
    assert "quality_gate_video_character_distinctiveness_min_score" in report["stale"]


def test_workflow_profile_tracks_video_performance_gate(tmp_path, monkeypatch):
    image, reference, video = write_production_workflows(tmp_path)
    profile = tmp_path / "profile.json"
    monkeypatch.setattr("src.services.production_workflow_profile.settings.COMFYUI_WORKFLOW_PATH", str(image))
    monkeypatch.setattr("src.services.production_workflow_profile.settings.COMFYUI_VIDEO_WORKFLOW_PATH", str(video))
    monkeypatch.setattr("src.services.production_workflow_profile.settings.COMFYUI_REFERENCE_WORKFLOW_PATH", str(reference))
    monkeypatch.setattr("src.services.production_workflow_profile.settings.GENERATION_VIDEO_PERFORMANCE_MIN_SCORE", 4.0)

    service = ProductionWorkflowProfileService()
    manifest = service.freeze_profile(profile_path=str(profile))
    assert manifest["quality_gates"]["video_performance_min_score"] == 4.0

    monkeypatch.setattr("src.services.production_workflow_profile.settings.GENERATION_VIDEO_PERFORMANCE_MIN_SCORE", 4.5)
    report = service.validate_profile(profile_path=str(profile))

    assert report["status"] == "blocked"
    assert "quality_gate_video_performance_min_score" in report["stale"]


def test_workflow_profile_tracks_generation_quality_budget(tmp_path, monkeypatch):
    image, reference, video = write_production_workflows(tmp_path)
    profile = tmp_path / "profile.json"
    monkeypatch.setattr("src.services.production_workflow_profile.settings.COMFYUI_WORKFLOW_PATH", str(image))
    monkeypatch.setattr("src.services.production_workflow_profile.settings.COMFYUI_VIDEO_WORKFLOW_PATH", str(video))
    monkeypatch.setattr("src.services.production_workflow_profile.settings.COMFYUI_REFERENCE_WORKFLOW_PATH", str(reference))
    monkeypatch.setattr("src.services.production_workflow_profile.settings.GENERATION_QUALITY_PROFILE", "hongguo_reference")
    monkeypatch.setattr("src.services.production_workflow_profile.settings.GENERATION_IMAGE_CANDIDATES", 5)
    monkeypatch.setattr("src.services.production_workflow_profile.settings.GENERATION_IMAGE_REFINEMENT_PASSES", 2)
    monkeypatch.setattr("src.services.production_workflow_profile.settings.GENERATION_MAX_IMAGE_CANDIDATES", 12)
    monkeypatch.setattr("src.services.production_workflow_profile.settings.GENERATION_REPAIR_IMAGE_CANDIDATE_MULTIPLIER", 1.5)
    monkeypatch.setattr("src.services.production_workflow_profile.settings.GENERATION_REPAIR_EXTRA_REFINEMENT_PASSES", 1)
    monkeypatch.setattr("src.services.production_workflow_profile.settings.GENERATION_VIDEO_CANDIDATES", 4)
    monkeypatch.setattr("src.services.production_workflow_profile.settings.GENERATION_VIDEO_REFINEMENT_PASSES", 2)
    monkeypatch.setattr("src.services.production_workflow_profile.settings.GENERATION_MAX_VIDEO_CANDIDATES", 8)
    monkeypatch.setattr("src.services.production_workflow_profile.settings.GENERATION_REPAIR_VIDEO_CANDIDATE_MULTIPLIER", 1.5)
    monkeypatch.setattr("src.services.production_workflow_profile.settings.GENERATION_VIDEO_END_FRAME_ENABLED", True)
    monkeypatch.setattr("src.services.production_workflow_profile.settings.GENERATION_STEPS", 40)

    service = ProductionWorkflowProfileService()
    manifest = service.freeze_profile(profile_path=str(profile))

    assert manifest["quality_gates"]["quality_profile"] == "hongguo_reference"
    assert manifest["quality_gates"]["image_candidates"] == 5
    assert manifest["quality_gates"]["image_refinement_passes"] == 2
    assert manifest["quality_gates"]["max_image_candidates"] == 12
    assert manifest["quality_gates"]["repair_image_candidate_multiplier"] == 1.5
    assert manifest["quality_gates"]["repair_extra_refinement_passes"] == 1
    assert manifest["quality_gates"]["video_candidates"] == 4
    assert manifest["quality_gates"]["video_refinement_passes"] == 2
    assert manifest["quality_gates"]["max_video_candidates"] == 8
    assert manifest["quality_gates"]["repair_video_candidate_multiplier"] == 1.5
    assert manifest["quality_gates"]["effective_image_candidates"] == 5
    assert manifest["quality_gates"]["effective_image_refinement_passes"] == 2
    assert manifest["quality_gates"]["effective_video_candidates"] == 4
    assert manifest["quality_gates"]["effective_video_refinement_passes"] == 2
    assert manifest["quality_gates"]["video_end_frame_enabled"] is True

    monkeypatch.setattr("src.services.production_workflow_profile.settings.GENERATION_IMAGE_CANDIDATES", 1)
    monkeypatch.setattr("src.services.production_workflow_profile.settings.GENERATION_VIDEO_REFINEMENT_PASSES", 0)
    monkeypatch.setattr("src.services.production_workflow_profile.settings.GENERATION_REPAIR_EXTRA_REFINEMENT_PASSES", 0)
    monkeypatch.setattr("src.services.production_workflow_profile.settings.GENERATION_QUALITY_PROFILE", "draft")

    report = service.validate_profile(profile_path=str(profile))

    assert report["status"] == "blocked"
    assert "quality_gate_image_candidates" in report["stale"]
    assert "quality_gate_video_refinement_passes" in report["stale"]
    assert "quality_gate_repair_extra_refinement_passes" in report["stale"]
    assert "quality_gate_quality_profile" in report["stale"]


def test_workflow_profile_rejects_low_generation_quality_budget(tmp_path, monkeypatch):
    image, reference, video = write_production_workflows(tmp_path)
    profile = tmp_path / "profile.json"
    monkeypatch.setattr("src.services.production_workflow_profile.settings.COMFYUI_WORKFLOW_PATH", str(image))
    monkeypatch.setattr("src.services.production_workflow_profile.settings.COMFYUI_VIDEO_WORKFLOW_PATH", str(video))
    monkeypatch.setattr("src.services.production_workflow_profile.settings.COMFYUI_REFERENCE_WORKFLOW_PATH", str(reference))
    monkeypatch.setattr("src.services.production_workflow_profile.settings.GENERATION_QUALITY_PROFILE", "draft")
    monkeypatch.setattr("src.services.production_workflow_profile.settings.GENERATION_IMAGE_CANDIDATES", 1)
    monkeypatch.setattr("src.services.production_workflow_profile.settings.GENERATION_IMAGE_REFINEMENT_PASSES", 0)
    monkeypatch.setattr("src.services.production_workflow_profile.settings.GENERATION_VIDEO_CANDIDATES", 1)
    monkeypatch.setattr("src.services.production_workflow_profile.settings.GENERATION_VIDEO_REFINEMENT_PASSES", 0)
    monkeypatch.setattr("src.services.production_workflow_profile.settings.GENERATION_VIDEO_END_FRAME_ENABLED", False)
    monkeypatch.setattr("src.services.production_workflow_profile.settings.GENERATION_STEPS", 24)

    service = ProductionWorkflowProfileService()

    with pytest.raises(ValueError, match="generation quality budget"):
        service.freeze_profile(profile_path=str(profile))


def test_workflow_profile_blocks_existing_low_quality_budget(tmp_path, monkeypatch):
    image, reference, video = write_production_workflows(tmp_path)
    profile = tmp_path / "profile.json"
    monkeypatch.setattr("src.services.production_workflow_profile.settings.COMFYUI_WORKFLOW_PATH", str(image))
    monkeypatch.setattr("src.services.production_workflow_profile.settings.COMFYUI_VIDEO_WORKFLOW_PATH", str(video))
    monkeypatch.setattr("src.services.production_workflow_profile.settings.COMFYUI_REFERENCE_WORKFLOW_PATH", str(reference))
    monkeypatch.setattr("src.services.production_workflow_profile.settings.GENERATION_QUALITY_PROFILE", "hongguo_reference")
    monkeypatch.setattr("src.services.production_workflow_profile.settings.GENERATION_IMAGE_CANDIDATES", 5)
    monkeypatch.setattr("src.services.production_workflow_profile.settings.GENERATION_IMAGE_REFINEMENT_PASSES", 2)
    monkeypatch.setattr("src.services.production_workflow_profile.settings.GENERATION_VIDEO_CANDIDATES", 4)
    monkeypatch.setattr("src.services.production_workflow_profile.settings.GENERATION_VIDEO_REFINEMENT_PASSES", 2)
    monkeypatch.setattr("src.services.production_workflow_profile.settings.GENERATION_VIDEO_END_FRAME_ENABLED", True)
    monkeypatch.setattr("src.services.production_workflow_profile.settings.GENERATION_STEPS", 40)

    service = ProductionWorkflowProfileService()
    service.freeze_profile(profile_path=str(profile))

    data = profile.read_text(encoding="utf-8")
    data = data.replace('"image_candidates": 5', '"image_candidates": 1')
    data = data.replace('"quality_profile": "hongguo_reference"', '"quality_profile": "draft"')
    data = data.replace('"video_end_frame_enabled": true', '"video_end_frame_enabled": false')
    profile.write_text(data, encoding="utf-8")

    report = service.validate_profile(profile_path=str(profile))

    assert report["status"] == "blocked"
    assert "production_quality_budget" in report["missing"]
    assert "image_candidates_below_5" in report["quality_budget_issues"]
    assert "quality_profile_not_production_approved" in report["quality_budget_issues"]
    assert "video_end_frame_disabled" in report["quality_budget_issues"]
