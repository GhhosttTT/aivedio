import json

from scripts import validate_local_generation as validator
from src.services import video_engine_preflight


def write_json(path, payload):
    path.write_text(json.dumps(payload), encoding="utf-8")


def rendered_cases(*ids, render_profile=None):
    return {
        "status": "rendered_pending_human_review",
        "render_profile": render_profile or {
            "quality_mode": "ultra",
            "optimization_mode": "quality",
            "prompt_optimization": True,
            "parameter_optimization": True,
        },
        "cases": [
            {
                "id": item,
                "image": f"{item}.png",
                "actual_workflow": {"steps": 45, "cfg": 7.0, "sampler_name": "dpmpp_2m"},
            }
            for item in ids
        ],
    }


def passed_video_review():
    return {
        "status": "passed",
        "batches": [{
            "platform_score": 4.2,
            "review": {
                "story_match": {"score": 4, "evidence": "scene matches"},
                "composition": {"score": 4, "evidence": "framing is usable"},
                "aesthetic_quality": {"score": 4, "evidence": "commercial short-drama look"},
                "visual_integrity": {"score": 4, "evidence": "no broken anatomy"},
                "facial_identity": {"score": 4, "evidence": "face matches"},
                "identity_consistency": {"score": 4, "evidence": "identity stable"},
                "temporal_consistency": {"score": 4, "evidence": "motion stable"},
            }
        }],
    }


def passed_image_review(*ids):
    return {
        "status": "passed",
        "cases": [
            {
                "id": item,
                "status": "passed",
                "average": 4.4,
                "platform_score": 4.3,
                "review": {
                    "facial_identity": {"score": 4, "evidence": "face matches"},
                    "identity_consistency": {"score": 4, "evidence": "wardrobe stable"},
                },
                "platform_aesthetic_gate": {
                    "status": "passed",
                    "scores": {},
                    "low": {},
                    "missing": [],
                },
            }
            for item in ids
        ],
    }


def test_review_models_endpoint_uses_llama_cpp_openai_contract(monkeypatch):
    monkeypatch.setattr(validator.settings, "LOCAL_REVIEW_BASE_URL", "http://127.0.0.1:8080")

    assert validator._review_models_endpoint() == "http://127.0.0.1:8080/v1/models"


def test_default_validation_cases_carry_scene_review_context():
    cases = json.loads((validator.Path("examples") / "local_generation_cases.json").read_text(encoding="utf-8"))

    assert cases
    assert all(case.get("scene", {}).get("scene_number") for case in cases)
    assert all(case.get("scene", {}).get("visual_description") for case in cases)
    assert all(case.get("scene", {}).get("reference_requirements") for case in cases)
    character_cases = [
        case for case in cases
        if case["id"] in {"discovery", "reaction", "reverse_shot", "stylized"}
    ]
    assert all(case["scene"]["visible_characters"] for case in character_cases)
    assert any(case["scene"]["visible_characters"][0]["name"] == "Victor" for case in character_cases)


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


def test_render_images_uses_production_quality_profile(tmp_path, monkeypatch):
    calls = []

    class FakeClient:
        def close(self):
            return None

    class FakeComfyUIService:
        def __init__(self, *args, **kwargs):
            self.client = FakeClient()

        def generate_image(self, **kwargs):
            calls.append(kwargs)
            path = tmp_path / "rendered.png"
            path.write_bytes(b"image")
            (tmp_path / "rendered.workflow.json").write_text(json.dumps({
                "8": {"class_type": "KSampler", "inputs": {"steps": 45, "cfg": 7.0, "seed": 123}},
                "7": {"class_type": "EmptyLatentImage", "inputs": {"width": 1344, "height": 768}},
            }), encoding="utf-8")
            return str(path)

    monkeypatch.setattr(validator, "ComfyUIService", FakeComfyUIService)

    report = validator.render_images(
        [{
            "id": "case_1",
            "prompt": "woman reads a letter in a cinematic office",
            "seed": 123,
            "reference_image": "alice_front.png",
            "scene": {
                "scene_number": 3,
                "visual_description": "Alice reads a letter in a cinematic office",
                "visible_characters": [{"name": "Alice", "appearance": "Alice identity"}],
            },
        }],
        tmp_path,
    )

    assert report["status"] == "rendered_pending_human_review"
    assert calls[0]["reference_image"] == "alice_front.png"
    assert calls[0]["use_ipadapter"] is True
    assert calls[0]["quality_mode"] == "ultra"
    assert calls[0]["optimization_mode"] == "quality"
    assert calls[0]["enable_prompt_optimization"] is True
    assert calls[0]["enable_parameter_optimization"] is True
    assert report["render_profile"]["quality_mode"] == "ultra"
    assert report["cases"][0]["source_prompt"] == "woman reads a letter in a cinematic office"
    assert report["cases"][0]["scene"]["scene_number"] == 3
    assert report["cases"][0]["scene"]["visible_characters"][0]["name"] == "Alice"
    assert report["cases"][0]["actual_workflow"]["steps"] == 45
    assert report["cases"][0]["request"]["quality_mode"] == "ultra"
    assert report["cases"][0]["request"]["reference_image"] == "alice_front.png"
    assert report["cases"][0]["request"]["enable_parameter_optimization"] is True


