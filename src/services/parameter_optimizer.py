"""
参数自动优化器（ParameterOptimizer）

根据场景类型、质量模式、GPU 显存等因素自动选择最优参数
"""

from typing import Dict, Optional, Any
from enum import Enum
from dataclasses import dataclass

from src.utils.logger import logger


class SceneType(str, Enum):
    """场景类型枚举"""
    PORTRAIT = "portrait"  # 人物特写
    CLOSE_UP = "close_up"  # 特写
    FULL_BODY = "full_body"  # 全身照
    WIDE_SHOT = "wide_shot"  # 广角/全景
    ACTION = "action"  # 动作场景
    INDOOR = "indoor"  # 室内
    OUTDOOR = "outdoor"  # 室外
    NIGHT = "night"  # 夜景
    LANDSCAPE = "landscape"  # 风景
    GENERAL = "general"  # 通用


class QualityMode(str, Enum):
    """质量模式枚举"""
    FAST = "fast"  # 快速模式（15-20步）
    NORMAL = "normal"  # 正常模式（20-25步）
    HIGH_QUALITY = "high_quality"  # 高质量模式（28-35步）
    ULTRA = "ultra"  # 超高质量模式（40-50步）


@dataclass
class OptimizedParameters:
    """优化后的参数"""
    steps: int
    cfg_scale: float
    width: int
    height: int
    sampler: str
    scheduler: str
    ipadapter_weight: Optional[float] = None
    denoise: float = 1.0
    
    # 优化决策依据
    decision_reasons: Dict[str, str] = None
    
    def __post_init__(self):
        if self.decision_reasons is None:
            self.decision_reasons = {}


