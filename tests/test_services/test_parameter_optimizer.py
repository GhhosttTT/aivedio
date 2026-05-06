"""
参数优化器（ParameterOptimizer）单元测试
"""

import pytest
from unittest.mock import patch, MagicMock

from src.services.parameter_optimizer import (
    ParameterOptimizer,
    SceneType,
    QualityMode,
    OptimizedParameters,
    get_parameter_optimizer,
    cleanup_parameter_optimizer
)


class TestSceneType:
    """测试场景类型枚举"""
    
    def test_scene_type_values(self):
        """测试场景类型枚举值"""
        assert SceneType.PORTRAIT == "portrait"
        assert SceneType.CLOSE_UP == "close_up"
        assert SceneType.FULL_BODY == "full_body"
        assert SceneType.WIDE_SHOT == "wide_shot"
        assert SceneType.ACTION == "action"
        assert SceneType.INDOOR == "indoor"
        assert SceneType.OUTDOOR == "outdoor"
        assert SceneType.NIGHT == "night"
        assert SceneType.LANDSCAPE == "landscape"
        assert SceneType.GENERAL == "general"


class TestQualityMode:
    """测试质量模式枚举"""
    
    def test_quality_mode_values(self):
        """测试质量模式枚举值"""
        assert QualityMode.FAST == "fast"
        assert QualityMode.NORMAL == "normal"
        assert QualityMode.HIGH_QUALITY == "high_quality"
        assert QualityMode.ULTRA == "ultra"


class TestOptimizedParameters:
    """测试优化参数数据类"""
    
    def test_create_optimized_parameters(self):
        """测试创建优化参数"""
        params = OptimizedParameters(
            steps=20,
            cfg_scale=7.0,
            width=1024,
            height=1024,
            sampler="euler",
            scheduler="normal"
        )
        
        assert params.steps == 20
        assert params.cfg_scale == 7.0
        assert params.width == 1024
        assert params.height == 1024
        assert params.sampler == "euler"
        assert params.scheduler == "normal"
        assert params.ipadapter_weight is None
        assert params.denoise == 1.0
        assert params.decision_reasons == {}
    
    def test_create_with_ipadapter(self):
        """测试创建带 IP-Adapter 的参数"""
        params = OptimizedParameters(
            steps=30,
            cfg_scale=6.5,
            width=1024,
            height=1024,
            sampler="dpmpp_2m",
            scheduler="karras",
            ipadapter_weight=0.85
        )
        
        assert params.ipadapter_weight == 0.85
    
    def test_decision_reasons(self):
        """测试决策依据"""
        reasons = {"steps": "根据质量模式选择", "cfg_scale": "根据场景类型选择"}
        params = OptimizedParameters(
            steps=20,
            cfg_scale=7.0,
            width=1024,
            height=1024,
            sampler="euler",
            scheduler="normal",
            decision_reasons=reasons
        )
        
        assert params.decision_reasons == reasons


