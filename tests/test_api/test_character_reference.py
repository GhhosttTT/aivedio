import pytest

from src.api import character_reference


@pytest.mark.asyncio
async def test_generate_reference_images_keeps_prompt_only_mode(monkeypatch):
    class FakeGenerator:
        def generate_character_description(self, **_kwargs):
            return {"name": "Alice"}

        def generate_reference_prompts(self, _character_data):
            return {"front_closeup": {"prompt": "front", "negative": "bad"}}

    monkeypatch.setattr(character_reference, "CharacterReferenceGenerator", lambda **_kwargs: FakeGenerator())
    monkeypatch.setattr(character_reference, "get_llm_service", lambda: object())
    result = await character_reference.generate_reference_images(
        character_reference.CharacterRequest(name="Alice")
    )

    assert result["success"] is True
    assert result["reference_images"] == []
    assert result["prompts"]["front_closeup"]["prompt"] == "front"


@pytest.mark.asyncio
async def test_generate_reference_images_runs_quality_selected_generation(monkeypatch, tmp_path):
    class FakeGenerator:
        def generate_character_description(self, **_kwargs):
            return {"name": "Alice"}

        def generate_reference_prompts(self, _character_data):
            return {"front_closeup": {"prompt": "front", "negative": "bad"}}

    class FakeAutoGenerator:
        def __init__(self, **_kwargs):
            pass

        def generate_multiple_references(self, **kwargs):
            assert kwargs["count"] == 4
            assert kwargs["save_dir"] == str(tmp_path)
            return {
                "success": True,
                "reference_images": ["selected.png"],
                "reference_image_path": "selected.png",
                "reference_prompts": {"front_closeup": {"prompt": "front"}},
                "message": "ok",
            }

    monkeypatch.setattr(character_reference, "CharacterReferenceGenerator", lambda **_kwargs: FakeGenerator())
    monkeypatch.setattr(character_reference, "get_llm_service", lambda: object())
    monkeypatch.setattr(character_reference, "CharacterReferenceAutoGenerator", FakeAutoGenerator)
    result = await character_reference.generate_reference_images(
        character_reference.CharacterRequest(
            name="Alice", generate_images=True, count=4, save_dir=str(tmp_path)
        )
    )

    assert result["success"] is True
    assert result["reference_images"] == ["selected.png"]
    assert result["prompts"]["front_closeup"]["prompt"] == "front"
