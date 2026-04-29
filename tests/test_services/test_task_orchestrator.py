"""
TaskOrchestrator 服务单元测试
测试任务编排服务的核心功能
"""

import pytest
from unittest.mock import Mock, patch
from datetime import datetime
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.database.models import (
    Base, Project, Scene, Task as TaskModel,
    TaskStatus, TaskType, ProjectStatus
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
    project = Project(
        name="测试项目",
        description="测试描述",
        theme="测试主题",
        status=ProjectStatus.SCRIPT_GENERATED,
        total_scenes=3
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
            description=f"场景 {i + 1} 描述",
            dialogue=f"对话 {i + 1}",
            character_name=f"角色 {i + 1}",
            visual_prompt=f"视觉提示词 {i + 1}"
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
        self, mock_chain, orchestrator, sample_project, sample_scenes
    ):
        """测试成功创建生产任务"""
        # Mock Celery chain
        mock_result = Mock()
        mock_result.id = "test-celery-task-id"
        mock_chain.return_value.apply_async.return_value = mock_result
        
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
        assert task.status == TaskStatus.RUNNING
    
    def test_create_production_task_project_not_found(self, orchestrator):
        """测试项目不存在时抛出异常"""
        with pytest.raises(ValueError, match="项目不存在"):
            orchestrator.create_production_task(project_id=999)
    
    def test_create_production_task_no_scenes(self, orchestrator, sample_project):
        """测试项目没有分镜时抛出异常"""
        with pytest.raises(ValueError, match="项目没有分镜"):
            orchestrator.create_production_task(project_id=sample_project.id)


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
        # 3 scenes * 4 steps + 1 compose = 13
        assert total == 13


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
            task_type=TaskType.VIDEO_COMPOSITION,
            status=TaskStatus.RUNNING,
            celery_task_id="test-task-id",
            total_steps=10,
            progress=50.0
        )
        orchestrator.db.add(task)
        orchestrator.db.commit()
        
        # Mock AsyncResult
        mock_result = Mock()
        mock_result.state = "STARTED"
        mock_async_result.return_value = mock_result
        
        # 获取任务状态
        status = orchestrator.get_task_status("test-task-id")
        
        # 验证
        assert status["task_id"] == task.id
        assert status["status"] == TaskStatus.RUNNING.value
        assert status["progress"] == 50
    
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
            task_type=TaskType.VIDEO_COMPOSITION,
            status=TaskStatus.RUNNING,
            celery_task_id="running-task-id"
        )
        orchestrator.db.add(task)
        orchestrator.db.commit()
        
        # 取消任务
        result = orchestrator.cancel_task("running-task-id")
        
        # 验证
        assert result is True
        orchestrator.db.refresh(task)
        assert task.status == TaskStatus.CANCELLED
    
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
            task_type=TaskType.VIDEO_COMPOSITION,
            status=TaskStatus.FAILED,
            celery_task_id="failed-task-id",
            retry_count=0
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
            task_type=TaskType.VIDEO_COMPOSITION,
            status=TaskStatus.FAILED,
            celery_task_id="failed-task-id",
            retry_count=3
        )
        orchestrator.db.add(task)
        orchestrator.db.commit()
        
        result = orchestrator.retry_failed_task("failed-task-id")
        assert result is None


class TestUpdateTaskProgress:
    """测试更新任务进度"""
    
    def test_update_task_progress(self, orchestrator, sample_project):
        """测试更新任务进度"""
        task = TaskModel(
            project_id=sample_project.id,
            task_type=TaskType.VIDEO_COMPOSITION,
            status=TaskStatus.RUNNING,
            celery_task_id="test-task-id",
            progress=0.0
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
            task_type=TaskType.VIDEO_COMPOSITION,
            status=TaskStatus.RUNNING,
            celery_task_id="test-task-id"
        )
        orchestrator.db.add(task)
        orchestrator.db.commit()
        
        # 标记完成
        output_path = "/path/to/output.mp4"
        orchestrator.mark_task_completed(task.id, output_path)
        
        # 验证
        orchestrator.db.refresh(task)
        assert task.status == TaskStatus.COMPLETED
        assert task.result["output_path"] == output_path
        assert task.progress == 100.0


class TestMarkTaskFailed:
    """测试标记任务失败"""
    
    def test_mark_task_failed(self, orchestrator, sample_project):
        """测试标记任务失败"""
        task = TaskModel(
            project_id=sample_project.id,
            task_type=TaskType.VIDEO_COMPOSITION,
            status=TaskStatus.RUNNING,
            celery_task_id="test-task-id"
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
