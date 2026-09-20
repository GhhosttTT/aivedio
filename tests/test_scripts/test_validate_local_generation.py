import json

from scripts import validate_local_generation as validator
from src.services import video_engine_preflight


def write_json(path, payload):
    path.write_text(json.dumps(payload), encoding="utf-8")


def rendered_cases(*ids):
    return {
        "status": "rendered_pending_human_review",
        "cases": [{"id": item, "image": f"{item}.png"} for item in ids],
    }


def passed_video_review():
    return {
        "status": "passed",
        "batches": [{
            "review": {
                "facial_identity": {"score": 4, "evidence": "face matches"},
                "identity_consistency": {"score": 4, "evidence": "identity stable"},
                "temporal_consistency": {"score": 4, "evidence": "motion stable"},
            }
        }],
    }


def test_review_models_endpoint_uses_llama_cpp_openai_contract(monkeypatch):
    monkeypatch.setattr(validator.settings, "LOCAL_REVIEW_BASE_URL", "http://127.0.0.1:8080")

    assert validator._review_models_endpoint() == "http://127.0.0.1:8080/v1/models"


def test_installed_review_models_reads_openai_models(monkeypatch):
    calls = []

    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {"data": [{"id": "qwen2.5-vl"}, {"name": "fallback-vlm"}]}

    class FakeClient:
        def __init__(self, **kwargs):
            calls.append(kwargs)

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def get(self, url):
            calls.append({"url": url})
            return FakeResponse()

    monkeypatch.setattr(validator.settings, "LOCAL_REVIEW_BASE_URL", "http://127.0.0.1:8080/v1")
    monkeypatch.setattr(validator.httpx, "Client", FakeClient)

    assert validator._installed_review_models() == ["qwen2.5-vl", "fallback-vlm"]
    assert calls[0]["trust_env"] is False
    assert calls[1]["url"] == "http://127.0.0.1:8080/v1/models"


def test_video_workflow_preflight_skips_when_unconfigured(monkeypatch):
    monkeypatch.setattr(validator.settings, "COMFYUI_VIDEO_WORKFLOW_PATH", "")

    report = validator.preflight_video_workflow()

    assert report["status"] == "skipped"
    assert report["checks"]["configured"] is False


def test_production_video_preflight_blocks_svd_only(monkeypatch):
    monkeypatch.setattr(validator.settings, "COMFYUI_VIDEO_WORKFLOW_PATH", "")

    report = validator.preflight_production_video_engine()

    assert report["status"] == "production_not_ready"
    assert "COMFYUI_VIDEO_WORKFLOW_PATH" in report["action_items"][0]


def test_production_video_preflight_accepts_configured_http_provider(monkeypatch):
    monkeypatch.setattr(validator.settings, "GENERATION_PROVIDER", "http_video_api")
    monkeypatch.setenv("HTTP_VIDEO_ENDPOINT", "https://gateway.example/video")
    monkeypatch.setenv("HTTP_VIDEO_API_KEY", "secret")
    monkeypatch.setattr(video_engine_preflight, "preflight_video_workflow", lambda *_args, **_kwargs: {"status": "skipped"})

    report = validator.preflight_production_video_engine()

    assert report["status"] == "ready_for_production_video_test"
    assert report["provider"]["status"] == "configured"


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

    monkeypatch.setattr(video_engine_preflight, "ComfyUIService", FakeService)

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
        "3": {"class_type": "LoadImage", "inputs": {"image": "{last_frame}"}},
        "4": {"class_type": "VHS_VideoCombine", "inputs": {"filename_prefix": "{output_prefix}"}},
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

    monkeypatch.setattr(video_engine_preflight, "ComfyUIService", FakeService)

    report = validator.preflight_video_workflow(workflow_path=str(workflow))

    assert report["status"] == "ready_for_live_test"
    assert report["checks"]["has_end_frame_placeholder"] is True
    assert report["placeholders"] == ["last_frame", "output_prefix", "prompt", "reference_image"]
    assert report["likely_output_nodes"][0]["class_type"] == "VHS_VideoCombine"


