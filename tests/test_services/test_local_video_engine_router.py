import json

import pytest

from src.services.local_video_engine_router import (
    evaluate_local_video_engine_fleet,
    LocalVideoEngineRoutingError,
    load_local_video_engine_registry,
    rank_local_video_engine_routes,
    select_local_video_engine,
)


def _engine(engine_id, workflow_path, *, capabilities, priority=0):
    return {
        "id": engine_id,
        "model_profile": engine_id,
        "workflow_path": str(workflow_path),
        "bindings_path": None,
        "capabilities": capabilities,
        "priority": priority,
    }


def test_temporal_shot_routes_to_keyframe_capable_engine(tmp_path):
    wan = tmp_path / "wan.json"
    ltx = tmp_path / "ltx.json"
    wan.write_text("{}", encoding="utf-8")
    ltx.write_text("{}", encoding="utf-8")
    engines = [
        _engine("wan", wan, capabilities={"identity_reference": True}, priority=20),
        _engine(
            "ltx", ltx,
            capabilities={"temporal_keyframes": True, "motion_control": True},
            priority=10,
        ),
    ]

    route = select_local_video_engine(
        engines,
        shot_plan={"shot_role": "action", "action_intensity": "high"},
        has_temporal_keyframes=True,
    )

    assert route.engine_id == "ltx"
    assert route.selection_reasons == (
        "required:temporal_keyframes",
        "required:motion_control",
    )


def test_dialogue_shot_prefers_identity_and_performance_capabilities(tmp_path):
    generic = tmp_path / "generic.json"
    performance = tmp_path / "performance.json"
    generic.write_text("{}", encoding="utf-8")
    performance.write_text("{}", encoding="utf-8")
    engines = [
        _engine("generic", generic, capabilities={}, priority=100),
        _engine(
            "performance", performance,
            capabilities={"identity_reference": True, "performance_control": True},
            priority=1,
        ),
    ]

    route = select_local_video_engine(
        engines,
        shot_plan={"shot_role": "dialogue_reaction", "visible_character_count": 1},
        has_temporal_keyframes=False,
    )

    assert route.engine_id == "performance"
    assert route.selection_reasons == (
        "required:identity_reference",
        "required:performance_control",
    )
    assert route.requested_capabilities == (
        "identity_reference",
        "performance_control",
    )
    assert route.unmet_preferences == ()


def test_ranked_routes_expose_all_executable_engines_by_priority(tmp_path):
    first = tmp_path / "first.json"
    second = tmp_path / "second.json"
    first.write_text("{}", encoding="utf-8")
    second.write_text("{}", encoding="utf-8")
    engines = [
        _engine("second", second, capabilities={"identity_reference": True}, priority=10),
        _engine("first", first, capabilities={"identity_reference": True}, priority=20),
    ]

    routes = rank_local_video_engine_routes(
        engines,
        shot_plan={"visible_character_count": 1},
        has_temporal_keyframes=False,
    )

    assert [route.engine_id for route in routes] == ["first", "second"]


def test_explicit_shot_capabilities_survive_role_inference(tmp_path):
    generic = tmp_path / "generic.json"
    controlled = tmp_path / "controlled.json"
    generic.write_text("{}", encoding="utf-8")
    controlled.write_text("{}", encoding="utf-8")
    engines = [
        _engine("generic", generic, capabilities={}, priority=100),
        _engine(
            "controlled", controlled,
            capabilities={"identity_reference": True, "performance_control": True},
            priority=1,
        ),
    ]

    route = select_local_video_engine(
        engines,
        shot_plan={
            "shot_role": "establishing",
            "required_engine_capabilities": ["identity_reference", "performance_control"],
        },
        has_temporal_keyframes=False,
    )

    assert route.engine_id == "controlled"
    assert route.requested_capabilities == ("identity_reference", "performance_control")


def test_explicit_shot_capabilities_reject_unknown_names(tmp_path):
    workflow = tmp_path / "generic.json"
    workflow.write_text("{}", encoding="utf-8")

    with pytest.raises(LocalVideoEngineRoutingError, match="unknown required engine capabilities"):
        select_local_video_engine(
            [_engine("generic", workflow, capabilities={})],
            shot_plan={"required_engine_capabilities": ["lip_magic"]},
            has_temporal_keyframes=False,
        )


