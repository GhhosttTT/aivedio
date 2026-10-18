from src.database.models import Project, Scene
from src.services.story_room_quality import StoryRoomQualityService


def scene(number, visual, dialogue=""):
    return Scene(
        project_id=1,
        scene_number=number,
        visual_description=visual,
        dialogue=dialogue,
    )


def test_story_room_quality_flags_underdeveloped_short_drama():
    project = Project(name="Quiet draft", theme="A room", outline="", description="")
    scenes = [
        scene(1, "A calm room with people standing quietly."),
        scene(2, "People continue waiting near the table.", "They talk calmly."),
        scene(3, "The room stays unchanged."),
        scene(4, "Everyone leaves without a visible consequence."),
    ]

    report = StoryRoomQualityService().evaluate(project, scenes).to_dict()

    assert report["status"] == "weak"
    assert "market_brief" in report["missing"]
    assert "early_hook" in report["missing"]
    assert "character_goal_conflict" in report["missing"]
    assert "reversal" in report["missing"]
    assert "ending_hook" in report["missing"]
    assert report["rewrite_actions"]
    assert report["repair_queue"][0]["action"] == "rewrite_short_drama_story_rhythm"
    assert report["repair_queue"][0]["execution"] == "setup_required"


def test_story_room_quality_accepts_platform_ready_story_shape():
    project = Project(
        name="Evidence Heiress",
        theme="都市复仇短剧，目标女性受众，抖音竖屏平台",
        outline="女主拿到背叛证据后逆袭，面向甜宠复仇用户，结尾保留下一集真相。",
        description="platform: Douyin vertical short drama, audience: romance revenge viewers",
    )
    scenes = [
        scene(1, "女主发现秘密证据，前夫威胁她闭嘴，震惊。", "你以为我还会怕你吗？"),
        scene(2, "她握紧录音笔，身份线索露出，害怕转为坚定。", "这次轮到我选择。"),
        scene(3, "家族会议上众人质问她，她拒绝交出证据，愤怒。", "证据在我手里。"),
        scene(4, "反派冷笑逼迫她签字，她当众撕掉协议。", "我不会再退。"),
        scene(5, "原来遗嘱揭露她的继承身份，全场震惊。", "现在谁该离开？"),
        scene(6, "母亲哭着承认误会，女主失望地后退。", "你早就知道？"),
        scene(7, "反派报警威胁，女主拿出第二份证据。", "真正该被带走的人是你。"),
        scene(8, "电话响起，新的真相出现，门被推开，未完。", "还有一个人没到场。"),
    ]

    report = StoryRoomQualityService().evaluate(project, scenes).to_dict()

    assert report["status"] == "passed"
    assert report["score"] >= 7
    assert report["missing"] == []
    assert report["repair_queue"] == []
    assert report["signals"]["early_hook"] is True
    assert report["signals"]["character_goal_conflict"] is True
    assert report["signals"]["has_reversal"] is True
    assert report["signals"]["has_payoff"] is True
    assert report["signals"]["ending_hook"] is True
    assert report["signals"]["beat_contract"]["payoff"]["detected"] is True


def test_story_room_quality_reads_locked_topic_brief(monkeypatch, tmp_path):
    from src.utils.storage import storage_manager
    monkeypatch.setattr(storage_manager, "get_project_path", lambda _id: tmp_path)
    (tmp_path / "topic_brief.json").write_text(
        '{"audience":"18-35岁女性","platform":"抖音竖屏","genre":"都市悬疑","hook_type":"秘密证据","region":"中文","policy_notes":"无"}',
        encoding="utf-8",
    )
    project = Project(id=1, name="Brief locked", theme="A story", outline="", description="")
    report = StoryRoomQualityService().evaluate(project, [scene(1, "秘密证据出现。", "我看到了证据。")]).to_dict()

    assert report["signals"]["has_market_brief"] is True
    assert "market_brief" not in report["missing"]


