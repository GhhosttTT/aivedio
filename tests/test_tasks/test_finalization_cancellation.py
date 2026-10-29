"""Publication must not undo cancellation or complete a different task."""

from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from threading import Event, get_ident
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from celery.exceptions import Ignore
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from src.database.models import Base, Project, ProjectStatus, Scene, Task, TaskStatus, User
from src.tasks import composition_tasks, draft_tasks
from src.services.task_orchestrator import TaskOrchestrator


@pytest.fixture
def finalization_case(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'finalization.db'}", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine, autoflush=False)
    final = tmp_path / "final.mp4"
    final.write_bytes(b"previous approved master")
    video = tmp_path / "scene.mp4"
    video.write_bytes(b"generated scene")
    with sessions() as db:
        user = User(username="finalizer", email="finalizer@example.com", hashed_password="x")
        db.add(user)
        db.flush()
        project = Project(name="finalizer", user_id=user.id, status=ProjectStatus.IN_PRODUCTION, final_video_path=str(final))
        db.add(project)
        db.flush()
        task = Task(project_id=project.id, celery_task_id="finalizer", status=TaskStatus.RUNNING, total_steps=2)
        db.add_all([task, Scene(project_id=project.id, scene_number=1, visual_description="A quiet room", video_path=str(video))])
        db.commit()
        project_id, task_id = project.id, task.id

    def concat(_paths, output, **kwargs):
        Path(output).write_bytes(b"new reviewed master")
        return output

    composer = SimpleNamespace(concat_videos=Mock(side_effect=concat), has_provider_chroma_fidelity=lambda _path: False)
    for module in (composition_tasks, draft_tasks):
        monkeypatch.setattr(module, "get_db", lambda: iter([sessions()]))
    monkeypatch.setattr(composition_tasks, "get_project_final_video_path", lambda _id: str(final))
    monkeypatch.setattr(composition_tasks, "get_video_composer", lambda: composer)
    monkeypatch.setattr(composition_tasks, "get_subtitle_generator", Mock())
    monkeypatch.setattr(composition_tasks.compose_final_video_task, "update_state", Mock())
    monkeypatch.setattr("src.tasks.review_tasks.require_generation_review", lambda *_args: None)
    monkeypatch.setattr(composition_tasks, "_require_passed_scene_videos", lambda *_args: None)
    monkeypatch.setattr(composition_tasks, "_native_audio_is_ready_for_video_paths", lambda *_args: True)
    monkeypatch.setattr(composition_tasks, "_composition_audio_plan", lambda *_args: (True, None))
    monkeypatch.setattr(composition_tasks, "_require_scene_subtitles", lambda *_args: None)
    monkeypatch.setattr(composition_tasks, "_require_editing_plan", lambda *_args: [])
    monkeypatch.setattr(composition_tasks, "_review_final_composed_video", lambda *_args, **_kwargs: None)
    publisher = composition_tasks._publish_composition_candidate
    publish = Mock(wraps=publisher)
    monkeypatch.setattr(composition_tasks, "_publish_composition_candidate", publish)
    monkeypatch.setattr(draft_tasks.storage_manager, "get_project_path", lambda _id: tmp_path)
    yield SimpleNamespace(sessions=sessions, project_id=project_id, task_id=task_id,
                          final=final, root=tmp_path, composer=composer, publish=publish, publisher=publisher, engine=engine)
    engine.dispose()


def _end_or_supersede(case, state):
    with case.sessions() as db:
        if state == "newer":
            db.add(Task(project_id=case.project_id, celery_task_id="new-run", status=TaskStatus.RUNNING, total_steps=2))
        else:
            db.get(Task, case.task_id).status = TaskStatus(state)
            if state in {"failed", "completed"}:
                db.get(Project, case.project_id).status = ProjectStatus(state)
        db.commit()


@pytest.mark.parametrize("state", ["cancelled", "failed", "completed", "newer"])
def test_composition_does_not_publish_after_task_ends_or_is_superseded(finalization_case, monkeypatch, state):
    case = finalization_case

    def reviewed(*_args, **_kwargs):
        _end_or_supersede(case, state)

    monkeypatch.setattr(composition_tasks, "_review_final_composed_video", reviewed)
    with pytest.raises(Ignore):
        composition_tasks.compose_final_video_task.run(case.project_id, case.task_id)

    case.publish.assert_not_called()
    assert case.final.read_bytes() == b"previous approved master"
    with case.sessions() as db:
        assert db.get(Task, case.task_id).status == (TaskStatus.RUNNING if state == "newer" else TaskStatus(state))
        expected_project = "in_production" if state == "newer" else "script_generated" if state == "cancelled" else state
        assert db.get(Project, case.project_id).status.value == expected_project


