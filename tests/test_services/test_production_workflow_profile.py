from src.services.production_workflow_profile import ProductionWorkflowProfileService


def test_workflow_profile_freezes_required_workflow_hashes(tmp_path, monkeypatch):
    image = tmp_path / "image_workflow.json"
    video = tmp_path / "video_workflow.json"
    profile = tmp_path / "profile.json"
    image.write_text('{"1":{"class_type":"KSampler"}}', encoding="utf-8")
    video.write_text('{"1":{"class_type":"VHS_VideoCombine"}}', encoding="utf-8")
    monkeypatch.setattr("src.services.production_workflow_profile.settings.COMFYUI_WORKFLOW_PATH", str(image))
    monkeypatch.setattr("src.services.production_workflow_profile.settings.COMFYUI_VIDEO_WORKFLOW_PATH", str(video))
    monkeypatch.setattr("src.services.production_workflow_profile.settings.COMFYUI_REFERENCE_WORKFLOW_PATH", "")

    service = ProductionWorkflowProfileService()
    manifest = service.freeze_profile(profile_path=str(profile), notes="approved local profile")

    assert manifest["status"] == "approved"
    assert set(manifest["required_workflows"]) == {"image", "video"}
    assert manifest["capabilities"]["character_identity"] is True
    assert service.validate_profile(profile_path=str(profile))["status"] == "valid"

    video.write_text('{"1":{"class_type":"DifferentVideoNode"}}', encoding="utf-8")
    stale = service.validate_profile(profile_path=str(profile))
    assert stale["status"] == "blocked"
    assert "video_workflow_hash" in stale["stale"]


def test_workflow_profile_requires_quality_capabilities(tmp_path, monkeypatch):
    image = tmp_path / "image_workflow.json"
    video = tmp_path / "video_workflow.json"
    profile = tmp_path / "profile.json"
    image.write_text("{}", encoding="utf-8")
    video.write_text("{}", encoding="utf-8")
    monkeypatch.setattr("src.services.production_workflow_profile.settings.COMFYUI_WORKFLOW_PATH", str(image))
    monkeypatch.setattr("src.services.production_workflow_profile.settings.COMFYUI_VIDEO_WORKFLOW_PATH", str(video))
    monkeypatch.setattr("src.services.production_workflow_profile.settings.COMFYUI_REFERENCE_WORKFLOW_PATH", "")

    service = ProductionWorkflowProfileService()
    service.freeze_profile(profile_path=str(profile), capabilities={"face_repair": False})

    report = service.validate_profile(profile_path=str(profile))

    assert report["status"] == "blocked"
    assert "required_capabilities" in report["missing"]
    assert "face_repair" in report["missing_capabilities"]


def test_workflow_profile_tracks_postprocess_command(tmp_path, monkeypatch):
    image = tmp_path / "image_workflow.json"
    video = tmp_path / "video_workflow.json"
    profile = tmp_path / "profile.json"
    image.write_text("{}", encoding="utf-8")
    video.write_text("{}", encoding="utf-8")
    monkeypatch.setattr("src.services.production_workflow_profile.settings.COMFYUI_WORKFLOW_PATH", str(image))
    monkeypatch.setattr("src.services.production_workflow_profile.settings.COMFYUI_VIDEO_WORKFLOW_PATH", str(video))
    monkeypatch.setattr("src.services.production_workflow_profile.settings.COMFYUI_REFERENCE_WORKFLOW_PATH", "")
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
    image = tmp_path / "image_workflow.json"
    video = tmp_path / "video_workflow.json"
    profile = tmp_path / "profile.json"
    image.write_text("{}", encoding="utf-8")
    video.write_text("{}", encoding="utf-8")
    monkeypatch.setattr("src.services.production_workflow_profile.settings.COMFYUI_WORKFLOW_PATH", str(image))
    monkeypatch.setattr("src.services.production_workflow_profile.settings.COMFYUI_VIDEO_WORKFLOW_PATH", str(video))
    monkeypatch.setattr("src.services.production_workflow_profile.settings.COMFYUI_REFERENCE_WORKFLOW_PATH", "")
    monkeypatch.setattr("src.services.production_workflow_profile.settings.GENERATION_TURNAROUND_FEATURE_MIN_SCORE", 4.0)

    service = ProductionWorkflowProfileService()
    manifest = service.freeze_profile(profile_path=str(profile))
    assert manifest["quality_gates"]["turnaround_feature_min_score"] == 4.0

    monkeypatch.setattr("src.services.production_workflow_profile.settings.GENERATION_TURNAROUND_FEATURE_MIN_SCORE", 4.5)
    report = service.validate_profile(profile_path=str(profile))

    assert report["status"] == "blocked"
    assert "quality_gate_turnaround_feature_min_score" in report["stale"]