class TestParameterOptimizer:
    """测试参数优化器"""
    
    @pytest.fixture
    def optimizer(self):
        """创建参数优化器实例"""
        return ParameterOptimizer()
    
    # ==================== 测试采样步数优化 ====================
    
    def test_optimize_steps_fast_mode(self, optimizer):
        """测试快速模式的步数优化"""
        decision_reasons = {}
        steps = optimizer._optimize_steps(QualityMode.FAST, decision_reasons)
        
        assert steps == 15
        assert "steps" in decision_reasons
        assert "fast" in decision_reasons["steps"].lower()
    
    def test_optimize_steps_normal_mode(self, optimizer):
        """测试正常模式的步数优化"""
        decision_reasons = {}
        steps = optimizer._optimize_steps(QualityMode.NORMAL, decision_reasons)
        
        assert steps == 20
        assert "steps" in decision_reasons
    
    def test_optimize_steps_high_quality_mode(self, optimizer):
        """测试高质量模式的步数优化"""
        decision_reasons = {}
        steps = optimizer._optimize_steps(QualityMode.HIGH_QUALITY, decision_reasons)
        
        assert steps == 30
        assert "steps" in decision_reasons
    
    def test_optimize_steps_ultra_mode(self, optimizer):
        """测试超高质量模式的步数优化"""
        decision_reasons = {}
        steps = optimizer._optimize_steps(QualityMode.ULTRA, decision_reasons)
        
        assert steps == 45
        assert "steps" in decision_reasons
    
    # ==================== 测试 CFG Scale 优化 ====================
    
    def test_optimize_cfg_scale_portrait(self, optimizer):
        """测试人物特写的 CFG Scale 优化"""
        decision_reasons = {}
        cfg_scale = optimizer._optimize_cfg_scale(SceneType.PORTRAIT, decision_reasons)
        
        assert cfg_scale == 6.5
        assert "cfg_scale" in decision_reasons
        assert "portrait" in decision_reasons["cfg_scale"].lower()
    
    def test_optimize_cfg_scale_close_up(self, optimizer):
        """测试特写的 CFG Scale 优化"""
        decision_reasons = {}
        cfg_scale = optimizer._optimize_cfg_scale(SceneType.CLOSE_UP, decision_reasons)
        
        assert cfg_scale == 6.5
        assert "cfg_scale" in decision_reasons
    
    def test_optimize_cfg_scale_full_body(self, optimizer):
        """测试全身照的 CFG Scale 优化"""
        decision_reasons = {}
        cfg_scale = optimizer._optimize_cfg_scale(SceneType.FULL_BODY, decision_reasons)
        
        assert cfg_scale == 7.0
        assert "cfg_scale" in decision_reasons
    
    def test_optimize_cfg_scale_landscape(self, optimizer):
        """测试风景的 CFG Scale 优化"""
        decision_reasons = {}
        cfg_scale = optimizer._optimize_cfg_scale(SceneType.LANDSCAPE, decision_reasons)
        
        assert cfg_scale == 8.0
        assert "cfg_scale" in decision_reasons
    
    def test_optimize_cfg_scale_action(self, optimizer):
        """测试动作场景的 CFG Scale 优化"""
        decision_reasons = {}
        cfg_scale = optimizer._optimize_cfg_scale(SceneType.ACTION, decision_reasons)
        
        assert cfg_scale == 8.0
        assert "cfg_scale" in decision_reasons
    
    def test_optimize_cfg_scale_general(self, optimizer):
        """测试通用场景的 CFG Scale 优化"""
        decision_reasons = {}
        cfg_scale = optimizer._optimize_cfg_scale(SceneType.GENERAL, decision_reasons)
        
        assert cfg_scale == 7.0
        assert "cfg_scale" in decision_reasons
    
    # ==================== 测试分辨率优化 ====================
    
    def test_optimize_resolution_no_vram_info(self, optimizer):
        """测试没有显存信息时使用基础分辨率"""
        decision_reasons = {}
        width, height = optimizer._optimize_resolution(
            None, 1024, 1024, decision_reasons
        )
        
        assert width == 1024
        assert height == 1024
        assert "resolution" in decision_reasons
        assert "基础分辨率" in decision_reasons["resolution"]
    
    def test_optimize_resolution_4gb_vram(self, optimizer):
        """测试 4GB 显存的分辨率优化"""
        decision_reasons = {}
        width, height = optimizer._optimize_resolution(
            4, 1024, 1024, decision_reasons
        )
        
        assert width == 768
        assert height == 768
        assert "resolution" in decision_reasons
        assert "4" in decision_reasons["resolution"]
    
    def test_optimize_resolution_6gb_vram(self, optimizer):
        """测试 6GB 显存的分辨率优化"""
        decision_reasons = {}
        width, height = optimizer._optimize_resolution(
            6, 1024, 1024, decision_reasons
        )
        
        assert width == 1024
        assert height == 1024
        assert "resolution" in decision_reasons
    
    def test_optimize_resolution_12gb_vram(self, optimizer):
        """测试 12GB 显存的分辨率优化"""
        decision_reasons = {}
        width, height = optimizer._optimize_resolution(
            12, 1280, 1280, decision_reasons
        )
        
        assert width == 1280
        assert height == 1280
        assert "resolution" in decision_reasons
    
    def test_optimize_resolution_16gb_vram(self, optimizer):
        """测试 16GB 显存的分辨率优化"""
        decision_reasons = {}
        width, height = optimizer._optimize_resolution(
            16, 1536, 1536, decision_reasons
        )
        
        assert width == 1536
        assert height == 1536
        assert "resolution" in decision_reasons
    
    def test_optimize_resolution_base_smaller_than_recommended(self, optimizer):
        """测试基础分辨率小于推荐分辨率时使用基础分辨率"""
        decision_reasons = {}
        width, height = optimizer._optimize_resolution(
            12, 1024, 1024, decision_reasons
        )
        
        # 12GB 推荐 1280x1280，但基础是 1024x1024
        assert width == 1024
        assert height == 1024
    
    def test_optimize_resolution_ensure_multiple_of_8(self, optimizer):
        """测试确保分辨率是 8 的倍数"""
        decision_reasons = {}
        width, height = optimizer._optimize_resolution(
            8, 1025, 1025, decision_reasons
        )
        
        # 1025 不是 8 的倍数，应该向下取整到 1024
        assert width % 8 == 0
        assert height % 8 == 0
    
    def test_optimize_resolution_insufficient_vram(self, optimizer):
        """测试显存不足时降低分辨率"""
        decision_reasons = {}
        width, height = optimizer._optimize_resolution(
            2, 1024, 1024, decision_reasons
        )
        
        assert width == 768
        assert height == 768
        assert "显存不足" in decision_reasons["resolution"]
    
    # ==================== 测试 IP-Adapter 权重优化 ====================
    
    def test_optimize_ipadapter_weight_no_reference(self, optimizer):
        """测试没有参考图像时不使用 IP-Adapter"""
        decision_reasons = {}
        weight = optimizer._optimize_ipadapter_weight(
            SceneType.PORTRAIT, False, decision_reasons
        )
        
        assert weight is None
        assert "ipadapter_weight" in decision_reasons
        assert "无参考图像" in decision_reasons["ipadapter_weight"]
    
    def test_optimize_ipadapter_weight_portrait(self, optimizer):
        """测试人物特写的 IP-Adapter 权重"""
        decision_reasons = {}
        weight = optimizer._optimize_ipadapter_weight(
            SceneType.PORTRAIT, True, decision_reasons
        )
        
        assert weight == 0.85
        assert "ipadapter_weight" in decision_reasons
        assert "较高权重" in decision_reasons["ipadapter_weight"]
    
    def test_optimize_ipadapter_weight_close_up(self, optimizer):
        """测试特写的 IP-Adapter 权重"""
        decision_reasons = {}
        weight = optimizer._optimize_ipadapter_weight(
            SceneType.CLOSE_UP, True, decision_reasons
        )
        
        assert weight == 0.85
        assert "ipadapter_weight" in decision_reasons
    
    def test_optimize_ipadapter_weight_full_body(self, optimizer):
        """测试全身照的 IP-Adapter 权重"""
        decision_reasons = {}
        weight = optimizer._optimize_ipadapter_weight(
            SceneType.FULL_BODY, True, decision_reasons
        )
        
        assert weight == 0.75
        assert "ipadapter_weight" in decision_reasons
        assert "中等权重" in decision_reasons["ipadapter_weight"]
    
    def test_optimize_ipadapter_weight_wide_shot(self, optimizer):
        """测试广角的 IP-Adapter 权重"""
        decision_reasons = {}
        weight = optimizer._optimize_ipadapter_weight(
            SceneType.WIDE_SHOT, True, decision_reasons
        )
        
        assert weight == 0.65
        assert "ipadapter_weight" in decision_reasons
        assert "较低权重" in decision_reasons["ipadapter_weight"]
    
    def test_optimize_ipadapter_weight_landscape(self, optimizer):
        """测试风景的 IP-Adapter 权重"""
        decision_reasons = {}
        weight = optimizer._optimize_ipadapter_weight(
            SceneType.LANDSCAPE, True, decision_reasons
        )
        
        assert weight == 0.65
        assert "ipadapter_weight" in decision_reasons
    
    def test_optimize_ipadapter_weight_general(self, optimizer):
        """测试通用场景的 IP-Adapter 权重"""
        decision_reasons = {}
        weight = optimizer._optimize_ipadapter_weight(
            SceneType.GENERAL, True, decision_reasons
        )
        
        assert weight == 0.75
        assert "ipadapter_weight" in decision_reasons
        assert "默认权重" in decision_reasons["ipadapter_weight"]
    
    # ==================== 测试采样器和调度器选择 ====================
    
    def test_select_sampler_scheduler_fast_mode(self, optimizer):
        """测试快速模式的采样器选择"""
        decision_reasons = {}
        sampler, scheduler = optimizer._select_sampler_scheduler(
            QualityMode.FAST, decision_reasons
        )
        
        assert sampler == "euler"
        assert scheduler == "normal"
        assert "sampler" in decision_reasons
        assert "快速模式" in decision_reasons["sampler"]
    
    def test_select_sampler_scheduler_normal_mode(self, optimizer):
        """测试正常模式的采样器选择"""
        decision_reasons = {}
        sampler, scheduler = optimizer._select_sampler_scheduler(
            QualityMode.NORMAL, decision_reasons
        )
        
        assert sampler == "euler"
        assert scheduler == "normal"
        assert "sampler" in decision_reasons
    
    def test_select_sampler_scheduler_high_quality_mode(self, optimizer):
        """测试高质量模式的采样器选择"""
        decision_reasons = {}
        sampler, scheduler = optimizer._select_sampler_scheduler(
            QualityMode.HIGH_QUALITY, decision_reasons
        )
        
        assert sampler == "dpmpp_2m"
        assert scheduler == "karras"
        assert "sampler" in decision_reasons
        assert "高质量模式" in decision_reasons["sampler"]
    
    def test_select_sampler_scheduler_ultra_mode(self, optimizer):
        """测试超高质量模式的采样器选择"""
        decision_reasons = {}
        sampler, scheduler = optimizer._select_sampler_scheduler(
            QualityMode.ULTRA, decision_reasons
        )
        
        assert sampler == "dpmpp_2m"
        assert scheduler == "karras"
        assert "sampler" in decision_reasons
    
    # ==================== 测试完整优化流程 ====================
    
    def test_optimize_default_parameters(self, optimizer):
        """测试使用默认参数优化"""
        result = optimizer.optimize()
        
        # 默认值：GENERAL 场景，NORMAL 质量
        assert result.steps == 20
        assert result.cfg_scale == 7.0
        assert result.width == 1024
        assert result.height == 1024
        assert result.sampler == "euler"
        assert result.scheduler == "normal"
        assert result.ipadapter_weight is None
        assert result.denoise == 1.0
        assert len(result.decision_reasons) > 0
    
    def test_optimize_portrait_high_quality(self, optimizer):
        """测试人物特写高质量模式"""
        result = optimizer.optimize(
            scene_type=SceneType.PORTRAIT,
            quality_mode=QualityMode.HIGH_QUALITY,
            has_reference_image=True,
            gpu_vram_gb=12
        )
        
        assert result.steps == 30
        assert result.cfg_scale == 6.5
        assert result.width == 1024
        assert result.height == 1024
        assert result.sampler == "dpmpp_2m"
        assert result.scheduler == "karras"
        assert result.ipadapter_weight == 0.85
    
    def test_optimize_landscape_fast(self, optimizer):
        """测试风景快速模式"""
        result = optimizer.optimize(
            scene_type=SceneType.LANDSCAPE,
            quality_mode=QualityMode.FAST,
            has_reference_image=False,
            gpu_vram_gb=6
        )
        
        assert result.steps == 15
        assert result.cfg_scale == 8.0
        assert result.width == 1024
        assert result.height == 1024
        assert result.sampler == "euler"
        assert result.scheduler == "normal"
        assert result.ipadapter_weight is None
    
    def test_optimize_with_custom_params(self, optimizer):
        """测试自定义参数覆盖"""
        custom_params = {
            "steps": 25,
            "cfg_scale": 7.5,
            "width": 768,
            "height": 768,
            "sampler": "dpmpp_sde",
            "scheduler": "exponential",
            "ipadapter_weight": 0.9
        }
        
        result = optimizer.optimize(
            scene_type=SceneType.PORTRAIT,
            quality_mode=QualityMode.NORMAL,
            has_reference_image=True,
            custom_params=custom_params
        )
        
        # 自定义参数应该覆盖优化结果
        assert result.steps == 25
        assert result.cfg_scale == 7.5
        assert result.width == 768
        assert result.height == 768
        assert result.sampler == "dpmpp_sde"
        assert result.scheduler == "exponential"
        assert result.ipadapter_weight == 0.9
        assert "custom_override" in result.decision_reasons
    
    def test_optimize_with_partial_custom_params(self, optimizer):
        """测试部分自定义参数覆盖"""
        custom_params = {
            "steps": 35,
            "cfg_scale": 8.5
        }
        
        result = optimizer.optimize(
            scene_type=SceneType.ACTION,
            quality_mode=QualityMode.ULTRA,
            custom_params=custom_params
        )
        
        # 自定义参数覆盖
        assert result.steps == 35
        assert result.cfg_scale == 8.5
        
        # 其他参数使用优化结果
        assert result.sampler == "dpmpp_2m"
        assert result.scheduler == "karras"
    
    def test_optimize_ultra_quality_with_large_vram(self, optimizer):
        """测试超高质量模式 + 大显存"""
        result = optimizer.optimize(
            scene_type=SceneType.CLOSE_UP,
            quality_mode=QualityMode.ULTRA,
            has_reference_image=True,
            gpu_vram_gb=16,
            base_width=1536,
            base_height=1536
        )
        
        assert result.steps == 45
        assert result.cfg_scale == 6.5
        assert result.width == 1536
        assert result.height == 1536
        assert result.sampler == "dpmpp_2m"
        assert result.scheduler == "karras"
        assert result.ipadapter_weight == 0.85
    
    def test_optimize_with_low_vram(self, optimizer):
        """测试低显存优化"""
        result = optimizer.optimize(
            scene_type=SceneType.FULL_BODY,
            quality_mode=QualityMode.NORMAL,
            gpu_vram_gb=4,
            base_width=1024,
            base_height=1024
        )
        
        # 4GB 显存应该降低到 768x768
        assert result.width == 768
        assert result.height == 768
    
    @patch('src.services.parameter_optimizer.logger')
    def test_optimize_logs_decision(self, mock_logger, optimizer):
        """测试优化决策日志记录"""
        result = optimizer.optimize(
            scene_type=SceneType.PORTRAIT,
            quality_mode=QualityMode.HIGH_QUALITY,
            has_reference_image=True
        )
        
        # 验证日志记录被调用
        assert mock_logger.info.called
        assert mock_logger.debug.called


