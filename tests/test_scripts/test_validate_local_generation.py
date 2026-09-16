import json

from scripts import validate_local_generation as validator


def test_video_workflow_preflight_skips_when_unconfigured(monkeypatch):
    monkeypatch.setattr(validator.settings, "COMFYUI_VIDEO_WORKFLOW_PATH", "")

    report = validator.preflight_video_workflow()

    assert report["status"] == "skipped"
    assert report["checks"]["configured"] is False


def test_video_workflow_preflight_blocks_missing_video_contract(tmp_path, monkeypatch):
    workflow = tmp_path / "video.json"
    workflow.write_text(json.dumps({
        "1": {"class_type": "LoadImage", "inputs": {"image": "literal.png"}},
        "2": {"class_type": "CLIPTextEncode", "inputs": {"text": "literal prompt"}},
    }), encoding="utf-8")

    class FakeService:
        def __init__(self, *args, **kwargs):
            self.client = type("Client", (), {"close": lambda _self: None})()

        def _replace_workflow_placeholders(self, workflow, _replacements):
            return workflow

        def preflight(self, _workflow):
            return None

    monkeypatch.setattr(validator, "ComfyUIService", FakeService)

    report = validator.preflight_video_workflow(workflow_path=str(workflow))

    assert report["status"] == "blocked"
    assert report["checks"]["has_reference_placeholder"] is False
    assert report["checks"]["has_prompt_placeholder"] is False
    assert report["checks"]["has_likely_video_output"] is False


def test_video_workflow_preflight_accepts_placeholder_contract(tmp_path, monkeypatch):
    workflow = tmp_path / "video.json"
    workflow.write_text(json.dumps({
        "1": {"class_type": "LoadImage", "inputs": {"image": "{reference_image}"}},
        "2": {"class_type": "CLIPTextEncode", "inputs": {"text": "{prompt}"}},
        "3": {"class_type": "VHS_VideoCombine", "inputs": {"filename_prefix": "{output_prefix}"}},
    }), encoding="utf-8")

    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {"devices": [{"name": "RTX 3060"}]}

    class FakeClient:
        def get(self, _url):
            return FakeResponse()

        def close(self):
            return None

    class FakeService:
        def __init__(self, *args, **kwargs):
            self.client = FakeClient()
            self.base_url = "http://127.0.0.1:8188"

        def _replace_workflow_placeholders(self, workflow, _replacements):
            return workflow

        def preflight(self, _workflow):
            return None

    monkeypatch.setattr(validator, "ComfyUIService", FakeService)

    report = validator.preflight_video_workflow(workflow_path=str(workflow))

    assert report["status"] == "ready_for_live_test"
    assert report["placeholders"] == ["output_prefix", "prompt", "reference_image"]
    assert report["likely_output_nodes"][0]["class_type"] == "VHS_VideoCombine"
