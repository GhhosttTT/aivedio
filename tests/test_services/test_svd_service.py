"""
SVD 服务单元测试

测试 SVDService 的核心功能
"""

import pytest
import sys
from unittest.mock import Mock, patch, MagicMock
from pathlib import Path

# 创建 Mock 模块
mock_torch = MagicMock()
mock_torch.float16 = MagicMock()
mock_torch.float32 = MagicMock()
mock_torch.cuda = MagicMock()
mock_torch.cuda.is_available = MagicMock(return_value=False)
mock_torch.cuda.empty_cache = MagicMock()

mock_diffusers = MagicMock()
mock_diffusers.StableVideoDiffusionPipeline = MagicMock
mock_diffusers.utils = MagicMock()
mock_diffusers.utils.load_image = MagicMock()
mock_diffusers.utils.export_to_video = MagicMock()

# 在导入前设置 Mock
sys.modules['torch'] = mock_torch
sys.modules['diffusers'] = mock_diffusers
sys.modules['diffusers.utils'] = mock_diffusers.utils

# 导入服务模块
from src.services.svd_service import (
    SVDService,
    SVDError,
    get_svd_service,
    cleanup_svd_service
)

# Patch DIFFUSERS_AVAILABLE 为 True（因为我们已经 Mock 了模块）
import src.services.svd_service as svd_module
svd_module.DIFFUSERS_AVAILABLE = True
svd_module.torch = mock_torch
svd_module.StableVideoDiffusionPipeline = mock_diffusers.StableVideoDiffusionPipeline


class TestSVDService:
    """SVD 服务测试类"""
    
    @pytest.fixture
    def mock_pipeline(self):
        """创建 Mock Pipeline"""
        pipeline = MagicMock()
        pipeline.to.return_value = pipeline
        pipeline.enable_model_cpu_offload = MagicMock()
        return pipeline
    
    @pytest.fixture
    def mock_gpu_utils(self):
        """Mock GPU 工具函数"""
        with patch('src.services.svd_service.is_gpu_available', return_value=False):
            with patch('src.services.svd_service.get_gpu_memory_info', return_value={
                'total_gb': 24.0,
                'used_gb': 10.0,
                'free_gb': 14.0
            }):
                with patch('src.services.svd_service.clear_gpu_cache'):
                    yield
    
    def test_init_success(self, mock_gpu_utils):
        """测试：成功初始化服务"""
        service = SVDService(
            model_path="test_model",
            num_frames=16,
            fps=8
        )
        
        assert service.model_path == "test_model"
        assert service.num_frames == 16
        assert service.fps == 8
        assert service.device == "cpu"  # GPU 不可用时使用 CPU
        assert service.is_loaded is False
    
    def test_load_model_success(self, mock_pipeline, mock_gpu_utils):
        """测试：成功加载模型"""
        with patch.object(svd_module, 'StableVideoDiffusionPipeline') as mock_svd:
            mock_svd.from_pretrained.return_value = mock_pipeline
            
            service = SVDService(model_path="test_model")
            service.load_model()
            
            assert service.is_loaded is True
            assert service.pipeline is not None
            mock_svd.from_pretrained.assert_called_once()
    
    def test_load_model_already_loaded(self, mock_pipeline, mock_gpu_utils):
        """测试：模型已加载时跳过"""
        with patch.object(svd_module, 'StableVideoDiffusionPipeline') as mock_svd:
            mock_svd.from_pretrained.return_value = mock_pipeline
            
            service = SVDService(model_path="test_model")
            service.load_model()
            service.load_model()  # 第二次调用
            
            # 验证只调用一次
            assert mock_svd.from_pretrained.call_count == 1
    
    def test_unload_model(self, mock_pipeline, mock_gpu_utils):
        """测试：卸载模型"""
        with patch.object(svd_module, 'StableVideoDiffusionPipeline') as mock_svd:
            mock_svd.from_pretrained.return_value = mock_pipeline
            
            service = SVDService(model_path="test_model")
            service.load_model()
            service.unload_model()
            
            assert service.pipeline is None
            assert service.is_loaded is False
    
    def test_check_gpu_memory_cpu_device(self, mock_gpu_utils):
        """测试：CPU 设备时总是返回 True"""
        service = SVDService(model_path="test_model")
        
        assert service.check_gpu_memory() is True
    
    def test_check_gpu_memory_sufficient(self):
        """测试：GPU 显存足够"""
        with patch('src.services.svd_service.is_gpu_available', return_value=True):
            with patch('src.services.svd_service.get_gpu_memory_info', return_value={
                'total_gb': 24.0,
                'used_gb': 10.0,
                'free_gb': 14.0
            }):
                service = SVDService(model_path="test_model")
                service.device = "cuda"
                
                assert service.check_gpu_memory(required_gb=8.0) is True
    
    def test_check_gpu_memory_insufficient(self):
        """测试：GPU 显存不足"""
        with patch('src.services.svd_service.is_gpu_available', return_value=True):
            with patch('src.services.svd_service.get_gpu_memory_info', return_value={
                'total_gb': 24.0,
                'used_gb': 20.0,
                'free_gb': 4.0
            }):
                service = SVDService(model_path="test_model")
                service.device = "cuda"
                
                assert service.check_gpu_memory(required_gb=8.0) is False
    
    def test_generate_video_image_not_found(self, mock_gpu_utils):
        """测试：输入图像不存在时抛出异常"""
        service = SVDService(model_path="test_model")
        
        with pytest.raises(FileNotFoundError):
            service.generate_video("nonexistent_image.png")
    
    def test_get_model_info(self, mock_gpu_utils):
        """测试：获取模型信息"""
        service = SVDService(
            model_path="test_model",
            num_frames=16,
            fps=8
        )
        
        info = service.get_model_info()
        
        assert info["model_path"] == "test_model"
        assert info["device"] == "cpu"
        assert info["num_frames"] == 16
        assert info["fps"] == 8
        assert info["is_loaded"] is False


class TestGlobalSVDService:
    """全局 SVD 服务测试类"""
    
    def setup_method(self):
        """每个测试前清理全局实例"""
        cleanup_svd_service()
    
    def teardown_method(self):
        """每个测试后清理全局实例"""
        cleanup_svd_service()
    
    def test_get_svd_service_singleton(self):
        """测试：全局服务实例是单例"""
        with patch('src.services.svd_service.is_gpu_available', return_value=False):
            # 获取两次实例
            service1 = get_svd_service()
            service2 = get_svd_service()
            
            # 验证是同一个实例
            assert service1 is service2
    
    def test_cleanup_svd_service(self):
        """测试：清理全局服务实例"""
        with patch('src.services.svd_service.is_gpu_available', return_value=False):
            # 获取实例
            service = get_svd_service()
            assert service is not None
            
            # 清理实例
            cleanup_svd_service()
            
            # 再次获取应该创建新实例
            service2 = get_svd_service()
            assert service2 is not service


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