def test_story_room_quality_requires_reversal_before_final_payoff():
    project = Project(
        name="Late twist",
        theme="都市悬疑女性受众抖音竖屏",
        outline="秘密证据引发危机，最后揭开真相。",
        description="platform: Douyin, audience: mystery viewers",
    )
    scenes = [
        scene(1, "她发现秘密证据，震惊。", "我必须保护孩子。"),
        scene(2, "反派威胁她交出证据，她拒绝。", "我不会交出来。"),
        scene(3, "她继续逃跑，局势更加危机。", "快走。"),
        scene(4, "她拿出文件准备离开。", "现在轮到我赢。"),
        scene(5, "原来反派才是真正继承人，身份反转。", "我赢了，真相终于揭开。"),
        scene(6, "电话响起，新的证据出现，未完。", "还有一个人没出现。"),
    ]

    report = StoryRoomQualityService().evaluate(project, scenes).to_dict()

    assert report["signals"]["has_reversal"] is True
    assert report["signals"]["reversal_scenes"] == [5]
    assert report["signals"]["beat_order_valid"] is False
    assert "beat_order" in report["missing"]


def test_story_room_quality_does_not_pass_with_a_missing_critical_beat():
    project = Project(
        name="No reversal",
        theme="都市悬疑女性受众抖音竖屏",
        outline="秘密证据引发危机，女主最终获得胜利并留下悬念。",
        description="platform: Douyin, audience: mystery viewers",
    )
    scenes = [
        scene(1, "她握紧秘密文件，震惊。", "我必须保护孩子。"),
        scene(2, "反派威胁她交出文件，她拒绝。", "我不会交出来。"),
        scene(3, "她撕掉协议，反派付出代价。", "我赢了。"),
        scene(4, "电话响起，新的证据出现，未完。", "还有一个人没出现。"),
    ]

    report = StoryRoomQualityService().evaluate(project, scenes).to_dict()

    assert report["status"] != "passed"
    assert report["signals"]["critical_missing"]
    assert "beat_order" in report["signals"]["critical_missing"]


def test_story_room_approval_freezes_current_story_snapshot(monkeypatch, tmp_path):
    from src.utils.storage import storage_manager

    monkeypatch.setattr(storage_manager, "get_project_path", lambda _id: tmp_path)
    project = Project(
        id=1,
        name="Approved drama",
        theme="都市复仇短剧，目标女性受众，抖音竖屏平台",
        outline="女主拿到背叛证据后逆袭，结尾保留下一集真相。",
        description="platform: Douyin vertical short drama, audience: romance revenge viewers",
    )
    scenes = [
        scene(1, "女主发现秘密证据，前夫威胁她闭嘴，震惊。", "你以为我还会怕你吗？"),
        scene(2, "她握紧录音笔，身份线索露出，害怕转为坚定。", "这次轮到我选择。"),
        scene(3, "家族会议上众人质问她，她拒绝交出证据，愤怒。", "证据在我手里。"),
        scene(4, "反派冷笑逼迫她签字，她当众撕掉协议。", "我不会再退。"),
        scene(5, "原来遗嘱揭露她的继承身份，全场震惊。", "现在谁该离开？"),
        scene(6, "母亲哭着承认误会，女主失望地后退。", "你早就知道？"),
        scene(7, "反派报警威胁，女主拿出第二份证据。", "真正该被带走的人是你。"),
        scene(8, "电话响起，新的真相出现，门被推开，未完。", "还有一个人没到场。"),
    ]
    service = StoryRoomQualityService()

    approval = service.freeze_approval(project, scenes, notes="approved", reviewer="producer")

    assert approval["status"] == "approved"
    assert approval["approved_by"] == "producer"
    saved = service.load_approval(1)
    assert saved["input_hash"] == service.input_signature(project, scenes)
    scenes[0].dialogue = "changed after approval"
    assert service.input_signature(project, scenes) != saved["input_hash"]
