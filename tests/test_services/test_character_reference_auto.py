from pathlib import Path
from unittest.mock import Mock

from PIL import Image

from src.services.character_reference_auto import (
    CharacterReferenceAutoGenerator,
    _reference_review_payload,
    _turnaround_review_payload,
)
from src.services.character_turnaround_album import PRODUCTION_TURNAROUND_VIEWS
from src.services.turnaround_quality import TURNAROUND_FEATURES


class FakeComfyUI:
    def __init__(self):
        self.calls = []

    def generate_image(self, **kwargs):
        self.calls.append(kwargs)
        path = Path(kwargs["output_path"])
        path.parent.mkdir(parents=True, exist_ok=True)
        shade = 80 + len(self.calls) * 30
        Image.new("RGB", (kwargs["width"], kwargs["height"]), (shade, shade, shade)).save(path)
        return str(path)


class FakeDescriptionGenerator:
    def generate_character_description(self, character_name, role="", personality=""):
        return {
            "name": character_name,
            "age": 28,
            "gender": "female",
            "ethnicity": "East Asian",
            "face_shape": "oval face",
            "eyes": "almond brown eyes",
            "nose": "straight nose bridge",
            "mouth": "medium lips",
            "hair": "short black hair",
            "body_type": "slender",
            "height": "168cm",
            "clothing_style": "modern drama",
            "outfit_details": "green jacket",
            "skin_tone": "fair warm skin",
            "distinctive_features": "small mole under left eye",
            "expression_default": "calm",
            "pose_front": "facing camera",
            "pose_side": "three-quarter view",
            "pose_fullbody": "standing naturally",
            "lighting_preference": "soft light",
            "style_tags": ["cinematic"],
        }

    def generate_reference_prompts(self, character_data):
        return {
            "front_closeup": {
                "prompt": "front portrait, clear face",
                "negative": "blurry, deformed",
                "description": "front",
            },
            "side_profile": {
                "prompt": "strict side profile, full body",
                "negative": "blurry, deformed",
                "description": "side",
            },
            "back_view": {
                "prompt": "strict back view, outfit silhouette",
                "negative": "blurry, deformed",
                "description": "back",
            }
        }


def _passed_review(index, image_path, scene, prompt, reference_image=None):
    return {
        "index": index,
        "path": image_path,
        "status": "passed",
        "average": 4.6,
        "review": {
            "composition": {"score": 5, "evidence": "strong framing"},
            "aesthetic_quality": {"score": 5, "evidence": "commercial lighting"},
            "visual_integrity": {"score": 5, "evidence": "clean render"},
            "facial_identity": {"score": 5, "evidence": "face matches"},
            "identity_consistency": {"score": 5, "evidence": "wardrobe stable"},
            "turnaround_feature_scores": {
                feature: {"score": 5, "evidence": f"{feature} visibly matches the character sheet"}
                for feature in TURNAROUND_FEATURES.get(scene.get("turnaround_view", "front"), [])
            },
            "issues": [],
        },
        "metrics": {"technical_score": 4.6},
    }


def test_character_reference_generation_selects_best_candidate(tmp_path, monkeypatch):
    generator = CharacterReferenceAutoGenerator(comfyui_service=FakeComfyUI(), generator=FakeDescriptionGenerator())
    monkeypatch.setattr("src.services.generation_quality_policy.settings.GENERATION_QUALITY_PROFILE", "hongguo_reference")
    monkeypatch.setattr("src.services.character_reference_auto.settings.GENERATION_IMAGE_MIN_SCORE", 0.0)
    monkeypatch.setattr("src.services.character_reference_auto.settings.GENERATION_REQUIRE_IMAGE_REVIEW", False)
    monkeypatch.setattr(
        "src.services.character_reference_auto.ImageQualitySelector.review_candidate",
        lambda self, index, image_path, scene, prompt, reference_image=None: _passed_review(index, image_path, scene, prompt, reference_image),
    )

    result = generator.generate_multiple_references(
        character_name="林安",
        role="女主",
        personality="克制",
        count=3,
        save_dir=str(tmp_path),
    )

    assert result["success"] is True
    assert Path(result["reference_image_path"]).is_file()
    assert len(result["reference_images"]) == 5
    assert result["quality_report"]["requested_candidate_count"] == 5
    assert result["quality_report"]["kind"] == "image_candidate_selection"
    assert Path(tmp_path / "林安" / "reference_quality.json").is_file()
    assert len(generator.comfyui.calls) == 5
    assert "consistent facial identity reference" in generator.comfyui.calls[0]["prompt"]
    assert "natural skin texture" in generator.comfyui.calls[0]["prompt"]


