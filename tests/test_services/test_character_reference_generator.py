from src.services.character_reference_generator import CharacterReferenceGenerator


def test_reference_prompts_avoid_generic_ai_quality_tags():
    generator = CharacterReferenceGenerator()

    prompts = generator.generate_reference_prompts(
        {
            "age": 31,
            "gender": "female",
            "ethnicity": "East Asian",
            "face_shape": "round face with soft jawline",
            "eyes": "slightly downturned brown eyes",
            "nose": "small rounded nose",
            "mouth": "thin lips",
            "hair": "shoulder-length black hair",
            "outfit_details": "gray cardigan over white blouse",
            "skin_tone": "warm light skin",
        }
    )

    joined = " ".join(item["prompt"].lower() for item in prompts.values())
    for banned in (
        "masterpiece",
        "best quality",
        "ultra-detailed",
        "8k uhd",
        "flawless skin",
        "perfect symmetry",
        "bokeh background",
        "lens flare",
    ):
        assert banned not in joined

    assert "short-drama casting reference" in joined
    assert "phone-readable face" in joined
    assert "visible skin texture" in joined
    assert "gray cardigan over white blouse" in joined
