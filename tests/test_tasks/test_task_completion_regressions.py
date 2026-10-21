from concurrent.futures import ThreadPoolExecutor
import json
import sys
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from celery.app.autoretry import add_autoretry_behaviour
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.database.models import Base, Project, ProjectStatus, Task, TaskStatus, User
from src.services.comfyui_service import ComfyUIWaitTimeout
from src.services.generation_review import ReviewError
from src.services.generation_provider import GenerationProviderError
from src.api.websocket import TASK_EVENT_CHANNEL, publish_project_event
from src.tasks.celery_app import BaseTask, _broadcast_task_event


def test_task_event_bridge_delivers_without_leaking_asyncio_state(monkeypatch):
    publish = Mock(return_value=True)
    monkeypatch.setattr("src.api.websocket.publish_project_event", publish)

    _broadcast_task_event(7, {"type": "progress_update", "progress": 0.5})

    publish.assert_called_once_with(7, {"type": "progress_update", "progress": 0.5})


def test_project_event_publisher_uses_shared_redis_channel(monkeypatch):
    published = []

    class FakeRedis:
        def publish(self, channel, payload):
            published.append((channel, json.loads(payload)))

        def close(self):
            pass

    monkeypatch.setitem(sys.modules, "redis", SimpleNamespace(from_url=lambda *args, **kwargs: FakeRedis()))

    assert publish_project_event(7, {"type": "completion", "progress": 1.0}) is True
    assert published == [(
        TASK_EVENT_CHANNEL,
        {"project_id": 7, "message": {"type": "completion", "progress": 1.0}},
    )]


@pytest.mark.parametrize("error", [
    ComfyUIWaitTimeout("job may still be active"),
    ReviewError("face identity failed"),
    GenerationProviderError("provider task failed after bounded retries"),
    ValueError("split this shot"),
])
def test_nonretryable_generation_failures_do_not_resubmit_gpu_work(error):
    class ProbeTask(BaseTask):
        name = "retry_probe"

        def run(self):
            raise error

    task = ProbeTask()
    task.retry = Mock(side_effect=AssertionError("must not retry"))
    add_autoretry_behaviour(task)
    with pytest.raises(type(error)):
        task.run()
    task.retry.assert_not_called()


def test_concurrent_success_callbacks_count_every_completed_step(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'progress.db'}", connect_args={"timeout": 30})
    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine)
    db = sessions()
    user = User(username="progress", email="progress@example.com", hashed_password="test")
    db.add(user)
    db.flush()
    project = Project(name="repair", user_id=user.id, status=ProjectStatus.IN_PRODUCTION)
    db.add(project)
    db.flush()
    record = Task(project_id=project.id, celery_task_id="repair", status=TaskStatus.RUNNING, total_steps=12, current_step=0)
    db.add(record)
    db.commit()
    record_id = record.id
    monkeypatch.setattr("src.database.session.get_db_session", lambda: iter([sessions()]))

    def completed(_index):
        task = BaseTask()
        task._production_record = lambda _args, _kwargs, session: session.get(Task, record_id)
        task.on_success({}, "step", (), {})

    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(completed, range(12)))
    db.expire_all()
    assert db.get(Task, record_id).current_step == 12
    assert db.get(Task, record_id).progress == 100.0
    assert db.get(Task, record_id).status == TaskStatus.COMPLETED
    assert db.get(Project, project.id).status == ProjectStatus.SCRIPT_GENERATED
    db.close()
    engine.dispose()


def test_cancelled_task_failure_releases_project_and_broadcasts_terminal_state(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'cancel.db'}")
    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine)
    db = sessions()
    user = User(username="cancel", email="cancel@example.com", hashed_password="test")
    db.add(user)
    db.flush()
    project = Project(name="cancelled", user_id=user.id, status=ProjectStatus.IN_PRODUCTION)
    db.add(project)
    db.flush()
    record = Task(
        project_id=project.id,
        celery_task_id="cancelled-task",
        status=TaskStatus.CANCELLED,
        total_steps=4,
    )
    db.add(record)
    db.commit()
    record_id = record.id
    events = []
    monkeypatch.setattr("src.database.session.get_db_session", lambda: iter([sessions()]))
    monkeypatch.setattr("src.tasks.celery_app._broadcast_task_event", lambda project_id, message: events.append((project_id, message)))

    task = BaseTask()
    task._production_record = lambda _args, _kwargs, session: session.get(Task, record_id)
    task.on_failure(RuntimeError("cancelled"), "cancelled-task", (), {}, None)

    db.expire_all()
    assert db.get(Project, project.id).status == ProjectStatus.SCRIPT_GENERATED
    assert events[0][1]["status"] == "cancelled"
    db.close()
    engine.dispose()


def test_project_event_publisher_reuses_redis_connection(monkeypatch):
    created = []

    class FakeRedis:
        def publish(self, channel, payload):
            return 1

        def close(self):
            pass

    def from_url(*args, **kwargs):
        client = FakeRedis()
        created.append(client)
        return client

    monkeypatch.setitem(sys.modules, "redis", SimpleNamespace(from_url=from_url))

    assert publish_project_event(7, {"type": "a"}) is True
    assert publish_project_event(7, {"type": "b"}) is True
    assert len(created) == 1


def test_task_callbacks_swallow_database_failures(monkeypatch):
    def broken_session():
        raise RuntimeError("database unavailable")

    monkeypatch.setattr("src.database.session.get_db_session", broken_session)
    task = BaseTask()

    task.on_failure(RuntimeError("original"), "task-1", (), {}, None)
    task.on_success({}, "task-1", (), {})


def test_before_start_swallows_database_failures(monkeypatch):
    def broken_session():
        raise RuntimeError("database unavailable")

    monkeypatch.setattr("src.database.session.get_db_session", broken_session)
    task = BaseTask()

    task.before_start("task-1", (), {})
