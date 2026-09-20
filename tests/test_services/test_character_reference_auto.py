from pathlib import Path

from PIL import Image

from src.services.character_reference_auto import (
    CharacterReferenceAutoGenerator,
    _reference_review_payload,
)


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
            }
        }


def test_character_reference_generation_selects_best_candidate(tmp_path, monkeypatch):
    generator = CharacterReferenceAutoGenerator(comfyui_service=FakeComfyUI(), generator=FakeDescriptionGenerator())
    monkeypatch.setattr("src.services.character_reference_auto.settings.GENERATION_IMAGE_MIN_SCORE", 0.0)
    monkeypatch.setattr("src.services.character_reference_auto.settings.GENERATION_REQUIRE_IMAGE_REVIEW", False)

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
