from types import SimpleNamespace

from src.services.visual_style_assets import VisualStyleAssetService
from src.utils.storage import storage_manager


def _project(theme="都市复仇"):
    return SimpleNamespace(id=1, theme=theme, outline="女主拿到关键证据", description="")


def _scene(text="Alice waits in the office doorway.", location="office"):
    return SimpleNamespace(
        scene_number=1,
        visual_description=text,
        location=location,
        time_period="night",
    )


def test_visual_style_pack_freezes_and_detects_scene_style_changes(tmp_path, monkeypatch):
    monkeypatch.setattr(storage_manager, "base_path", tmp_path / "storage")
    service = VisualStyleAssetService()
    project = _project()
    scene = _scene()

    manifest = service.freeze_project_style(project, [scene], notes="approved look bible")

    assert manifest["status"] == "frozen"
    assert "vertical mobile short-drama look" in manifest["style_prompt"]
    assert "style drift between shots" in manifest["negative_prompt"]
    assert service.validate_project_style(project, [scene])["status"] == "valid"

    scene.visual_description = "Alice runs through a rainy parking garage."
    stale = service.validate_project_style(project, [scene])
    assert stale["status"] == "stale"
    assert "scene_style_hash" in stale["stale"]


def test_visual_style_pack_preserves_custom_prompts(tmp_path, monkeypatch):
    monkeypatch.setattr(storage_manager, "base_path", tmp_path / "storage")
    service = VisualStyleAssetService()
    project = _project()

    service.freeze_project_style(
        project,
        [_scene()],
        style_prompt="consistent premium red-and-teal short drama look",
        negative_prompt="random color grade",
    )

    assert service.style_prompt_for_project(project.id) == "consistent premium red-and-teal short drama look"
    assert service.negative_prompt_for_project(project.id) == "random color grade"
