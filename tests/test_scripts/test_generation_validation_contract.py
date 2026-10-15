import json
from types import SimpleNamespace
from unittest.mock import Mock

from scripts import validate_local_generation as validator


def pair_case():
    return {
        "id": "pair", "prompt": "Alice on frame left confronts Victor on frame right, medium two-shot in an office", "seed": 42,
        "validation_categories": ["two_character_regional_identity"],
        "character_references": [{"name": "Alice", "path": "alice.png"}, {"name": "Victor", "path": "victor.png"}],
        "scene": {"scene_number": 7, "visible_characters": [{"name": "Alice"}, {"name": "Victor"}]},
    }


def fake_service(monkeypatch):
    service = SimpleNamespace(client=Mock(), free_memory=Mock(), generate_image=Mock())
    monkeypatch.setattr(validator, "ComfyUIService", lambda **_kwargs: service)
    return service


def test_category_label_alone_cannot_claim_regional_identity_coverage():
    case = pair_case()
    assert "two_character_regional_identity" not in validator._sample_case_categories(case)
    case["request"] = {"character_references": case["character_references"]}
    case["actual_workflow"] = {"identity_bindings": [{"regional_mask": True}, {"regional_mask": True}]}
    assert "two_character_regional_identity" in validator._sample_case_categories(case)
    case["actual_workflow"]["identity_bindings"][1]["regional_mask"] = False
    assert "two_character_regional_identity" not in validator._sample_case_categories(case)


def test_multi_character_render_cannot_use_one_global_identity_for_both_roles(tmp_path, monkeypatch):
    service = fake_service(monkeypatch)
    case = pair_case()
    case["character_references"] = []
    report = validator.render_images([case], tmp_path, reference="alice.png")
    assert report["status"] == "error"
    assert "one independent" in report["error"]
    service.generate_image.assert_not_called()
    service.client.close.assert_called_once()


def test_production_validation_uses_the_same_candidate_search_as_generation(tmp_path, monkeypatch):
    service = fake_service(monkeypatch)
    selected_prompt = "Alice and Victor with distinct faces, office medium two-shot"
    selection = {"candidates": [{"request": {"prompt": selected_prompt, "negative_prompt": "merged faces"}}], "search": {"completed_passes": 2}}
    search = Mock(return_value=(str(tmp_path / "pair.png"), selection))
    monkeypatch.setattr(validator, "_generate_quality_candidates", search)
    case = pair_case()
    report = validator.render_images([case], tmp_path, production_search=True)
    assert report["status"] == "rendered_pending_human_review"
    provider, request, scene, reference, action = search.call_args.args
    assert provider.comfyui_service is service
    assert request.character_references == case["character_references"]
    assert request.use_ipadapter is True
    assert scene["character_sheet_references"] == case["character_references"]
    assert scene["shot_aesthetic_profile"]["id"] == "two_shot"
    assert reference is None and action is None
    assert report["cases"][0]["prompt"] == selected_prompt
    assert report["cases"][0]["search"]["completed_passes"] == 2
    assert report["cases"][0]["selection_report"].endswith("pair.quality.json")
    service.generate_image.assert_not_called()


def test_local_validation_reviewer_retains_role_reference_mapping(tmp_path, monkeypatch):
    case = pair_case()
    case["image"] = str(tmp_path / "pair.png")
    case["scene"]["character_sheet_references"] = case["character_references"]
    case["scene"]["identity_contrast_matrix"] = {"pairs": [{"names": ["Alice", "Victor"]}]}
    (tmp_path / "render.json").write_text(json.dumps({"status": "rendered_pending_human_review", "cases": [case]}), encoding="utf-8")
    selector = Mock(review_candidate=Mock(return_value={"status": "needs_review", "average": 3.0}))
    monkeypatch.setattr(validator, "ImageQualitySelector", lambda: selector)
    report = validator.review_images(tmp_path)
    payload = selector.review_candidate.call_args.args[2]
    assert payload["character_sheet_references"] == case["character_references"]
    assert payload["identity_contrast_matrix"] == case["scene"]["identity_contrast_matrix"]
    assert report["cases"][0]["scene"]["visible_characters"] == case["scene"]["visible_characters"]
