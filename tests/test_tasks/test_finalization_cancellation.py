"""Publication and cleanup must respect task ownership and cancellation."""

from pathlib import Path
import json
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
    reviewer = composition_tasks._review_final_composed_video
    monkeypatch.setattr(composition_tasks, "_review_final_composed_video", lambda *_args, **_kwargs: None)
    publisher = composition_tasks._publish_composition_candidate
    publish = Mock(wraps=publisher)
    monkeypatch.setattr(composition_tasks, "_publish_composition_candidate", publish)
    monkeypatch.setattr(draft_tasks.storage_manager, "get_project_path", lambda _id: tmp_path)
    yield SimpleNamespace(sessions=sessions, project_id=project_id, task_id=task_id,
                          final=final, root=tmp_path, composer=composer, publish=publish, publisher=publisher, reviewer=reviewer, engine=engine)
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


@pytest.mark.parametrize("supersede", [False, True], ids=["duplicate-delivery", "newer-task"])
def test_overlapping_compositions_cannot_overwrite_or_clean_each_others_scratch(finalization_case, supersede):
    case = finalization_case
    outputs = []

    def concat(_paths, output, **_kwargs):
        outputs.append(Path(output))
        if len(outputs) == 1:
            Path(output).write_bytes(b"first attempt scratch")
            next_task_id = case.task_id
            if supersede:
                with case.sessions() as db:
                    task = Task(project_id=case.project_id, celery_task_id="overlapping-run", status=TaskStatus.RUNNING, total_steps=2)
                    db.add(task)
                    db.commit()
                    next_task_id = task.id
            composition_tasks.compose_final_video_task.run(case.project_id, next_task_id)
            # The other attempt has published and cleaned up. This attempt's
            # intermediate must still contain its own bytes until it exits.
            assert Path(output).read_bytes() == b"first attempt scratch"
        else:
            Path(output).write_bytes(b"winning attempt master")
        return output

    case.composer.concat_videos.side_effect = concat
    with pytest.raises(Ignore):
        composition_tasks.compose_final_video_task.run(case.project_id, case.task_id)

    assert len(set(outputs)) == 2
    assert all(not output.exists() for output in outputs)
    assert case.final.read_bytes() == b"winning attempt master"
    assert (case.root / "scene.mp4").read_bytes() == b"generated scene"


@pytest.mark.parametrize("outcome", ["completed", "cancelled", "review-error"])
def test_all_composition_stages_share_only_their_own_workspace(finalization_case, monkeypatch, outcome):
    case = finalization_case
    subtitle = case.root / "scene.srt"
    subtitle.write_text("1\n00:00:00,000 --> 00:00:01,000\n你好\n", encoding="utf-8")
    with case.sessions() as db:
        db.query(Scene).filter(Scene.project_id == case.project_id).one().subtitle_path = str(subtitle)
        db.commit()
    bgm = case.root / "music.wav"
    bgm.write_bytes(b"music source")
    # Shared names from earlier versions may belong to a different worker.
    legacy_paths = [case.root / f"final{suffix}" for suffix in ("_temp.mp4", "_with_audio.mp4", "_merged_audio.wav", "_with_bgm.mp4", ".srt")]
    for path in legacy_paths:
        path.write_bytes(b"another worker's file")
    outputs = []

    def write_output(path):
        outputs.append(Path(path))
        Path(path).write_bytes(b"isolated composition output")
        return str(path)

    case.composer.concat_videos.side_effect = lambda _paths, output, **_kwargs: write_output(output)
    case.composer.compose_scene_audio = Mock(side_effect=lambda _segments, output, **_kwargs: write_output(output))
    case.composer.sync_audio_video = Mock(side_effect=lambda **kwargs: write_output(kwargs["output_path"]))
    case.composer.add_bgm = Mock(side_effect=lambda **kwargs: write_output(kwargs["output_path"]))
    case.composer._get_duration = lambda _path: 1.0
    monkeypatch.setattr(composition_tasks, "_composition_audio_plan", lambda *_args: (False, [(str(bgm), 1.0)]))
    burn = Mock(side_effect=lambda **kwargs: write_output(kwargs["output_path"]))
    monkeypatch.setattr(composition_tasks, "get_subtitle_generator", lambda: SimpleNamespace(burn_subtitle=burn))
    inspect = Mock(return_value={"status": "available", "score": 0.95})
    monkeypatch.setattr(composition_tasks, "LocalizationQualityService", lambda: SimpleNamespace(inspect_rendered_subtitles=inspect))

    def review(_project, _scenes, video_path, **_kwargs):
        assert composition_tasks._final_rendered_subtitle_visual_audit(video_path) == inspect.return_value
        merged_subtitle = Path(burn.call_args.kwargs["subtitle_path"])
        assert merged_subtitle == Path(video_path).with_suffix(".srt")
        outputs.append(merged_subtitle)
        assert all(path.is_file() for path in outputs)
        if outcome == "cancelled":
            _end_or_supersede(case, "cancelled")
        elif outcome == "review-error":
            raise ValueError("composition review rejected")

    monkeypatch.setattr(composition_tasks, "_review_final_composed_video", review)
    if outcome == "completed":
        composition_tasks.compose_final_video_task.run(case.project_id, case.task_id, add_bgm=True, bgm_path=str(bgm))
    else:
        with pytest.raises(Ignore if outcome == "cancelled" else ValueError):
            composition_tasks.compose_final_video_task.run(case.project_id, case.task_id, add_bgm=True, bgm_path=str(bgm))
        assert case.final.read_bytes() == b"previous approved master"

    inspect.assert_called_once()
    assert inspect.call_args.args[1][0].text == "你好"
    workspace = outputs[0].parent
    assert workspace != case.root
    assert all(path.parent == workspace for path in outputs)
    assert not workspace.exists()
    assert all(path.read_bytes() == b"another worker's file" for path in legacy_paths)
    assert subtitle.is_file() and bgm.is_file()