def test_review_images_builds_repair_queue_for_failed_keyframes(tmp_path, monkeypatch):
    write_json(tmp_path / "render.json", {
        "status": "rendered_pending_human_review",
        "cases": [{
            "id": "discovery",
            "image": "discovery.png",
            "prompt": "Alice reacts in a premium office",
            "scene": {"scene_number": 7, "visual_description": "Alice reacts in a premium office"},
        }],
    })

    class FakeSelector:
        def review_candidate(self, index, image_path, scene, prompt, reference=None):
            return {
                "index": index,
                "path": str(image_path),
                "status": "passed",
                "average": 4.4,
                "platform_score": 3.0,
                "review": {
                    "facial_identity": {"score": 4, "evidence": "face matches"},
                    "identity_consistency": {"score": 4, "evidence": "wardrobe stable"},
                },
                "platform_aesthetic_gate": {
                    "status": "needs_review",
                    "low": {
                        "skin_texture": {"score": 2, "evidence": "plastic skin"},
                    },
                },
            }

    monkeypatch.setattr(validator, "ImageQualitySelector", lambda: FakeSelector())

    report = validator.review_images(tmp_path)

    assert report["status"] == "needs_review"
    assert report["repair_queue"][0]["action"] == "refine_prompt_composition"
    assert report["repair_queue"][0]["scene_number"] == 7


def test_review_images_uses_per_case_reference_and_scene_contract(tmp_path, monkeypatch):
    write_json(tmp_path / "render.json", {
        "status": "rendered_pending_human_review",
        "cases": [{
            "id": "side_profile",
            "image": "side_profile.png",
            "prompt": "Alice side profile in a premium office",
            "scene": {
                "scene_number": 4,
                "visual_description": "Alice side profile in a premium office",
                "turnaround_view": "side",
                "turnaround_expected_features": {"nose_silhouette": "straight nose bridge"},
                "visible_characters": [{"name": "Alice", "appearance": "Alice identity"}],
            },
            "request": {"reference_image": "alice_side.png"},
        }],
    })

    class FakeSelector:
        def review_candidate(self, index, image_path, scene, prompt, reference=None):
            assert reference == "alice_side.png"
            assert scene["turnaround_view"] == "side"
            assert scene["turnaround_expected_features"]["nose_silhouette"] == "straight nose bridge"
            assert scene["visible_characters"][0]["name"] == "Alice"
            return {
                "index": index,
                "path": str(image_path),
                "status": "passed",
                "average": 4.4,
                "platform_score": 4.2,
                "review": {
                    "facial_identity": {"score": 4, "evidence": "profile matches"},
                    "identity_consistency": {"score": 4, "evidence": "wardrobe stable"},
                },
                "platform_aesthetic_gate": {"status": "passed", "low": {}, "missing": []},
            }

    monkeypatch.setattr(validator, "ImageQualitySelector", lambda: FakeSelector())

    report = validator.review_images(tmp_path)

    assert report["status"] == "passed"
    assert report["repair_queue"] == []


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
    write_json(tmp_path / "image_review.json", passed_image_review("discovery", "reaction"))
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
    assert report["checks"]["video_platform_gate_passed"] is True
    assert report["checks"]["render_profile_passed"] is True
    assert report["checks"]["render_workflow_parameters_passed"] is True
    assert report["checks"]["image_review_passed"] is True
    assert report["checks"]["manual_review_covers_rendered_cases"] is True
    assert report["action_items"] == []


def test_validation_summary_requires_image_review(tmp_path):
    write_json(tmp_path / "preflight.json", {"status": "ready_for_live_test"})
    write_json(tmp_path / "video_workflow_preflight.json", {"status": "ready_for_live_test"})
    write_json(tmp_path / "render.json", rendered_cases("discovery"))
    write_json(tmp_path / "video_review.json", passed_video_review())
    write_json(tmp_path / "seed_dance_baseline_comparison.json", {"status": "passed"})
    write_json(tmp_path / "manual_review.json", {
        "cases": [{"id": "discovery", "score": 4.5, "decision": "accept"}]
    })

    report = validator.summarize_validation(tmp_path)

    assert report["status"] == "partial_needs_review"
    assert report["checks"]["image_review_present"] is False
    assert any("review-images" in item for item in report["action_items"])


