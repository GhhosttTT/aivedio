from src.services.prompt_converter import PromptConverter


def test_json_prompt_converter_uses_short_drama_quality_terms():
    converter = PromptConverter()

    prompt = converter.convert_json_to_prompt(
        {
            "appearance": "31 year old East Asian woman with shoulder-length black hair",
            "expression": "worried expression",
            "pose": "standing at an apartment doorway",
            "lighting": "soft side light",
            "style": "photorealistic",
            "camera": "medium shot",
        }
    )

    lowered = prompt.lower()
    for banned in ("masterpiece", "best quality", "ultra-detailed", "8k uhd"):
        assert banned not in lowered

    assert "photorealistic short-drama frame" in prompt
    assert "natural skin texture" in prompt
    assert "medium shot" in prompt


def test_json_prompt_converter_fallback_avoids_generic_ai_quality_tags():
    converter = PromptConverter()

    prompt = converter.convert_json_to_prompt(object())

    lowered = prompt.lower()
    assert "masterpiece" not in lowered
    assert "best quality" not in lowered
    assert "8k uhd" not in lowered
    assert "readable face" in lowered
