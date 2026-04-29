"""
GPU 工具模块测试

测试 GPU 显存监控和缓存清理功能
"""

import pytest
from unittest.mock import Mock, patch, MagicMock


class TestGPUUtils:
    """GPU 工具测试类"""
    
    def test_is_gpu_available_with_cuda(self):
        """测试 GPU 可用性检查（CUDA 可用）"""
        with patch('src.utils.gpu_utils.torch') as mock_torch:
            mock_torch.cuda.is_available.return_value = True
            
            from src.utils.gpu_utils import is_gpu_available
            
            assert is_gpu_available() is True
            mock_torch.cuda.is_available.assert_called_once()
    
    def test_is_gpu_available_without_cuda(self):
        """测试 GPU 可用性检查（CUDA 不可用）"""
        with patch('src.utils.gpu_utils.torch') as mock_torch:
            mock_torch.cuda.is_available.return_value = False
            
            from src.utils.gpu_utils import is_gpu_available
            
            assert is_gpu_available() is False
    
    def test_is_gpu_available_no_torch(self):
        """测试 GPU 可用性检查（PyTorch 未安装）"""
        with patch('src.utils.gpu_utils.torch', side_effect=ImportError):
            from src.utils.gpu_utils import is_gpu_available
            
            assert is_gpu_available() is False
    
    def test_get_gpu_memory_info_success(self):
        """测试获取 GPU 显存信息（成功）"""
        with patch('src.utils.gpu_utils.torch') as mock_torch:
            # Mock CUDA 可用
            mock_torch.cuda.is_available.return_value = True
            mock_torch.cuda.device_count.return_value = 1
            
            # Mock 设备属性
            mock_props = Mock()
            mock_props.total_memory = 24 * 1024**3  # 24GB
            mock_torch.cuda.get_device_properties.return_value = mock_props
            mock_torch.cuda.get_device_name.return_value = "NVIDIA RTX 4090"
            
            # Mock 显存使用情况
            mock_torch.cuda.memory_allocated.return_value = 8 * 1024**3  # 8GB
            mock_torch.cuda.memory_reserved.return_value = 10 * 1024**3  # 10GB
            
            from src.utils.gpu_utils import get_gpu_memory_info
            
            info = get_gpu_memory_info(0)
            
            assert info is not None
            assert info["device_id"] == 0
            assert info["device_name"] == "NVIDIA RTX 4090"
            assert info["total"] == 24 * 1024  # MB
            assert info["used"] == 8 * 1024  # MB
            assert info["free"] == 16 * 1024  # MB
            assert 30 < info["usage_percent"] < 35  # 约 33.3%
    
    def test_get_gpu_memory_info_no_cuda(self):
        """测试获取 GPU 显存信息（CUDA 不可用）"""
        with patch('src.utils.gpu_utils.torch') as mock_torch:
            mock_torch.cuda.is_available.return_value = False
            
            from src.utils.gpu_utils import get_gpu_memory_info
            
            info = get_gpu_memory_info(0)
            
            assert info is None
    
    def test_get_gpu_memory_info_invalid_device(self):
        """测试获取 GPU 显存信息（无效设备 ID）"""
        with patch('src.utils.gpu_utils.torch') as mock_torch:
            mock_torch.cuda.is_available.return_value = True
            mock_torch.cuda.device_count.return_value = 1
            
            from src.utils.gpu_utils import get_gpu_memory_info
            
            info = get_gpu_memory_info(5)  # 设备 5 不存在
            
            assert info is None
    
    def test_clear_gpu_cache_success(self):
        """测试清理 GPU 缓存（成功）"""
        with patch('src.utils.gpu_utils.torch') as mock_torch:
            mock_torch.cuda.is_available.return_value = True
            mock_torch.cuda.memory_allocated.side_effect = [
                1000 * 1024**2,  # 清理前
                500 * 1024**2    # 清理后
            ]
            
            from src.utils.gpu_utils import clear_gpu_cache
            
            result = clear_gpu_cache(0)
            
            assert result is True
            mock_torch.cuda.empty_cache.assert_called_once()
    
    def test_clear_gpu_cache_all_devices(self):
        """测试清理所有 GPU 设备的缓存"""
        with patch('src.utils.gpu_utils.torch') as mock_torch:
            mock_torch.cuda.is_available.return_value = True
            mock_torch.cuda.device_count.return_value = 2
            mock_torch.cuda.memory_allocated.return_value = 1000 * 1024**2
            
            from src.utils.gpu_utils import clear_gpu_cache
            
            result = clear_gpu_cache(None)  # 清理所有设备
            
            assert result is True
            assert mock_torch.cuda.empty_cache.call_count == 2
    
    def test_clear_gpu_cache_no_cuda(self):
        """测试清理 GPU 缓存（CUDA 不可用）"""
        with patch('src.utils.gpu_utils.torch') as mock_torch:
            mock_torch.cuda.is_available.return_value = False
            
            from src.utils.gpu_utils import clear_gpu_cache
            
            result = clear_gpu_cache(0)
            
            assert result is False
    
    def test_check_gpu_memory_threshold_exceeded(self):
        """测试 GPU 显存阈值检查（超过阈值）"""
        with patch('src.utils.gpu_utils.get_gpu_memory_info') as mock_get_info:
            mock_get_info.return_value = {
                "device_id": 0,
                "device_name": "NVIDIA RTX 4090",
                "total": 24 * 1024,
                "used": 23 * 1024,
                "free": 1 * 1024,
                "usage_percent": 96.0
            }
            
            from src.utils.gpu_utils import check_gpu_memory_threshold
            
            result = check_gpu_memory_threshold(0, threshold_percent=95.0)
            
            assert result is True
    
    def test_check_gpu_memory_threshold_not_exceeded(self):
        """测试 GPU 显存阈值检查（未超过阈值）"""
        with patch('src.utils.gpu_utils.get_gpu_memory_info') as mock_get_info:
            mock_get_info.return_value = {
                "device_id": 0,
                "device_name": "NVIDIA RTX 4090",
                "total": 24 * 1024,
                "used": 12 * 1024,
                "free": 12 * 1024,
                "usage_percent": 50.0
            }
            
            from src.utils.gpu_utils import check_gpu_memory_threshold
            
            result = check_gpu_memory_threshold(0, threshold_percent=95.0)
            
            assert result is False
    
    def test_get_optimal_gpu_layers_sufficient_memory(self):
        """测试计算最优 GPU 层数（显存充足）"""
        from src.utils.gpu_utils import get_optimal_gpu_layers
        
        # 24GB GPU，8GB 模型
        layers = get_optimal_gpu_layers(24.0, 8.0)
        
        # 24 - 8 = 16GB 可用，8GB / 40层 = 0.2GB/层
        # 16 / 0.2 = 80 层，但最多 40 层
        assert layers == 40
    
    def test_get_optimal_gpu_layers_limited_memory(self):
        """测试计算最优 GPU 层数（显存有限）"""
        from src.utils.gpu_utils import get_optimal_gpu_layers
        
        # 12GB GPU，8GB 模型
        layers = get_optimal_gpu_layers(12.0, 8.0)
        
        # 12 - 8 = 4GB 可用，8GB / 40层 = 0.2GB/层
        # 4 / 0.2 = 20 层
        assert layers == 20
    
    def test_get_optimal_gpu_layers_insufficient_memory(self):
        """测试计算最优 GPU 层数（显存不足）"""
        from src.utils.gpu_utils import get_optimal_gpu_layers
        
        # 6GB GPU，8GB 模型
        layers = get_optimal_gpu_layers(6.0, 8.0)
        
        # 6 - 8 = -2GB，不足
        assert layers == 0
    
    def test_log_gpu_status_with_gpu(self):
        """测试记录 GPU 状态（GPU 可用）"""
        with patch('src.utils.gpu_utils.get_gpu_memory_info') as mock_get_info:
            mock_get_info.return_value = {
                "device_id": 0,
                "device_name": "NVIDIA RTX 4090",
                "total": 24 * 1024,
                "used": 12 * 1024,
                "free": 12 * 1024,
                "usage_percent": 50.0
            }
            
            from src.utils.gpu_utils import log_gpu_status
            
            # 不应该抛出异常
            log_gpu_status(0)
    
    def test_log_gpu_status_without_gpu(self):
        """测试记录 GPU 状态（GPU 不可用）"""
        with patch('src.utils.gpu_utils.get_gpu_memory_info') as mock_get_info:
            mock_get_info.return_value = None
            
            from src.utils.gpu_utils import log_gpu_status
            
            # 不应该抛出异常
            log_gpu_status(0)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