def test_character_reference_generation_expands_candidates_for_seed_dance_profile(tmp_path, monkeypatch):
    fake_comfy = FakeComfyUI()
    generator = CharacterReferenceAutoGenerator(comfyui_service=fake_comfy, generator=FakeDescriptionGenerator())
    monkeypatch.setattr("src.services.generation_quality_policy.settings.GENERATION_QUALITY_PROFILE", "seed_dance_reference")
    monkeypatch.setattr("src.services.generation_quality_policy.settings.GENERATION_IMAGE_CANDIDATES", 3)
    monkeypatch.setattr("src.services.generation_quality_policy.settings.GENERATION_MAX_IMAGE_CANDIDATES", 6)
    monkeypatch.setattr("src.services.character_reference_auto.settings.GENERATION_IMAGE_MIN_SCORE", 0.0)
    monkeypatch.setattr("src.services.character_reference_auto.settings.GENERATION_REQUIRE_IMAGE_REVIEW", False)
    monkeypatch.setattr(
        "src.services.character_reference_auto.ImageQualitySelector.review_candidate",
        lambda self, index, image_path, scene, prompt, reference_image=None: _passed_review(index, image_path, scene, prompt, reference_image),
    )

    result = generator.generate_multiple_references(
        character_name="林安",
        role="女主",
        personality="克制",
        count=1,
        save_dir=str(tmp_path),
    )

    assert result["success"] is True
    assert len(fake_comfy.calls) == 6
    assert result["quality_report"]["requested_candidate_count"] == 6
    assert result["quality_report"]["quality_budget"]["profile"] == "seed_dance_reference"
    assert result["quality_report"]["candidates"][0]["request"]["quality_budget"]["candidate_count"] == 6


def test_reference_review_payload_carries_identity_anchor():
    character_data = FakeDescriptionGenerator().generate_character_description("林安")

    payload = _reference_review_payload("林安", character_data)

    assert payload["visible_characters"][0]["name"] == "林安"
    appearance = payload["visible_characters"][0]["appearance"]
    assert "oval face" in appearance
    assert "almond brown eyes" in appearance
    assert "small mole under left eye" in appearance
    assert "green jacket" in appearance
    assert "mobile short-drama commercial portrait quality" in payload["reference_requirements"]


def test_turnaround_album_generation_selects_each_required_view(tmp_path, monkeypatch):
    fake_comfy = FakeComfyUI()
    generator = CharacterReferenceAutoGenerator(comfyui_service=fake_comfy, generator=FakeDescriptionGenerator())
    monkeypatch.setattr("src.services.generation_quality_policy.settings.GENERATION_QUALITY_PROFILE", "hongguo_reference")
    monkeypatch.setattr("src.services.character_reference_auto.settings.GENERATION_IMAGE_MIN_SCORE", 0.0)
    monkeypatch.setattr("src.services.character_reference_auto.settings.GENERATION_IMAGE_PLATFORM_MIN_SCORE", 0.0)
    monkeypatch.setattr("src.services.character_reference_auto.settings.GENERATION_REQUIRE_IMAGE_REVIEW", False)
    monkeypatch.setattr(
        "src.services.character_reference_auto.ImageQualitySelector.review_candidate",
        lambda self, index, image_path, scene, prompt, reference_image=None: _passed_review(index, image_path, scene, prompt, reference_image),
    )

    result = generator.generate_turnaround_album(
        character_name="林安",
        role="女主",
        personality="克制",
        count_per_view=2,
        save_dir=str(tmp_path),
    )

    assert result["success"] is True
    assert set(result["selected_views"]) == set(PRODUCTION_TURNAROUND_VIEWS)
    assert set(result["quality_reports"]) == set(PRODUCTION_TURNAROUND_VIEWS)
    assert all(Path(path).is_file() for path in result["selected_views"].values())
    assert len(fake_comfy.calls) == 45
    prompts = [call["prompt"] for call in fake_comfy.calls]
    assert any("strict front turnaround view" in prompt for prompt in prompts)
    assert any("strict left 45 degree three-quarter view" in prompt for prompt in prompts)
    assert any("full-body head-to-toe model sheet" in prompt for prompt in prompts)
    assert any("intense short-drama expression sheet" in prompt for prompt in prompts)
    assert any("90 degree side view" in prompt for prompt in prompts)
    assert any("strict rear turnaround view" in prompt for prompt in prompts)
    view_calls = fake_comfy.calls[5:]
    assert all(call["reference_image"] == result["identity_reference_image"] for call in view_calls)
    assert all(call["use_ipadapter"] for call in view_calls)
    assert all("plain light gray background" in call["prompt"] for call in view_calls)
    expression_calls = [call for call in view_calls if Path(call["output_path"]).name.startswith("turnaround_expression_")]
    assert expression_calls and all("full body head-to-toe visible" not in call["prompt"] for call in expression_calls)
    assert all("same scale as other views" in call["prompt"] for call in view_calls if call not in expression_calls)
    assert Path(tmp_path / "林安" / "turnaround_front_quality.json").is_file()
    assert result["quality_reports"]["front"]["turnaround_gate"]["status"] == "passed"
    assert result["quality_reports"]["front"]["turnaround_contract"]["layout"].startswith("single character")
    assert result["quality_reports"]["front"]["candidates"][0]["request"]["turnaround_contract"]["expected_features"]["face_shape"] == "oval face"
    assert set(result["quality_reports"]["side"]["turnaround_gate"]["scores"]) == set(TURNAROUND_FEATURES["side"])


