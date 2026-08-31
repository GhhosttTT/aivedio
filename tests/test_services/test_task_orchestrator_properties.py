"""Property tests use a new in-memory database for every generated example."""
from contextlib import contextmanager
from types import SimpleNamespace
from uuid import uuid4
from unittest.mock import Mock, patch
from hypothesis import given, strategies as st, settings
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from celery.utils.time import get_exponential_backoff_interval
from src.database.models import Base, User, Project, Scene, Task, ProjectStatus, TaskStatus
from src.services.task_orchestrator import TaskOrchestrator

@contextmanager
def case(count=1):
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        user = User(username="test", email="test@example.com", hashed_password="test")
        db.add(user); db.flush()
        project = Project(name="Test", user_id=user.id, status=ProjectStatus.SCRIPT_GENERATED)
        db.add(project); db.flush()
        for i in range(count):
            db.add(Scene(project_id=project.id, scene_number=i + 1, visual_description="A letter on a table"))
        db.commit()
        yield TaskOrchestrator(db), project
    engine.dispose()

def submit(orchestrator, project):
    identifier = str(uuid4())
    with patch("src.services.task_orchestrator.chain") as chain:
        chain.return_value.freeze.return_value = SimpleNamespace(id=identifier)
        orchestrator.create_production_task(project.id)
    return orchestrator.db.query(Task).filter(Task.celery_task_id == identifier).one()

@given(st.integers(1, 12))
@settings(deadline=None)
def test_task_chain_structure_and_real_id(count):
    with case(count) as (service, project):
        task = submit(service, project)
        assert task.total_steps == count * 4 + 3
        assert task.id > 0 and task.status == TaskStatus.RUNNING

@given(st.lists(st.floats(min_value=-10, max_value=110, allow_nan=False), min_size=1, max_size=20))
@settings(deadline=None)
def test_task_progress_monotonic(updates):
    with case() as (service, project):
        task = submit(service, project)
        previous = 0
        for progress in updates:
            service.update_task_progress(task.id, progress)
            service.db.refresh(task)
            assert previous <= task.progress <= 100
            previous = task.progress

@given(st.integers(1, 5))
@settings(deadline=None)
def test_cancellation_is_persisted(count):
    with case(count) as (service, project):
        task = submit(service, project)
        with patch("src.services.task_orchestrator.celery_app.control.revoke") as revoke:
            assert service.cancel_task(task.celery_task_id)
            revoke.assert_called_once_with(task.celery_task_id, terminate=False)
        assert service.get_task_status(task.celery_task_id)["status"] == "cancelled"
        assert not service.cancel_task(task.celery_task_id)

@given(st.integers(0, 5))
@settings(deadline=None)
def test_retry_limit_and_lineage(retries):
    with case() as (service, project):
        task = submit(service, project)
        task.status = TaskStatus.FAILED
        project.status = ProjectStatus.FAILED
        task.retry_count = retries
        service.db.commit()
        identifier = str(uuid4())
        with patch("src.services.task_orchestrator.chain") as chain:
            chain.return_value.freeze.return_value.id = identifier
            result = service.retry_failed_task(task.celery_task_id)
        if retries >= 3:
            assert result is None
        else:
            assert result == identifier
            replacement = service.db.query(Task).filter(Task.celery_task_id == result).one()
            assert replacement.retry_count == retries + 1

@given(st.integers(0, 12))
def test_configured_exponential_backoff(retries):
    from src.tasks.celery_app import BaseTask
    assert BaseTask.retry_backoff
    actual = get_exponential_backoff_interval(1, retries, BaseTask.retry_backoff_max, full_jitter=False)
    assert actual == min(2 ** retries, 600)

@given(st.integers(1, 5))
@settings(deadline=None)
def test_composition_follows_review(count):
    with case(count) as (service, project):
        scenes = service.db.query(Scene).all()
        with patch("src.services.task_orchestrator.chain") as chain:
            service._build_task_chain(project.id, 7, scenes, True, True, True, True, False, None)
            steps = chain.call_args.args
            assert steps[0].task == "prepare_generation"
            assert steps[-2].task == "review_generation"
            assert steps[-1].task == "compose_final_video"
            assert steps[-1].args[:2] == (project.id, 7)
