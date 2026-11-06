import json

import pytest
from pydantic import ValidationError

from src.database.models import Project, Scene
from src.models.shot_specification import ShotSpecification
from src.services.script_generator import ScriptGenerator, ScriptParseError
from src.services.video_director_service import VideoDirectorService


def test_script_specification_reaches_director_without_reinterpretation():
    specification = {
        "purpose": "Escalate the confrontation", "emotion": "controlled anger",
        "shot_role": "dialogue_reaction",
        "required_engine_capabilities": ["identity_reference", "performance_control"],
        "camera_movement": "locked camera", "camera_intensity": "low",
        "action_intensity": "low", "performance_intensity": 2,
        "duration_seconds": 3.0,
        "motion_reference_video": "D:/assets/motion/confrontation.mp4",
        "performance_reference_audio": "D:/assets/audio/confrontation.wav",
        "continuity_constraints": ["Knife stays in Alice's right hand"],
        "continuity_assets": [{"asset_id": "prop:knife", "kind": "prop", "start_state": {"holder": "Alice", "hand": "right"}, "end_state": {"holder": "Alice", "hand": "right"}}],
        "character_states": [{"character_name": "Alice", "start_state": "wet coat",
                              "end_state": "wet coat, one step closer"}],
    }
    parser = object.__new__(ScriptGenerator)
    parsed = parser._parse_scene_fields(
        "- 环境描述：rooftop\n- 人物描述：Alice runs forward\n"
        "- 出现角色：[Alice]\n- 镜头规格：" + json.dumps(specification)
    )
    parsed["scene_number"] = 1
    project = Project(script=json.dumps({"scenes": [parsed]}))
    scene = Scene(project=project, scene_number=1, visual_description=parsed["description"], dialogue="")

    plan = VideoDirectorService().plan_scene(scene, visible_characters=[{"name": "Alice"}])

    assert plan.action_intensity == "low"
    assert plan.shot_role == "dialogue_reaction"
    assert plan.required_engine_capabilities == ["identity_reference", "performance_control"]
    assert plan.target_duration_seconds == 3.0
    assert plan.camera_movement == "locked camera (camera intensity: low)"
    assert "controlled anger" in plan.director_prompt
    assert "wet coat, one step closer" in plan.director_prompt
    assert "Knife stays in Alice's right hand" in plan.continuity_priorities
    assert "wet coat, one step closer" in plan.end_frame_prompt
    assert "Knife stays in Alice's right hand" in plan.end_frame_prompt
    assert "Continuity asset prop:knife" in plan.director_prompt
    assert "prop:knife: holder=Alice, hand=right" in plan.end_frame_prompt
    assert "Temporal state at" in plan.temporal_keyframes[0]["prompt"]
    assert "wet coat" in plan.temporal_keyframes[0]["prompt"]
    assert "Continuity asset prop:knife" in plan.temporal_keyframes[0]["prompt"]
    assert "Knife stays in Alice's right hand" in plan.temporal_keyframes[0]["prompt"]
    assert plan.motion_reference_video == "D:/assets/motion/confrontation.mp4"
    assert plan.performance_reference_audio == "D:/assets/audio/confrontation.wav"
    assert plan.as_dict()["shot_spec"] == scene.shot_spec
    assert plan.as_dict()["required_engine_capabilities"] == ["identity_reference", "performance_control"]


def test_temporal_state_directive_preserves_declared_transition_without_inventing_values():
    specification = ShotSpecification.model_validate({
        "continuity_constraints": ["Wound remains on the left cheek"],
        "character_states": [{
            "character_name": "Alice",
            "emotion": "controlled anger",
            "start_state": "beside the door",
            "end_state": "one step closer to Bob",
        }],
        "continuity_assets": [{
            "asset_id": "prop:knife",
            "kind": "prop",
            "start_state": {"holder": "Alice", "hand": "right"},
            "end_state": {"holder": "Bob", "hand": "left"},
            "transition_note": "transfer only after eye contact",
        }],
    })

    early = specification.temporal_state_directive(0.32)
    late = specification.temporal_state_directive(0.68)

    assert "begins moving toward" in early
    assert "still closer to its start state" in early
    assert "is close to" in late
    assert "now closer to its end state" in late
    assert "transfer only after eye contact" in early
    assert "Wound remains on the left cheek" in late


