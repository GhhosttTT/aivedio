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
            "video_aesthetic_gate": {
                "status": "passed",
                "average": 4.2,
                "missing": [],
                "low": {},
            },
            "character_distinctiveness_gate": {
                "status": "passed",
                "average": 4.2,
                "missing": [],
                "low": {},
            },
            "video_performance_gate": {
                "status": "passed",
                "average": 4.2,
                "missing": [],
                "low": {},
            },
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


def passed_seed_dance_baseline(tmp_path):
    contact_sheet = tmp_path / "seed_dance_contact_sheet.png"
    contact_sheet.write_bytes(b"visual comparison evidence")
    return {"status": "passed", "score": 4.2, "contact_sheet_path": str(contact_sheet)}


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


def passed_manual_review(*ids):
    return {
        "cases": [
            {"id": item, "score": 4.5 if index == 0 else 4.0, "decision": "accept", "note": "case passes human review"}
            for index, item in enumerate(ids)
        ],
        "clip": {
            "score": 4.3,
            "decision": "accept",
            "watched_full_clip": True,
            "watched_seed_dance_contact_sheet": True,
            "note": "full clip is stable enough for candidate review",
        },
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


def test_render_images_applies_repair_action_constraints(tmp_path, monkeypatch):
    calls = []

    class FakeClient:
        def close(self):
            return None

    class FakeComfyUIService:
        def __init__(self, *args, **kwargs):
            self.client = FakeClient()

        def generate_image(self, **kwargs):
            calls.append(kwargs)
            path = tmp_path / "repair.png"
            path.write_bytes(b"image")
            (tmp_path / "repair.workflow.json").write_text(json.dumps({
                "8": {"class_type": "KSampler", "inputs": {"steps": kwargs["steps"], "cfg": kwargs["cfg_scale"], "seed": 321}},
            }), encoding="utf-8")
            return str(path)

    monkeypatch.setattr(validator, "ComfyUIService", FakeComfyUIService)
    monkeypatch.setattr(validator.settings, "GENERATION_STEP_VARIATION", 0)
    monkeypatch.setattr(validator.settings, "GENERATION_CFG_VARIATION", 0)

    report = validator.render_images(
        [{"id": "face", "prompt": "premium short drama close-up", "seed": 321}],
        tmp_path,
        repair_action="refine_face_aesthetic_detail",
    )

    assert report["status"] == "rendered_pending_human_review"
    assert calls[0]["steps"] == validator.settings.GENERATION_STEPS + 12
    assert calls[0]["cfg_scale"] == round(validator.settings.GENERATION_CFG - 0.35, 2)
    assert "natural skin texture" in calls[0]["prompt"]
    assert "plastic skin" in calls[0]["negative_prompt"]
    assert report["render_profile"]["repair_action"] == "refine_face_aesthetic_detail"
    assert report["cases"][0]["request"]["repair_action"] == "refine_face_aesthetic_detail"
    assert report["cases"][0]["request"]["repair_parameter_profile"]["reason"] == "face_aesthetic_detail_repair"


def test_render_images_can_target_one_scene_number(tmp_path, monkeypatch):
    calls = []

    class FakeClient:
        def close(self):
            return None

    class FakeComfyUIService:
        def __init__(self, *args, **kwargs):
            self.client = FakeClient()

        def generate_image(self, **kwargs):
            calls.append(kwargs)
            path = tmp_path / f"rendered_{len(calls)}.png"
            path.write_bytes(b"image")
            return str(path)

    monkeypatch.setattr(validator, "ComfyUIService", FakeComfyUIService)

    report = validator.render_images(
        [
            {"id": "first", "prompt": "first scene", "seed": 1, "scene": {"scene_number": 1}},
            {"id": "second", "prompt": "second scene", "seed": 2, "scene": {"scene_number": 2}},
        ],
        tmp_path,
        repair_action="refine_prompt_composition",
        scene_number=2,
    )

    assert report["status"] == "rendered_pending_human_review"
    assert len(calls) == 1
    assert report["render_profile"]["target_scene_number"] == 2
    assert report["cases"][0]["id"] == "second"
    assert report["cases"][0]["request"]["repair_action"] == "refine_prompt_composition"
    assert report["skipped_cases"] == [{
        "id": "first",
        "scene_number": 1,
        "reason": "scene_number_filter",
    }]


def test_render_images_reports_error_when_scene_filter_matches_nothing(tmp_path, monkeypatch):
    class FakeClient:
        def close(self):
            return None

    class FakeComfyUIService:
        def __init__(self, *args, **kwargs):
            self.client = FakeClient()

        def generate_image(self, **_kwargs):
            raise AssertionError("generate_image should not be called")

    monkeypatch.setattr(validator, "ComfyUIService", FakeComfyUIService)

    report = validator.render_images(
        [{"id": "first", "prompt": "first scene", "seed": 1, "scene": {"scene_number": 1}}],
        tmp_path,
        scene_number=9,
    )

    assert report["status"] == "error"
    assert "scene_number=9" in report["error"]
    assert report["cases"] == []


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
    assert report["repair_queue"][0]["action"] == "refine_face_aesthetic_detail"
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
    write_json(tmp_path / "seed_dance_baseline_comparison.json", passed_seed_dance_baseline(tmp_path))

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
    write_json(tmp_path / "seed_dance_baseline_comparison.json", passed_seed_dance_baseline(tmp_path))
    write_json(tmp_path / "manual_review.json", passed_manual_review("discovery", "reaction"))

    report = validator.summarize_validation(tmp_path)

    assert report["status"] == "ready_for_seed_dance_candidate"
    assert report["checks"]["manual_average_score"] == 4.25
    assert report["checks"]["baseline_comparison_passed"] is True
    assert report["checks"]["baseline_contact_sheet_present"] is True
    assert report["checks"]["video_identity_gate_passed"] is True
    assert report["checks"]["video_temporal_gate_passed"] is True
    assert report["checks"]["video_platform_gate_passed"] is True
    assert report["checks"]["video_aesthetic_gate_passed"] is True
    assert report["checks"]["video_character_distinctiveness_gate_passed"] is True
    assert report["checks"]["render_profile_passed"] is True
    assert report["checks"]["render_workflow_parameters_passed"] is True
    assert report["checks"]["image_review_passed"] is True
    assert report["checks"]["image_review_covers_rendered_cases"] is True
    assert report["checks"]["image_review_missing_case_ids"] == []
    assert report["checks"]["manual_review_covers_rendered_cases"] is True
    assert report["checks"]["manual_clip_review_passed"] is True
    assert report["checks"]["manual_blocking_issues_passed"] is True
    assert report["checks"]["repair_queue_empty"] is True
    assert report["action_items"] == []


def test_validation_summary_requires_image_review(tmp_path):
    write_json(tmp_path / "preflight.json", {"status": "ready_for_live_test"})
    write_json(tmp_path / "video_workflow_preflight.json", {"status": "ready_for_live_test"})
    write_json(tmp_path / "render.json", rendered_cases("discovery"))
    write_json(tmp_path / "video_review.json", passed_video_review())
    write_json(tmp_path / "seed_dance_baseline_comparison.json", passed_seed_dance_baseline(tmp_path))
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
    write_json(tmp_path / "seed_dance_baseline_comparison.json", passed_seed_dance_baseline(tmp_path))
    write_json(tmp_path / "manual_review.json", {
        "cases": [{"id": "discovery", "score": 4.5, "decision": "accept"}]
    })

    report = validator.summarize_validation(tmp_path)

    assert report["status"] == "partial_needs_review"
    assert report["checks"]["image_review_passed"] is False
    assert any("image VLM review passes" in item for item in report["action_items"])


def test_validation_summary_requires_image_review_for_every_rendered_case(tmp_path):
    write_json(tmp_path / "preflight.json", {"status": "ready_for_live_test"})
    write_json(tmp_path / "video_workflow_preflight.json", {"status": "ready_for_live_test"})
    write_json(tmp_path / "render.json", rendered_cases("discovery", "reaction"))
    write_json(tmp_path / "image_review.json", passed_image_review("discovery"))
    write_json(tmp_path / "video_review.json", passed_video_review())
    write_json(tmp_path / "seed_dance_baseline_comparison.json", passed_seed_dance_baseline(tmp_path))
    write_json(tmp_path / "manual_review.json", {
        "cases": [
            {"id": "discovery", "score": 4.5, "decision": "accept"},
            {"id": "reaction", "score": 4.0, "decision": "accept"},
        ]
    })

    report = validator.summarize_validation(tmp_path)

    assert report["status"] == "partial_needs_review"
    assert report["checks"]["image_review_passed"] is False
    assert report["checks"]["image_review_covers_rendered_cases"] is False
    assert report["checks"]["image_review_missing_case_ids"] == ["reaction"]
    assert any("review-images" in item and "reaction" in item for item in report["action_items"])


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
    write_json(tmp_path / "seed_dance_baseline_comparison.json", passed_seed_dance_baseline(tmp_path))
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
    write_json(tmp_path / "seed_dance_baseline_comparison.json", passed_seed_dance_baseline(tmp_path))
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
    write_json(tmp_path / "seed_dance_baseline_comparison.json", passed_seed_dance_baseline(tmp_path))
    write_json(tmp_path / "manual_review.json", {
        "cases": [{"id": "discovery", "score": 4.5, "decision": "accept"}]
    })

    report = validator.summarize_validation(tmp_path)

    assert report["status"] == "partial_needs_review"
    assert report["checks"]["manual_review_covers_rendered_cases"] is False
    assert report["checks"]["manual_review_missing_case_ids"] == ["reaction"]
    assert any("reaction" in item for item in report["action_items"])


def test_validation_summary_requires_manual_clip_review(tmp_path):
    write_json(tmp_path / "preflight.json", {"status": "ready_for_live_test"})
    write_json(tmp_path / "video_workflow_preflight.json", {"status": "ready_for_live_test"})
    write_json(tmp_path / "render.json", rendered_cases("discovery", "reaction"))
    write_json(tmp_path / "image_review.json", passed_image_review("discovery", "reaction"))
    write_json(tmp_path / "video_review.json", passed_video_review())
    write_json(tmp_path / "seed_dance_baseline_comparison.json", passed_seed_dance_baseline(tmp_path))
    write_json(tmp_path / "manual_review.json", {
        "cases": [
            {"id": "discovery", "score": 4.5, "decision": "accept"},
            {"id": "reaction", "score": 4.0, "decision": "accept"},
        ]
    })

    report = validator.summarize_validation(tmp_path)

    assert report["status"] == "partial_needs_review"
    assert report["checks"]["manual_review_covers_rendered_cases"] is True
    assert report["checks"]["manual_clip_review_present"] is False
    assert report["checks"]["manual_clip_review_passed"] is False
    assert report["checks"]["manual_review_passed"] is False
    assert any("full generated clip" in item for item in report["action_items"])


def test_validation_summary_blocks_unresolved_repair_queue(tmp_path):
    write_json(tmp_path / "preflight.json", {"status": "ready_for_live_test"})
    write_json(tmp_path / "video_workflow_preflight.json", {"status": "ready_for_live_test"})
    write_json(tmp_path / "render.json", rendered_cases("discovery"))
    image_review = passed_image_review("discovery")
    image_review["repair_queue"] = [{
        "action": "regenerate_character_identity",
        "execution": "setup_required",
        "reason": "face identity needs stronger anchor",
    }]
    write_json(tmp_path / "image_review.json", image_review)
    write_json(tmp_path / "video_review.json", passed_video_review())
    write_json(tmp_path / "seed_dance_baseline_comparison.json", passed_seed_dance_baseline(tmp_path))
    write_json(tmp_path / "manual_review.json", passed_manual_review("discovery"))

    report = validator.summarize_validation(tmp_path)

    assert report["status"] == "partial_needs_review"
    assert report["checks"]["repair_queue_empty"] is False
    assert report["repair_queue"][0]["action"] == "regenerate_character_identity"
    assert any("repair_queue" in item for item in report["action_items"])


def test_validation_summary_blocks_manual_issue_tags_even_with_passing_scores(tmp_path):
    manual_review = passed_manual_review("discovery")
    manual_review["cases"][0]["issue_tags"] = ["identity drift"]
    write_json(tmp_path / "preflight.json", {"status": "ready_for_live_test"})
    write_json(tmp_path / "video_workflow_preflight.json", {"status": "ready_for_live_test"})
    write_json(tmp_path / "render.json", rendered_cases("discovery"))
    write_json(tmp_path / "image_review.json", passed_image_review("discovery"))
    write_json(tmp_path / "video_review.json", passed_video_review())
    write_json(tmp_path / "seed_dance_baseline_comparison.json", passed_seed_dance_baseline(tmp_path))
    write_json(tmp_path / "manual_review.json", manual_review)

    report = validator.summarize_validation(tmp_path)

    assert report["status"] == "partial_needs_review"
    assert report["checks"]["manual_blocking_issues_passed"] is False
    assert report["checks"]["manual_review_passed"] is False
    assert report["checks"]["manual_blocking_issues"] == [{
        "id": "discovery",
        "blocking_issues": ["identity drift"],
    }]
    assert any("manual blocking issues" in item for item in report["action_items"])


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


def test_validation_summary_requires_seed_dance_contact_sheet(tmp_path):
    write_json(tmp_path / "preflight.json", {"status": "ready_for_live_test"})
    write_json(tmp_path / "video_workflow_preflight.json", {"status": "ready_for_live_test"})
    write_json(tmp_path / "render.json", rendered_cases("discovery"))
    write_json(tmp_path / "image_review.json", passed_image_review("discovery"))
    write_json(tmp_path / "video_review.json", passed_video_review())
    write_json(tmp_path / "seed_dance_baseline_comparison.json", {
        "status": "passed",
        "contact_sheet_path": str(tmp_path / "missing_contact_sheet.png"),
    })
    write_json(tmp_path / "manual_review.json", {
        "cases": [{"id": "discovery", "score": 4.5, "decision": "accept"}]
    })

    report = validator.summarize_validation(tmp_path)

    assert report["status"] == "partial_needs_review"
    assert report["checks"]["baseline_contact_sheet_present"] is False
    assert report["checks"]["baseline_comparison_passed"] is False
    assert any("seed_dance_contact_sheet.png" in item for item in report["action_items"])


def test_validation_summary_requires_video_aesthetic_gate(tmp_path):
    write_json(tmp_path / "preflight.json", {"status": "ready_for_live_test"})
    write_json(tmp_path / "video_workflow_preflight.json", {"status": "ready_for_live_test"})
    write_json(tmp_path / "render.json", rendered_cases("discovery"))
    write_json(tmp_path / "image_review.json", passed_image_review("discovery"))
    write_json(tmp_path / "seed_dance_baseline_comparison.json", passed_seed_dance_baseline(tmp_path))
    video_review = passed_video_review()
    video_review["batches"][0].pop("video_aesthetic_gate")
    write_json(tmp_path / "video_review.json", video_review)
    write_json(tmp_path / "manual_review.json", {
        "cases": [{"id": "discovery", "score": 4.5, "decision": "accept"}]
    })

    report = validator.summarize_validation(tmp_path)

    assert report["status"] == "partial_needs_review"
    assert report["checks"]["video_aesthetic_gate_passed"] is False
    assert report["checks"]["video_review_passed"] is False
    assert any("aesthetic/character-distinctiveness/performance gates" in item for item in report["action_items"])


def test_validation_summary_requires_video_character_distinctiveness_gate_when_present(tmp_path):
    write_json(tmp_path / "preflight.json", {"status": "ready_for_live_test"})
    write_json(tmp_path / "video_workflow_preflight.json", {"status": "ready_for_live_test"})
    write_json(tmp_path / "render.json", rendered_cases("discovery"))
    write_json(tmp_path / "image_review.json", passed_image_review("discovery"))
    write_json(tmp_path / "seed_dance_baseline_comparison.json", passed_seed_dance_baseline(tmp_path))
    video_review = passed_video_review()
    video_review["batches"][0]["character_distinctiveness_gate"] = {
        "status": "needs_review",
        "average": 3.2,
        "missing": [],
        "low": {
            "no_same_face_casting": {"score": 2, "evidence": "two roles share the same face"},
        },
    }
    write_json(tmp_path / "video_review.json", video_review)
    write_json(tmp_path / "manual_review.json", passed_manual_review("discovery"))

    report = validator.summarize_validation(tmp_path)

    assert report["status"] == "partial_needs_review"
    assert report["checks"]["video_character_distinctiveness_gate_passed"] is False
    assert report["checks"]["video_review_passed"] is False
    assert any("character-distinctiveness" in item for item in report["action_items"])


def test_validation_summary_requires_video_performance_gate(tmp_path):
    write_json(tmp_path / "preflight.json", {"status": "ready_for_live_test"})
    write_json(tmp_path / "video_workflow_preflight.json", {"status": "ready_for_live_test"})
    write_json(tmp_path / "render.json", rendered_cases("discovery"))
    write_json(tmp_path / "image_review.json", passed_image_review("discovery"))
    write_json(tmp_path / "seed_dance_baseline_comparison.json", passed_seed_dance_baseline(tmp_path))
    video_review = passed_video_review()
    video_review["batches"][0].pop("video_performance_gate")
    write_json(tmp_path / "video_review.json", video_review)
    write_json(tmp_path / "manual_review.json", passed_manual_review("discovery"))

    report = validator.summarize_validation(tmp_path)

    assert report["status"] == "partial_needs_review"
    assert report["checks"]["video_performance_gate_passed"] is False
    assert report["checks"]["video_review_passed"] is False
    assert any("performance gates" in item for item in report["action_items"])


def test_validation_summary_blocks_failed_final_normalized_video_review(tmp_path):
    write_json(tmp_path / "preflight.json", {"status": "ready_for_live_test"})
    write_json(tmp_path / "video_workflow_preflight.json", {"status": "ready_for_live_test"})
    write_json(tmp_path / "render.json", rendered_cases("discovery"))
    write_json(tmp_path / "image_review.json", passed_image_review("discovery"))
    write_json(tmp_path / "video_review.json", passed_video_review())
    write_json(tmp_path / "seed_dance_baseline_comparison.json", passed_seed_dance_baseline(tmp_path))
    write_json(tmp_path / "manual_review.json", passed_manual_review("discovery"))
    write_json(tmp_path / "scene_1.quality.json", {
        "status": "needs_review",
        "final_video_review": {
            "status": "needs_review",
            "average": 2.8,
            "scene": {"scene_number": 1},
            "gate_scores": {
                "facial_identity": 5,
                "identity_consistency": 5,
                "temporal_consistency": 2,
            },
            "platform_score": 4.2,
            "video_aesthetic_gate": {
                "status": "needs_review",
                "low": {"motion_smoothness": {"score": 2, "evidence": "clip stutters after normalization"}},
                "missing": [],
            },
        },
        "repair_queue": [{
            "scene_number": 1,
            "action": "lower_motion_and_regenerate_video",
            "execution": "auto",
            "reason": "clip stutters after normalization",
        }],
    })

    report = validator.summarize_validation(tmp_path)

    assert report["status"] == "partial_needs_review"
    assert report["checks"]["final_normalized_video_review_count"] == 1
    assert report["checks"]["final_normalized_video_review_passed"] is False
    assert report["checks"]["video_review_passed"] is False
    assert report["repair_queue"][0]["action"] == "lower_motion_and_regenerate_video"
    assert any("final normalized video review" in item for item in report["action_items"])


def test_validation_summary_blocks_failed_final_composition_review(tmp_path):
    write_json(tmp_path / "preflight.json", {"status": "ready_for_live_test"})
    write_json(tmp_path / "video_workflow_preflight.json", {"status": "ready_for_live_test"})
    write_json(tmp_path / "render.json", rendered_cases("discovery"))
    write_json(tmp_path / "image_review.json", passed_image_review("discovery"))
    write_json(tmp_path / "video_review.json", passed_video_review())
    write_json(tmp_path / "seed_dance_baseline_comparison.json", passed_seed_dance_baseline(tmp_path))
    write_json(tmp_path / "manual_review.json", passed_manual_review("discovery"))
    write_json(tmp_path / "final.composition_review.json", {
        "status": "needs_review",
        "average": 3.1,
        "stage": "final_composition",
        "error": "composition review batch 1 performance gate failed",
        "batches": [{
            "status": "needs_review",
            "average": 3.1,
            "video_aesthetic_gate": {"status": "passed", "low": {}, "missing": []},
            "character_distinctiveness_gate": {"status": "passed", "low": {}, "missing": []},
            "video_performance_gate": {
                "status": "needs_review",
                "low": {
                    "emotion_readability": {
                        "score": 2,
                        "evidence": "flat acting across the composed episode",
                    },
                },
            },
        }],
        "repair_queue": [{
            "action": "regenerate_video_with_performance_direction",
            "execution": "auto",
            "stage": "video",
            "reason": "flat acting across the composed episode",
        }],
    })

    report = validator.summarize_validation(tmp_path)

    assert report["status"] == "partial_needs_review"
    assert report["checks"]["composition_review_count"] == 1
    assert report["checks"]["composition_review_passed"] is False
    assert report["checks"]["video_review_passed"] is False
    assert report["repair_queue"][0]["action"] == "regenerate_video_with_performance_direction"
    assert any("final composed episode review" in item for item in report["action_items"])


def test_validation_summary_blocks_low_video_identity_gate(tmp_path):
    write_json(tmp_path / "preflight.json", {"status": "ready_for_live_test"})
    write_json(tmp_path / "video_workflow_preflight.json", {"status": "ready_for_live_test"})
    write_json(tmp_path / "render.json", rendered_cases("discovery"))
    write_json(tmp_path / "image_review.json", passed_image_review("discovery"))
    write_json(tmp_path / "seed_dance_baseline_comparison.json", passed_seed_dance_baseline(tmp_path))
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
    assert any("identity/temporal/platform/aesthetic/character-distinctiveness/performance gates" in item for item in report["action_items"])


def test_validation_summary_recommends_targeted_calibration(tmp_path):
    write_json(tmp_path / "preflight.json", {"status": "ready_for_live_test"})
    write_json(tmp_path / "video_workflow_preflight.json", {"status": "ready_for_live_test"})
    write_json(tmp_path / "render.json", rendered_cases("discovery"))
    write_json(tmp_path / "image_review.json", passed_image_review("discovery"))
    write_json(tmp_path / "seed_dance_baseline_comparison.json", passed_seed_dance_baseline(tmp_path))
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
    write_json(tmp_path / "seed_dance_baseline_comparison.json", passed_seed_dance_baseline(tmp_path))
    write_json(tmp_path / "manual_review.json", passed_manual_review("discovery", "reaction"))

    package = validator.build_acceptance_package(tmp_path)

    assert package["status"] == "ready_for_seed_dance_candidate"
    assert package["required_status"] == "ready_for_seed_dance_candidate"
    assert package["manual_review"]["missing_case_ids"] == []
    assert package["manual_review"]["clip"]["passed"] is True
    assert [case["id"] for case in package["manual_review"]["cases"]] == ["discovery", "reaction"]
    assert package["evidence_files"]["render"]["present"] is True
    assert package["evidence_files"]["image_review"]["present"] is True
    assert (tmp_path / "acceptance_package.json").is_file()
    markdown = (tmp_path / "acceptance_package.md").read_text(encoding="utf-8")
    assert "Local Generation Acceptance Package" in markdown
    assert "Full Clip Review" in markdown
    assert "discovery" in markdown
    assert "ready_for_seed_dance_candidate" in markdown


def test_acceptance_package_includes_final_normalized_video_reviews(tmp_path):
    write_json(tmp_path / "preflight.json", {"status": "ready_for_live_test"})
    write_json(tmp_path / "video_workflow_preflight.json", {"status": "ready_for_live_test"})
    write_json(tmp_path / "render.json", rendered_cases("discovery"))
    write_json(tmp_path / "image_review.json", passed_image_review("discovery"))
    write_json(tmp_path / "video_review.json", passed_video_review())
    write_json(tmp_path / "seed_dance_baseline_comparison.json", passed_seed_dance_baseline(tmp_path))
    write_json(tmp_path / "manual_review.json", passed_manual_review("discovery"))
    write_json(tmp_path / "scene_1.quality.json", {
        "status": "passed",
        "final_video_review": {
            "status": "passed",
            "average": 4.4,
            "scene": {"scene_number": 1},
            "gate_scores": {
                "facial_identity": 4,
                "identity_consistency": 4,
                "temporal_consistency": 4,
            },
            "platform_score": 4.2,
            "video_aesthetic_gate": {"status": "passed", "low": {}, "missing": []},
            "character_distinctiveness_gate": {"status": "passed", "low": {}, "missing": []},
            "video_performance_gate": {"status": "passed", "low": {}, "missing": []},
        },
    })

    package = validator.build_acceptance_package(tmp_path)

    assert package["status"] == "ready_for_seed_dance_candidate"
    assert package["evidence_files"]["quality_reports"]["count"] == 1
    assert package["video_review"]["final_normalized_reviews"][0]["source_report"] == "scene_1.quality.json"
    assert package["video_review"]["final_normalized_reviews"][0]["status"] == "passed"


def test_acceptance_package_includes_final_composition_reviews(tmp_path):
    write_json(tmp_path / "preflight.json", {"status": "ready_for_live_test"})
    write_json(tmp_path / "video_workflow_preflight.json", {"status": "ready_for_live_test"})
    write_json(tmp_path / "render.json", rendered_cases("discovery"))
    write_json(tmp_path / "image_review.json", passed_image_review("discovery"))
    write_json(tmp_path / "video_review.json", passed_video_review())
    write_json(tmp_path / "seed_dance_baseline_comparison.json", passed_seed_dance_baseline(tmp_path))
    write_json(tmp_path / "manual_review.json", passed_manual_review("discovery"))
    write_json(tmp_path / "final.composition_review.json", {
        "status": "passed",
        "average": 4.5,
        "stage": "final_composition",
        "batches": [{
            "status": "passed",
            "average": 4.5,
            "video_aesthetic_gate": {"status": "passed", "low": {}, "missing": []},
            "character_distinctiveness_gate": {"status": "passed", "low": {}, "missing": []},
            "video_performance_gate": {"status": "passed", "low": {}, "missing": []},
        }],
    })

    package = validator.build_acceptance_package(tmp_path)

    assert package["status"] == "ready_for_seed_dance_candidate"
    assert package["checks"]["composition_review_count"] == 1
    assert package["checks"]["composition_review_passed"] is True
    assert package["evidence_files"]["composition_reviews"]["count"] == 1
    assert package["video_review"]["composition_reviews"][0]["source_report"] == "final.composition_review.json"
    markdown = (tmp_path / "acceptance_package.md").read_text(encoding="utf-8")
    assert "composition_review_passed" in markdown


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
    write_json(tmp_path / "seed_dance_baseline_comparison.json", passed_seed_dance_baseline(tmp_path))
    write_json(tmp_path / "manual_review.json", {
        "cases": [{"id": "discovery", "score": 4.5, "decision": "accept"}]
    })

    package = validator.build_acceptance_package(tmp_path)

    assert package["status"] == "partial_needs_review"
    assert package["manual_review"]["missing_case_ids"] == ["reaction"]
    assert package["repair_queue"][0]["execution"] == "setup_required"
    assert package["quality_loop_plan"]["status"] == "setup_required"
    assert package["quality_loop_plan"]["setup_required"][0]["action"] == "regenerate_turnaround_album"
    assert any("missing rendered cases" in item for item in package["blocking_action_items"])
    assert any("setup-required" in item for item in package["blocking_action_items"])


def test_acceptance_package_includes_repair_rerun_plan(tmp_path):
    write_json(tmp_path / "preflight.json", {"status": "ready_for_live_test"})
    write_json(tmp_path / "video_workflow_preflight.json", {"status": "ready_for_live_test"})
    write_json(tmp_path / "render.json", rendered_cases("discovery"))
    write_json(tmp_path / "image_review.json", passed_image_review("discovery"))
    write_json(tmp_path / "video_review.json", {
        **passed_video_review(),
        "repair_queue": [{
            "action": "lower_motion_and_regenerate_video",
            "execution": "auto",
            "stage": "video",
            "scene_number": 1,
            "reason": "stutter and repair scar flickers",
            "recommendation": "Lower motion strength/noise and regenerate the video clip from the accepted keyframe.",
        }],
    })
    write_json(tmp_path / "seed_dance_baseline_comparison.json", passed_seed_dance_baseline(tmp_path))
    write_json(tmp_path / "manual_review.json", passed_manual_review("discovery"))

    package = validator.build_acceptance_package(tmp_path)

    plan = package["repair_execution_plan"]
    loop_plan = package["quality_loop_plan"]
    assert plan["auto"][0]["action"] == "lower_motion_and_regenerate_video"
    assert plan["auto"][0]["parameter_hints"]["lower_motion_bucket_id"] is True
    assert loop_plan["status"] == "can_auto_repair"
    assert loop_plan["selected"][0]["action"] == "lower_motion_and_regenerate_video"
    assert loop_plan["selected"][0]["scene_number"] == 1
    assert package["selected_repair_execution_plan"]["auto"][0]["action"] == "lower_motion_and_regenerate_video"
    assert any("review-video" in command for command in plan["rerun_validation_commands"])
    assert any("compare-baseline" in command for command in plan["rerun_validation_commands"])
    markdown = (tmp_path / "acceptance_package.md").read_text(encoding="utf-8")
    assert "Repair Rerun Plan" in markdown
    assert "Next Quality Loop" in markdown
    assert "Commands for selected repairs" in markdown
    assert "lower_motion_and_regenerate_video" in markdown
    assert "review-video" in markdown


def test_quality_loop_package_writes_direct_next_repair_plan(tmp_path):
    write_json(tmp_path / "validation_summary.json", {"status": "partial_needs_review"})
    write_json(tmp_path / "video_review.json", {
        "status": "needs_review",
        "repair_queue": [
            {
                "action": "refine_face_aesthetic_detail",
                "execution": "auto",
                "stage": "image",
                "scene_number": 1,
                "priority": "high",
                "reason": "plastic skin",
            },
            {
                "action": "lower_motion_and_regenerate_video",
                "execution": "auto",
                "stage": "video",
                "scene_number": 2,
                "priority": "high",
                "reason": "stutter",
            },
        ],
    })

    package = validator.build_quality_loop_package(tmp_path, max_actions=1)

    assert package["status"] == "can_auto_repair"
    assert package["repair_queue_total"] == 2
    assert len(package["plan"]["selected"]) == 1
    assert package["plan"]["selected"][0]["action"] == "refine_face_aesthetic_detail"
    assert package["plan"]["skipped"][0]["reason"] == "max_actions_reached"
    assert package["repair_execution_plan"]["auto"][0]["action"] == "refine_face_aesthetic_detail"
    assert len(package["repair_execution_plan"]["auto"]) == 2
    assert package["selected_repair_execution_plan"]["auto"][0]["action"] == "refine_face_aesthetic_detail"
    assert len(package["selected_repair_execution_plan"]["auto"]) == 1
    assert (tmp_path / "quality_loop_plan.json").is_file()


def test_quality_loop_package_surfaces_setup_required_without_auto_actions(tmp_path):
    write_json(tmp_path / "validation_summary.json", {"status": "partial_needs_review"})
    write_json(tmp_path / "image_review.json", {
        "status": "needs_review",
        "repair_queue": [{
            "action": "regenerate_turnaround_album",
            "execution": "setup_required",
            "stage": "character",
            "scene_number": 1,
            "reason": "turnaround mismatch",
        }],
    })

    package = validator.build_quality_loop_package(tmp_path)

    assert package["status"] == "setup_required"
    assert package["plan"]["setup_required"][0]["action"] == "regenerate_turnaround_album"
    assert package["plan"]["selected"] == []