def test_workflow_profile_tracks_image_aesthetic_feature_gate(tmp_path, monkeypatch):
    image = tmp_path / "image_workflow.json"
    video = tmp_path / "video_workflow.json"
    profile = tmp_path / "profile.json"
    image.write_text("{}", encoding="utf-8")
    video.write_text("{}", encoding="utf-8")
    monkeypatch.setattr("src.services.production_workflow_profile.settings.COMFYUI_WORKFLOW_PATH", str(image))
    monkeypatch.setattr("src.services.production_workflow_profile.settings.COMFYUI_VIDEO_WORKFLOW_PATH", str(video))
    monkeypatch.setattr("src.services.production_workflow_profile.settings.COMFYUI_REFERENCE_WORKFLOW_PATH", "")
    monkeypatch.setattr("src.services.production_workflow_profile.settings.GENERATION_IMAGE_AESTHETIC_FEATURE_MIN_SCORE", 4.0)

    service = ProductionWorkflowProfileService()
    manifest = service.freeze_profile(profile_path=str(profile))
    assert manifest["quality_gates"]["image_aesthetic_feature_min_score"] == 4.0

    monkeypatch.setattr("src.services.production_workflow_profile.settings.GENERATION_IMAGE_AESTHETIC_FEATURE_MIN_SCORE", 4.6)
    report = service.validate_profile(profile_path=str(profile))

    assert report["status"] == "blocked"
    assert "quality_gate_image_aesthetic_feature_min_score" in report["stale"]


def test_workflow_profile_tracks_video_aesthetic_feature_gate(tmp_path, monkeypatch):
    image = tmp_path / "image_workflow.json"
    video = tmp_path / "video_workflow.json"
    profile = tmp_path / "profile.json"
    image.write_text("{}", encoding="utf-8")
    video.write_text("{}", encoding="utf-8")
    monkeypatch.setattr("src.services.production_workflow_profile.settings.COMFYUI_WORKFLOW_PATH", str(image))
    monkeypatch.setattr("src.services.production_workflow_profile.settings.COMFYUI_VIDEO_WORKFLOW_PATH", str(video))
    monkeypatch.setattr("src.services.production_workflow_profile.settings.COMFYUI_REFERENCE_WORKFLOW_PATH", "")
    monkeypatch.setattr("src.services.production_workflow_profile.settings.GENERATION_VIDEO_AESTHETIC_FEATURE_MIN_SCORE", 4.0)

    service = ProductionWorkflowProfileService()
    manifest = service.freeze_profile(profile_path=str(profile))
    assert manifest["quality_gates"]["video_aesthetic_feature_min_score"] == 4.0

    monkeypatch.setattr("src.services.production_workflow_profile.settings.GENERATION_VIDEO_AESTHETIC_FEATURE_MIN_SCORE", 4.5)
    report = service.validate_profile(profile_path=str(profile))

    assert report["status"] == "blocked"
    assert "quality_gate_video_aesthetic_feature_min_score" in report["stale"]
