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
    assert "reversal" in report["missing"]
    assert "ending_hook" in report["missing"]
    assert report["rewrite_actions"]


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
    assert report["signals"]["early_hook"] is True
    assert report["signals"]["has_reversal"] is True
    assert report["signals"]["ending_hook"] is True
