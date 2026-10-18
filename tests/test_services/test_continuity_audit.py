from types import SimpleNamespace

from src.services.continuity_audit import ContinuityAuditService


def test_continuity_audit_reports_clean_adjacent_shots(monkeypatch):
    monkeypatch.setattr(
        "src.services.continuity_audit.VideoDirectorService.plan_scene",
        lambda _self, scene, *_args: SimpleNamespace(as_dict=lambda: {
            "shot_role": "dialogue_reaction",
            "spatial_plan": {
                "camera_axis": "fixed 180-degree screen direction",
                "character_positions": {scene.character_name: "frame left"},
                "prop_focus": "phone",
            },
        }),
    )
    project = SimpleNamespace(id=1, script="{}")
    scenes = [
        SimpleNamespace(scene_number=1, character_name="A", visual_description="A看手机", location="客厅"),
        SimpleNamespace(scene_number=2, character_name="A", visual_description="A继续看手机", location="客厅"),
    ]

    report = ContinuityAuditService().audit(project, scenes)

    assert report.status == "passed"
    assert report.pair_count == 1


def test_continuity_audit_flags_axis_jump(monkeypatch):
    axes = iter(["left-to-right", "right-to-left"])
    monkeypatch.setattr(
        "src.services.continuity_audit.VideoDirectorService.plan_scene",
        lambda *_args: SimpleNamespace(as_dict=lambda: {
            "shot_role": "dialogue_reaction",
            "spatial_plan": {"camera_axis": next(axes)},
        }),
    )
    project = SimpleNamespace(id=1, script="{}")
    scenes = [SimpleNamespace(scene_number=1, character_name="A", visual_description="A"), SimpleNamespace(scene_number=2, character_name="A", visual_description="A")]

    report = ContinuityAuditService().audit(project, scenes)

    assert report.status == "needs_review"
    assert report.issues[0]["code"] == "screen_direction_jump"
