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


def test_topic_brief_scores_commercial_specificity(monkeypatch, tmp_path):
    monkeypatch.setattr("src.services.topic_brief.storage_manager.get_project_path", lambda _id: tmp_path)
    service = TopicBriefService()
    service.save(1, {
        "audience": "18-35岁女性，喜欢复仇爽剧",
        "platform": "抖音竖屏",
        "genre": "都市悬疑复仇",
        "hook_type": "秘密证据曝光",
        "region": "中国大陆 / 中文",
        "policy_notes": "无未成年人和血腥内容",
    })

    report = service.check(1)

    assert report["score"] == 10
    assert report["score_status"] == "passed"
    assert report["signals"]["hook_specific"] is True
    assert report["recommendations"] == []


def test_topic_brief_explains_low_specificity(monkeypatch, tmp_path):
    monkeypatch.setattr("src.services.topic_brief.storage_manager.get_project_path", lambda _id: tmp_path)
    service = TopicBriefService()
    service.save(1, {
        "audience": "观众",
        "platform": "平台",
        "genre": "故事",
        "hook_type": "开场",
        "region": "中文",
        "policy_notes": "",
    })

    report = service.check(1)

    assert report["score_status"] == "weak"
    assert "audience_specific" in report["score_missing"]
    assert report["recommendations"]
