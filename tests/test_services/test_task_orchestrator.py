"""
TaskOrchestrator 服务单元测试
测试任务编排服务的核心功能
"""

import pytest
from unittest.mock import ANY, Mock, patch
from datetime import datetime
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.database.models import (
    Base, Project, Scene, Task as TaskModel,
    TaskStatus, ProjectStatus
)
from src.services.task_orchestrator import (
    TaskOrchestrator,
    get_task_orchestrator,
    cleanup_task_orchestrator
)


@pytest.fixture
def db_session():
    """创建测试数据库会话"""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()


@pytest.fixture
def sample_project(db_session):
    """创建示例项目"""
    # 创建用户
    from src.database.models import User
    user = User(
        username="test_user",
        email="test@example.com",
        hashed_password="hashed_password"
    )
    db_session.add(user)
    db_session.commit()
    
    # 创建项目
    project = Project(
        name="测试项目",
        description="测试描述",
        theme="测试主题",
        status=ProjectStatus.SCRIPT_GENERATED,
        user_id=user.id
    )
    db_session.add(project)
    db_session.commit()
    db_session.refresh(project)
    return project


@pytest.fixture
def sample_scenes(db_session, sample_project):
    """创建示例分镜"""
    scenes = []
    for i in range(3):
        scene = Scene(
            project_id=sample_project.id,
            scene_number=i + 1,
            character_name=f"角色 {i + 1}",
            dialogue=f"对话 {i + 1}",
            visual_description=f"场景 {i + 1} 描述",
            image_prompt=f"视觉提示词 {i + 1}"
        )
        db_session.add(scene)
        scenes.append(scene)
    
    db_session.commit()
    for scene in scenes:
        db_session.refresh(scene)
    
    return scenes


@pytest.fixture
def orchestrator(db_session):
    """创建 TaskOrchestrator 实例"""
    return TaskOrchestrator(db_session)


class TestTaskOrchestratorInit:
    """测试 TaskOrchestrator 初始化"""
    
    def test_init(self, db_session):
        """测试初始化"""
        orchestrator = TaskOrchestrator(db_session)
        assert orchestrator.db == db_session


