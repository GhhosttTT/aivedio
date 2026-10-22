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


def test_find_old_files_is_read_only(tmp_path):
    manager = StorageManager(base_path=tmp_path / "storage")
    old = manager.base_path / "old.txt"
    fresh = manager.base_path / "fresh.txt"
    old.write_text("old", encoding="utf-8")
    fresh.write_text("fresh", encoding="utf-8")
    old_time = time.time() - 40 * 24 * 60 * 60
    os.utime(old, (old_time, old_time))

    found = manager.find_old_files(days=30)

    assert found == [old]
    assert old.exists() and fresh.exists()


def _run_cleanup(*args):
    import subprocess
    import sys
    from pathlib import Path

    repo = Path(__file__).resolve().parents[2]
    return subprocess.run(
        [sys.executable, str(repo / "scripts" / "cleanup_old_files.py"), *args],
        capture_output=True,
        text=True,
        cwd=repo,
    )


def test_cleanup_cli_defaults_to_dry_run(tmp_path):
    storage = tmp_path / "storage"
    old = storage / "old.txt"
    old.parent.mkdir()
    old.write_text("old", encoding="utf-8")
    old_time = time.time() - 40 * 24 * 60 * 60
    os.utime(old, (old_time, old_time))

    result = _run_cleanup("--days", "30", "--path", str(storage))

    assert result.returncode == 0, result.stderr
    assert "dry run" in result.stdout
    assert "old.txt" in result.stdout
    assert old.exists()


def test_cleanup_cli_apply_deletes_old_files(tmp_path):
    storage = tmp_path / "storage"
    old = storage / "old.txt"
    old.parent.mkdir()
    old.write_text("old", encoding="utf-8")
    old_time = time.time() - 40 * 24 * 60 * 60
    os.utime(old, (old_time, old_time))

    result = _run_cleanup("--days", "30", "--path", str(storage), "--apply")

    assert result.returncode == 0, result.stderr
    assert "deleted: 1" in result.stdout
    assert not old.exists()


def test_cleanup_cli_rejects_missing_storage_root(tmp_path):
    storage = tmp_path / "missing-storage"

    result = _run_cleanup("--path", str(storage))

    assert result.returncode == 2
    assert "does not exist" in result.stderr
    assert not storage.exists()


def test_cleanup_does_not_follow_symlinked_directories(tmp_path):
    if not hasattr(os, "symlink"):
        pytest.skip("symlinks are unavailable")
    manager = StorageManager(base_path=tmp_path / "storage")
    outside = tmp_path / "outside"
    outside.mkdir()
    outside_file = outside / "keep.txt"
    outside_file.write_text("outside", encoding="utf-8")
    old_time = time.time() - 40 * 24 * 60 * 60
    os.utime(outside_file, (old_time, old_time))
    try:
        (manager.base_path / "linked").symlink_to(outside, target_is_directory=True)
    except OSError as exc:
        pytest.skip(f"cannot create symlink: {exc}")

    manager.cleanup_old_files(days=30)

    assert outside_file.exists()
    assert (manager.base_path / "linked").is_symlink()
