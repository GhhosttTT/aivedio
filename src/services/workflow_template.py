"""
工作流模板服务

提供可复用的工作流模板，支持模板参数化、创建和导出。
"""

import json
import logging
from pathlib import Path
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field, asdict
from enum import Enum
from threading import Lock

from src.models.workflow_config import (
    WorkflowConfig, 
    WorkflowType,
    WorkflowMetadata,
    ParameterConfig,
    NegativePromptConfig,
    NodeConfig
)


logger = logging.getLogger(__name__)


class TemplateCategory(str, Enum):
    """模板分类"""
    BASIC = "basic"  # 基础模板
    ADVANCED = "advanced"  # 高级模板
    SPECIALIZED = "specialized"  # 专用模板
    CUSTOM = "custom"  # 自定义模板


@dataclass
class WorkflowTemplate:
    """
    工作流模板数据类
    
    定义可复用的工作流模板，支持参数化和实例化。
    """
    
    # 基本信息
    id: str  # 唯一标识符
    name: str  # 模板名称
    description: str  # 描述
    category: TemplateCategory  # 分类
    
    # 模板配置
    workflow_type: WorkflowType  # 工作流类型
    base_config: Dict[str, Any]  # 基础配置
    
    # 参数定义
    parameters: Dict[str, Dict[str, Any]] = field(default_factory=dict)  # 可配置参数
    
    # 元数据
    author: Optional[str] = None  # 作者
    version: str = "1.0"  # 版本号
    tags: List[str] = field(default_factory=list)  # 标签
    
    # 使用说明
    usage_guide: Optional[str] = None  # 使用指南
    example_params: Optional[Dict[str, Any]] = None  # 示例参数
    
    def validate_parameters(self, params: Dict[str, Any]) -> bool:
        """
        验证参数是否有效
        
        Args:
            params: 参数字典
            
        Returns:
            是否有效
        """
        for param_name, param_value in params.items():
            if param_name not in self.parameters:
                logger.warning(f"未知参数: {param_name}")
                return False
            
            param_def = self.parameters[param_name]
            
            # 检查类型
            expected_type = param_def.get("type")
            if expected_type:
                if expected_type == "int" and not isinstance(param_value, int):
                    logger.warning(f"参数 {param_name} 类型错误，期望 int")
                    return False
                elif expected_type == "float" and not isinstance(param_value, (int, float)):
                    logger.warning(f"参数 {param_name} 类型错误，期望 float")
                    return False
                elif expected_type == "str" and not isinstance(param_value, str):
                    logger.warning(f"参数 {param_name} 类型错误，期望 str")
                    return False
                elif expected_type == "bool" and not isinstance(param_value, bool):
                    logger.warning(f"参数 {param_name} 类型错误，期望 bool")
                    return False
            
            # 检查范围
            min_value = param_def.get("min")
            max_value = param_def.get("max")
            if min_value is not None and param_value < min_value:
                logger.warning(f"参数 {param_name} 小于最小值 {min_value}")
                return False
            if max_value is not None and param_value > max_value:
                logger.warning(f"参数 {param_name} 大于最大值 {max_value}")
                return False
        
        return True
    
    def create_config(self, params: Optional[Dict[str, Any]] = None) -> WorkflowConfig:
        """
        从模板创建工作流配置
        
        Args:
            params: 参数字典（可选）
            
        Returns:
            WorkflowConfig 实例
        """
        # 使用基础配置
        config_dict = self.base_config.copy()
        
        # 应用参数（合并到 parameters 字段）
        if params:
            if not self.validate_parameters(params):
                logger.warning("参数验证失败，使用默认参数")
            else:
                # 合并参数到配置的 parameters 字段
                if "parameters" not in config_dict:
                    config_dict["parameters"] = {}
                for param_name, param_value in params.items():
                    config_dict["parameters"][param_name] = param_value
        
        # 创建 WorkflowConfig
        try:
            # 创建 WorkflowMetadata
            workflow_meta = WorkflowMetadata(
                name=config_dict.get("name", self.name),
                version=config_dict.get("version", self.version),
                description=self.description,
                author=self.author or "",
                tags=self.tags
            )
            
            # 创建 ParameterConfig
            param_dict = config_dict.get("parameters", {})
            param_config = ParameterConfig(
                default=param_dict
            )
            
            # 创建 NegativePromptConfig
            negative_prompt_config = NegativePromptConfig(
                default=config_dict.get("negative_prompt", "")
            )
            
            # 创建 WorkflowConfig
            config = WorkflowConfig(
                workflow=workflow_meta,
                nodes=config_dict.get("nodes", {}),
                parameters=param_config,
                negative_prompt=negative_prompt_config,
                version=config_dict.get("config_version", "1.0")
            )
            return config
        except Exception as e:
            logger.error(f"创建配置失败: {e}")
            raise
    
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
            "category": self.category.value,
            "workflow_type": self.workflow_type.value,
            "base_config": self.base_config,
            "parameters": self.parameters,
            "author": self.author,
            "version": self.version,
            "tags": self.tags,
            "usage_guide": self.usage_guide,
            "example_params": self.example_params,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "WorkflowTemplate":
        """
        从字典创建实例
        
        Args:
            data: 字典数据
            
        Returns:
            WorkflowTemplate 实例
        """
        # 转换枚举类型
        if "category" in data and isinstance(data["category"], str):
            data["category"] = TemplateCategory(data["category"])
        
        if "workflow_type" in data and isinstance(data["workflow_type"], str):
            data["workflow_type"] = WorkflowType(data["workflow_type"])
        
        return cls(**data)