def test_validation_summary_requires_manual_scores(tmp_path):
    write_json(tmp_path / "preflight.json", {"status": "ready_for_live_test"})
    write_json(tmp_path / "video_workflow_preflight.json", {"status": "ready_for_live_test"})
    write_json(tmp_path / "render.json", rendered_cases("discovery"))
    write_json(tmp_path / "video_review.json", passed_video_review())
    write_json(tmp_path / "seed_dance_baseline_comparison.json", {"status": "passed"})

    report = validator.summarize_validation(tmp_path)

    assert report["status"] == "partial_needs_review"
    assert report["checks"]["manual_review_present"] is False
    assert any("manual_review.json" in item for item in report["action_items"])


def test_validation_summary_accepts_seed_dance_candidate(tmp_path):
    write_json(tmp_path / "preflight.json", {"status": "ready_for_live_test"})
    write_json(tmp_path / "video_workflow_preflight.json", {"status": "ready_for_live_test"})
    write_json(tmp_path / "render.json", rendered_cases("discovery", "reaction"))
    write_json(tmp_path / "video_review.json", passed_video_review())
    write_json(tmp_path / "seed_dance_baseline_comparison.json", {"status": "passed"})
    write_json(tmp_path / "manual_review.json", {
        "cases": [
            {"id": "discovery", "score": 4.5, "decision": "accept"},
            {"id": "reaction", "score": 4.0, "decision": "accept"},
        ]
    })

    report = validator.summarize_validation(tmp_path)

    assert report["status"] == "ready_for_seed_dance_candidate"
    assert report["checks"]["manual_average_score"] == 4.25
    assert report["checks"]["baseline_comparison_passed"] is True
    assert report["checks"]["video_identity_gate_passed"] is True
    assert report["checks"]["video_temporal_gate_passed"] is True
    assert report["checks"]["manual_review_covers_rendered_cases"] is True
    assert report["action_items"] == []


def test_validation_summary_requires_manual_review_for_every_rendered_case(tmp_path):
    write_json(tmp_path / "preflight.json", {"status": "ready_for_live_test"})
    write_json(tmp_path / "video_workflow_preflight.json", {"status": "ready_for_live_test"})
    write_json(tmp_path / "render.json", rendered_cases("discovery", "reaction"))
    write_json(tmp_path / "video_review.json", passed_video_review())
    write_json(tmp_path / "seed_dance_baseline_comparison.json", {"status": "passed"})
    write_json(tmp_path / "manual_review.json", {
        "cases": [{"id": "discovery", "score": 4.5, "decision": "accept"}]
    })

    report = validator.summarize_validation(tmp_path)

    assert report["status"] == "partial_needs_review"
    assert report["checks"]["manual_review_covers_rendered_cases"] is False
    assert report["checks"]["manual_review_missing_case_ids"] == ["reaction"]
    assert any("reaction" in item for item in report["action_items"])


def test_validation_summary_requires_seed_dance_baseline_comparison(tmp_path):
    write_json(tmp_path / "preflight.json", {"status": "ready_for_live_test"})
    write_json(tmp_path / "video_workflow_preflight.json", {"status": "ready_for_live_test"})
    write_json(tmp_path / "render.json", rendered_cases("discovery"))
    write_json(tmp_path / "video_review.json", passed_video_review())
    write_json(tmp_path / "manual_review.json", {
        "cases": [{"id": "discovery", "score": 4.5, "decision": "accept"}]
    })

    report = validator.summarize_validation(tmp_path)

    assert report["status"] == "partial_needs_review"
    assert report["checks"]["baseline_comparison_present"] is False
    assert any("compare-baseline" in item for item in report["action_items"])


def test_validation_summary_blocks_failed_seed_dance_comparison(tmp_path):
    write_json(tmp_path / "preflight.json", {"status": "ready_for_live_test"})
    write_json(tmp_path / "video_workflow_preflight.json", {"status": "ready_for_live_test"})
    write_json(tmp_path / "render.json", rendered_cases("discovery"))
    write_json(tmp_path / "video_review.json", passed_video_review())
    write_json(tmp_path / "seed_dance_baseline_comparison.json", {"status": "needs_review"})
    write_json(tmp_path / "manual_review.json", {
        "cases": [{"id": "discovery", "score": 4.5, "decision": "accept"}]
    })

    report = validator.summarize_validation(tmp_path)

    assert report["status"] == "partial_needs_review"
    assert report["checks"]["baseline_comparison_passed"] is False
    assert any("Seed Dance baseline comparison passes" in item for item in report["action_items"])


