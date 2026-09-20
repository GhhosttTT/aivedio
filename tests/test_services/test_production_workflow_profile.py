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