class TestCreateProductionTask:
    """测试创建生产任务"""
    
    @patch('src.services.task_orchestrator.chain')
    def test_create_production_task_success(
        self, mock_chain, orchestrator, sample_project, sample_scenes, monkeypatch
    ):
        """测试成功创建生产任务"""
        monkeypatch.setattr("src.services.task_orchestrator.settings.GENERATION_ALLOW_SVD_PRODUCTION_FALLBACK", True)
        # Mock Celery chain
        mock_result = Mock()
        mock_result.id = "test-celery-task-id"
        mock_chain.return_value.apply_async.return_value = mock_result
        mock_chain.return_value.freeze.return_value = mock_result
        
        # 创建生产任务
        celery_task_id = orchestrator.create_production_task(
            project_id=sample_project.id
        )
        
        # 验证返回值
        assert celery_task_id == "test-celery-task-id"
        
        # 验证数据库记录
        task = orchestrator.db.query(TaskModel).filter(
            TaskModel.celery_task_id == celery_task_id
        ).first()
        
        assert task is not None
        assert task.project_id == sample_project.id
        assert task.status == TaskStatus.PENDING
    
    def test_create_production_task_project_not_found(self, orchestrator):
        """测试项目不存在时抛出异常"""
        with pytest.raises(ValueError, match="项目不存在"):
            orchestrator.create_production_task(project_id=999)
    
    def test_create_production_task_no_scenes(self, orchestrator, sample_project):
        """测试项目没有分镜时抛出异常"""
        with pytest.raises(ValueError, match="项目没有分镜"):
            orchestrator.create_production_task(project_id=sample_project.id)

    @patch('src.services.task_orchestrator.chain')
    @patch('src.services.task_orchestrator.generate_sequence_video_task')
    def test_sequence_level_multi_shot_uses_one_sequence_task(
        self, mock_sequence_task, mock_chain, orchestrator, sample_project, sample_scenes, monkeypatch
    ):
        monkeypatch.setattr("src.services.task_orchestrator.settings.GENERATION_ALLOW_SVD_PRODUCTION_FALLBACK", True)
        mock_result = Mock(id="sequence-celery-task-id")
        mock_chain.return_value.freeze.return_value = mock_result
        mock_sequence_task.si.return_value = Mock(name="sequence-task")

        celery_task_id = orchestrator.create_production_task(
            project_id=sample_project.id,
            sequence_level_multi_shot=True,
        )

        assert celery_task_id == "sequence-celery-task-id"
        mock_sequence_task.si.assert_called_once()
        assert mock_sequence_task.si.call_args.args[0] == [scene.id for scene in sample_scenes]

    def test_create_production_task_blocks_failed_readiness(
        self, orchestrator, sample_project, sample_scenes, monkeypatch
    ):
        monkeypatch.setattr("src.services.task_orchestrator.settings.GENERATION_ALLOW_SVD_PRODUCTION_FALLBACK", False)

        class FakeReadiness:
            def __init__(self, _db):
                pass

            def build_report(self, project_id, include_engine_preflight=True):
                return {
                    "status": "needs_review",
                    "action_items": ["Run real GPU validation samples."],
                }

        monkeypatch.setattr("src.services.task_orchestrator.ProductionReadinessService", FakeReadiness)

        with pytest.raises(ValueError, match="Production readiness is not ready"):
            orchestrator.create_production_task(project_id=sample_project.id)

    @patch('src.services.task_orchestrator.chain')
    def test_per_run_provider_is_used_by_readiness_and_engine_preflight(
        self, mock_chain, orchestrator, sample_project, sample_scenes, monkeypatch
    ):
        monkeypatch.setattr("src.services.task_orchestrator.settings.GENERATION_ALLOW_SVD_PRODUCTION_FALLBACK", False)
        monkeypatch.setattr("src.services.task_orchestrator.MIN_PRODUCTION_SCENES", 3)
        monkeypatch.setenv("GENERATION_PROVIDER", "local_comfyui")
        mock_result = Mock(id="per-run-provider-task-id")
        mock_chain.return_value.freeze.return_value = mock_result

        readiness_calls = []

        class FakeReadiness:
            def __init__(self, _db):
                pass

            def build_report(self, project_id, **kwargs):
                readiness_calls.append((project_id, kwargs))
                return {"status": "ready", "action_items": []}

        preflight_calls = []

        def fake_preflight(**kwargs):
            preflight_calls.append(kwargs)
            return {"status": "ready_for_production_video_test", "action_items": []}

        monkeypatch.setattr("src.services.task_orchestrator.ProductionReadinessService", FakeReadiness)
        monkeypatch.setattr("src.services.task_orchestrator.preflight_production_video_engine", fake_preflight)

        assert orchestrator.create_production_task(
            project_id=sample_project.id,
            provider="seedance_api",
        ) == "per-run-provider-task-id"
        assert readiness_calls == [(
            sample_project.id,
            {"include_engine_preflight": False, "provider_override": "seedance_api"},
        )]
        assert preflight_calls == [{"provider_override": "seedance_api"}]

    def test_create_scene_repair_task_handles_dialogue_audio_repair(
        self, orchestrator, sample_project, sample_scenes, monkeypatch
    ):
        workflow = Mock()
        workflow.freeze.return_value.id = "audio-repair-task-id"
        generate = Mock(return_value=Mock(name="audio-signature"))
        subtitle = Mock(return_value=Mock(name="subtitle-signature"))
        build_chain = Mock(return_value=workflow)
        monkeypatch.setattr("src.services.task_orchestrator.generate_audio_task.si", generate)
        monkeypatch.setattr("src.services.task_orchestrator.generate_subtitle_task.si", subtitle)
        monkeypatch.setattr("src.services.task_orchestrator.chain", build_chain)
        scene = sample_scenes[0]
        scene.audio_path = "old.mp3"
        scene.audio_duration = 1.5
        scene.subtitle_path = "old.srt"
        scene.video_path = "keep-video.mp4"
        orchestrator.db.commit()

        celery_task_id = orchestrator.create_scene_repair_task(
            sample_project.id,
            scene.scene_number,
            "refine_dialogue_audio_delivery",
        )

        assert celery_task_id == "audio-repair-task-id"
        assert generate.call_args.kwargs["repair_action"] == "refine_dialogue_audio_delivery"
        subtitle.assert_called_once_with(scene.id, sample_project.id, ANY)
        build_chain.assert_called_once()
        orchestrator.db.refresh(scene)
        assert scene.audio_path is None
        assert scene.audio_duration is None
        assert scene.subtitle_path is None
        assert scene.video_path == "keep-video.mp4"
        workflow.apply_async.assert_called_once()
        task = orchestrator.db.query(TaskModel).filter(
            TaskModel.celery_task_id == celery_task_id
        ).one()
        assert task.total_steps == 2

    def test_create_scene_repair_task_rerenders_video_after_keyframe_repair(
        self, orchestrator, sample_project, sample_scenes, monkeypatch
    ):
        workflow = Mock()
        workflow.freeze.return_value.id = "image-repair-task-id"
        generate_image = Mock(return_value=Mock(name="image-signature"))
        generate_video = Mock(return_value=Mock(name="video-signature"))
        review = Mock(return_value=Mock(name="review-signature"))
        build_chain = Mock(return_value=workflow)
        monkeypatch.setattr(
            "src.services.task_orchestrator.ProductionWorkflowProfileService",
            lambda: Mock(validate_profile=Mock(return_value={"status": "valid"})),
        )
        monkeypatch.setattr("src.services.task_orchestrator.generate_image_task.si", generate_image)
        monkeypatch.setattr("src.services.task_orchestrator.generate_video_task.si", generate_video)
        monkeypatch.setattr("src.services.task_orchestrator.review_generation_task.si", review)
        monkeypatch.setattr("src.services.task_orchestrator.chain", build_chain)
        scene = sample_scenes[0]
        scene.image_path = "old.png"
        scene.video_path = "old.mp4"
        orchestrator.db.commit()

        celery_task_id = orchestrator.create_scene_repair_task(
            sample_project.id,
            scene.scene_number,
            "refine_face_aesthetic_detail",
        )

        assert celery_task_id == "image-repair-task-id"
        assert generate_image.call_args.kwargs["repair_action"] == "refine_face_aesthetic_detail"
        generate_video.assert_called_once()
        assert generate_video.call_args.args[:3] == (scene.id, sample_project.id, ANY)
        assert generate_video.call_args.kwargs["provider"] == "seedance_api"
        assert generate_video.call_args.kwargs["sequence_level_multi_shot"] is False
        assert generate_video.call_args.kwargs["draft"] is False
        review.assert_called_once_with(sample_project.id, ANY)
        build_chain.assert_called_once()
        orchestrator.db.refresh(scene)
        assert scene.image_path is None
        assert scene.video_path is None
        workflow.apply_async.assert_called_once()
        task = orchestrator.db.query(TaskModel).filter(
            TaskModel.celery_task_id == celery_task_id
        ).one()
        assert task.total_steps == 3

    def test_create_scene_repair_task_reviews_after_video_repair(
        self, orchestrator, sample_project, sample_scenes, monkeypatch
    ):
        workflow = Mock()
        workflow.freeze.return_value.id = "video-repair-task-id"
        generate_video = Mock(return_value=Mock(name="video-signature"))
        review = Mock(return_value=Mock(name="review-signature"))
        build_chain = Mock(return_value=workflow)
        monkeypatch.setattr(
            "src.services.task_orchestrator.ProductionWorkflowProfileService",
            lambda: Mock(validate_profile=Mock(return_value={"status": "valid"})),
        )
        monkeypatch.setattr("src.services.task_orchestrator.generate_video_task.si", generate_video)
        monkeypatch.setattr("src.services.task_orchestrator.review_generation_task.si", review)
        monkeypatch.setattr("src.services.task_orchestrator.chain", build_chain)
        scene = sample_scenes[0]
        scene.image_path = "passed-keyframe.png"
        scene.video_path = "old.mp4"
        orchestrator.db.commit()

        celery_task_id = orchestrator.create_scene_repair_task(
            sample_project.id,
            scene.scene_number,
            "increase_motion_and_regenerate_video",
        )

        assert celery_task_id == "video-repair-task-id"
        assert generate_video.call_args.kwargs["repair_action"] == "increase_motion_and_regenerate_video"
        review.assert_called_once_with(sample_project.id, ANY)
        build_chain.assert_called_once()
        orchestrator.db.refresh(scene)
        assert scene.video_path is None
        workflow.apply_async.assert_called_once()
        task = orchestrator.db.query(TaskModel).filter(
            TaskModel.celery_task_id == celery_task_id
        ).one()
        assert task.total_steps == 2


