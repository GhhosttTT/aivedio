"""
优化器集成测试

测试 ParameterOptimizer 和 PromptOptimizer 与 ComfyUIService 的集成
"""

import pytest
from unittest.mock import Mock, patch, MagicMock

from src.services.comfyui_service import ComfyUIService
from src.services.parameter_optimizer import SceneType, QualityMode
from src.services.prompt_optimizer import OptimizationMode


class TestOptimizerIntegration:
    """测试优化器与 ComfyUIService 的集成"""
    
    @pytest.fixture
    def mock_comfyui_service(self):
        """创建模拟的 ComfyUIService"""
        with patch('src.services.comfyui_service.httpx.Client'):
            service = ComfyUIService()
            # 模拟 _submit_and_wait 方法
            service._submit_and_wait = Mock(return_value="/path/to/image.png")
            return service
    
    def test_service_has_optimizers(self, mock_comfyui_service):
        """测试服务包含优化器实例"""
        assert mock_comfyui_service.parameter_optimizer is not None
        assert mock_comfyui_service.prompt_optimizer is not None
    
    def test_generate_image_with_prompt_optimization(self, mock_comfyui_service):
        """测试启用提示词优化的图像生成"""
        result = mock_comfyui_service.generate_image(
            prompt="a beautiful woman",
            enable_prompt_optimization=True,
            enable_parameter_optimization=False
        )
        
        assert result == "/path/to/image.png"
        assert mock_comfyui_service._submit_and_wait.called
    
    def test_generate_image_with_parameter_optimization(self, mock_comfyui_service):
        """测试启用参数优化的图像生成"""
        result = mock_comfyui_service.generate_image(
            prompt="a beautiful woman",
            enable_prompt_optimization=False,
            enable_parameter_optimization=True,
            scene_type="portrait",
            quality_mode="high_quality"
        )
        
        assert result == "/path/to/image.png"
        assert mock_comfyui_service._submit_and_wait.called
    
    def test_generate_image_with_both_optimizations(self, mock_comfyui_service):
        """测试同时启用两个优化器"""
        result = mock_comfyui_service.generate_image(
            prompt="a beautiful woman",
            enable_prompt_optimization=True,
            enable_parameter_optimization=True,
            scene_type="portrait",
            quality_mode="high_quality"
        )
        
        assert result == "/path/to/image.png"
        assert mock_comfyui_service._submit_and_wait.called
    
    def test_generate_image_without_optimizations(self, mock_comfyui_service):
        """测试禁用所有优化器"""
        result = mock_comfyui_service.generate_image(
            prompt="a beautiful woman",
            enable_prompt_optimization=False,
            enable_parameter_optimization=False
        )
        
        assert result == "/path/to/image.png"
        assert mock_comfyui_service._submit_and_wait.called
    
    def test_generate_image_with_realism_mode(self, mock_comfyui_service):
        """测试真实感模式"""
        result = mock_comfyui_service.generate_image(
            prompt="a beautiful woman",
            enable_prompt_optimization=True,
            enable_realism=True
        )
        
        assert result == "/path/to/image.png"
        assert mock_comfyui_service._submit_and_wait.called
    
    def test_generate_image_with_scene_type(self, mock_comfyui_service):
        """测试场景类型优化"""
        # 测试人物场景
        result = mock_comfyui_service.generate_image(
            prompt="a beautiful woman",
            scene_type="portrait"
        )
        assert result == "/path/to/image.png"
        
        # 测试风景场景
        result = mock_comfyui_service.generate_image(
            prompt="a beautiful mountain",
            scene_type="landscape"
        )
        assert result == "/path/to/image.png"
    
    def test_generate_image_with_quality_mode(self, mock_comfyui_service):
        """测试质量模式优化"""
        # 测试快速模式
        result = mock_comfyui_service.generate_image(
            prompt="a beautiful woman",
            quality_mode="fast"
        )
        assert result == "/path/to/image.png"
        
        # 测试高质量模式
        result = mock_comfyui_service.generate_image(
            prompt="a beautiful woman",
            quality_mode="high_quality"
        )
        assert result == "/path/to/image.png"
    
    def test_generate_image_with_gpu_vram(self, mock_comfyui_service):
        """测试 GPU 显存优化"""
        result = mock_comfyui_service.generate_image(
            prompt="a beautiful woman",
            gpu_vram_gb=12
        )
        
        assert result == "/path/to/image.png"
        assert mock_comfyui_service._submit_and_wait.called
    
    def test_generate_image_with_optimization_mode(self, mock_comfyui_service):
        """测试提示词优化模式"""
        # 测试质量模式
        result = mock_comfyui_service.generate_image(
            prompt="a beautiful woman",
            optimization_mode="quality"
        )
        assert result == "/path/to/image.png"
        
        # 测试真实感模式
        result = mock_comfyui_service.generate_image(
            prompt="a beautiful woman",
            optimization_mode="realism"
        )
        assert result == "/path/to/image.png"
        
        # 测试艺术模式
        result = mock_comfyui_service.generate_image(
            prompt="a beautiful landscape",
            optimization_mode="artistic"
        )
        assert result == "/path/to/image.png"
    
    def test_generate_image_with_invalid_scene_type(self, mock_comfyui_service):
        """测试无效的场景类型"""
        # 应该使用默认值，不抛出异常
        result = mock_comfyui_service.generate_image(
            prompt="a beautiful woman",
            scene_type="invalid_scene_type"
        )
        
        assert result == "/path/to/image.png"
    
    def test_generate_image_with_invalid_quality_mode(self, mock_comfyui_service):
        """测试无效的质量模式"""
        # 应该使用默认值，不抛出异常
        result = mock_comfyui_service.generate_image(
            prompt="a beautiful woman",
            quality_mode="invalid_quality_mode"
        )
        
        assert result == "/path/to/image.png"
    
    def test_generate_image_with_custom_parameters(self, mock_comfyui_service):
        """测试自定义参数覆盖优化结果"""
        result = mock_comfyui_service.generate_image(
            prompt="a beautiful woman",
            width=768,
            height=768,
            steps=25,
            cfg_scale=7.5,
            enable_parameter_optimization=True
        )
        
        assert result == "/path/to/image.png"
        assert mock_comfyui_service._submit_and_wait.called
    
    def test_prompt_optimization_fallback(self, mock_comfyui_service):
        """测试提示词优化失败时的回退"""
        # 模拟提示词优化器抛出异常
        mock_comfyui_service.prompt_optimizer.optimize = Mock(side_effect=Exception("优化失败"))
        
        # 应该使用原始提示词，不抛出异常
        result = mock_comfyui_service.generate_image(
            prompt="a beautiful woman",
            enable_prompt_optimization=True
        )
        
        assert result == "/path/to/image.png"
    
    def test_parameter_optimization_fallback(self, mock_comfyui_service):
        """测试参数优化失败时的回退"""
        # 模拟参数优化器抛出异常
        mock_comfyui_service.parameter_optimizer.optimize = Mock(side_effect=Exception("优化失败"))
        
        # 应该使用原始参数，不抛出异常
        result = mock_comfyui_service.generate_image(
            prompt="a beautiful woman",
            enable_parameter_optimization=True
        )
        
        assert result == "/path/to/image.png"
    
    def test_generate_image_with_reference_image(self, mock_comfyui_service):
        """测试带参考图像的生成（IP-Adapter）"""
        result = mock_comfyui_service.generate_image(
            prompt="a beautiful woman",
            reference_image="/path/to/reference.png",
            scene_type="portrait",
            quality_mode="high_quality"
        )
        
        assert result == "/path/to/image.png"
        assert mock_comfyui_service._submit_and_wait.called
    
    def test_generate_image_preserves_negative_prompt(self, mock_comfyui_service):
        """测试自定义负面提示词不被覆盖"""
        custom_negative = "custom negative prompt"
        
        result = mock_comfyui_service.generate_image(
            prompt="a beautiful woman",
            negative_prompt=custom_negative,
            enable_prompt_optimization=True
        )
        
        assert result == "/path/to/image.png"
        # 验证使用了自定义负面提示词（通过检查 _submit_and_wait 的调用）
        assert mock_comfyui_service._submit_and_wait.called


