import pytest

from src.services.topic_brief import TopicBriefService


def test_topic_brief_round_trip_and_prompt(monkeypatch, tmp_path):
    from src.utils.storage import storage_manager
    monkeypatch.setattr(storage_manager, "base_path", tmp_path)
    service = TopicBriefService()
    payload = {
        "audience": "18-35 women",
        "platform": "vertical short drama",
        "genre": "urban suspense",
        "hook_type": "secret revealed",
        "region": "zh-CN",
        "policy_notes": "no medical claims",
    }

    saved = service.save(1, payload)
    report = service.check(1)

    assert saved["status"] == "ready"
    assert report["status"] == "ready"
    assert "MARKET AND AUDIENCE LOCK" in service.prompt_fragment(1)


def test_topic_brief_requires_all_production_fields():
    with pytest.raises(ValueError, match="Missing topic brief fields"):
        TopicBriefService().normalize({"audience": "viewers"})