class TestCalculateTotalSteps:
    """测试计算总步骤数"""
    
    def test_calculate_all_steps(self, orchestrator):
        """测试计算所有步骤"""
        total = orchestrator._calculate_total_steps(
            scene_count=3,
            generate_images=True,
            generate_videos=True,
            generate_audios=True,
            generate_subtitles=True
        )
        # Preparation, review, and composition each count as a step.
        assert total == 15


class TestGetTaskStatus:
    """测试获取任务状态"""
    
    @patch('src.services.task_orchestrator.AsyncResult')
    def test_get_task_status_success(
        self, mock_async_result, orchestrator, sample_project
    ):
        """测试成功获取任务状态"""
        # 创建任务记录
        task = TaskModel(
            project_id=sample_project.id,
            status=TaskStatus.RUNNING,
            celery_task_id="test-task-id",
            total_steps=10,
            progress=50.0
        )
        orchestrator.db.add(task)
        orchestrator.db.commit()
        
        # Mock AsyncResult
        mock_result = Mock()
        mock_result.state = "PROGRESS"
        mock_result.info = {"current": 42, "step": "provider_processing"}
        mock_async_result.return_value = mock_result
        
        # 获取任务状态
        status = orchestrator.get_task_status("test-task-id")
        
        # 验证
        assert status["task_id"] == task.id
        assert status["status"] == TaskStatus.RUNNING.value
        assert status["progress"] == 50
        assert status["provider_progress"] == 42
        assert status["provider_stage"] == "provider_processing"
    
    def test_get_task_status_not_found(self, orchestrator):
        """测试任务不存在"""
        status = orchestrator.get_task_status("non-existent-task-id")
        assert status["status"] == "unknown"


