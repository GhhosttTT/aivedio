"""
测试任务链构建和执行

验证修复后的任务链是否能正确构建和执行
"""

import pytest
from unittest.mock import Mock, patch, MagicMock
from sqlalchemy.orm import Session

from src.services.task_orchestrator import TaskOrchestrator
from src.database.models import Project, Scene, TaskStatus


class TestTaskChain:
    """测试任务链"""
    
    @pytest.fixture
    def mock_db_session(self):
        """模拟数据库会话"""
        session = Mock(spec=Session)
        return session
    
    @pytest.fixture
    def mock_project(self):
        """模拟项目"""
        project = Mock(spec=Project)
        project.id = 1
        project.name = "测试项目"
        project.status = "script_generated"
        return project
    
    @pytest.fixture
    def mock_scenes(self):
        """模拟分镜列表"""
        scenes = []
        for i in range(3):
            scene = Mock(spec=Scene)
            scene.id = i + 1
            scene.scene_number = i + 1
            scene.visual_description = f"分镜 {i + 1} 描述"
            scene.image_prompt = f"分镜 {i + 1} 提示词"
            scene.dialogue = f"分镜 {i + 1} 对话"
            scene.character_name = "角色A"
            scenes.append(scene)
        return scenes
    
    @pytest.fixture
    def orchestrator(self, mock_db_session):
        """创建任务编排器实例"""
        return TaskOrchestrator(mock_db_session)
    
    def test_build_task_chain_structure(self, orchestrator, mock_scenes):
        """测试任务链结构是否正确"""
        # 构建任务链
        task_chain = orchestrator._build_task_chain(
            project_id=1,
            task_id=1,
            scenes=mock_scenes,
            generate_images=True,
            generate_videos=True,
            generate_audios=True,
            generate_subtitles=True,
            add_bgm=False,
            bgm_path=None
        )
        
        # 验证任务链不为空
        assert task_chain is not None
        
        # 验证任务链类型
        from celery import chain
        assert isinstance(task_chain, chain)
    
    def test_build_task_chain_with_partial_steps(self, orchestrator, mock_scenes):
        """测试部分步骤的任务链"""
        # 只生成图像和视频
        task_chain = orchestrator._build_task_chain(
            project_id=1,
            task_id=1,
            scenes=mock_scenes,
            generate_images=True,
            generate_videos=True,
            generate_audios=False,
            generate_subtitles=False,
            add_bgm=False,
            bgm_path=None
        )
        
        assert task_chain is not None
    
    def test_calculate_total_steps(self, orchestrator):
        """测试总步骤数计算"""
        # 完整流程
        total = orchestrator._calculate_total_steps(
            scene_count=3,
            generate_images=True,
            generate_videos=True,
            generate_audios=True,
            generate_subtitles=True
        )
        # 3个分镜 * 4个步骤 + 1个合成步骤 = 13
        assert total == 13
        
        # 只生成图像
        total = orchestrator._calculate_total_steps(
            scene_count=3,
            generate_images=True,
            generate_videos=False,
            generate_audios=False,
            generate_subtitles=False
        )
        # 3个分镜 * 1个步骤 + 1个合成步骤 = 4
        assert total == 4
    
    @patch('src.services.task_orchestrator.chain')
    @patch('src.services.task_orchestrator.group')
    def test_task_chain_uses_immutable_signatures(
        self, 
        mock_group, 
        mock_chain, 
        orchestrator, 
        mock_scenes
    ):
        """测试任务链是否使用不可变签名 (.si())"""
        # 模拟 group 和 chain
        mock_group.return_value = MagicMock()
        mock_chain.return_value = MagicMock()
        
        # 构建任务链
        orchestrator._build_task_chain(
            project_id=1,
            task_id=1,
            scenes=mock_scenes,
            generate_images=True,
            generate_videos=True,
            generate_audios=True,
            generate_subtitles=True,
            add_bgm=False,
            bgm_path=None
        )
        
        # 验证 group 被调用了4次（图像、视频、音频、字幕）
        assert mock_group.call_count == 4
        
        # 验证 chain 被调用了1次
        assert mock_chain.call_count == 1
    
    @patch('src.services.task_orchestrator.TaskOrchestrator.create_production_task')
    def test_create_production_task_integration(
        self, 
        mock_create_task,
        mock_db_session,
        mock_project,
        mock_scenes
    ):
        """测试创建生产任务的集成流程"""
        # 模拟数据库查询
        mock_db_session.query.return_value.filter.return_value.first.return_value = mock_project
        mock_db_session.query.return_value.filter.return_value.order_by.return_value.all.return_value = mock_scenes
        
        # 模拟任务创建返回值
        mock_create_task.return_value = "test-task-id-123"
        
        # 创建任务编排器
        orchestrator = TaskOrchestrator(mock_db_session)
        
        # 调用创建生产任务
        task_id = orchestrator.create_production_task(project_id=1)
        
        # 验证返回了任务ID
        assert task_id == "test-task-id-123"


class TestTaskSignatures:
    """测试任务签名"""
    
    def test_video_task_signature(self):
        """测试视频生成任务签名"""
        from src.tasks.video_tasks import generate_video_task
        import inspect
        
        # 获取函数签名
        sig = inspect.signature(generate_video_task)
        params = list(sig.parameters.keys())
        
        # 验证参数列表
        assert 'self' in params
        assert 'scene_id' in params
        assert 'project_id' in params
        assert 'task_id' in params
        assert 'kwargs' in params
        
        # 验证不包含 previous_result
        assert 'previous_result' not in params
    
    def test_audio_task_signature(self):
        """测试音频生成任务签名"""
        from src.tasks.audio_tasks import generate_audio_task
        import inspect
        
        sig = inspect.signature(generate_audio_task)
        params = list(sig.parameters.keys())
        
        assert 'self' in params
        assert 'scene_id' in params
        assert 'text' in params
        assert 'speaker' in params
        assert 'project_id' in params
        assert 'task_id' in params
        assert 'kwargs' in params
        
        # 验证不包含 previous_result
        assert 'previous_result' not in params
    
    def test_subtitle_task_signature(self):
        """测试字幕生成任务签名"""
        from src.tasks.subtitle_tasks import generate_subtitle_task
        import inspect
        
        sig = inspect.signature(generate_subtitle_task)
        params = list(sig.parameters.keys())
        
        assert 'self' in params
        assert 'scene_id' in params
        assert 'project_id' in params
        assert 'task_id' in params
        assert 'kwargs' in params
        
        # 验证不包含 previous_result
        assert 'previous_result' not in params
    
    def test_compose_task_signature(self):
        """测试合成任务签名"""
        from src.tasks.composition_tasks import compose_final_video_task
        import inspect
        
        sig = inspect.signature(compose_final_video_task)
        params = list(sig.parameters.keys())
        
        assert 'self' in params
        assert 'project_id' in params
        assert 'task_id' in params
        assert 'add_bgm' in params
        assert 'bgm_path' in params
        assert 'kwargs' in params
        
        # 验证不包含 previous_result
        assert 'previous_result' not in params


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