def test_composition_validation_error_cannot_fail_cancelled_task(finalization_case, monkeypatch):
    case = finalization_case

    def review_fails(*_args, **_kwargs):
        _end_or_supersede(case, "cancelled")
        raise ValueError("late validation error")

    monkeypatch.setattr(composition_tasks, "_review_final_composed_video", review_fails)
    with pytest.raises(ValueError, match="late validation error"):
        composition_tasks.compose_final_video_task.run(case.project_id, case.task_id)

    with case.sessions() as db:
        assert db.get(Task, case.task_id).status == TaskStatus.CANCELLED
        assert db.get(Project, case.project_id).status == ProjectStatus.IN_PRODUCTION
    case.publish.assert_not_called()
    assert case.final.read_bytes() == b"previous approved master"


def test_composition_requires_exact_task_instead_of_latest_fallback(finalization_case):
    case = finalization_case
    with pytest.raises(ValueError, match="exact project task"):
        composition_tasks.compose_final_video_task.run(case.project_id, case.task_id + 100)
    case.composer.concat_videos.assert_not_called()
    with case.sessions() as db:
        assert db.get(Task, case.task_id).status == TaskStatus.RUNNING
        assert db.get(Project, case.project_id).status == ProjectStatus.IN_PRODUCTION


def test_successful_composition_publishes_and_completes_exact_task(finalization_case):
    case = finalization_case
    result = composition_tasks.compose_final_video_task.run(case.project_id, case.task_id)
    assert result["status"] == "completed"
    assert case.final.read_bytes() == b"new reviewed master"
    with case.sessions() as db:
        task = db.get(Task, case.task_id)
        assert task.status == TaskStatus.COMPLETED
        assert task.progress == 100.0
        assert task.result_path == str(case.final)
        assert db.get(Project, case.project_id).status == ProjectStatus.COMPLETED


def test_publication_failure_rolls_back_completion_claim(finalization_case):
    case = finalization_case
    case.publish.side_effect = OSError("disk unavailable")
    with pytest.raises(OSError, match="disk unavailable"):
        composition_tasks.compose_final_video_task.run(case.project_id, case.task_id)
    with case.sessions() as db:
        assert db.get(Task, case.task_id).status == TaskStatus.FAILED
        assert db.get(Project, case.project_id).status == ProjectStatus.FAILED
    assert case.final.read_bytes() == b"previous approved master"


def test_publication_claim_serializes_later_cancellation(finalization_case, monkeypatch):
    case = finalization_case
    worker_thread = get_ident()
    cancellation_attempted = Event()
    revoke = Mock()
    monkeypatch.setattr("src.services.task_orchestrator.celery_app.control.revoke", revoke)
    monkeypatch.setattr("src.services.task_orchestrator._broadcast_task_event", Mock())

    def attempted_update(_connection, _cursor, statement, _parameters, _context, _many):
        if get_ident() != worker_thread and statement.startswith("UPDATE tasks"):
            cancellation_attempted.set()

    event.listen(case.engine, "before_cursor_execute", attempted_update)

    def cancel():
        with case.sessions() as db:
            return TaskOrchestrator(db).cancel_task("finalizer")

    actual_publish = case.publisher
    with ThreadPoolExecutor(max_workers=1) as pool:
        pending = []

        def publish(*args, **kwargs):
            pending.append(pool.submit(cancel))
            assert cancellation_attempted.wait(timeout=5)
            return actual_publish(*args, **kwargs)

        case.publish.side_effect = publish
        try:
            composition_tasks.compose_final_video_task.run(case.project_id, case.task_id)
            assert pending[0].result(timeout=10) is False
        finally:
            event.remove(case.engine, "before_cursor_execute", attempted_update)
    revoke.assert_not_called()
    assert case.final.read_bytes() == b"new reviewed master"
    with case.sessions() as db:
        assert db.get(Task, case.task_id).status == TaskStatus.COMPLETED
        assert db.get(Project, case.project_id).status == ProjectStatus.COMPLETED


@pytest.mark.parametrize("state", ["cancelled", "newer"])
def test_draft_finalization_cannot_overwrite_report_after_cancellation_or_new_run(finalization_case, monkeypatch, state):
    case = finalization_case
    report = case.root / "reviews" / "draft_generation.json"
    report.parent.mkdir(parents=True)
    report.write_bytes(b"previous draft evidence")
    original_hash = draft_tasks.file_hash

    def read_hash(path):
        _end_or_supersede(case, state)
        return original_hash(path)

    monkeypatch.setattr(draft_tasks, "file_hash", read_hash)
    with pytest.raises(Ignore):
        draft_tasks.finalize_draft_generation_task.run(case.project_id, case.task_id)
    assert report.read_bytes() == b"previous draft evidence"
    with case.sessions() as db:
        assert db.get(Task, case.task_id).status == (TaskStatus.CANCELLED if state == "cancelled" else TaskStatus.RUNNING)
