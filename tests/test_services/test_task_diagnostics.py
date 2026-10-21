"""Tests for stale task discovery and explicit cleanup."""

from datetime import datetime, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.database import Base
from src.database.models import Project, Task, TaskStatus, User
from src.services.task_diagnostics import find_stale_tasks, mark_stale_tasks_failed


@pytest.fixture()
def db_session(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'tasks.db'}",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(bind=engine)
    factory = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    db = factory()
    try:
        yield db
    finally:
        db.close()
        Base.metadata.drop_all(bind=engine)


def _seed(db_session, now):
    user = User(username="stale-user", email="stale@example.com", hashed_password="x")
    db_session.add(user)
    db_session.commit()
    project = Project(name="stale project", user_id=user.id)
    db_session.add(project)
    db_session.commit()

    def add(celery_id, status, hours_ago):
        task = Task(
            project_id=project.id,
            celery_task_id=celery_id,
            status=status,
            total_steps=1,
            updated_at=now - timedelta(hours=hours_ago),
        )
        db_session.add(task)
        return task

    add("pending-old", TaskStatus.PENDING, 7)
    add("running-old", TaskStatus.RUNNING, 8)
    add("running-fresh", TaskStatus.RUNNING, 1)
    add("completed-old", TaskStatus.COMPLETED, 10)
    add("failed-old", TaskStatus.FAILED, 9)
    db_session.commit()
    return project


def test_find_stale_tasks_only_returns_old_pending_or_running(db_session):
    now = datetime(2026, 1, 1, 12, 0, 0)
    project = _seed(db_session, now)

    tasks = find_stale_tasks(db_session, older_than_hours=6, now=now)

    assert [task.celery_task_id for task in tasks] == ["running-old", "pending-old"]
    assert find_stale_tasks(db_session, older_than_hours=6, now=now, project_ids=[project.id + 1]) == []


def test_mark_stale_tasks_failed_keeps_other_statuses(db_session):
    now = datetime(2026, 1, 1, 12, 0, 0)
    _seed(db_session, now)

    count = mark_stale_tasks_failed(db_session, older_than_hours=6, now=now)

    assert count == 2
    statuses = {
        task.celery_task_id: task.status
        for task in db_session.query(Task).all()
    }
    assert statuses["pending-old"] == TaskStatus.FAILED
    assert statuses["running-old"] == TaskStatus.FAILED
    assert statuses["running-fresh"] == TaskStatus.RUNNING
    assert statuses["completed-old"] == TaskStatus.COMPLETED
    assert statuses["failed-old"] == TaskStatus.FAILED
    stale = db_session.query(Task).filter(Task.celery_task_id == "running-old").one()
    assert "小时未更新" in stale.error_message
    assert find_stale_tasks(db_session, older_than_hours=6, now=now) == []


def test_stale_threshold_must_be_positive(db_session):
    with pytest.raises(ValueError):
        find_stale_tasks(db_session, older_than_hours=0, now=datetime.utcnow())


def test_cli_reports_and_applies_stale_tasks(tmp_path):
    import json
    import os
    import subprocess
    import sys
    from pathlib import Path

    db_path = tmp_path / "cli.db"
    engine = create_engine(f"sqlite:///{db_path}", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    factory = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    db = factory()
    try:
        user = User(username="cli-user", email="cli@example.com", hashed_password="x")
        db.add(user)
        db.commit()
        project = Project(name="cli project", user_id=user.id)
        db.add(project)
        db.commit()
        stale = Task(
            project_id=project.id,
            celery_task_id="cli-stale",
            status=TaskStatus.RUNNING,
            total_steps=1,
            updated_at=datetime.utcnow() - timedelta(hours=10),
        )
        db.add(stale)
        db.commit()
    finally:
        db.close()
        engine.dispose()

    repo = Path(__file__).resolve().parents[2]
    env = os.environ.copy()
    env["DATABASE_URL"] = f"sqlite:///{db_path}"
    base = [sys.executable, str(repo / "scripts" / "recover_stale_tasks.py"), "--older-than-hours", "6"]

    report = subprocess.run(base + ["--json"], capture_output=True, text=True, env=env, cwd=repo)
    assert report.returncode == 0, report.stderr
    rows = json.loads(report.stdout)
    assert [row["celery_task_id"] for row in rows] == ["cli-stale"]

    applied = subprocess.run(base + ["--apply"], capture_output=True, text=True, env=env, cwd=repo)
    assert applied.returncode == 0, applied.stderr
    assert "marked 1 task(s) failed" in applied.stdout

    engine = create_engine(f"sqlite:///{db_path}", connect_args={"check_same_thread": False})
    db = sessionmaker(bind=engine)()
    try:
        assert db.query(Task).filter(Task.celery_task_id == "cli-stale").one().status == TaskStatus.FAILED
    finally:
        db.close()
        engine.dispose()
