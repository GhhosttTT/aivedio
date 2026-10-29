from concurrent.futures import ThreadPoolExecutor
import json
import sys
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from celery.app.autoretry import add_autoretry_behaviour
from celery.exceptions import Ignore
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.orm.attributes import set_committed_value

from src.database.models import Base, Project, ProjectStatus, Task, TaskStatus, User
from src.services.comfyui_service import ComfyUIWaitTimeout
from src.services.generation_review import ReviewError
from src.services.generation_provider import GenerationProviderError
from src.api.websocket import TASK_EVENT_CHANNEL, publish_project_event
from src.tasks.celery_app import BaseTask, _broadcast_task_event


@pytest.fixture
def task_state_case(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'state.db'}")
    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine)
    db = sessions()
    user = User(username="state", email="state@example.com", hashed_password="test")
    db.add(user)
    db.flush()
    project = Project(name="state", user_id=user.id, status=ProjectStatus.IN_PRODUCTION)
    db.add(project)
    db.flush()
    old = Task(project_id=project.id, celery_task_id="old", status=TaskStatus.CANCELLED, total_steps=2)
    db.add(old)
    db.commit()
    monkeypatch.setattr("src.database.session.get_db_session", lambda: iter([sessions()]))
    monkeypatch.setattr("src.tasks.celery_app._broadcast_task_event", lambda *_args: None)
    task = BaseTask()
    task._production_record = lambda _args, _kwargs, session: session.get(Task, old.id)
    yield db, project, old, task
    db.close()
    engine.dispose()


@pytest.mark.parametrize("old_status", [TaskStatus.CANCELLED, TaskStatus.FAILED, TaskStatus.COMPLETED])
@pytest.mark.parametrize("hook", ["before_start", "on_failure", "on_success"])
def test_old_terminal_callbacks_cannot_change_new_project_run(task_state_case, old_status, hook):
    db, project, old, task = task_state_case
    old.status = old_status
    current = Task(project_id=project.id, celery_task_id="new", status=TaskStatus.RUNNING, total_steps=2)
    db.add(current)
    db.commit()
    if hook == "before_start":
        with pytest.raises(Ignore):
            task.before_start("old-step", (), {})
    elif hook == "on_failure":
        task.on_failure(RuntimeError("late failure"), "old-step", (), {}, None)
    else:
        task.on_success({}, "old-step", (), {})
    db.expire_all()
    assert db.get(Project, project.id).status == ProjectStatus.IN_PRODUCTION
    assert db.get(Task, current.id).status == TaskStatus.RUNNING
    assert db.get(Task, old.id).status == old_status


@pytest.mark.parametrize("hook", ["on_success", "on_failure"])
def test_late_running_callback_cannot_release_or_fail_new_project(task_state_case, hook):
    db, project, old, task = task_state_case
    old.status = TaskStatus.RUNNING
    old.current_step = 1
    current = Task(project_id=project.id, celery_task_id="new", status=TaskStatus.RUNNING, total_steps=2)
    db.add(current)
    db.commit()
    if hook == "on_success":
        task.on_success({}, "old-step", (), {})
    else:
        task.on_failure(RuntimeError("late failure"), "old-step", (), {}, None)
    db.expire_all()
    assert project.status == ProjectStatus.IN_PRODUCTION
    assert current.status == TaskStatus.RUNNING
    assert old.status == (TaskStatus.COMPLETED if hook == "on_success" else TaskStatus.FAILED)


def test_completed_redelivery_and_late_failure_preserve_completed_status(task_state_case):
    db, project, old, task = task_state_case
    old.status = TaskStatus.COMPLETED
    project.status = ProjectStatus.COMPLETED
    db.commit()

    with pytest.raises(Ignore):
        task.before_start("duplicate-completed-step", (), {})
    task.on_failure(RuntimeError("late exception"), "duplicate-completed-step", (), {}, None)
    db.expire_all()
    assert old.status == TaskStatus.COMPLETED
    assert project.status == ProjectStatus.COMPLETED


def test_cancelled_task_does_not_execute_when_project_release_fails(task_state_case, monkeypatch):
    _db, _project, _old, task = task_state_case
    def failed_update(*args, **kwargs):
        raise RuntimeError("database unavailable during release")
    monkeypatch.setattr("src.tasks.celery_app._update_current_project_state", failed_update)
    with pytest.raises(Ignore):
        task.before_start("cancelled-step", (), {})


