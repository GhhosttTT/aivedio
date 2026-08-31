import json
from unittest.mock import Mock

import pytest

from src.services.shot_prompt_service import ShotPromptService, ShotPlanningError


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
    assert result.prompt == prompt
    llm.generate.assert_not_called()
    assert "cartoon" not in result.negative_prompt


def test_identity_is_prepended_verbatim_and_style_preserved():
    llm = Mock()
    llm.generate.return_value = frame()
    anchor = "young woman, short black hair, green jacket"
    result = ShotPromptService(llm).compile("女孩在办公室门口拿着信", anchor)
    assert result.prompt.startswith(anchor)
    assert result.prompt.endswith("anime")
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


def test_invalid_second_response_fails_instead_of_generating_garbage():
    llm = Mock()
    llm.generate.return_value = "not JSON"
    with pytest.raises(ShotPlanningError):
        ShotPromptService(llm).compile("中文场景")
    assert llm.generate.call_count == 2


def test_prompt_hash_changes_on_identity_or_scene_edit():
    service = ShotPromptService()
    assert service.source_hash("letter", "red jacket") != service.source_hash("letter", "blue jacket")
    assert service.source_hash("letter", None) != service.source_hash("phone", None)


@pytest.mark.parametrize("prompt", ["", "standing " * 76, "he stands then sits", "男人 medium shot"])
def test_invalid_prompt_rejected(prompt):
    with pytest.raises(ShotPlanningError):
        ShotPromptService.validate_prompt(prompt)