def test_validation_summary_blocks_low_video_identity_gate(tmp_path):
    write_json(tmp_path / "preflight.json", {"status": "ready_for_live_test"})
    write_json(tmp_path / "video_workflow_preflight.json", {"status": "ready_for_live_test"})
    write_json(tmp_path / "render.json", rendered_cases("discovery"))
    write_json(tmp_path / "seed_dance_baseline_comparison.json", {"status": "passed"})
    write_json(tmp_path / "video_review.json", {
        "status": "passed",
        "batches": [{
            "review": {
                "facial_identity": {"score": 3, "evidence": "face drift"},
                "identity_consistency": {"score": 4, "evidence": "wardrobe stable"},
                "temporal_consistency": {"score": 4, "evidence": "motion stable"},
            }
        }],
    })
    write_json(tmp_path / "manual_review.json", {
        "cases": [{"id": "discovery", "score": 4.5, "decision": "accept"}]
    })

    report = validator.summarize_validation(tmp_path)

    assert report["status"] == "partial_needs_review"
    assert report["checks"]["video_review_passed"] is False
    assert report["checks"]["video_identity_gate_passed"] is False
    assert any("identity/temporal gates" in item for item in report["action_items"])


def test_validation_summary_recommends_targeted_calibration(tmp_path):
    write_json(tmp_path / "preflight.json", {"status": "ready_for_live_test"})
    write_json(tmp_path / "video_workflow_preflight.json", {"status": "ready_for_live_test"})
    write_json(tmp_path / "render.json", rendered_cases("discovery"))
    write_json(tmp_path / "seed_dance_baseline_comparison.json", {"status": "passed"})
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


def test_acceptance_package_writes_json_and_markdown(tmp_path):
    write_json(tmp_path / "preflight.json", {"status": "ready_for_live_test"})
    write_json(tmp_path / "video_workflow_preflight.json", {"status": "ready_for_live_test"})
    write_json(tmp_path / "render.json", rendered_cases("discovery", "reaction"))
    write_json(tmp_path / "video_review.json", passed_video_review())
    write_json(tmp_path / "seed_dance_baseline_comparison.json", {"status": "passed", "score": 4.2})
    write_json(tmp_path / "manual_review.json", {
        "cases": [
            {"id": "discovery", "score": 4.5, "decision": "accept", "note": "face stable"},
            {"id": "reaction", "score": 4.0, "decision": "accept", "note": "composition OK"},
        ]
    })

    package = validator.build_acceptance_package(tmp_path)

    assert package["status"] == "ready_for_seed_dance_candidate"
    assert package["required_status"] == "ready_for_seed_dance_candidate"
    assert package["manual_review"]["missing_case_ids"] == []
    assert [case["id"] for case in package["manual_review"]["cases"]] == ["discovery", "reaction"]
    assert package["evidence_files"]["render"]["present"] is True
    assert (tmp_path / "acceptance_package.json").is_file()
    markdown = (tmp_path / "acceptance_package.md").read_text(encoding="utf-8")
    assert "Local Generation Acceptance Package" in markdown
    assert "discovery" in markdown
    assert "ready_for_seed_dance_candidate" in markdown


def test_acceptance_package_surfaces_missing_manual_review_and_setup_actions(tmp_path):
    write_json(tmp_path / "preflight.json", {"status": "ready_for_live_test"})
    write_json(tmp_path / "video_workflow_preflight.json", {"status": "ready_for_live_test"})
    write_json(tmp_path / "render.json", rendered_cases("discovery", "reaction"))
    write_json(tmp_path / "video_review.json", {
        **passed_video_review(),
        "repair_queue": [
            {"action": "regenerate_turnaround_album", "execution": "setup_required", "reason": "identity drift"}
        ],
    })
    write_json(tmp_path / "seed_dance_baseline_comparison.json", {"status": "passed"})
    write_json(tmp_path / "manual_review.json", {
        "cases": [{"id": "discovery", "score": 4.5, "decision": "accept"}]
    })

    package = validator.build_acceptance_package(tmp_path)

    assert package["status"] == "partial_needs_review"
    assert package["manual_review"]["missing_case_ids"] == ["reaction"]
    assert package["repair_queue"][0]["execution"] == "setup_required"
    assert any("missing rendered cases" in item for item in package["blocking_action_items"])
    assert any("setup-required" in item for item in package["blocking_action_items"])