class TestGlobalParameterOptimizer:
    """测试全局参数优化器实例"""
    
    def test_get_parameter_optimizer_singleton(self):
        """测试单例模式"""
        # 清理现有实例
        cleanup_parameter_optimizer()
        
        # 获取第一个实例
        optimizer1 = get_parameter_optimizer()
        assert optimizer1 is not None
        
        # 获取第二个实例，应该是同一个对象
        optimizer2 = get_parameter_optimizer()
        assert optimizer2 is optimizer1
    
    def test_cleanup_parameter_optimizer(self):
        """测试清理全局实例"""
        # 获取实例
        optimizer1 = get_parameter_optimizer()
        assert optimizer1 is not None
        
        # 清理实例
        cleanup_parameter_optimizer()
        
        # 再次获取应该是新实例
        optimizer2 = get_parameter_optimizer()
        assert optimizer2 is not None
        assert optimizer2 is not optimizer1


class TestParameterOptimizerEdgeCases:
    """测试参数优化器边界情况"""
    
    @pytest.fixture
    def optimizer(self):
        """创建参数优化器实例"""
        return ParameterOptimizer()
    
    def test_optimize_with_zero_vram(self, optimizer):
        """测试 0GB 显存"""
        decision_reasons = {}
        width, height = optimizer._optimize_resolution(
            0, 1024, 1024, decision_reasons
        )
        
        # 应该降低到最低分辨率
        assert width == 768
        assert height == 768
    
    def test_optimize_with_very_large_vram(self, optimizer):
        """测试超大显存（32GB）"""
        decision_reasons = {}
        width, height = optimizer._optimize_resolution(
            32, 2048, 2048, decision_reasons
        )
        
        # 应该使用 16GB 的推荐分辨率（最高档）
        assert width == 1536
        assert height == 1536
    
    def test_optimize_with_odd_resolution(self, optimizer):
        """测试奇数分辨率"""
        decision_reasons = {}
        width, height = optimizer._optimize_resolution(
            8, 1023, 1023, decision_reasons
        )
        
        # 应该向下取整到 8 的倍数
        assert width % 8 == 0
        assert height % 8 == 0
        assert width <= 1023
        assert height <= 1023
    
    def test_optimize_with_empty_custom_params(self, optimizer):
        """测试空的自定义参数"""
        result = optimizer.optimize(
            scene_type=SceneType.GENERAL,
            quality_mode=QualityMode.NORMAL,
            custom_params={}
        )
        
        # 应该使用优化结果
        assert result.steps == 20
        assert result.cfg_scale == 7.0
    
    def test_optimize_with_none_custom_params(self, optimizer):
        """测试 None 自定义参数"""
        result = optimizer.optimize(
            scene_type=SceneType.GENERAL,
            quality_mode=QualityMode.NORMAL,
            custom_params=None
        )
        
        # 应该使用优化结果
        assert result.steps == 20
        assert result.cfg_scale == 7.0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