def test_previously_recorded_failure_keeps_diagnosis_and_still_broadcasts(task_state_case, monkeypatch):
    db, project, old, task = task_state_case
    old.status = TaskStatus.FAILED
    old.error_message = "Detailed media validation failure"
    project.status = ProjectStatus.FAILED
    db.commit()
    events = []
    monkeypatch.setattr("src.tasks.celery_app._broadcast_task_event", lambda *_args: events.append(_args))

    task.on_failure(RuntimeError("wrapper failed"), "old-step", (), {}, None)

    db.expire_all()
    assert old.error_message == "Detailed media validation failure"
    assert events[0][1]["status"] == "failed"
    assert events[0][1]["error"] == old.error_message


def test_worker_cannot_reactivate_task_cancelled_after_pending_read(task_state_case):
    db, project, old, task = task_state_case
    old.status = TaskStatus.PENDING
    db.commit()

    def cancelled_after_read(_args, _kwargs, session):
        record = session.get(Task, old.id)
        assert record.status == TaskStatus.PENDING
        # Simulate the cancellation becoming visible after the initial read;
        # keep the worker's ORM instance stale until its guarded claim refreshes.
        session.query(Task).filter(Task.id == old.id).update(
            {Task.status: TaskStatus.CANCELLED}, synchronize_session=False,
        )
        return record

    task._production_record = cancelled_after_read
    with pytest.raises(Ignore):
        task.before_start("cancelled-before-claim", (), {})
    db.expire_all()
    assert old.status == TaskStatus.CANCELLED
    assert project.status == ProjectStatus.SCRIPT_GENERATED


@pytest.mark.parametrize("winning_status", [TaskStatus.CANCELLED, TaskStatus.COMPLETED])
@pytest.mark.parametrize("hook", ["on_success", "on_failure"])
def test_callback_cannot_overwrite_terminal_state_committed_after_read(task_state_case, monkeypatch, winning_status, hook):
    db, project, old, task = task_state_case
    old.status = TaskStatus.RUNNING
    db.commit()
    events = []
    monkeypatch.setattr("src.tasks.celery_app._broadcast_task_event", lambda *_args: events.append(_args[1]))

    def stale_running_record(_args, _kwargs, session):
        record = session.get(Task, old.id)
        record.status = winning_status
        if winning_status == TaskStatus.COMPLETED:
            record.project.status = ProjectStatus.COMPLETED
        session.commit()
        # Model another worker's durable terminal update while this callback
        # still holds the earlier RUNNING snapshot, without dirtying the ORM.
        set_committed_value(record, "status", TaskStatus.RUNNING)
        return record

    task._production_record = stale_running_record
    if hook == "on_failure":
        task.on_failure(RuntimeError("late exception"), "old-step", (), {}, None)
    else:
        task.on_success({}, "old-step", (), {})
    db.expire_all()
    assert old.status == winning_status
    assert project.status == (ProjectStatus.SCRIPT_GENERATED if winning_status == TaskStatus.CANCELLED else ProjectStatus.COMPLETED)
    assert all(event["status"] != "failed" for event in events)


@pytest.mark.parametrize("status", [TaskStatus.COMPLETED, TaskStatus.CANCELLED])
def test_success_broadcasts_terminal_state_already_persisted_by_task(task_state_case, monkeypatch, status):
    db, project, old, task = task_state_case
    old.status = status
    old.current_step = old.total_steps
    old.progress = 100.0
    project.status = ProjectStatus.COMPLETED if status == TaskStatus.COMPLETED else ProjectStatus.IN_PRODUCTION
    db.commit()
    events = []
    monkeypatch.setattr("src.tasks.celery_app._broadcast_task_event", lambda *_args: events.append(_args[1]))

    task.on_success({}, "old-step", (), {})

    assert events[0]["status"] == status.value
    assert events[0]["type"] == ("completion" if status == TaskStatus.COMPLETED else "status_update")
    assert events[0]["task_id"] == old.celery_task_id
    db.refresh(old)
    assert old.current_step == old.total_steps


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


def test_sequence_video_task_is_tracked_as_a_production_record():
    record = SimpleNamespace(id=42)
    query = SimpleNamespace(filter=lambda *_args: query, first=lambda: record)
    db = SimpleNamespace(query=lambda *_args: query)
    task = BaseTask()
    task.name = "generate_sequence_video"
    task.run = lambda scene_ids, project_id, task_id, **kwargs: None

    assert task._production_record(([1, 2], 7, 42), {}, db) is record
