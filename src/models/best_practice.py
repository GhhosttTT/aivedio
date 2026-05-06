"""
最佳实践数据模型

定义最佳实践的数据结构，用于存储和管理从 Civitai 和 GitHub 收集的优秀工作流配置。
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any
from enum import Enum
from datetime import datetime


class PracticeSource(str, Enum):
    """最佳实践来源"""
    CIVITAI = "civitai"
    GITHUB = "github"
    COMMUNITY = "community"
    OFFICIAL = "official"
    CUSTOM = "custom"


class SceneCategory(str, Enum):
    """场景分类"""
    PORTRAIT = "portrait"  # 人物特写
    FULL_BODY = "full_body"  # 全身照
    CLOSE_UP = "close_up"  # 近景
    WIDE_SHOT = "wide_shot"  # 远景
    ACTION = "action"  # 动作场景
    INDOOR = "indoor"  # 室内场景
    OUTDOOR = "outdoor"  # 户外场景
    NIGHT = "night"  # 夜景
    LANDSCAPE = "landscape"  # 风景
    GENERAL = "general"  # 通用


@dataclass
class BestPractice:
    """
    最佳实践数据类
    
    存储优秀工作流配置的详细信息，包括来源、适用场景、关键参数和效果评分。
    """
    
    # 基本信息
    id: str  # 唯一标识符
    name: str  # 实践名称
    description: str  # 描述
    source: PracticeSource  # 来源
    source_url: Optional[str] = None  # 来源 URL
    author: Optional[str] = None  # 作者
    
    # 适用场景
    applicable_scenes: List[SceneCategory] = field(default_factory=list)  # 适用场景列表
    tags: List[str] = field(default_factory=list)  # 标签
    
    # 关键参数
    workflow_type: Optional[str] = None  # 工作流类型
    checkpoint: Optional[str] = None  # Checkpoint 模型
    lora_models: List[str] = field(default_factory=list)  # LoRA 模型列表
    sampling_steps: Optional[int] = None  # 采样步数
    cfg_scale: Optional[float] = None  # CFG Scale
    sampler: Optional[str] = None  # 采样器
    scheduler: Optional[str] = None  # 调度器
    resolution: Optional[str] = None  # 分辨率（如 "1024x1024"）
    ipadapter_weight: Optional[float] = None  # IP-Adapter 权重
    prompt_template: Optional[str] = None  # 提示词模板
    negative_prompt: Optional[str] = None  # 负面提示词
    additional_params: Dict[str, Any] = field(default_factory=dict)  # 其他参数
    
    # 效果评分
    quality_score: float = 0.0  # 质量评分（0-100）
    realism_score: float = 0.0  # 真实感评分（0-100）
    consistency_score: float = 0.0  # 一致性评分（0-100）
    speed_score: float = 0.0  # 速度评分（0-100）
    overall_score: float = 0.0  # 综合评分（0-100）
    
    # 使用统计
    usage_count: int = 0  # 使用次数
    success_rate: float = 0.0  # 成功率（0-1）
    average_generation_time: float = 0.0  # 平均生成时间（秒）
    
    # 元数据
    created_at: Optional[datetime] = None  # 创建时间
    updated_at: Optional[datetime] = None  # 更新时间
    version: str = "1.0"  # 版本号
    
    def __post_init__(self):
        """初始化后处理"""
        # 如果没有设置时间，使用当前时间
        if self.created_at is None:
            self.created_at = datetime.now()
        if self.updated_at is None:
            self.updated_at = datetime.now()
        
        # 计算综合评分（如果未设置）
        if self.overall_score == 0.0 and any([
            self.quality_score, self.realism_score, 
            self.consistency_score, self.speed_score
        ]):
            self.calculate_overall_score()
    
    def calculate_overall_score(self) -> float:
        """
        计算综合评分
        
        综合评分 = 质量评分 * 0.4 + 真实感评分 * 0.3 + 一致性评分 * 0.2 + 速度评分 * 0.1
        
        Returns:
            综合评分（0-100）
        """
        self.overall_score = (
            self.quality_score * 0.4 +
            self.realism_score * 0.3 +
            self.consistency_score * 0.2 +
            self.speed_score * 0.1
        )
        return self.overall_score
    
    def is_applicable_for_scene(self, scene: SceneCategory) -> bool:
        """
        检查是否适用于指定场景
        
        Args:
            scene: 场景类型
            
        Returns:
            是否适用
        """
        # 如果没有指定适用场景，则适用于所有场景
        if not self.applicable_scenes:
            return True
        
        # 如果包含 GENERAL，则适用于所有场景
        if SceneCategory.GENERAL in self.applicable_scenes:
            return True
        
        # 检查是否在适用场景列表中
        return scene in self.applicable_scenes
    
    def to_dict(self) -> Dict[str, Any]:
        """
        转换为字典
        
        Returns:
            字典表示
        """
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "source": self.source.value,
            "source_url": self.source_url,
            "author": self.author,
            "applicable_scenes": [scene.value for scene in self.applicable_scenes],
            "tags": self.tags,
            "workflow_type": self.workflow_type,
            "checkpoint": self.checkpoint,
            "lora_models": self.lora_models,
            "sampling_steps": self.sampling_steps,
            "cfg_scale": self.cfg_scale,
            "sampler": self.sampler,
            "scheduler": self.scheduler,
            "resolution": self.resolution,
            "ipadapter_weight": self.ipadapter_weight,
            "prompt_template": self.prompt_template,
            "negative_prompt": self.negative_prompt,
            "additional_params": self.additional_params,
            "quality_score": self.quality_score,
            "realism_score": self.realism_score,
            "consistency_score": self.consistency_score,
            "speed_score": self.speed_score,
            "overall_score": self.overall_score,
            "usage_count": self.usage_count,
            "success_rate": self.success_rate,
            "average_generation_time": self.average_generation_time,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
            "version": self.version,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "BestPractice":
        """
        从字典创建实例
        
        Args:
            data: 字典数据
            
        Returns:
            BestPractice 实例
        """
        # 转换枚举类型
        if "source" in data and isinstance(data["source"], str):
            data["source"] = PracticeSource(data["source"])
        
        if "applicable_scenes" in data:
            data["applicable_scenes"] = [
                SceneCategory(scene) if isinstance(scene, str) else scene
                for scene in data["applicable_scenes"]
            ]
        
        # 转换时间类型
        if "created_at" in data and isinstance(data["created_at"], str):
            data["created_at"] = datetime.fromisoformat(data["created_at"])
        
        if "updated_at" in data and isinstance(data["updated_at"], str):
            data["updated_at"] = datetime.fromisoformat(data["updated_at"])
        
        return cls(**data)
    
    def update_usage_stats(self, success: bool, generation_time: float):
        """
        更新使用统计
        
        Args:
            success: 是否成功
            generation_time: 生成时间（秒）
        """
        self.usage_count += 1
        
        # 更新成功率
        if self.usage_count == 1:
            self.success_rate = 1.0 if success else 0.0
        else:
            total_success = self.success_rate * (self.usage_count - 1)
            total_success += 1 if success else 0
            self.success_rate = total_success / self.usage_count
        
        # 更新平均生成时间
        if self.usage_count == 1:
            self.average_generation_time = generation_time
        else:
            total_time = self.average_generation_time * (self.usage_count - 1)
            total_time += generation_time
            self.average_generation_time = total_time / self.usage_count
        
        # 更新时间戳
        self.updated_at = datetime.now()