class ParameterOptimizer:
    """参数自动优化器"""
    
    # 场景类型的 CFG Scale 推荐值
    SCENE_CFG_SCALE = {
        SceneType.PORTRAIT: 6.5,
        SceneType.CLOSE_UP: 6.5,
        SceneType.FULL_BODY: 7.0,
        SceneType.WIDE_SHOT: 7.5,
        SceneType.ACTION: 8.0,
        SceneType.INDOOR: 7.0,
        SceneType.OUTDOOR: 7.5,
        SceneType.NIGHT: 7.5,
        SceneType.LANDSCAPE: 8.0,
        SceneType.GENERAL: 7.0
    }
    
    # 质量模式的采样步数
    QUALITY_STEPS = {
        QualityMode.FAST: 15,
        QualityMode.NORMAL: 20,
        QualityMode.HIGH_QUALITY: 30,
        QualityMode.ULTRA: 45
    }
    
    # GPU 显存与分辨率的映射（单位：GB）
    VRAM_RESOLUTION = {
        4: (768, 768),    # 4GB 显存
        6: (1024, 1024),  # 6GB 显存
        8: (1024, 1024),  # 8GB 显存
        12: (1280, 1280), # 12GB 显存
        16: (1536, 1536), # 16GB+ 显存
    }
    
    def __init__(self):
        """初始化参数优化器"""
        logger.info("参数优化器初始化完成")
    
    def optimize(
        self,
        scene_type: Optional[SceneType] = None,
        quality_mode: Optional[QualityMode] = None,
        has_reference_image: bool = False,
        gpu_vram_gb: Optional[int] = None,
        base_width: int = 1024,
        base_height: int = 1024,
        custom_params: Optional[Dict[str, Any]] = None
    ) -> OptimizedParameters:
        """
        优化参数
        
        Args:
            scene_type: 场景类型
            quality_mode: 质量模式
            has_reference_image: 是否有参考图像
            gpu_vram_gb: GPU 显存大小（GB）
            base_width: 基础宽度
            base_height: 基础高度
            custom_params: 自定义参数（会覆盖优化结果）
            
        Returns:
            优化后的参数
        """
        # 默认值
        scene_type = scene_type or SceneType.GENERAL
        quality_mode = quality_mode or QualityMode.NORMAL
        custom_params = custom_params or {}
        
        decision_reasons = {}
        
        # 1. 优化采样步数
        steps = self._optimize_steps(quality_mode, decision_reasons)
        
        # 2. 优化 CFG Scale
        cfg_scale = self._optimize_cfg_scale(scene_type, decision_reasons)
        
        # 3. 优化分辨率
        width, height = self._optimize_resolution(
            gpu_vram_gb, base_width, base_height, decision_reasons
        )
        
        # 4. 优化 IP-Adapter 权重
        ipadapter_weight = self._optimize_ipadapter_weight(
            scene_type, has_reference_image, decision_reasons
        )
        
        # 5. 选择采样器和调度器
        sampler, scheduler = self._select_sampler_scheduler(
            quality_mode, decision_reasons
        )
        
        # 6. 应用自定义参数
        if custom_params:
            steps = custom_params.get("steps", steps)
            cfg_scale = custom_params.get("cfg_scale", cfg_scale)
            width = custom_params.get("width", width)
            height = custom_params.get("height", height)
            sampler = custom_params.get("sampler", sampler)
            scheduler = custom_params.get("scheduler", scheduler)
            if "ipadapter_weight" in custom_params:
                ipadapter_weight = custom_params["ipadapter_weight"]
            decision_reasons["custom_override"] = "应用了自定义参数覆盖"
        
        # 创建优化结果
        result = OptimizedParameters(
            steps=steps,
            cfg_scale=cfg_scale,
            width=width,
            height=height,
            sampler=sampler,
            scheduler=scheduler,
            ipadapter_weight=ipadapter_weight,
            decision_reasons=decision_reasons
        )
        
        # 记录优化决策
        self._log_optimization(result, scene_type, quality_mode, has_reference_image)
        
        return result
    
    def _optimize_steps(
        self,
        quality_mode: QualityMode,
        decision_reasons: Dict[str, str]
    ) -> int:
        """
        优化采样步数
        
        Args:
            quality_mode: 质量模式
            decision_reasons: 决策依据字典
            
        Returns:
            优化后的步数
        """
        steps = self.QUALITY_STEPS.get(quality_mode, 20)
        decision_reasons["steps"] = f"根据质量模式 {quality_mode} 选择 {steps} 步"
        return steps
    
    def _optimize_cfg_scale(
        self,
        scene_type: SceneType,
        decision_reasons: Dict[str, str]
    ) -> float:
        """
        优化 CFG Scale
        
        Args:
            scene_type: 场景类型
            decision_reasons: 决策依据字典
            
        Returns:
            优化后的 CFG Scale
        """
        cfg_scale = self.SCENE_CFG_SCALE.get(scene_type, 7.0)
        decision_reasons["cfg_scale"] = f"根据场景类型 {scene_type} 选择 CFG {cfg_scale}"
        return cfg_scale
    
    def _optimize_resolution(
        self,
        gpu_vram_gb: Optional[int],
        base_width: int,
        base_height: int,
        decision_reasons: Dict[str, str]
    ) -> tuple[int, int]:
        """
        优化分辨率（根据 GPU 显存）
        
        Args:
            gpu_vram_gb: GPU 显存大小（GB）
            base_width: 基础宽度
            base_height: 基础高度
            decision_reasons: 决策依据字典
            
        Returns:
            优化后的宽度和高度
        """
        if gpu_vram_gb is None:
            # 没有提供显存信息，使用基础分辨率
            decision_reasons["resolution"] = f"使用基础分辨率 {base_width}x{base_height}"
            return base_width, base_height
        
        # 根据显存选择合适的分辨率
        for vram_threshold in sorted(self.VRAM_RESOLUTION.keys(), reverse=True):
            if gpu_vram_gb >= vram_threshold:
                recommended_width, recommended_height = self.VRAM_RESOLUTION[vram_threshold]
                
                # 如果基础分辨率小于推荐分辨率，使用基础分辨率
                width = min(base_width, recommended_width)
                height = min(base_height, recommended_height)
                
                # 确保是 8 的倍数
                width = (width // 8) * 8
                height = (height // 8) * 8
                
                decision_reasons["resolution"] = (
                    f"根据 {gpu_vram_gb}GB 显存选择 {width}x{height} "
                    f"(推荐最大 {recommended_width}x{recommended_height})"
                )
                return width, height
        
        # 显存不足，降低分辨率
        width = 768
        height = 768
        decision_reasons["resolution"] = f"显存不足 ({gpu_vram_gb}GB)，降低到 {width}x{height}"
        logger.warning(f"GPU 显存不足 ({gpu_vram_gb}GB)，自动降低分辨率到 {width}x{height}")
        return width, height
    
    def _optimize_ipadapter_weight(
        self,
        scene_type: SceneType,
        has_reference_image: bool,
        decision_reasons: Dict[str, str]
    ) -> Optional[float]:
        """
        优化 IP-Adapter 权重
        
        Args:
            scene_type: 场景类型
            has_reference_image: 是否有参考图像
            decision_reasons: 决策依据字典
            
        Returns:
            优化后的 IP-Adapter 权重（如果不使用则返回 None）
        """
        if not has_reference_image:
            decision_reasons["ipadapter_weight"] = "无参考图像，不使用 IP-Adapter"
            return None
        
        # 根据场景类型调整权重
        if scene_type in [SceneType.PORTRAIT, SceneType.CLOSE_UP]:
            # 人物特写，使用较高权重以保持面部一致性
            weight = 0.85
            decision_reasons["ipadapter_weight"] = (
                f"场景类型 {scene_type} 使用较高权重 {weight} 以保持面部一致性"
            )
        elif scene_type in [SceneType.FULL_BODY]:
            # 全身照，使用中等权重
            weight = 0.75
            decision_reasons["ipadapter_weight"] = (
                f"场景类型 {scene_type} 使用中等权重 {weight} 平衡面部和整体"
            )
        elif scene_type in [SceneType.WIDE_SHOT, SceneType.LANDSCAPE]:
            # 广角/风景，使用较低权重
            weight = 0.65
            decision_reasons["ipadapter_weight"] = (
                f"场景类型 {scene_type} 使用较低权重 {weight} 避免过度约束"
            )
        else:
            # 其他场景，使用默认权重
            weight = 0.75
            decision_reasons["ipadapter_weight"] = f"使用默认权重 {weight}"
        
        return weight
    
    def _select_sampler_scheduler(
        self,
        quality_mode: QualityMode,
        decision_reasons: Dict[str, str]
    ) -> tuple[str, str]:
        """
        选择采样器和调度器
        
        Args:
            quality_mode: 质量模式
            decision_reasons: 决策依据字典
            
        Returns:
            采样器和调度器名称
        """
        if quality_mode == QualityMode.FAST:
            # 快速模式：使用 euler 采样器
            sampler = "euler"
            scheduler = "normal"
            decision_reasons["sampler"] = "快速模式使用 euler 采样器"
        elif quality_mode in [QualityMode.HIGH_QUALITY, QualityMode.ULTRA]:
            # 高质量模式：使用 dpmpp_2m 采样器
            sampler = "dpmpp_2m"
            scheduler = "karras"
            decision_reasons["sampler"] = "高质量模式使用 dpmpp_2m + karras"
        else:
            # 正常模式：使用 euler 采样器
            sampler = "euler"
            scheduler = "normal"
            decision_reasons["sampler"] = "正常模式使用 euler 采样器"
        
        return sampler, scheduler
    
    def _log_optimization(
        self,
        result: OptimizedParameters,
        scene_type: SceneType,
        quality_mode: QualityMode,
        has_reference_image: bool
    ):
        """
        记录优化决策
        
        Args:
            result: 优化结果
            scene_type: 场景类型
            quality_mode: 质量模式
            has_reference_image: 是否有参考图像
        """
        logger.info(
            f"参数优化完成 - 场景: {scene_type}, 质量: {quality_mode}, "
            f"参考图像: {has_reference_image}"
        )
        logger.info(
            f"优化结果 - steps: {result.steps}, cfg: {result.cfg_scale}, "
            f"分辨率: {result.width}x{result.height}, "
            f"采样器: {result.sampler}/{result.scheduler}"
        )
        if result.ipadapter_weight:
            logger.info(f"IP-Adapter 权重: {result.ipadapter_weight}")
        
        # 记录决策依据
        logger.debug("优化决策依据:")
        for key, reason in result.decision_reasons.items():
            logger.debug(f"  {key}: {reason}")


# 全局参数优化器实例（单例模式）
_parameter_optimizer_instance: Optional[ParameterOptimizer] = None


def get_parameter_optimizer() -> ParameterOptimizer:
    """
    获取全局参数优化器实例（单例模式）
    
    Returns:
        参数优化器实例
    """
    global _parameter_optimizer_instance
    
    if _parameter_optimizer_instance is None:
        _parameter_optimizer_instance = ParameterOptimizer()
        logger.info("全局参数优化器实例创建成功")
    
    return _parameter_optimizer_instance


def cleanup_parameter_optimizer():
    """
    清理全局参数优化器实例
    
    用于应用关闭时释放资源
    """
    global _parameter_optimizer_instance
    
    if _parameter_optimizer_instance is not None:
        _parameter_optimizer_instance = None
        logger.info("全局参数优化器实例已清理")