def test_router_skips_avatar_without_performance_audio(tmp_path):
    avatar = tmp_path / "avatar.json"
    custom = tmp_path / "custom.json"
    avatar.write_text("{}", encoding="utf-8")
    custom.write_text("{}", encoding="utf-8")
    engines = [
        {
            **_engine(
                "avatar", avatar,
                capabilities={"identity_reference": True, "performance_control": True},
                priority=100,
            ),
            "model_profile": "hunyuanvideo_avatar",
        },
        {
            **_engine(
                "custom", custom,
                capabilities={"identity_reference": True, "performance_control": True},
                priority=1,
            ),
            "model_profile": "hunyuan_custom",
        },
    ]

    route = select_local_video_engine(
        engines,
        shot_plan={
            "required_engine_capabilities": ["identity_reference", "performance_control"],
            "has_motion_reference_video": True,
        },
        has_temporal_keyframes=False,
    )

    assert route.engine_id == "custom"


def test_router_reports_missing_native_conditioning_input(tmp_path):
    avatar = tmp_path / "avatar.json"
    avatar.write_text("{}", encoding="utf-8")
    engine = {
        **_engine(
            "avatar", avatar,
            capabilities={"identity_reference": True, "performance_control": True},
        ),
        "model_profile": "hunyuanvideo_avatar",
    }

    with pytest.raises(LocalVideoEngineRoutingError, match="inputs performance_audio"):
        select_local_video_engine(
            [engine],
            shot_plan={
                "required_engine_capabilities": ["identity_reference", "performance_control"],
            },
            has_temporal_keyframes=False,
        )


def test_establishing_shot_does_not_prefer_identity_engine_without_characters(tmp_path):
    generic = tmp_path / "generic.json"
    identity = tmp_path / "identity.json"
    generic.write_text("{}", encoding="utf-8")
    identity.write_text("{}", encoding="utf-8")
    engines = [
        _engine("generic", generic, capabilities={}, priority=20),
        _engine("identity", identity, capabilities={"identity_reference": True}, priority=1),
    ]

    route = select_local_video_engine(
        engines,
        shot_plan={"shot_role": "establishing", "visible_character_count": 0},
        has_temporal_keyframes=False,
    )

    assert route.engine_id == "generic"
    assert route.selection_reasons == ("fallback:priority",)
    assert route.requested_capabilities == ()


def test_establishing_shot_excludes_high_priority_dialogue_specialist(tmp_path):
    generic = tmp_path / "generic.json"
    avatar = tmp_path / "avatar.json"
    generic.write_text("{}", encoding="utf-8")
    avatar.write_text("{}", encoding="utf-8")
    engines = [
        {
            **_engine(
                "avatar", avatar,
                capabilities={
                    "identity_reference": True,
                    "performance_control": True,
                    "multi_character": True,
                },
                priority=100,
            ),
            "model_profile": "hunyuanvideo_avatar",
        },
        {
            **_engine("generic", generic, capabilities={}, priority=1),
            "model_profile": "wan_2_2_i2v_14b",
        },
    ]

    routes = rank_local_video_engine_routes(
        engines,
        shot_plan={"shot_role": "establishing", "visible_character_count": 0},
        has_temporal_keyframes=False,
    )

    assert [route.engine_id for route in routes] == ["generic"]


def test_hunyuan_custom_can_cover_multi_character_action_dialogue(tmp_path):
    workflow = tmp_path / "custom.json"
    workflow.write_text("{}", encoding="utf-8")
    engine = {
        **_engine(
            "custom", workflow,
            capabilities={
                "identity_reference": True,
                "performance_control": True,
                "multi_character": True,
                "motion_control": True,
            },
        ),
        "model_profile": "hunyuan_custom",
    }

    route = select_local_video_engine(
        [engine],
        shot_plan={
            "shot_role": "action",
            "visible_character_count": 2,
            "required_engine_capabilities": [
                "identity_reference", "performance_control",
                "multi_character", "motion_control",
            ],
            "has_performance_audio": True,
            "has_motion_reference_video": True,
        },
        has_temporal_keyframes=False,
    )

    assert route.engine_id == "custom"
    assert route.requested_capabilities == (
        "identity_reference", "performance_control", "multi_character", "motion_control",
    )


def test_route_blocks_unmet_short_drama_requirements(tmp_path):
    workflow = tmp_path / "identity.json"
    workflow.write_text("{}", encoding="utf-8")

    with pytest.raises(LocalVideoEngineRoutingError, match="performance_control, multi_character"):
        select_local_video_engine(
            [_engine("identity", workflow, capabilities={"identity_reference": True})],
            shot_plan={
                "shot_role": "dialogue_reaction",
                "visible_character_count": 2,
            },
            has_temporal_keyframes=False,
        )