class WorkflowTemplateManager:
    """
    工作流模板管理器
    
    单例类，管理所有工作流模板。
    """
    
    _instance = None
    _lock = Lock()
    
    def __new__(cls):
        """单例模式"""
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
        return cls._instance
    
    def __init__(self):
        """初始化模板管理器"""
        # 避免重复初始化
        if hasattr(self, '_initialized'):
            return
        
        self._initialized = True
        self._templates: Dict[str, WorkflowTemplate] = {}  # ID -> Template
        self._templates_by_category: Dict[TemplateCategory, List[str]] = {}  # Category -> Template IDs
        self._template_dir = Path("configs/templates")
        
        # 加载预定义模板
        self._load_predefined_templates()
        
        logger.info("工作流模板管理器已初始化")
    
    def _load_predefined_templates(self):
        """加载预定义模板"""
        # 1. 基础文生图模板
        basic_txt2img = WorkflowTemplate(
            id="basic-txt2img",
            name="基础文生图",
            description="基础的文本生成图像模板，适合快速生成",
            category=TemplateCategory.BASIC,
            workflow_type=WorkflowType.BASIC,
            base_config={
                "name": "基础文生图",
                "version": "1.0",
                "nodes": {},
                "parameters": {
                    "sampling_steps": 20,
                    "cfg_scale": 7.0,
                    "sampler": "dpmpp_2m",
                    "scheduler": "karras",
                    "width": 1024,
                    "height": 1024,
                },
                "negative_prompt": "low quality, blurry, distorted, bad anatomy"
            },
            parameters={
                "sampling_steps": {
                    "type": "int",
                    "min": 1,
                    "max": 100,
                    "default": 20,
                    "description": "采样步数"
                },
                "cfg_scale": {
                    "type": "float",
                    "min": 1.0,
                    "max": 20.0,
                    "default": 7.0,
                    "description": "CFG Scale"
                },
                "width": {
                    "type": "int",
                    "min": 512,
                    "max": 2048,
                    "default": 1024,
                    "description": "图像宽度"
                },
                "height": {
                    "type": "int",
                    "min": 512,
                    "max": 2048,
                    "default": 1024,
                    "description": "图像高度"
                },
            },
            author="ComfyUI Official",
            tags=["基础", "文生图", "通用"],
            usage_guide="适合快速生成图像，参数简单易用",
            example_params={
                "sampling_steps": 25,
                "cfg_scale": 7.5,
                "width": 1024,
                "height": 1024
            }
        )
        self.add_template(basic_txt2img)
        
        # 2. IP-Adapter 模板
        ipadapter_template = WorkflowTemplate(
            id="ipadapter-template",
            name="IP-Adapter 模板",
            description="使用 IP-Adapter 实现人物一致性的模板",
            category=TemplateCategory.ADVANCED,
            workflow_type=WorkflowType.IPADAPTER,
            base_config={
                "name": "IP-Adapter",
                "version": "1.0",
                "nodes": {},
                "parameters": {
                    "sampling_steps": 25,
                    "cfg_scale": 6.0,
                    "sampler": "dpmpp_2m",
                    "scheduler": "karras",
                    "width": 1024,
                    "height": 1024,
                    "ipadapter_weight": 0.85,
                },
                "negative_prompt": "different person, multiple people, inconsistent face"
            },
            parameters={
                "sampling_steps": {
                    "type": "int",
                    "min": 1,
                    "max": 100,
                    "default": 25,
                    "description": "采样步数"
                },
                "cfg_scale": {
                    "type": "float",
                    "min": 1.0,
                    "max": 20.0,
                    "default": 6.0,
                    "description": "CFG Scale"
                },
                "ipadapter_weight": {
                    "type": "float",
                    "min": 0.0,
                    "max": 1.0,
                    "default": 0.85,
                    "description": "IP-Adapter 权重"
                },
            },
            author="ComfyUI Community",
            tags=["IP-Adapter", "人物一致性", "高级"],
            usage_guide="适合需要保持人物一致性的场景，需要提供参考图像",
            example_params={
                "sampling_steps": 30,
                "cfg_scale": 6.5,
                "ipadapter_weight": 0.90
            }
        )
        self.add_template(ipadapter_template)
        
        # 3. 真实感增强模板
        realism_template = WorkflowTemplate(
            id="realism-enhanced",
            name="真实感增强",
            description="专门优化的真实感增强模板，使用 Film Grain 和低 CFG",
            category=TemplateCategory.SPECIALIZED,
            workflow_type=WorkflowType.REALISM,
            base_config={
                "name": "真实感增强",
                "version": "1.0",
                "nodes": {},
                "parameters": {
                    "sampling_steps": 30,
                    "cfg_scale": 6.0,
                    "sampler": "dpmpp_2m",
                    "scheduler": "karras",
                    "width": 1024,
                    "height": 1024,
                },
                "negative_prompt": "CGI, 3D render, plastic skin, airbrushed, fake, artificial"
            },
            parameters={
                "sampling_steps": {
                    "type": "int",
                    "min": 20,
                    "max": 50,
                    "default": 30,
                    "description": "采样步数"
                },
                "cfg_scale": {
                    "type": "float",
                    "min": 5.0,
                    "max": 8.0,
                    "default": 6.0,
                    "description": "CFG Scale（真实感模式建议 5.5-6.5）"
                },
            },
            author="ComfyUI Community",
            tags=["真实感", "Film Grain", "专用"],
            usage_guide="适合需要极高真实感的场景，建议使用 RealVisXL 模型",
            example_params={
                "sampling_steps": 35,
                "cfg_scale": 5.8
            }
        )
        self.add_template(realism_template)
        
        # 4. 高清修复模板
        hires_fix_template = WorkflowTemplate(
            id="hires-fix",
            name="高清修复",
            description="使用高清修复技术提升图像分辨率和细节",
            category=TemplateCategory.ADVANCED,
            workflow_type=WorkflowType.HIGH_QUALITY,  # 使用 HIGH_QUALITY 代替 HIRES_FIX
            base_config={
                "name": "高清修复",
                "version": "1.0",
                "nodes": {},
                "parameters": {
                    "sampling_steps": 28,
                    "cfg_scale": 7.0,
                    "sampler": "dpmpp_2m",
                    "scheduler": "karras",
                    "width": 1024,
                    "height": 1024,
                    "upscale_factor": 1.5,
                    "denoise": 0.5,
                },
                "negative_prompt": "low quality, blurry, pixelated"
            },
            parameters={
                "sampling_steps": {
                    "type": "int",
                    "min": 15,
                    "max": 50,
                    "default": 28,
                    "description": "采样步数"
                },
                "upscale_factor": {
                    "type": "float",
                    "min": 1.0,
                    "max": 2.0,
                    "default": 1.5,
                    "description": "放大倍数"
                },
                "denoise": {
                    "type": "float",
                    "min": 0.0,
                    "max": 1.0,
                    "default": 0.5,
                    "description": "去噪强度"
                },
            },
            author="ComfyUI Official",
            tags=["高清修复", "放大", "细节"],
            usage_guide="适合需要提升图像分辨率的场景，建议先生成低分辨率图像再放大",
            example_params={
                "sampling_steps": 30,
                "upscale_factor": 2.0,
                "denoise": 0.6
            }
        )
        self.add_template(hires_fix_template)
        
        # 5. 快速生成模板
        fast_generation_template = WorkflowTemplate(
            id="fast-generation",
            name="快速生成",
            description="使用 SDXL Turbo 或低步数实现快速生成",
            category=TemplateCategory.BASIC,
            workflow_type=WorkflowType.FAST,
            base_config={
                "name": "快速生成",
                "version": "1.0",
                "nodes": {},
                "parameters": {
                    "sampling_steps": 15,
                    "cfg_scale": 7.0,
                    "sampler": "euler",
                    "scheduler": "normal",
                    "width": 768,
                    "height": 768,
                },
                "negative_prompt": "low quality, blurry"
            },
            parameters={
                "sampling_steps": {
                    "type": "int",
                    "min": 4,
                    "max": 20,
                    "default": 15,
                    "description": "采样步数"
                },
                "width": {
                    "type": "int",
                    "min": 512,
                    "max": 1024,
                    "default": 768,
                    "description": "图像宽度"
                },
                "height": {
                    "type": "int",
                    "min": 512,
                    "max": 1024,
                    "default": 768,
                    "description": "图像高度"
                },
            },
            author="ComfyUI Official",
            tags=["快速", "预览", "低步数"],
            usage_guide="适合快速预览和迭代，质量略低但速度快",
            example_params={
                "sampling_steps": 10,
                "width": 768,
                "height": 768
            }
        )
        self.add_template(fast_generation_template)
        
        logger.info("已加载 5 个预定义模板")
    
    def add_template(self, template: WorkflowTemplate):
        """
        添加模板
        
        Args:
            template: WorkflowTemplate 实例
        """
        self._templates[template.id] = template
        
        # 添加到分类索引
        if template.category not in self._templates_by_category:
            self._templates_by_category[template.category] = []
        if template.id not in self._templates_by_category[template.category]:
            self._templates_by_category[template.category].append(template.id)
        
        logger.debug(f"已添加模板: {template.name} (ID: {template.id})")
    
    def get_template(self, template_id: str) -> Optional[WorkflowTemplate]:
        """
        根据 ID 获取模板
        
        Args:
            template_id: 模板 ID
            
        Returns:
            WorkflowTemplate 实例，不存在返回 None
        """
        return self._templates.get(template_id)
    
    def get_all_templates(self) -> List[WorkflowTemplate]:
        """
        获取所有模板
        
        Returns:
            所有模板列表
        """
        return list(self._templates.values())
    
    def get_templates_by_category(self, category: TemplateCategory) -> List[WorkflowTemplate]:
        """
        根据分类获取模板
        
        Args:
            category: 分类
            
        Returns:
            模板列表
        """
        template_ids = self._templates_by_category.get(category, [])
        return [self._templates[tid] for tid in template_ids if tid in self._templates]
    
    def search_templates(
        self,
        keyword: Optional[str] = None,
        category: Optional[TemplateCategory] = None,
        tags: Optional[List[str]] = None
    ) -> List[WorkflowTemplate]:
        """
        搜索模板
        
        Args:
            keyword: 关键词（搜索名称和描述）
            category: 分类
            tags: 标签列表
            
        Returns:
            模板列表
        """
        templates = list(self._templates.values())
        
        # 关键词过滤
        if keyword:
            keyword_lower = keyword.lower()
            templates = [
                t for t in templates
                if keyword_lower in t.name.lower() or keyword_lower in t.description.lower()
            ]
        
        # 分类过滤
        if category:
            templates = [t for t in templates if t.category == category]
        
        # 标签过滤
        if tags:
            templates = [
                t for t in templates
                if all(tag in t.tags for tag in tags)
            ]
        
        return templates
    
    def export_template(
        self,
        config: WorkflowConfig,
        template_id: str,
        name: str,
        description: str,
        workflow_type: WorkflowType,  # 添加 workflow_type 参数
        category: TemplateCategory = TemplateCategory.CUSTOM,
        author: Optional[str] = None
    ) -> WorkflowTemplate:
        """
        从工作流配置导出为模板
        
        Args:
            config: WorkflowConfig 实例
            template_id: 模板 ID
            name: 模板名称
            description: 描述
            workflow_type: 工作流类型
            category: 分类
            author: 作者
            
        Returns:
            WorkflowTemplate 实例
        """
        # 创建基础配置
        base_config = {
            "name": config.workflow.name,
            "version": config.workflow.version,
            "nodes": config.nodes,
            "parameters": config.parameters.default,
            "negative_prompt": config.negative_prompt.default,
            "config_version": config.version
        }
        
        # 创建模板
        template = WorkflowTemplate(
            id=template_id,
            name=name,
            description=description,
            category=category,
            workflow_type=workflow_type,
            base_config=base_config,
            parameters={},  # 可以后续添加参数定义
            author=author or config.workflow.author,
            version=config.workflow.version,
            tags=config.workflow.tags,
        )
        
        # 添加到管理器
        self.add_template(template)
        
        logger.info(f"已导出模板: {name} (ID: {template_id})")
        return template
    
    def save_template(self, template: WorkflowTemplate, directory: Optional[Path] = None):
        """
        保存模板到文件
        
        Args:
            template: WorkflowTemplate 实例
            directory: 保存目录，默认为 configs/templates
        """
        if directory is None:
            directory = self._template_dir
        
        # 确保目录存在
        directory.mkdir(parents=True, exist_ok=True)
        
        # 生成文件名
        file_path = directory / f"{template.id}.json"
        
        try:
            with open(file_path, 'w', encoding='utf-8') as f:
                json.dump(template.to_dict(), f, indent=2, ensure_ascii=False)
            
            logger.info(f"已保存模板到文件: {file_path}")
        except Exception as e:
            logger.error(f"保存模板到文件失败 {file_path}: {e}")
            raise
    
    def load_template(self, file_path: Path) -> Optional[WorkflowTemplate]:
        """
        从文件加载模板
        
        Args:
            file_path: 文件路径
            
        Returns:
            WorkflowTemplate 实例，加载失败返回 None
        """
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            template = WorkflowTemplate.from_dict(data)
            return template
        except Exception as e:
            logger.error(f"从文件加载模板失败 {file_path}: {e}")
            return None
    
    def load_from_directory(self, directory: Optional[Path] = None) -> int:
        """
        从目录加载所有模板
        
        Args:
            directory: 目录路径，默认为 configs/templates
            
        Returns:
            加载的模板数量
        """
        if directory is None:
            directory = self._template_dir
        
        if not directory.exists():
            logger.warning(f"模板目录不存在: {directory}")
            return 0
        
        loaded_count = 0
        
        # 遍历目录中的所有 JSON 文件
        for template_file in directory.glob("*.json"):
            try:
                template = self.load_template(template_file)
                if template:
                    self.add_template(template)
                    loaded_count += 1
                    logger.info(f"已加载模板: {template.name} (ID: {template.id})")
            except Exception as e:
                logger.error(f"加载模板失败 {template_file}: {e}")
        
        logger.info(f"从 {directory} 加载了 {loaded_count} 个模板")
        return loaded_count


# 全局单例实例
_manager_instance = None


def get_workflow_template_manager() -> WorkflowTemplateManager:
    """
    获取工作流模板管理器单例实例
    
    Returns:
        WorkflowTemplateManager 实例
    """
    global _manager_instance
    if _manager_instance is None:
        _manager_instance = WorkflowTemplateManager()
    return _manager_instance
