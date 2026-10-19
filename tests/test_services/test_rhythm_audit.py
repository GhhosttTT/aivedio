from types import SimpleNamespace

from src.services.rhythm_audit import RhythmAuditService


def _scene(number, dialogue="", audio_duration=None):
    return SimpleNamespace(
        scene_number=number,
        visual_description="A person looks toward the door.",
        image_prompt="A person looks toward the door.",
        dialogue=dialogue,
        audio_duration=audio_duration,
    )


def test_rhythm_audit_uses_audio_duration_and_passes_with_reaction_room(monkeypatch):
    monkeypatch.setattr(
        "src.services.rhythm_audit.VideoDirectorService.plan_scene",
        lambda _self, scene, project_id=None: SimpleNamespace(
            shot_role="dialogue_reaction", target_duration_seconds=3.0
        ),
    )
    report = RhythmAuditService().audit(SimpleNamespace(id=1), [_scene(1, "你好", 1.8)])
    assert report.status == "passed"
    assert report.timeline[0]["duration_seconds"] == 3.0
    assert report.total_duration_seconds == 3.0
    assert report.editing_plan[0]["cut_type"] == "opening_hold"
    assert report.to_dict()["editing_plan"][0]["audio_strategy"] == "start_at_zero"


def test_rhythm_audit_blocks_dialogue_without_reaction_margin(monkeypatch):
    monkeypatch.setattr(
        "src.services.rhythm_audit.VideoDirectorService.plan_scene",
        lambda _self, scene, project_id=None: SimpleNamespace(
            shot_role="dialogue_reaction", target_duration_seconds=2.0
        ),
    )
    report = RhythmAuditService().audit(SimpleNamespace(id=1), [_scene(1, "你好", 1.9)])
    assert report.status == "needs_review"
    assert report.issues[0]["code"] == "dialogue_reaction_margin"
    assert report.repair_queue[0]["action"] == "refine_dialogue_audio_delivery"


def test_rhythm_audit_warns_on_repeated_shot_roles(monkeypatch):
    monkeypatch.setattr(
        "src.services.rhythm_audit.VideoDirectorService.plan_scene",
        lambda _self, scene, project_id=None: SimpleNamespace(
            shot_role="establishing", target_duration_seconds=2.0
        ),
    )
    report = RhythmAuditService().audit(SimpleNamespace(id=1), [_scene(1), _scene(2), _scene(3)])
    assert report.status == "warn"
    assert report.issues[0]["code"] == "repeated_shot_role"


def test_rhythm_audit_builds_motivated_cut_and_audio_plan(monkeypatch):
    roles = iter(["establishing", "dialogue_reaction", "emotion_reaction", "prop_interaction"])
    monkeypatch.setattr(
        "src.services.rhythm_audit.VideoDirectorService.plan_scene",
        lambda _self, scene, project_id=None: SimpleNamespace(
            shot_role=next(roles), target_duration_seconds=2.0, action_intensity="low"
        ),
    )
    report = RhythmAuditService().audit(SimpleNamespace(id=1), [_scene(index) for index in range(1, 5)])

    assert [item["cut_type"] for item in report.editing_plan] == [
        "opening_hold", "motivated_hard_cut", "reaction_cut", "match_cut_prop"
    ]
    assert report.editing_plan[1]["audio_strategy"] == "short_crossfade"
    assert report.editing_plan[0]["transition"] == {
        "video": "none", "duration_seconds": 0.0, "dialogue_protected": True
    }
    assert report.editing_plan[1]["transition"]["video"] == "crossfade"
    assert report.editing_plan[2]["transition"]["video"] == "hard_cut"
    assert report.editing_plan[3]["transition"]["dialogue_protected"] is True
    assert report.editing_plan[2]["audio_strategy"] == "hold_room_tone_then_dialogue"


def test_rhythm_audit_protects_dialogue_and_action_boundaries():
    assert RhythmAuditService._transition_contract("eyeline_cut", "dialogue_pre_lap", False) == {
        "video": "hard_cut", "duration_seconds": 0.0, "dialogue_protected": True
    }
    assert RhythmAuditService._transition_contract("location_cut", "room_tone_bridge", False)[
        "duration_seconds"
    ] <= 0.12


def test_rhythm_audit_enforces_locked_commercial_hook_timing(monkeypatch, tmp_path):
    monkeypatch.setattr(
        "src.services.rhythm_audit.TopicBriefService.load",
        lambda _self, _project_id: {"hook_type": "秘密证据曝光"},
    )
    monkeypatch.setattr(
        "src.services.rhythm_audit.VideoDirectorService.plan_scene",
        lambda _self, scene, project_id=None: SimpleNamespace(
            shot_role="story_shot", target_duration_seconds=3.0
        ),
    )
    scenes = [_scene(index) for index in range(1, 5)]
    scenes[-1].visual_description = "A secret evidence file is revealed."
    report = RhythmAuditService().audit(SimpleNamespace(id=1), scenes)

    assert report.hook_status == "needs_review"
    assert report.hook_latency_seconds == 9.0
    assert any(item["code"] == "late_opening_hook" for item in report.issues)


def test_rhythm_audit_does_not_require_hook_without_locked_brief(monkeypatch):
    monkeypatch.setattr(
        "src.services.rhythm_audit.TopicBriefService.load",
        lambda _self, _project_id: None,
    )
    monkeypatch.setattr(
        "src.services.rhythm_audit.VideoDirectorService.plan_scene",
        lambda _self, scene, project_id=None: SimpleNamespace(
            shot_role="story_shot", target_duration_seconds=2.0
        ),
    )
    report = RhythmAuditService().audit(SimpleNamespace(id=1), [_scene(1), _scene(2)])

    assert report.hook_status == "not_checked"
    assert not any(item["code"] == "late_opening_hook" for item in report.issues)


def test_rhythm_audit_uses_configured_thresholds(monkeypatch):
    monkeypatch.setattr("src.services.rhythm_audit.settings.GENERATION_RHYTHM_MIN_SHOT_SECONDS", 2.5)
    monkeypatch.setattr(
        "src.services.rhythm_audit.VideoDirectorService.plan_scene",
        lambda _self, scene, project_id=None: SimpleNamespace(
            shot_role="story_shot", target_duration_seconds=2.0
        ),
    )

    report = RhythmAuditService().audit(SimpleNamespace(id=1), [_scene(1)])

    assert report.status == "needs_review"
    assert report.thresholds["min_shot_seconds"] == 2.5
    assert report.issues[0]["code"] == "short_shot"