@pytest.mark.parametrize("payload", [
    {"duration_seconds": True}, {"duration_seconds": float("nan")},
    {"performance_intensity": 6}, {"camera_intensity": "extreme"},
    {"continuity_constraints": [""]},
    {"character_states": [{"character_name": "Alice"}, {"character_name": "Alice"}]},
    {"continuity_assets": [{"asset_id": "prop:knife"}, {"asset_id": "prop:knife"}]},
    {"shot_role": "dialogue"},
    {"required_engine_capabilities": ["performance_control", "performance_control"]},
    {"required_engine_capabilities": ["unknown_control"]},
])
def test_invalid_specification_is_rejected(payload):
    with pytest.raises(ValidationError):
        ShotSpecification.model_validate(payload)


def test_legacy_script_emotion_and_purpose_are_preserved():
    parser = object.__new__(ScriptGenerator)
    parsed = parser._parse_scene_fields("- 故事节点：揭露秘密\n- 情感：惊慌\n- 人物描述：Alice waits")
    assert parsed["shot_spec"]["purpose"] == "揭露秘密"
    assert parsed["shot_spec"]["emotion"] == "惊慌"


def test_script_parser_fills_missing_dialogue_execution_contract():
    parser = object.__new__(ScriptGenerator)
    parsed = parser.parse_script(
        "【剧本】冲突\n【角色】\n- Alice：律师\n- Bob：经理\n【分镜】\n"
        "分镜1：\n- 环境描述：办公室\n- 人物描述：Alice 注视 Bob\n"
        "- 出现角色：[Alice, Bob]\n- 对话：你早就知道真相。\n- 说话人：Alice\n"
    )

    specification = parsed["scenes"][0]["shot_spec"]
    assert specification["shot_role"] == "dialogue_reaction"
    assert specification["action_intensity"] == "low"
    assert specification["required_engine_capabilities"] == [
        "identity_reference", "performance_control", "multi_character",
    ]


def test_script_parser_preserves_explicit_execution_contract():
    parser = object.__new__(ScriptGenerator)
    specification = {
        "shot_role": "emotion_reaction",
        "required_engine_capabilities": ["identity_reference", "performance_control"],
        "action_intensity": "low",
    }
    parsed = parser.parse_script(
        "【剧本】反应\n【角色】\n- Alice：律师\n【分镜】\n"
        "分镜1：\n- 人物描述：Alice 冲向门口\n- 出现角色：[Alice]\n- 对话：无\n"
        "- 镜头规格：" + json.dumps(specification)
    )

    assert parsed["scenes"][0]["shot_spec"]["shot_role"] == "emotion_reaction"
    assert parsed["scenes"][0]["shot_spec"]["required_engine_capabilities"] == [
        "identity_reference", "performance_control",
    ]


def test_action_dialogue_requires_performance_and_motion_control():
    parser = object.__new__(ScriptGenerator)
    parsed = parser.parse_script(
        "【剧本】追逐\n【角色】\n- Alice：记者\n【分镜】\n"
        "分镜1：\n- 人物描述：Alice 奔跑追逐嫌疑人\n- 出现角色：[Alice]\n"
        "- 对话：站住！\n- 说话人：Alice\n"
    )

    specification = parsed["scenes"][0]["shot_spec"]
    assert specification["shot_role"] == "action"
    assert specification["action_intensity"] == "high"
    assert specification["required_engine_capabilities"] == [
        "identity_reference", "performance_control", "motion_control",
    ]


def test_script_specification_rejects_states_for_non_visible_characters():
    parser = object.__new__(ScriptGenerator)
    specification = {"character_states": [{"character_name": "Bob", "start_state": "at the door"}]}

    with pytest.raises(ScriptParseError, match="不属于出现角色: Bob"):
        parser._parse_scene_fields(
            "- 出现角色：[Alice]\n- 镜头规格：" + json.dumps(specification)
        )


def test_script_specification_requires_visible_characters_for_states():
    parser = object.__new__(ScriptGenerator)
    specification = {"character_states": [{"character_name": "Alice", "start_state": "at the door"}]}

    with pytest.raises(ScriptParseError, match="必须填写出现角色"):
        parser._parse_scene_fields("- 镜头规格：" + json.dumps(specification))


def test_specified_duration_must_fit_video_workflow(monkeypatch):
    from src.config import settings
    monkeypatch.setattr(settings, "GENERATION_VIDEO_MAX_SECONDS", 2.0)
    project = Project(script=json.dumps({"scenes": [{"scene_number": 1, "shot_spec": {"duration_seconds": 5}}]}))
    scene = Scene(project=project, scene_number=1, visual_description="Alice waits", dialogue="")
    with pytest.raises(ValueError, match="duration capacity"):
        VideoDirectorService().plan_scene(scene)