class TestCancelTask:
    """测试取消任务"""
    
    @patch('src.services.task_orchestrator.celery_app')
    def test_cancel_task_success(
        self, mock_celery_app, orchestrator, sample_project
    ):
        """测试成功取消任务"""
        # 创建运行中的任务
        task = TaskModel(
            project_id=sample_project.id,
            status=TaskStatus.RUNNING,
            celery_task_id="running-task-id",
            total_steps=10
        )
        orchestrator.db.add(task)
        orchestrator.db.commit()
        
        # 取消任务
        result = orchestrator.cancel_task("running-task-id")
        
        # 验证
        assert result is True
        orchestrator.db.refresh(task)
        assert task.status == TaskStatus.CANCELLED

    @patch('src.services.task_orchestrator.celery_app')
    def test_cancel_pending_task_keeps_project_reproducible(
        self, mock_celery_app, orchestrator, sample_project
    ):
        task = TaskModel(
            project_id=sample_project.id,
            status=TaskStatus.PENDING,
            celery_task_id="pending-task-id",
            total_steps=10,
        )
        orchestrator.db.add(task)
        orchestrator.db.commit()

        assert orchestrator.cancel_task("pending-task-id") is True
        orchestrator.db.refresh(task)
        orchestrator.db.refresh(sample_project)
        assert task.status == TaskStatus.CANCELLED
        assert sample_project.status == ProjectStatus.SCRIPT_GENERATED
    
    def test_cancel_task_not_found(self, orchestrator):
        """测试取消不存在的任务"""
        result = orchestrator.cancel_task("non-existent-task-id")
        assert result is False