def test_workspace_cleanup_keeps_borrowed_scene_source(finalization_case):
    case = finalization_case
    case.composer.concat_videos.side_effect = lambda paths, _output, **_kwargs: paths[0]
    composition_tasks.compose_final_video_task.run(case.project_id, case.task_id)
    assert (case.root / "scene.mp4").read_bytes() == b"generated scene"
    assert case.final.read_bytes() == b"generated scene"


@pytest.mark.parametrize("visibility", ["passed", "invisible", "unavailable"])
def test_composition_really_gates_rendered_subtitles_before_publication(finalization_case, monkeypatch, visibility):
    case = finalization_case
    subtitle = case.root / "scene.srt"
    subtitle.write_text("1\n00:00:00,000 --> 00:00:01,000\n可见字幕\n", encoding="utf-8")
    with case.sessions() as db:
        db.query(Scene).filter(Scene.project_id == case.project_id).one().subtitle_path = str(subtitle)
        db.commit()
    case.composer._get_duration = lambda _path: 1.0

    def burn(**kwargs):
        Path(kwargs["output_path"]).write_bytes(b"subtitled candidate")

    monkeypatch.setattr(composition_tasks, "get_subtitle_generator", lambda: SimpleNamespace(burn_subtitle=burn))
    monkeypatch.setattr(composition_tasks, "_review_final_composed_video", case.reviewer)
    monkeypatch.setattr(composition_tasks.settings, "GENERATION_REQUIRE_VIDEO_REVIEW", True)
    visual = {"status": "unavailable", "error": "cannot decode render"} if visibility == "unavailable" else {
        "status": "available", "score": 0.1 if visibility == "invisible" else 0.95,
    }
    inspect = Mock(return_value=visual)
    monkeypatch.setattr(composition_tasks, "LocalizationQualityService", lambda: SimpleNamespace(inspect_rendered_subtitles=inspect))
    monkeypatch.setattr(composition_tasks, "video_boundary_continuity", lambda _paths: {"status": "not_applicable"})
    monkeypatch.setattr(composition_tasks, "video_candidate_metrics", lambda _path: {
        "status": "available", "width": 1080, "height": 1920, "audio_present": True,
        "audio_duration_delta_seconds": 0.0, "audio_video_start_delta_seconds": 0.0,
        "audio_signal_status": "usable",
    })
    monkeypatch.setattr(composition_tasks, "_project_final_review_payload", lambda *_args: {})
    monkeypatch.setattr(composition_tasks, "_episode_style_consistency_gate", lambda _scenes: None)
    batch = {key: {"status": "passed"} for key in (
        "video_aesthetic_gate", "platform_reference_gate", "video_performance_gate",
        "episode_continuity_gate", "final_composition_finishing_gate",
    )}
    batch.update({"status": "passed", "review": {
        key: {"score": 5.0} for key in ("facial_identity", "identity_consistency", "temporal_consistency")
    }})
    model_review = {"status": "passed", "average": 5.0, "batches": [batch]}
    def sample_review(_video, _payload, report_path):
        frames_dir = report_path.with_suffix("")
        frames_dir.mkdir(parents=True, exist_ok=True)
        frame = frames_dir / "frame_000.jpg"
        frame.write_bytes(b"retained review frame")
        return {**model_review, "frames": [{"path": str(frame), "sha256": composition_tasks.file_hash(frame)}]}

    review_video = Mock(side_effect=sample_review)
    monkeypatch.setattr(composition_tasks, "GenerationReviewService", lambda: SimpleNamespace(review_video=review_video))

    if visibility == "passed":
        composition_tasks.compose_final_video_task.run(case.project_id, case.task_id)
        report = json.loads(case.final.with_suffix(".composition_review.json").read_text(encoding="utf-8"))
        assert case.final.read_bytes() == b"subtitled candidate"
    else:
        message = "not visibly integrated" if visibility == "invisible" else "visibility evidence is unavailable"
        with pytest.raises(ValueError, match=message):
            composition_tasks.compose_final_video_task.run(case.project_id, case.task_id)
        case.publish.assert_not_called()
        assert case.final.read_bytes() == b"previous approved master"
        report = json.loads((case.root / "reviews" / "final_composition.json").read_text(encoding="utf-8"))
    inspect.assert_called_once()
    assert inspect.call_args.args[1][0].text == "可见字幕"
    assert report["rendered_subtitle_visual"] == visual
    assert review_video.call_args.args[1]["rendered_subtitle_visual"] == visual
    assert not Path(inspect.call_args.args[0]).parent.exists()
    frame = Path(report["frames"][0]["path"])
    assert frame.read_bytes() == b"retained review frame"
    assert composition_tasks.file_hash(frame) == report["frames"][0]["sha256"]