def test_turnaround_album_generation_blocks_failed_feature_gate(tmp_path, monkeypatch):
    fake_comfy = FakeComfyUI()
    generator = CharacterReferenceAutoGenerator(comfyui_service=fake_comfy, generator=FakeDescriptionGenerator())
    monkeypatch.setattr("src.services.generation_quality_policy.settings.GENERATION_QUALITY_PROFILE", "hongguo_reference")
    monkeypatch.setattr("src.services.character_reference_auto.settings.GENERATION_IMAGE_MIN_SCORE", 0.0)
    monkeypatch.setattr("src.services.character_reference_auto.settings.GENERATION_IMAGE_PLATFORM_MIN_SCORE", 0.0)
    monkeypatch.setattr("src.services.character_reference_auto.settings.GENERATION_REQUIRE_IMAGE_REVIEW", False)

    def low_review(self, index, image_path, scene, prompt, reference_image=None):
        report = _passed_review(index, image_path, scene, prompt, reference_image)
        if not scene.get("turnaround_view"):
            return report
        feature = TURNAROUND_FEATURES[scene["turnaround_view"]][0]
        report["review"]["turnaround_feature_scores"][feature] = {
            "score": 2,
            "evidence": "wrong view angle",
        }
        return report

    monkeypatch.setattr("src.services.character_reference_auto.ImageQualitySelector.review_candidate", low_review)

    result = generator.generate_turnaround_album(
        character_name="林安",
        role="女主",
        personality="克制",
        count_per_view=1,
        save_dir=str(tmp_path),
    )

    assert result["success"] is False
    assert "Turnaround front feature gate failed" in result["message"]
    assert result["selected_views"] == {}


def test_turnaround_review_payload_carries_model_sheet_contract():
    character_data = FakeDescriptionGenerator().generate_character_description("林安")

    payload = _turnaround_review_payload("林安", character_data, "side")

    assert payload["turnaround_view"] == "side"
    assert payload["turnaround_contract"]["camera"] == "strict 90 degree side profile camera, no three-quarter rotation"
    assert payload["turnaround_contract"]["expected_features"]["nose_silhouette"] == "straight nose bridge"
    assert "strict side profile, not three-quarter" in payload["reference_requirements"]


def test_frozen_identity_and_master_image_are_reused_for_every_view(tmp_path, monkeypatch):
    portrait = tmp_path / "approved.png"
    Image.new("RGB", (64, 64), "green").save(portrait)
    description = FakeDescriptionGenerator()
    description.generate_character_description = Mock(side_effect=AssertionError("do not redesign the approved actor"))
    comfy = FakeComfyUI()
    comfy.release_generation_resources = Mock()
    generator = CharacterReferenceAutoGenerator(comfyui_service=comfy, generator=description)
    monkeypatch.setattr("src.services.generation_quality_policy.settings.GENERATION_QUALITY_PROFILE", "hongguo_reference")
    monkeypatch.setattr("src.services.character_reference_auto.settings.GENERATION_IMAGE_MIN_SCORE", 0.0)
    monkeypatch.setattr("src.services.character_reference_auto.settings.GENERATION_IMAGE_PLATFORM_MIN_SCORE", 0.0)
    monkeypatch.setattr("src.services.character_reference_auto.settings.GENERATION_REQUIRE_IMAGE_REVIEW", False)
    reviewed_references = []

    def review(self, index, image_path, scene, prompt, reference_image=None):
        reviewed_references.append(reference_image)
        assert scene["identity"]["face_shape"] == "square face with a broad jaw"
        return _passed_review(index, image_path, scene, prompt, reference_image)

    monkeypatch.setattr("src.services.character_reference_auto.ImageQualitySelector.review_candidate", review)
    spec = {"name": "Alice", "face_shape": "square face with a broad jaw", "wardrobe": "red jacket", "distinctive_mark": "mole beside left eye"}
    result = generator.generate_turnaround_album(
        "Alice", save_dir=str(tmp_path), identity_spec=spec, identity_reference_image=str(portrait),
    )
    assert result["success"] is True
    assert result["character_data"]["outfit_details"] == "red jacket"
    assert result["character_data"]["distinctive_features"] == "mole beside left eye"
    assert len(comfy.calls) == 40
    assert reviewed_references == [str(portrait)] * 40
    assert all(call["reference_image"] == str(portrait) and call["use_ipadapter"] for call in comfy.calls)
    assert comfy.release_generation_resources.call_count == 40
    description.generate_character_description.assert_not_called()


def test_rear_turnaround_does_not_require_a_front_facing_face():
    payload = _turnaround_review_payload("Alice", FakeDescriptionGenerator().generate_character_description("Alice"), "back")
    assert "front-facing readable face" not in payload["reference_requirements"]
    assert "no face or accidental front-facing pose" in payload["reference_requirements"]