class TestRetryFailedTask:
    """测试重试失败任务"""
    
    @patch('src.services.task_orchestrator.TaskOrchestrator.create_production_task')
    def test_retry_failed_task_success(
        self, mock_create, orchestrator, sample_project, sample_scenes
    ):
        """测试成功重试失败任务"""
        # 创建失败的任务
        task = TaskModel(
            project_id=sample_project.id,
            status=TaskStatus.FAILED,
            celery_task_id="failed-task-id",
            retry_count=0,
            total_steps=10
        )
        orchestrator.db.add(task)
        orchestrator.db.commit()
        
        # Mock create_production_task
        mock_create.return_value = "new-task-id"
        
        # 重试任务
        new_task_id = orchestrator.retry_failed_task("failed-task-id")
        
        # 验证
        assert new_task_id == "new-task-id"
        orchestrator.db.refresh(task)
        assert task.retry_count == 1
    
    def test_retry_task_max_retries_exceeded(self, orchestrator, sample_project):
        """测试重试次数超过上限"""
        task = TaskModel(
            project_id=sample_project.id,
            status=TaskStatus.FAILED,
            celery_task_id="failed-task-id",
            retry_count=3,
            total_steps=10
        )
        orchestrator.db.add(task)
        orchestrator.db.commit()
        
        result = orchestrator.retry_failed_task("failed-task-id")
        assert result is None

    @patch('src.services.task_orchestrator.load_pending_video_options')
    @patch('src.services.task_orchestrator.TaskOrchestrator.create_production_task')
    def test_retry_pending_provider_task_reuses_options_and_video_stage(
        self, mock_create, mock_pending, orchestrator, sample_project, sample_scenes
    ):
        task = TaskModel(
            project_id=sample_project.id,
            status=TaskStatus.FAILED,
            celery_task_id="pending-provider-task-id",
            retry_count=0,
            total_steps=10,
        )
        orchestrator.db.add(task)
        orchestrator.db.commit()
        mock_pending.return_value = {
            "provider": "seedance_api",
            "request_mode": "reference",
            "model": "doubao-seedance-2-5-260628",
            "resolution": "1080p",
            "output_format": "mp4",
            "duration_seconds": 2,
            "native_audio": True,
            "sequence_level_multi_shot": True,
            "sequence_output_path": "/tmp/sequence_42.mp4",
        }
        mock_create.return_value = "resumed-task-id"

        assert orchestrator.retry_failed_task(task.celery_task_id) == "resumed-task-id"
        kwargs = mock_create.call_args.kwargs
        assert kwargs["provider"] == "seedance_api"
        assert kwargs["model"] == "doubao-seedance-2-5-260628"
        assert kwargs["generate_images"] is False
        assert kwargs["generate_audios"] is False
        assert kwargs["generate_subtitles"] is False
        assert kwargs["generate_videos"] is True
        assert kwargs["sequence_level_multi_shot"] is True
        assert kwargs["sequence_output_path"] == "/tmp/sequence_42.mp4"

    @patch('src.services.task_orchestrator.load_production_video_options')
    @patch('src.services.task_orchestrator.TaskOrchestrator.create_production_task')
    def test_retry_without_pending_sidecar_preserves_last_video_options(
        self, mock_create, mock_saved, orchestrator, sample_project, sample_scenes
    ):
        task = TaskModel(
            project_id=sample_project.id,
            status=TaskStatus.FAILED,
            celery_task_id="failed-after-submit-task-id",
            retry_count=0,
            total_steps=10,
        )
        orchestrator.db.add(task)
        orchestrator.db.commit()
        mock_saved.return_value = {
            "provider": "seedance_api",
            "model": "doubao-seedance-2-0-260128",
            "resolution": "1080p",
            "output_format": "mp4",
            "draft_task_ids": {1: "draft-1", 2: "draft-2"},
            "sequence_level_multi_shot": False,
        }
        mock_create.return_value = "retry-with-options-task-id"

        assert orchestrator.retry_failed_task(task.celery_task_id) == "retry-with-options-task-id"
        mock_saved.assert_called_once_with(sample_project.id, task_id=task.id)
        kwargs = mock_create.call_args.kwargs
        assert kwargs["provider"] == "seedance_api"
        assert kwargs["model"] == "doubao-seedance-2-0-260128"
        assert kwargs["resolution"] == "1080p"
        assert kwargs["draft_task_ids"] == {1: "draft-1", 2: "draft-2"}
        assert kwargs.get("generate_images", True) is True
        assert kwargs.get("generate_videos", True) is True