def test_short_drama_fleet_coverage_requires_capability_combinations(tmp_path):
    workflow = tmp_path / "workflow.json"
    workflow.write_text("{}", encoding="utf-8")
    engines = [
        _engine(
            "dialogue", workflow,
            capabilities={
                "identity_reference": True,
                "performance_control": True,
                "multi_character": True,
            },
        ),
        _engine(
            "motion", workflow,
            capabilities={
                "identity_reference": True,
                "motion_control": True,
            },
        ),
    ]

    report = evaluate_local_video_engine_fleet(
        engines, temporal_keyframes_required=True
    )

    assert report["passed"] is False
    assert report["missing_profiles"] == ["temporal_character_motion"]

    engines[1]["capabilities"]["temporal_keyframes"] = True
    report = evaluate_local_video_engine_fleet(
        engines, temporal_keyframes_required=True
    )
    assert report["passed"] is True


def test_temporal_shot_fails_when_registry_has_no_capable_engine(tmp_path):
    workflow = tmp_path / "wan.json"
    workflow.write_text("{}", encoding="utf-8")

    with pytest.raises(LocalVideoEngineRoutingError, match="temporal_keyframes"):
        select_local_video_engine(
            [_engine("wan", workflow, capabilities={})],
            shot_plan={"shot_role": "action"},
            has_temporal_keyframes=True,
        )


def test_registry_resolves_paths_relative_to_registry(tmp_path):
    workflow = tmp_path / "ltx.json"
    bindings = tmp_path / "ltx.bindings.json"
    workflow.write_text("{}", encoding="utf-8")
    bindings.write_text("{}", encoding="utf-8")
    registry = tmp_path / "registry.json"
    registry.write_text(json.dumps({
        "engines": [{
            "id": "ltx",
            "model_profile": "ltx_2_keyframes",
            "workflow_path": "ltx.json",
            "bindings_path": "ltx.bindings.json",
            "capabilities": {"temporal_keyframes": True},
        }],
    }), encoding="utf-8")

    loaded = load_local_video_engine_registry(registry)

    assert loaded[0]["workflow_path"] == str(workflow.resolve())
    assert loaded[0]["bindings_path"] == str(bindings.resolve())


def test_registry_rejects_unknown_capability_name(tmp_path):
    workflow = tmp_path / "ltx.json"
    workflow.write_text("{}", encoding="utf-8")
    registry = tmp_path / "registry.json"
    registry.write_text(json.dumps({
        "engines": [{
            "id": "ltx",
            "workflow_path": "ltx.json",
            "capabilities": {"temporal_keyframe": True},
        }],
    }), encoding="utf-8")

    with pytest.raises(LocalVideoEngineRoutingError, match="unknown capabilities"):
        load_local_video_engine_registry(registry)


def test_registry_rejects_string_capability_boolean(tmp_path):
    workflow = tmp_path / "wan.json"
    workflow.write_text("{}", encoding="utf-8")
    registry = tmp_path / "registry.json"
    registry.write_text(json.dumps({
        "engines": [{
            "id": "wan",
            "workflow_path": "wan.json",
            "capabilities": {"identity_reference": "false"},
        }],
    }), encoding="utf-8")

    with pytest.raises(LocalVideoEngineRoutingError, match="JSON booleans"):
        load_local_video_engine_registry(registry)


def test_registry_rejects_capabilities_outside_model_profile(tmp_path):
    workflow = tmp_path / "wan.json"
    workflow.write_text("{}", encoding="utf-8")
    registry = tmp_path / "registry.json"
    registry.write_text(json.dumps({
        "engines": [{
            "id": "generic-wan",
            "model_profile": "wan_2_2_i2v_14b",
            "workflow_path": "wan.json",
            "capabilities": {
                "identity_reference": True,
                "performance_control": True,
            },
        }],
    }), encoding="utf-8")

    with pytest.raises(LocalVideoEngineRoutingError, match="cannot declare: performance_control"):
        load_local_video_engine_registry(registry)


def test_registry_requires_explicit_supported_model_profile(tmp_path):
    workflow = tmp_path / "custom.json"
    workflow.write_text("{}", encoding="utf-8")
    registry = tmp_path / "registry.json"
    registry.write_text(json.dumps({
        "engines": [{
            "id": "custom",
            "model_profile": "auto",
            "workflow_path": "custom.json",
            "capabilities": {},
        }],
    }), encoding="utf-8")

    with pytest.raises(LocalVideoEngineRoutingError, match="supported explicit model_profile"):
        load_local_video_engine_registry(registry)
