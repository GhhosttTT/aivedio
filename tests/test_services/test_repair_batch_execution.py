from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.database.models import Base, Project, ProjectStatus, Scene, Task, TaskStatus, User
from src.services.task_orchestrator import TaskOrchestrator


@pytest.fixture
def repair_case(monkeypatch):
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine)()
    user = User(username="repair", email="repair@example.com", hashed_password="test")
    db.add(user)
    db.flush()
    project = Project(name="repair batch", user_id=user.id, status=ProjectStatus.COMPLETED, final_video_path="approved.mp4")
    db.add(project)
    db.flush()
    scenes = [Scene(project_id=project.id, scene_number=i, visual_description="an actor at the doorway", dialogue="Wait.",
                    image_path=f"{i}.png", video_path=f"{i}.mp4", audio_path=f"{i}.wav", subtitle_path=f"{i}.srt", audio_duration=2.0)
              for i in (1, 2)]
    db.add_all(scenes)
    db.commit()
    workflow = Mock()
    workflow.freeze.return_value.id = "batch-job"
    chain = Mock(return_value=workflow)
    monkeypatch.setattr("src.services.task_orchestrator.chain", chain)
    monkeypatch.setattr("src.services.task_orchestrator.ProductionWorkflowProfileService", lambda: Mock(validate_profile=Mock(return_value={"status": "valid"})))
    for name in ("generate_image_task", "generate_video_task", "generate_audio_task", "generate_subtitle_task", "review_generation_task", "compose_final_video_task"):
        monkeypatch.setattr(f"src.services.task_orchestrator.{name}.si", lambda *args, _name=name, **kwargs: SimpleNamespace(task=_name, args=args, kwargs=kwargs))
    yield TaskOrchestrator(db), project, scenes, workflow, chain
    db.close()
    engine.dispose()


def test_audio_and_visual_repairs_share_one_task_and_review_once_at_the_end(repair_case):
    orchestrator, project, scenes, workflow, chain = repair_case
    result = orchestrator.create_repair_batch_task(project.id, [
        {"scene_number": 1, "action": "regenerate_keyframe_with_identity_lock"},
        {"scene_number": 2, "action": "lower_motion_and_regenerate_video"},
        {"scene_number": 1, "action": "refine_dialogue_audio_delivery"},
    ])
    assert result == "batch-job"
    assert [step.task for step in chain.call_args.args] == [
        "generate_audio_task", "generate_subtitle_task", "generate_image_task",
        "generate_video_task", "generate_video_task", "review_generation_task",
        "compose_final_video_task",
    ]
    task = orchestrator.db.query(Task).one()
    assert task.total_steps == 7
    assert {step.args[-1] for step in chain.call_args.args if step.task != "generate_audio_task"} == {task.id}
    assert project.status == ProjectStatus.IN_PRODUCTION
    assert scenes[0].image_path is None and scenes[0].audio_path is None
    workflow.apply_async.assert_called_once()


def test_visual_repair_inherits_last_production_video_options(repair_case, monkeypatch):
    orchestrator, project, _scenes, workflow, chain = repair_case
    monkeypatch.setattr(
        "src.services.task_orchestrator.load_production_video_options",
        lambda _project_id: {
            "provider": "seedance_api",
            "request_mode": "reference",
            "model": "doubao-seedance-2-5-260628",
            "resolution": "1080p",
            "output_format": "mp4",
            "sequence_level_multi_shot": True,
        },
    )

    orchestrator.create_scene_repair_task(project.id, 1, "lower_motion_and_regenerate_video")

    video_step = next(step for step in chain.call_args.args if step.task == "generate_video_task")
    assert video_step.kwargs["provider"] == "seedance_api"
    assert video_step.kwargs["model"] == "doubao-seedance-2-5-260628"
    assert video_step.kwargs["resolution"] == "1080p"
    assert video_step.kwargs["sequence_level_multi_shot"] is False
    assert video_step.kwargs["draft"] is False
    workflow.apply_async.assert_called_once()


def test_output_contract_repair_is_dispatchable_as_a_video_repair(repair_case):
    orchestrator, project, scenes, workflow, chain = repair_case

    orchestrator.create_scene_repair_task(project.id, scenes[0].scene_number, "fix_video_output_contract")

    video_step = next(step for step in chain.call_args.args if step.task == "generate_video_task")
    assert video_step.kwargs["repair_action"] == "fix_video_output_contract"
    assert video_step.kwargs["sequence_level_multi_shot"] is False
    assert scenes[0].video_path is None
    workflow.apply_async.assert_called_once()


def test_batch_validation_is_complete_before_any_scene_is_invalidated(repair_case):
    orchestrator, project, scenes, workflow, _chain = repair_case
    with pytest.raises(ValueError, match="分镜不存在"):
        orchestrator.create_repair_batch_task(project.id, [
            {"scene_number": 1, "action": "refine_face_aesthetic_detail"},
            {"scene_number": 99, "action": "lower_motion_and_regenerate_video"},
        ])
    assert scenes[0].image_path == "1.png"
    assert project.status == ProjectStatus.COMPLETED
    assert orchestrator.db.query(Task).count() == 0
    workflow.apply_async.assert_not_called()


def test_queue_dispatch_failure_restores_existing_approved_assets(repair_case):
    orchestrator, project, scenes, workflow, _chain = repair_case
    workflow.apply_async.side_effect = OSError("broker unavailable")
    with pytest.raises(OSError, match="broker"):
        orchestrator.create_repair_batch_task(project.id, [
            {"scene_number": 1, "action": "refine_dialogue_audio_delivery"},
            {"scene_number": 1, "action": "refine_face_aesthetic_detail"},
        ])
    orchestrator.db.refresh(project)
    orchestrator.db.refresh(scenes[0])
    assert project.status == ProjectStatus.COMPLETED
    assert project.final_video_path == "approved.mp4"
    assert (scenes[0].image_path, scenes[0].video_path, scenes[0].audio_path, scenes[0].audio_duration) == ("1.png", "1.mp4", "1.wav", 2.0)
    assert orchestrator.db.query(Task).one().status == TaskStatus.FAILED


def test_duplicate_visual_repairs_are_rejected_before_submission(repair_case):
    orchestrator, project, _scenes, workflow, _chain = repair_case
    with pytest.raises(ValueError, match="每轮"):
        orchestrator.create_repair_batch_task(project.id, [
            {"scene_number": 1, "action": "refine_face_aesthetic_detail"},
            {"scene_number": 1, "action": "lower_motion_and_regenerate_video"},
        ])
    assert orchestrator.db.query(Task).count() == 0
    workflow.apply_async.assert_not_called()


def test_second_repair_cannot_overlap_a_reserved_project(repair_case):
    orchestrator, project, _scenes, _workflow, _chain = repair_case
    orchestrator.create_scene_repair_task(project.id, 1, "refine_dialogue_audio_delivery")
    with pytest.raises(ValueError, match="项目正在制作"):
        orchestrator.create_scene_repair_task(project.id, 2, "refine_dialogue_audio_delivery")
    assert orchestrator.db.query(Task).count() == 1


def test_audio_only_repair_refreshes_media_review_when_all_videos_exist(repair_case):
    orchestrator, project, _scenes, _workflow, chain = repair_case
    orchestrator.create_scene_repair_task(project.id, 1, "refine_dialogue_audio_delivery")
    assert [step.task for step in chain.call_args.args] == [
        "generate_audio_task", "generate_subtitle_task", "review_generation_task",
        "compose_final_video_task",
    ]
    assert orchestrator.db.query(Task).one().total_steps == 4
