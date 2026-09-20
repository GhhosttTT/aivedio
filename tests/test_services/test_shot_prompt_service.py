import json
from unittest.mock import Mock

import pytest

from src.services.shot_prompt_service import ShotPromptService, ShotPlanningError
from src.config import settings


def frame(**changes):
    data = dict(subject="the character", action="holding a sealed letter",
                setting="office doorway", framing="medium shot", lighting="window light",
                style="anime", needs_split=False, reason="")
    data.update(changes)
    return json.dumps(data)


def test_concise_prompt_is_not_rewritten():
    llm = Mock()
    prompt = "An empty railway platform, wide shot, overcast daylight, watercolor illustration"
    result = ShotPromptService(llm).compile(prompt)
    assert result.prompt.startswith(prompt)
    assert "mobile short-drama composition" in result.prompt
    assert "readable face" in result.prompt
    assert "over-smoothed plastic skin" in result.negative_prompt
    llm.generate.assert_not_called()
    assert "cartoon" not in result.negative_prompt


def test_identity_is_prepended_verbatim_and_style_preserved():
    llm = Mock()
    llm.generate.return_value = frame()
    anchor = "young woman, short black hair, green jacket"
    result = ShotPromptService(llm).compile("女孩在办公室门口拿着信", anchor)
    assert result.prompt.startswith(anchor)
    assert "anime" in result.prompt
    assert "commercial lighting" in result.prompt
    assert "same-face characters" in result.negative_prompt
    assert result.word_count <= 75
    llm.generate.assert_called_once()


def test_complex_sequence_is_not_silently_truncated():
    llm = Mock()
    llm.generate.return_value = frame(needs_split=True, reason="Opening the door and sitting are separate actions")
    with pytest.raises(ShotPlanningError, match="separate shots"):
        ShotPromptService(llm).compile("He opens the door and then sits at the desk")
    llm.generate.assert_called_once()


def test_invalid_json_gets_one_bounded_correction():
    llm = Mock()
    llm.generate.side_effect = ["not JSON", frame()]
    result = ShotPromptService(llm).compile("拿着信的女孩")
    assert "sealed letter" in result.prompt
    assert llm.generate.call_count == 2


def test_invalid_second_response_uses_deterministic_english_fallback():
    llm = Mock()
    llm.generate.return_value = "not JSON"
    result = ShotPromptService(llm).compile("\u5496\u5561\u5e97\u9760\u7a97\u684c\uff0c\u6797\u8587\u72ec\u81ea\u5750\u5728\u684c\u8fb9\u7b49\u5f85\uff0c\u5168\u666f")
    assert "window-side cafe table" in result.prompt
    assert "\u6797\u8587" not in result.prompt
    assert llm.generate.call_count == 2


def test_prompt_hash_changes_on_identity_or_scene_edit():
    service = ShotPromptService()
    assert service.source_hash("letter", "red jacket") != service.source_hash("letter", "blue jacket")
    assert service.source_hash("letter", None) != service.source_hash("phone", None)


@pytest.mark.parametrize("prompt", ["", "standing " * 76, "he stands then sits", "男人 medium shot"])
def test_invalid_prompt_rejected(prompt):
    with pytest.raises(ShotPlanningError):
        ShotPromptService.validate_prompt(prompt)


def test_cached_prompt_allows_configured_quality_suffix(monkeypatch):
    monkeypatch.setattr(settings, "POSITIVE_PROMPT_SUFFIX", "natural symmetrical eyes, matching iris size, aligned pupils, consistent gaze direction")
    base = " ".join(f"word{i}" for i in range(75))
    prompt = f"{base}, {settings.POSITIVE_PROMPT_SUFFIX}"
    assert ShotPromptService.validate_cached_prompt(prompt) == prompt


def test_cached_prompt_allows_production_style_contract():
    base = " ".join(f"word{i}" for i in range(75))
    prompt = f"{base}, {ShotPromptService.PRODUCTION_STYLE_PROMPT}"

    assert ShotPromptService.validate_cached_prompt(prompt) == prompt
