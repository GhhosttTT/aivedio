"""Storage cleanup tests."""

import os
import time

import pytest

from src.utils.storage import StorageManager


def test_cleanup_removes_only_files_older_than_cutoff(tmp_path):
    manager = StorageManager(base_path=tmp_path / "storage")
    old = manager.base_path / "projects" / "1" / "old.txt"
    fresh = manager.base_path / "projects" / "1" / "fresh.txt"
    old.parent.mkdir(parents=True)
    old.write_text("old", encoding="utf-8")
    fresh.write_text("fresh", encoding="utf-8")
    old_time = time.time() - 40 * 24 * 60 * 60
    os.utime(old, (old_time, old_time))

    removed = manager.cleanup_old_files(days=30)

    assert removed == 1
    assert not old.exists()
    assert fresh.exists()


def test_cleanup_rejects_negative_age(tmp_path):
    manager = StorageManager(base_path=tmp_path / "storage")

    with pytest.raises(ValueError):
        manager.cleanup_old_files(days=-1)