class TestUpdateTaskProgress:
    """测试更新任务进度"""
    
    def test_update_task_progress(self, orchestrator, sample_project):
        """测试更新任务进度"""
        task = TaskModel(
            project_id=sample_project.id,
            status=TaskStatus.RUNNING,
            celery_task_id="test-task-id",
            progress=0.0,
            total_steps=10
        )
        orchestrator.db.add(task)
        orchestrator.db.commit()
        
        # 更新进度
        orchestrator.update_task_progress(task.id, 50.0)
        
        # 验证
        orchestrator.db.refresh(task)
        assert task.progress == 50.0


class TestMarkTaskCompleted:
    """测试标记任务完成"""
    
    def test_mark_task_completed(self, orchestrator, sample_project):
        """测试标记任务完成"""
        task = TaskModel(
            project_id=sample_project.id,
            status=TaskStatus.RUNNING,
            celery_task_id="test-task-id",
            total_steps=10
        )
        orchestrator.db.add(task)
        orchestrator.db.commit()
        
        # 标记完成
        output_path = "/path/to/output.mp4"
        orchestrator.mark_task_completed(task.id, output_path)
        
        # 验证
        orchestrator.db.refresh(task)
        assert task.status == TaskStatus.COMPLETED
        assert task.result_path == output_path
        assert task.progress == 100.0


class TestMarkTaskFailed:
    """测试标记任务失败"""
    
    def test_mark_task_failed(self, orchestrator, sample_project):
        """测试标记任务失败"""
        task = TaskModel(
            project_id=sample_project.id,
            status=TaskStatus.RUNNING,
            celery_task_id="test-task-id",
            total_steps=10
        )
        orchestrator.db.add(task)
        orchestrator.db.commit()
        
        # 标记失败
        error_message = "测试错误信息"
        orchestrator.mark_task_failed(task.id, error_message)
        
        # 验证
        orchestrator.db.refresh(task)
        assert task.status == TaskStatus.FAILED
        assert task.error_message == error_message


class TestSingletonPattern:
    """测试单例模式"""
    
    def test_get_task_orchestrator(self):
        """测试获取单例实例"""
        orchestrator1 = get_task_orchestrator()
        orchestrator2 = get_task_orchestrator()
        assert orchestrator1 is orchestrator2
    
    def test_cleanup_task_orchestrator(self):
        """测试清理单例实例"""
        orchestrator1 = get_task_orchestrator()
        cleanup_task_orchestrator()
        orchestrator2 = get_task_orchestrator()
        assert orchestrator1 is not orchestrator2
