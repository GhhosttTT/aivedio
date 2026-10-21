"""CLI tests for scripts/create_default_admin.py."""

import os
import re
import subprocess
import sys
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.api.auth import verify_password
from src.database import Base
from src.database.models import User


REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "scripts" / "create_default_admin.py"


def _prepare_db(db_path: Path) -> None:
    engine = create_engine(f"sqlite:///{db_path}", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    engine.dispose()


def _run(db_path: Path, *args, **env_extra):
    env = os.environ.copy()
    env.pop("DEFAULT_ADMIN_PASSWORD", None)
    env.pop("DEFAULT_ADMIN_USERNAME", None)
    env.pop("DEFAULT_ADMIN_EMAIL", None)
    env["DATABASE_URL"] = f"sqlite:///{db_path}"
    env.update(env_extra)
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        cwd=REPO,
        env=env,
        capture_output=True,
        text=True,
    )


def _admin(db_path: Path) -> User:
    engine = create_engine(f"sqlite:///{db_path}", connect_args={"check_same_thread": False})
    db = sessionmaker(bind=engine)()
    try:
        return db.query(User).filter(User.username == "admin").one()
    finally:
        db.close()
        engine.dispose()


def test_uses_password_from_environment_without_echo(tmp_path):
    db_path = tmp_path / "admin.db"
    _prepare_db(db_path)

    result = _run(db_path, DEFAULT_ADMIN_PASSWORD="S3cure-Admin-Pass")

    assert result.returncode == 0, result.stderr + result.stdout
    assert "S3cure-Admin-Pass" not in result.stdout
    assert verify_password("S3cure-Admin-Pass", _admin(db_path).hashed_password)


def test_generates_and_prints_random_password_when_missing(tmp_path):
    db_path = tmp_path / "random.db"
    _prepare_db(db_path)

    result = _run(db_path)

    assert result.returncode == 0, result.stderr + result.stdout
    match = re.search(r"初始密码: (\S+)", result.stdout)
    assert match, result.stdout
    password = match.group(1)
    assert len(password) >= 12
    assert verify_password(password, _admin(db_path).hashed_password)


def test_reports_existing_admin_without_overwriting(tmp_path):
    db_path = tmp_path / "existing.db"
    _prepare_db(db_path)
    assert _run(db_path, DEFAULT_ADMIN_PASSWORD="first-password").returncode == 0
    first_hash = _admin(db_path).hashed_password

    result = _run(db_path, DEFAULT_ADMIN_PASSWORD="second-password")

    assert result.returncode == 0
    assert "已存在" in result.stdout
    assert _admin(db_path).hashed_password == first_hash


def test_help_exits_without_touching_database(tmp_path):
    db_path = tmp_path / "unused.db"

    result = _run(db_path, "--help")

    assert result.returncode == 0
    assert "usage" in result.stdout.lower()
    assert not db_path.exists()


def test_custom_username_and_email_from_arguments(tmp_path):
    db_path = tmp_path / "custom.db"
    _prepare_db(db_path)

    result = _run(
        db_path,
        "--username", "ops",
        "--email", "ops@example.com",
        DEFAULT_ADMIN_PASSWORD="S3cure-Admin-Pass",
    )

    assert result.returncode == 0, result.stderr + result.stdout
    engine = create_engine(f"sqlite:///{db_path}", connect_args={"check_same_thread": False})
    db = sessionmaker(bind=engine)()
    try:
        user = db.query(User).filter(User.username == "ops").one()
        assert user.email == "ops@example.com"
        assert verify_password("S3cure-Admin-Pass", user.hashed_password)
    finally:
        db.close()
        engine.dispose()
