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
