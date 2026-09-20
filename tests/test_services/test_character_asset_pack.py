from pathlib import Path

import pytest
from PIL import Image

from src.services.character_identity_service import CharacterIdentityService
from src.services.character_service import CharacterManager


def test_character_asset_pack_freezes_identity_and_reference_hashes(tmp_path):
    source = tmp_path / "source.png"
    Image.new("RGB", (32, 32), "blue").save(source)
    manager = CharacterManager(base_dir=str(tmp_path / "characters"))
    spec = CharacterIdentityService().build_identity_spec("林安", "女主", project_id=1)

    saved = manager.save_character_reference(10, 1, str(source))
    manifest = manager.freeze_character_asset_pack(
        character_id=10,
        project_id=1,
        identity_spec=spec,
        distinctiveness={"status": "passed"},
        notes="approved closeup",
    )

    assert manifest["status"] == "frozen"
    assert manifest["reference_paths"] == [saved]
    assert Path(tmp_path / "characters" / "1" / "10" / "asset_pack.json").is_file()
    assert manager.validate_character_asset_pack(10, 1, spec)["status"] == "valid"

    Image.new("RGB", (32, 32), "red").save(saved)
    stale = manager.validate_character_asset_pack(10, 1, spec)
    assert stale["status"] == "stale"
    assert saved in stale["stale"]


def test_character_asset_pack_detects_changed_identity_spec(tmp_path):
    source = tmp_path / "source.png"
    Image.new("RGB", (32, 32), "blue").save(source)
    manager = CharacterManager(base_dir=str(tmp_path / "characters"))
    service = CharacterIdentityService()
    spec = service.build_identity_spec("林安", "女主", project_id=1)
    changed = dict(spec)
    changed["eyes"] = "different eye shape"

    manager.save_character_reference(10, 1, str(source))
    manager.freeze_character_asset_pack(10, 1, spec, {"status": "passed"})

    stale = manager.validate_character_asset_pack(10, 1, changed)
    assert stale["status"] == "stale"
    assert "identity_spec" in stale["stale"]


def test_character_asset_pack_requires_distinctiveness_pass(tmp_path):
    source = tmp_path / "source.png"
    Image.new("RGB", (32, 32), "blue").save(source)
    manager = CharacterManager(base_dir=str(tmp_path / "characters"))
    spec = CharacterIdentityService().build_identity_spec("林安", "女主", project_id=1)

    manager.save_character_reference(10, 1, str(source))

    with pytest.raises(ValueError, match="distinctiveness"):
        manager.freeze_character_asset_pack(10, 1, spec, {"status": "needs_revision"})
