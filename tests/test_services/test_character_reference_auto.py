from pathlib import Path

from PIL import Image

from src.services.character_reference_auto import (
    CharacterReferenceAutoGenerator,
    _reference_review_payload,
    _turnaround_review_payload,
)
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
                feature: {"score": 5, "evidence": f"{feature} matches"}
                for feature in TURNAROUND_FEATURES.get(scene.get("turnaround_view", "front"), [])
            },
            "issues": [],
        },
        "metrics": {"technical_score": 4.6},
    }


def test_character_reference_generation_selects_best_candidate(tmp_path, monkeypatch):
    generator = CharacterReferenceAutoGenerator(comfyui_service=FakeComfyUI(), generator=FakeDescriptionGenerator())
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
    assert len(result["reference_images"]) == 3
    assert result["quality_report"]["kind"] == "image_candidate_selection"
    assert Path(tmp_path / "林安" / "reference_quality.json").is_file()
    assert len(generator.comfyui.calls) == 3
    assert "consistent facial identity reference" in generator.comfyui.calls[0]["prompt"]
    assert "natural skin texture" in generator.comfyui.calls[0]["prompt"]


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
    assert set(result["selected_views"]) == {"front", "side", "back"}
    assert set(result["quality_reports"]) == {"front", "side", "back"}
    assert all(Path(path).is_file() for path in result["selected_views"].values())
    assert len(fake_comfy.calls) == 6
    prompts = [call["prompt"] for call in fake_comfy.calls]
    assert any("strict front turnaround view" in prompt for prompt in prompts)
    assert any("90 degree side view" in prompt for prompt in prompts)
    assert any("strict rear turnaround view" in prompt for prompt in prompts)
    assert all("same scale as other views" in prompt for prompt in prompts)
    assert all("plain light gray background" in prompt for prompt in prompts)
    assert Path(tmp_path / "林安" / "turnaround_front_quality.json").is_file()
    assert result["quality_reports"]["front"]["turnaround_gate"]["status"] == "passed"
    assert result["quality_reports"]["front"]["turnaround_contract"]["layout"].startswith("single full-body")
    assert result["quality_reports"]["front"]["candidates"][0]["request"]["turnaround_contract"]["expected_features"]["face_shape"] == "oval face"
    assert set(result["quality_reports"]["side"]["turnaround_gate"]["scores"]) == set(TURNAROUND_FEATURES["side"])


def test_turnaround_album_generation_blocks_failed_feature_gate(tmp_path, monkeypatch):
    fake_comfy = FakeComfyUI()
    generator = CharacterReferenceAutoGenerator(comfyui_service=fake_comfy, generator=FakeDescriptionGenerator())
    monkeypatch.setattr("src.services.character_reference_auto.settings.GENERATION_IMAGE_MIN_SCORE", 0.0)
    monkeypatch.setattr("src.services.character_reference_auto.settings.GENERATION_IMAGE_PLATFORM_MIN_SCORE", 0.0)
    monkeypatch.setattr("src.services.character_reference_auto.settings.GENERATION_REQUIRE_IMAGE_REVIEW", False)

    def low_review(self, index, image_path, scene, prompt, reference_image=None):
        report = _passed_review(index, image_path, scene, prompt, reference_image)
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
