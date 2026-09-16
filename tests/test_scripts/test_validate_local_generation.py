import json

from scripts import validate_local_generation as validator


def write_json(path, payload):
    path.write_text(json.dumps(payload), encoding="utf-8")


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


def test_validation_summary_requires_manual_scores(tmp_path):
    write_json(tmp_path / "preflight.json", {"status": "ready_for_live_test"})
    write_json(tmp_path / "video_workflow_preflight.json", {"status": "ready_for_live_test"})
    write_json(tmp_path / "render.json", {"status": "rendered_pending_human_review"})
    write_json(tmp_path / "video_review.json", {"status": "passed"})

    report = validator.summarize_validation(tmp_path)

    assert report["status"] == "partial_needs_review"
    assert report["checks"]["manual_review_present"] is False
    assert any("manual_review.json" in item for item in report["action_items"])


def test_validation_summary_accepts_calibrated_run(tmp_path):
    write_json(tmp_path / "preflight.json", {"status": "ready_for_live_test"})
    write_json(tmp_path / "video_workflow_preflight.json", {"status": "ready_for_live_test"})
    write_json(tmp_path / "render.json", {"status": "rendered_pending_human_review"})
    write_json(tmp_path / "video_review.json", {"status": "passed"})
    write_json(tmp_path / "manual_review.json", {
        "cases": [
            {"id": "discovery", "score": 4.5, "decision": "accept"},
            {"id": "reaction", "score": 4.0, "decision": "accept"},
        ]
    })

    report = validator.summarize_validation(tmp_path)

    assert report["status"] == "ready_for_calibrated_generation"
    assert report["checks"]["manual_average_score"] == 4.25
    assert report["action_items"] == []


def test_validation_summary_recommends_targeted_calibration(tmp_path):
    write_json(tmp_path / "preflight.json", {"status": "ready_for_live_test"})
    write_json(tmp_path / "video_workflow_preflight.json", {"status": "ready_for_live_test"})
    write_json(tmp_path / "render.json", {"status": "rendered_pending_human_review"})
    write_json(tmp_path / "video_review.json", {
        "status": "needs_review",
        "batches": [{
            "review": {
                "identity_consistency": {"score": 2, "evidence": "face changes"},
                "temporal_consistency": {"score": 2, "evidence": "flicker"},
                "composition": {"score": 3, "evidence": "bad crop"},
            }
        }],
    })
    write_json(tmp_path / "manual_review.json", {
        "cases": [
            {"id": "discovery", "score": 2.5, "decision": "reject", "issue_tags": ["identity drift", "crop"]},
            {"id": "reaction", "score": 3.5, "decision": "accept", "note": "flicker on face"},
        ]
    })

    report = validator.summarize_validation(tmp_path)

    areas = [item["area"] for item in report["calibration_recommendations"]]
    assert report["status"] == "partial_needs_review"
    assert "identity" in areas
    assert "video_motion" in areas
    assert "composition" in areas
    assert "shot_design" in areas