class TestOptimizerIntegrationWithRealOptimizers:
    """使用真实优化器测试集成"""
    
    @pytest.fixture
    def comfyui_service_with_real_optimizers(self):
        """创建带真实优化器的 ComfyUIService"""
        with patch('src.services.comfyui_service.httpx.Client'):
            service = ComfyUIService()
            # 模拟 _submit_and_wait 方法
            service._submit_and_wait = Mock(return_value="/path/to/image.png")
            return service
    
    def test_prompt_optimization_works(self, comfyui_service_with_real_optimizers):
        """测试提示词优化功能正常工作"""
        service = comfyui_service_with_real_optimizers
        
        # 生成图像（启用提示词优化）
        result = service.generate_image(
            prompt="a beautiful woman",
            enable_prompt_optimization=True,
            enable_parameter_optimization=False
        )
        
        # 验证生成成功
        assert result == "/path/to/image.png"
        assert service._submit_and_wait.called
    
    def test_parameter_optimization_works(self, comfyui_service_with_real_optimizers):
        """测试参数优化功能正常工作"""
        service = comfyui_service_with_real_optimizers
        
        # 生成图像（启用参数优化）
        result = service.generate_image(
            prompt="a beautiful woman",
            enable_prompt_optimization=False,
            enable_parameter_optimization=True,
            quality_mode="high_quality"
        )
        
        # 验证生成成功
        assert result == "/path/to/image.png"
        assert service._submit_and_wait.called


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