def test_validation_summary_blocks_failed_image_review(tmp_path):
    write_json(tmp_path / "preflight.json", {"status": "ready_for_live_test"})
    write_json(tmp_path / "video_workflow_preflight.json", {"status": "ready_for_live_test"})
    write_json(tmp_path / "render.json", rendered_cases("discovery"))
    write_json(tmp_path / "image_review.json", {
        "status": "needs_review",
        "cases": [{
            "id": "discovery",
            "status": "passed",
            "average": 4.6,
            "platform_score": 3.2,
            "review": {
                "facial_identity": {"score": 4, "evidence": "face matches"},
                "identity_consistency": {"score": 4, "evidence": "wardrobe stable"},
            },
            "platform_aesthetic_gate": {
                "status": "needs_review",
                "low": {"skin_texture": {"score": 2, "evidence": "plastic skin"}},
            },
        }],
    })
    write_json(tmp_path / "video_review.json", passed_video_review())
    write_json(tmp_path / "seed_dance_baseline_comparison.json", {"status": "passed"})
    write_json(tmp_path / "manual_review.json", {
        "cases": [{"id": "discovery", "score": 4.5, "decision": "accept"}]
    })

    report = validator.summarize_validation(tmp_path)

    assert report["status"] == "partial_needs_review"
    assert report["checks"]["image_review_passed"] is False
    assert any("image VLM review passes" in item for item in report["action_items"])


def test_validation_summary_blocks_non_production_render_profile(tmp_path):
    write_json(tmp_path / "preflight.json", {"status": "ready_for_live_test"})
    write_json(tmp_path / "video_workflow_preflight.json", {"status": "ready_for_live_test"})
    write_json(tmp_path / "render.json", rendered_cases(
        "discovery",
        render_profile={
            "quality_mode": "normal",
            "optimization_mode": "balanced",
            "prompt_optimization": False,
            "parameter_optimization": False,
        },
    ))
    write_json(tmp_path / "image_review.json", passed_image_review("discovery"))
    write_json(tmp_path / "video_review.json", passed_video_review())
    write_json(tmp_path / "seed_dance_baseline_comparison.json", {"status": "passed"})
    write_json(tmp_path / "manual_review.json", {
        "cases": [{"id": "discovery", "score": 4.5, "decision": "accept"}]
    })

    report = validator.summarize_validation(tmp_path)

    assert report["status"] == "partial_needs_review"
    assert report["checks"]["render_profile_passed"] is False
    assert any("--quality-mode ultra" in item for item in report["action_items"])


def test_validation_summary_blocks_missing_actual_workflow_parameters(tmp_path):
    write_json(tmp_path / "preflight.json", {"status": "ready_for_live_test"})
    write_json(tmp_path / "video_workflow_preflight.json", {"status": "ready_for_live_test"})
    render = rendered_cases("discovery")
    render["cases"][0].pop("actual_workflow")
    write_json(tmp_path / "render.json", render)
    write_json(tmp_path / "image_review.json", passed_image_review("discovery"))
    write_json(tmp_path / "video_review.json", passed_video_review())
    write_json(tmp_path / "seed_dance_baseline_comparison.json", {"status": "passed"})
    write_json(tmp_path / "manual_review.json", {
        "cases": [{"id": "discovery", "score": 4.5, "decision": "accept"}]
    })

    report = validator.summarize_validation(tmp_path)

    assert report["status"] == "partial_needs_review"
    assert report["checks"]["render_workflow_parameters_passed"] is False
    assert any("actual ComfyUI workflow steps" in item for item in report["action_items"])


def test_validation_summary_requires_manual_review_for_every_rendered_case(tmp_path):
    write_json(tmp_path / "preflight.json", {"status": "ready_for_live_test"})
    write_json(tmp_path / "video_workflow_preflight.json", {"status": "ready_for_live_test"})
    write_json(tmp_path / "render.json", rendered_cases("discovery", "reaction"))
    write_json(tmp_path / "image_review.json", passed_image_review("discovery", "reaction"))
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
    write_json(tmp_path / "image_review.json", passed_image_review("discovery"))
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
    write_json(tmp_path / "image_review.json", passed_image_review("discovery"))
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
    write_json(tmp_path / "image_review.json", passed_image_review("discovery"))
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
    assert any("identity/temporal/platform gates" in item for item in report["action_items"])


def test_validation_summary_recommends_targeted_calibration(tmp_path):
    write_json(tmp_path / "preflight.json", {"status": "ready_for_live_test"})
    write_json(tmp_path / "video_workflow_preflight.json", {"status": "ready_for_live_test"})
    write_json(tmp_path / "render.json", rendered_cases("discovery"))
    write_json(tmp_path / "image_review.json", passed_image_review("discovery"))
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
    write_json(tmp_path / "image_review.json", passed_image_review("discovery", "reaction"))
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
    assert package["evidence_files"]["image_review"]["present"] is True
    assert (tmp_path / "acceptance_package.json").is_file()
    markdown = (tmp_path / "acceptance_package.md").read_text(encoding="utf-8")
    assert "Local Generation Acceptance Package" in markdown
    assert "discovery" in markdown
    assert "ready_for_seed_dance_candidate" in markdown


def test_acceptance_package_surfaces_missing_manual_review_and_setup_actions(tmp_path):
    write_json(tmp_path / "preflight.json", {"status": "ready_for_live_test"})
    write_json(tmp_path / "video_workflow_preflight.json", {"status": "ready_for_live_test"})
    write_json(tmp_path / "render.json", rendered_cases("discovery", "reaction"))
    write_json(tmp_path / "image_review.json", passed_image_review("discovery", "reaction"))
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
