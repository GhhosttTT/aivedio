"""CLI tests for scripts/init_database.py."""

import os
import sqlite3
import subprocess
import sys
from pathlib import Path


REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "scripts" / "init_database.py"


def _run(db_path: Path, *args, stdin=None):
    env = os.environ.copy()
    env["DATABASE_URL"] = f"sqlite:///{db_path}"
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        cwd=REPO,
        env=env,
        stdin=stdin,
        capture_output=True,
        text=True,
    )


def _tables(db_path: Path) -> set[str]:
    with sqlite3.connect(db_path) as connection:
        return {
            row[0]
            for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }


def test_create_builds_tables_without_prompt(tmp_path):
    db_path = tmp_path / "created.db"

    result = _run(db_path, "--create")

    assert result.returncode == 0, result.stderr + result.stdout
    assert {"projects", "tasks", "users"} <= _tables(db_path)


def test_reset_rebuilds_tables_with_yes(tmp_path):
    db_path = tmp_path / "reset.db"
    assert _run(db_path, "--create").returncode == 0

    result = _run(db_path, "--reset", "--yes")

    assert result.returncode == 0, result.stderr + result.stdout
    assert {"projects", "tasks"} <= _tables(db_path)


def test_eof_without_action_returns_usage_hint(tmp_path):
    result = _run(tmp_path / "eof.db", stdin=subprocess.DEVNULL)

    assert result.returncode == 2
    assert "--create" in result.stdout
