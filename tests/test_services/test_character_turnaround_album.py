import json

from PIL import Image

from src.database.models import Character
from src.services.character_identity_service import CharacterIdentityService
from src.services.character_turnaround_album import CharacterTurnaroundAlbumService
from src.utils.storage import storage_manager


def _image(path, color):
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (32, 32), color).save(path)
    return str(path)


def test_turnaround_album_freezes_front_side_back_views(tmp_path, monkeypatch):
    monkeypatch.setattr(storage_manager, "base_path", tmp_path / "storage")
    spec = CharacterIdentityService().build_identity_spec("Alice", "lead", project_id=1)
    character = Character(
        id=7,
        project_id=1,
        name="Alice",
        appearance=spec["identity_anchor"],
        visual_description=json.dumps(spec),
    )
    views = {
        "front": _image(tmp_path / "front.png", "red"),
        "side": _image(tmp_path / "side.png", "green"),
        "back": _image(tmp_path / "back.png", "blue"),
    }
    service = CharacterTurnaroundAlbumService()

    album = service.freeze_album(character, views, notes="approved three-view")

    assert album["status"] == "frozen"
    assert album["required_views"] == ["front", "side", "back"]
    assert "strict side profile" in album["views"]["side"]["control_prompt"]
    assert album["views"]["front"]["expected_features"]["face_shape"] == spec["face_shape"]
    assert album["views"]["side"]["expected_features"]["nose_silhouette"] == spec["nose"]
    assert album["views"]["back"]["expected_features"]["outfit_back_silhouette"] == spec["wardrobe"]
    assert service.validate_album(character)["status"] == "valid"

    Image.new("RGB", (32, 32), "black").save(views["side"])
    stale = service.validate_album(character)
    assert stale["status"] == "stale"
    assert stale["stale"] == ["side"]


def test_turnaround_album_detects_changed_identity_spec(tmp_path, monkeypatch):
    monkeypatch.setattr(storage_manager, "base_path", tmp_path / "storage")
    spec = CharacterIdentityService().build_identity_spec("Alice", "lead", project_id=1)
    character = Character(id=7, project_id=1, name="Alice", visual_description=json.dumps(spec))
    views = {
        "front": _image(tmp_path / "front.png", "red"),
        "side": _image(tmp_path / "side.png", "green"),
        "back": _image(tmp_path / "back.png", "blue"),
    }
    service = CharacterTurnaroundAlbumService()
    service.freeze_album(character, views)

    changed = dict(spec)
    changed["hair"] = "different hair silhouette"
    character.visual_description = json.dumps(changed)

    stale = service.validate_album(character)
    assert stale["status"] == "stale"
    assert "identity_spec" in stale["stale"]
