"""Character reference storage tests."""

import pytest

from src.services.character_service import CharacterManager


def test_save_character_reference_is_atomic(tmp_path):
    manager = CharacterManager(base_dir=tmp_path / "characters")
    source = tmp_path / "source.png"
    source.write_bytes(b"png-bytes")

    saved = manager.save_character_reference(7, 3, str(source), "lead")

    target = tmp_path / "characters" / "3" / "7" / "reference_1.png"
    assert saved == str(target)
    assert target.read_bytes() == b"png-bytes"
    assert not list(target.parent.glob("*.part"))


def test_save_character_reference_cleans_up_on_copy_failure(tmp_path, monkeypatch):
    manager = CharacterManager(base_dir=tmp_path / "characters")
    source = tmp_path / "source.png"
    source.write_bytes(b"png-bytes")

    def fail_copy(*args, **kwargs):
        raise OSError("disk full")

    monkeypatch.setattr("shutil.copy2", fail_copy)
    with pytest.raises(OSError):
        manager.save_character_reference(7, 3, str(source), "lead")

    char_dir = tmp_path / "characters" / "3" / "7"
    assert not (char_dir / "reference_1.png").exists()
    assert not list(char_dir.glob("*.part"))
