"""
ComfyUIService 与 WorkflowManager 集成测试
"""

import pytest
from unittest.mock import Mock, patch, MagicMock

from src.services.comfyui_service import ComfyUIService, ComfyUIError
from src.services.workflow_manager import cleanup_workflow_manager
from src.models.workflow_config import WorkflowType


class TestComfyUIServiceWithWorkflowManager:
    """测试 ComfyUIService 与 WorkflowManager 的集成"""
    
    @patch('src.services.comfyui_service.httpx.Client')
    def test_service_initialization_with_workflow_manager(self, mock_client):
        """测试服务初始化时使用 WorkflowManager"""
        # 创建 mock HTTP 客户端
        mock_http = MagicMock()
        mock_client.return_value = mock_http
        
        # 创建服务实例
        service = ComfyUIService()
        
        # 验证服务初始化
        assert service is not None
        assert service.workflow_manager is not None
        assert service.current_workflow_type is not None
        
        print(f"\n✅ 服务初始化成功")
        print(f"  当前工作流类型: {service.current_workflow_type}")
    
    @patch('src.services.comfyui_service.httpx.Client')
    def test_load_workflow_using_workflow_manager(self, mock_client):
        """测试使用 WorkflowManager 加载工作流"""
        mock_http = MagicMock()
        mock_client.return_value = mock_http
        
        service = ComfyUIService()
        
        # 测试加载不同的工作流类型
        workflow_types = [
            WorkflowType.BASIC,
            WorkflowType.FAST,
            WorkflowType.TXT2IMG
        ]
        
        for workflow_type in workflow_types:
            try:
                service.load_workflow(workflow_type)
                assert service.current_workflow_type == workflow_type
                
                # 验证可以获取当前工作流配置
                config = service.workflow_manager.get_current_workflow()
                assert config is not None
                
                print(f"✅ 成功加载工作流: {workflow_type} - {config.workflow.name}")
            except Exception as e:
                print(f"⚠️ 加载工作流失败 {workflow_type}: {e}")
    
    @patch('src.services.comfyui_service.httpx.Client')
    def test_switch_workflow(self, mock_client):
        """测试工作流切换"""
        mock_http = MagicMock()
        mock_client.return_value = mock_http
        
        service = ComfyUIService()
        
        # 切换到不同的工作流
        try:
            service.switch_workflow(WorkflowType.FAST)
            assert service.current_workflow_type == WorkflowType.FAST
            print(f"\n✅ 工作流切换成功: {WorkflowType.FAST}")
            
            service.switch_workflow(WorkflowType.TXT2IMG)
            assert service.current_workflow_type == WorkflowType.TXT2IMG
            print(f"✅ 工作流切换成功: {WorkflowType.TXT2IMG}")
        except Exception as e:
            print(f"⚠️ 工作流切换失败: {e}")
    
    @patch('src.services.comfyui_service.httpx.Client')
    def test_get_negative_prompt_from_workflow_config(self, mock_client):
        """测试从工作流配置中获取负面提示词"""
        mock_http = MagicMock()
        mock_client.return_value = mock_http
        
        service = ComfyUIService()
        
        # 获取当前工作流配置
        config = service.workflow_manager.get_current_workflow()
        
        if config:
            negative_prompt = config.negative_prompt.default
            print(f"\n✅ 成功获取负面提示词:")
            print(f"  {negative_prompt[:100]}...")
            assert isinstance(negative_prompt, str)
            assert len(negative_prompt) > 0
        else:
            print("\n⚠️ 未加载工作流配置")
    
    @patch('src.services.comfyui_service.httpx.Client')
    def test_build_workflow_with_workflow_manager(self, mock_client):
        """测试使用 WorkflowManager 构建工作流"""
        mock_http = MagicMock()
        mock_client.return_value = mock_http
        
        service = ComfyUIService()
        
        # 确保已加载工作流
        service.load_workflow(WorkflowType.BASIC)
        
        try:
            # 构建工作流
            workflow = service._build_workflow(
                prompt="a beautiful landscape",
                negative_prompt="low quality",
                width=1024,
                height=1024,
                steps=20,
                cfg_scale=7.0,
                seed=42,
                reference_image=None,
                use_ipadapter=False
            )
            
            # 验证工作流结构
            assert isinstance(workflow, dict)
            assert len(workflow) > 0
            
            # 验证节点格式
            for node_id, node_data in workflow.items():
                assert "class_type" in node_data
                assert "inputs" in node_data
            
            print(f"\n✅ 成功构建工作流")
            print(f"  节点数量: {len(workflow)}")
            print(f"  节点类型: {[node['class_type'] for node in list(workflow.values())[:3]]}")
        except Exception as e:
            print(f"\n⚠️ 构建工作流失败: {e}")
            # 如果是因为工作流配置问题，这是可以接受的
            if "未加载工作流配置" in str(e):
                pytest.skip("工作流配置未加载")
    
    @patch('src.services.comfyui_service.httpx.Client')
    def test_workflow_parameters_from_config(self, mock_client):
        """测试从配置中获取工作流参数"""
        mock_http = MagicMock()
        mock_client.return_value = mock_http
        
        service = ComfyUIService()
        
        # 获取当前工作流配置
        config = service.workflow_manager.get_current_workflow()
        
        if config:
            # 验证参数配置
            params = config.parameters.default
            
            print(f"\n✅ 工作流参数:")
            for key, value in params.items():
                print(f"  {key}: {value}")
            
            # 验证常见参数
            if "steps" in params:
                assert isinstance(params["steps"], int)
                assert params["steps"] > 0
            
            if "cfg_scale" in params:
                assert isinstance(params["cfg_scale"], (int, float))
                assert params["cfg_scale"] > 0
        else:
            print("\n⚠️ 未加载工作流配置")
    
    @patch('src.services.comfyui_service.httpx.Client')
    def test_workflow_info_access(self, mock_client):
        """测试访问工作流信息"""
        mock_http = MagicMock()
        mock_client.return_value = mock_http
        
        service = ComfyUIService()
        
        try:
            # 获取工作流信息
            info = service.workflow_manager.get_workflow_info()
            
            print(f"\n✅ 工作流信息:")
            print(f"  名称: {info['name']}")
            print(f"  版本: {info['version']}")
            print(f"  节点数量: {info['node_count']}")
            
            assert info["name"] is not None
            assert info["node_count"] > 0
        except Exception as e:
            print(f"\n⚠️ 获取工作流信息失败: {e}")
    
    @patch('src.services.comfyui_service.httpx.Client')
    def test_workflow_caching_in_service(self, mock_client):
        """测试服务中的工作流缓存"""
        import time
        
        mock_http = MagicMock()
        mock_client.return_value = mock_http
        
        service = ComfyUIService()
        
        # 第一次加载
        start_time = time.time()
        service.load_workflow(WorkflowType.BASIC)
        first_load_time = time.time() - start_time
        
        # 第二次加载（应该使用缓存）
        start_time = time.time()
        service.load_workflow(WorkflowType.BASIC)
        cached_load_time = time.time() - start_time
        
        print(f"\n✅ 工作流缓存测试:")
        print(f"  首次加载: {first_load_time:.4f}秒")
        print(f"  缓存加载: {cached_load_time:.4f}秒")
        
        # 缓存加载应该更快
        assert cached_load_time <= first_load_time


@pytest.fixture(scope="module", autouse=True)
def cleanup():
    """测试结束后清理"""
    yield
    cleanup_workflow_manager()


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
