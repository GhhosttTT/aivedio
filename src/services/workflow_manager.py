"""
工作流管理器（WorkflowManager）

负责加载、切换、验证和管理多个 ComfyUI 工作流配置
"""

import os
import time
from typing import Dict, List, Optional
from pathlib import Path
import json

from src.models.workflow_config import WorkflowConfig, WorkflowType
from src.utils.logger import logger


class WorkflowManagerError(Exception):
    """工作流管理器错误"""
    pass


class WorkflowManager:
    """工作流管理器"""
    
    # 预定义工作流类型映射
    PREDEFINED_WORKFLOWS = {
        WorkflowType.BASIC: "./configs/comfyui_workflow.json",
        WorkflowType.FAST: "./configs/comfyui_workflow_fast.json",
        WorkflowType.HIGH_QUALITY: "./configs/comfyui_workflow_pro.json",
        WorkflowType.REALISM: "./configs/comfyui_workflow_juggernaut.json",
        WorkflowType.CHARACTER_CONSISTENCY: "./configs/comfyui_workflow_ipadapter.json",
        WorkflowType.IPADAPTER: "./configs/comfyui_workflow_ipadapter.json",
        WorkflowType.TXT2IMG: "./configs/comfyui_workflow_txt2img.json",
        WorkflowType.PRO: "./configs/comfyui_workflow_pro.json",
        WorkflowType.SDXL: "./configs/comfyui_workflow_sdxl.json",
        WorkflowType.SDXL_NATIVE: "./configs/comfyui_workflow_sdxl_native.json",
        WorkflowType.JUGGERNAUT: "./configs/comfyui_workflow_juggernaut.json"
    }
    
    # 默认工作流类型
    DEFAULT_WORKFLOW_TYPE = WorkflowType.BASIC
    
    def __init__(self, config_dir: Optional[str] = None):
        """
        初始化工作流管理器
        
        Args:
            config_dir: 配置文件目录（默认 ./configs）
        """
        self.config_dir = Path(config_dir or "./configs")
        
        # 当前加载的工作流配置
        self.current_workflow: Optional[WorkflowConfig] = None
        self.current_workflow_type: Optional[WorkflowType] = None
        self.current_workflow_path: Optional[str] = None
        
        # 工作流配置缓存（工作流类型 -> 配置对象）
        self.workflow_cache: Dict[str, WorkflowConfig] = {}
        
        # 自定义工作流注册表（名称 -> 文件路径）
        self.custom_workflows: Dict[str, str] = {}
        
        logger.info(f"工作流管理器初始化完成，配置目录: {self.config_dir}")
    
    def load_workflow(
        self,
        workflow_path: Optional[str] = None,
        workflow_type: Optional[WorkflowType] = None,
        use_cache: bool = True
    ) -> WorkflowConfig:
        """
        加载工作流配置文件
        
        Args:
            workflow_path: 工作流配置文件路径（可选）
            workflow_type: 工作流类型（可选，如果提供则使用预定义路径）
            use_cache: 是否使用缓存（默认 True）
            
        Returns:
            工作流配置对象
            
        Raises:
            WorkflowManagerError: 如果加载失败
        """
        start_time = time.time()
        
        try:
            # 确定工作流路径
            if workflow_type:
                if workflow_type not in self.PREDEFINED_WORKFLOWS:
                    raise WorkflowManagerError(f"不支持的工作流类型: {workflow_type}")
                workflow_path = self.PREDEFINED_WORKFLOWS[workflow_type]
            elif not workflow_path:
                # 使用默认工作流
                workflow_type = self.DEFAULT_WORKFLOW_TYPE
                workflow_path = self.PREDEFINED_WORKFLOWS[workflow_type]
            
            # 检查缓存
            cache_key = workflow_path
            if use_cache and cache_key in self.workflow_cache:
                logger.debug(f"从缓存加载工作流: {workflow_path}")
                config = self.workflow_cache[cache_key]
                self.current_workflow = config
                self.current_workflow_type = workflow_type
                self.current_workflow_path = workflow_path
                return config
            
            # 加载配置文件
            logger.info(f"加载工作流配置: {workflow_path}")
            
            # 支持相对路径和绝对路径
            path = Path(workflow_path)
            if not path.is_absolute():
                path = Path.cwd() / path
            
            if not path.exists():
                raise FileNotFoundError(f"工作流配置文件不存在: {path}")
            
            # 解析配置
            config = WorkflowConfig.from_json_file(str(path))
            
            # 验证配置
            errors = config.validate()
            if errors:
                error_msg = f"工作流配置验证失败:\n" + "\n".join(f"  - {err}" for err in errors)
                logger.error(error_msg)
                raise WorkflowManagerError(error_msg)
            
            # 缓存配置
            self.workflow_cache[cache_key] = config
            
            # 更新当前工作流
            self.current_workflow = config
            self.current_workflow_type = workflow_type
            self.current_workflow_path = workflow_path
            
            elapsed_time = time.time() - start_time
            logger.info(
                f"工作流加载成功: {config.workflow.name} v{config.workflow.version} "
                f"({elapsed_time:.2f}秒)"
            )
            
            return config
            
        except FileNotFoundError as e:
            error_msg = f"工作流配置文件不存在: {e}"
            logger.error(error_msg)
            # 尝试回退到默认工作流
            if workflow_type != self.DEFAULT_WORKFLOW_TYPE:
                logger.warning(f"回退到默认工作流: {self.DEFAULT_WORKFLOW_TYPE}")
                return self.load_workflow(workflow_type=self.DEFAULT_WORKFLOW_TYPE)
            raise WorkflowManagerError(error_msg) from e
            
        except json.JSONDecodeError as e:
            error_msg = f"工作流配置文件格式错误: {e}"
            logger.error(error_msg)
            # 尝试回退到默认工作流
            if workflow_type != self.DEFAULT_WORKFLOW_TYPE:
                logger.warning(f"回退到默认工作流: {self.DEFAULT_WORKFLOW_TYPE}")
                return self.load_workflow(workflow_type=self.DEFAULT_WORKFLOW_TYPE)
            raise WorkflowManagerError(error_msg) from e
            
        except WorkflowManagerError:
            # 已经是 WorkflowManagerError，直接抛出
            raise
            
        except Exception as e:
            error_msg = f"加载工作流配置失败: {e}"
            logger.error(error_msg)
            # 尝试回退到默认工作流
            if workflow_type != self.DEFAULT_WORKFLOW_TYPE:
                logger.warning(f"回退到默认工作流: {self.DEFAULT_WORKFLOW_TYPE}")
                return self.load_workflow(workflow_type=self.DEFAULT_WORKFLOW_TYPE)
            raise WorkflowManagerError(error_msg) from e
    
    def switch_workflow(
        self,
        workflow_type: WorkflowType,
        force_reload: bool = False
    ) -> WorkflowConfig:
        """
        切换工作流（2秒内完成）
        
        Args:
            workflow_type: 目标工作流类型
            force_reload: 是否强制重新加载（默认 False，使用缓存）
            
        Returns:
            工作流配置对象
            
        Raises:
            WorkflowManagerError: 如果切换失败
        """
        start_time = time.time()
        
        logger.info(f"切换工作流: {self.current_workflow_type} -> {workflow_type}")
        
        try:
            # 如果已经是目标工作流且不强制重新加载，直接返回
            if (not force_reload and 
                self.current_workflow_type == workflow_type and 
                self.current_workflow is not None):
                logger.debug(f"已经是目标工作流: {workflow_type}")
                return self.current_workflow
            
            # 加载新工作流
            config = self.load_workflow(
                workflow_type=workflow_type,
                use_cache=not force_reload
            )
            
            elapsed_time = time.time() - start_time
            
            # 检查是否在 2 秒内完成
            if elapsed_time > 2.0:
                logger.warning(f"工作流切换耗时超过 2 秒: {elapsed_time:.2f}秒")
            else:
                logger.info(f"工作流切换成功，耗时: {elapsed_time:.2f}秒")
            
            return config
            
        except Exception as e:
            error_msg = f"切换工作流失败: {e}"
            logger.error(error_msg)
            raise WorkflowManagerError(error_msg) from e
    
    def validate_workflow(self, config: WorkflowConfig) -> List[str]:
        """
        验证工作流配置
        
        Args:
            config: 工作流配置对象
            
        Returns:
            错误列表（空列表表示验证通过）
        """
        logger.debug(f"验证工作流配置: {config.workflow.name}")
        errors = config.validate()
        
        if errors:
            logger.warning(f"工作流配置验证失败，发现 {len(errors)} 个错误")
            for error in errors:
                logger.warning(f"  - {error}")
        else:
            logger.debug("工作流配置验证通过")
        
        return errors
    
    def get_current_workflow(self) -> Optional[WorkflowConfig]:
        """
        获取当前工作流配置
        
        Returns:
            当前工作流配置对象（如果未加载则返回 None）
        """
        return self.current_workflow
    
    def get_current_workflow_type(self) -> Optional[WorkflowType]:
        """
        获取当前工作流类型
        
        Returns:
            当前工作流类型（如果未加载则返回 None）
        """
        return self.current_workflow_type
    
    def list_available_workflows(self) -> List[Dict[str, str]]:
        """
        列出所有可用的工作流
        
        Returns:
            工作流列表（包含类型、名称、路径）
        """
        workflows = []
        
        # 预定义工作流
        for workflow_type, workflow_path in self.PREDEFINED_WORKFLOWS.items():
            path = Path(workflow_path)
            if not path.is_absolute():
                path = Path.cwd() / path
            
            workflows.append({
                "type": workflow_type,
                "name": workflow_type.replace("_", " ").title(),
                "path": str(path),
                "exists": path.exists(),
                "is_custom": False
            })
        
        # 自定义工作流
        for name, workflow_path in self.custom_workflows.items():
            path = Path(workflow_path)
            workflows.append({
                "type": "custom",
                "name": name,
                "path": str(path),
                "exists": path.exists(),
                "is_custom": True
            })
        
        return workflows
    
    def register_custom_workflow(self, name: str, workflow_path: str):
        """
        注册自定义工作流
        
        Args:
            name: 工作流名称
            workflow_path: 工作流配置文件路径
            
        Raises:
            WorkflowManagerError: 如果注册失败
        """
        try:
            path = Path(workflow_path)
            if not path.exists():
                raise FileNotFoundError(f"工作流配置文件不存在: {workflow_path}")
            
            # 验证配置文件
            config = WorkflowConfig.from_json_file(str(path))
            errors = config.validate()
            if errors:
                raise WorkflowManagerError(f"工作流配置验证失败: {errors}")
            
            # 注册
            self.custom_workflows[name] = workflow_path
            logger.info(f"自定义工作流注册成功: {name} -> {workflow_path}")
            
        except Exception as e:
            error_msg = f"注册自定义工作流失败: {e}"
            logger.error(error_msg)
            raise WorkflowManagerError(error_msg) from e
    
    def unregister_custom_workflow(self, name: str):
        """
        注销自定义工作流
        
        Args:
            name: 工作流名称
        """
        if name in self.custom_workflows:
            del self.custom_workflows[name]
            logger.info(f"自定义工作流已注销: {name}")
        else:
            logger.warning(f"自定义工作流不存在: {name}")
    
    def load_custom_workflow(self, name: str) -> WorkflowConfig:
        """
        加载自定义工作流
        
        Args:
            name: 工作流名称
            
        Returns:
            工作流配置对象
            
        Raises:
            WorkflowManagerError: 如果加载失败
        """
        if name not in self.custom_workflows:
            raise WorkflowManagerError(f"自定义工作流不存在: {name}")
        
        workflow_path = self.custom_workflows[name]
        return self.load_workflow(workflow_path=workflow_path)
    
    def clear_cache(self):
        """清除工作流配置缓存"""
        self.workflow_cache.clear()
        logger.info("工作流配置缓存已清除")
    
    def reload_current_workflow(self) -> WorkflowConfig:
        """
        重新加载当前工作流（不使用缓存）
        
        Returns:
            工作流配置对象
            
        Raises:
            WorkflowManagerError: 如果重新加载失败
        """
        if not self.current_workflow_path:
            raise WorkflowManagerError("当前没有加载任何工作流")
        
        logger.info(f"重新加载当前工作流: {self.current_workflow_path}")
        
        # 清除当前工作流的缓存
        if self.current_workflow_path in self.workflow_cache:
            del self.workflow_cache[self.current_workflow_path]
        
        # 重新加载
        return self.load_workflow(
            workflow_path=self.current_workflow_path,
            use_cache=False
        )
    
    def get_workflow_info(self, workflow_type: Optional[WorkflowType] = None) -> Dict:
        """
        获取工作流信息
        
        Args:
            workflow_type: 工作流类型（可选，默认当前工作流）
            
        Returns:
            工作流信息字典
            
        Raises:
            WorkflowManagerError: 如果获取失败
        """
        if workflow_type:
            # 获取指定工作流的信息
            if workflow_type not in self.PREDEFINED_WORKFLOWS:
                raise WorkflowManagerError(f"不支持的工作流类型: {workflow_type}")
            
            workflow_path = self.PREDEFINED_WORKFLOWS[workflow_type]
            
            # 尝试从缓存获取
            if workflow_path in self.workflow_cache:
                config = self.workflow_cache[workflow_path]
            else:
                # 临时加载（不更新当前工作流）
                path = Path(workflow_path)
                if not path.is_absolute():
                    path = Path.cwd() / path
                config = WorkflowConfig.from_json_file(str(path))
        else:
            # 获取当前工作流的信息
            if not self.current_workflow:
                raise WorkflowManagerError("当前没有加载任何工作流")
            config = self.current_workflow
            workflow_type = self.current_workflow_type
        
        return {
            "type": workflow_type,
            "name": config.workflow.name,
            "version": config.workflow.version,
            "description": config.workflow.description,
            "author": config.workflow.author,
            "tags": config.workflow.tags,
            "适用场景": config.workflow.适用场景,
            "node_count": len(config.nodes),
            "parameters": config.parameters.default
        }


# 全局工作流管理器实例（单例模式）
_workflow_manager_instance: Optional[WorkflowManager] = None


def get_workflow_manager() -> WorkflowManager:
    """
    获取全局工作流管理器实例（单例模式）
    
    Returns:
        工作流管理器实例
    """
    global _workflow_manager_instance
    
    if _workflow_manager_instance is None:
        _workflow_manager_instance = WorkflowManager()
        logger.info("全局工作流管理器实例创建成功")
    
    return _workflow_manager_instance


def cleanup_workflow_manager():
    """
    清理全局工作流管理器实例
    
    用于应用关闭时释放资源
    """
    global _workflow_manager_instance
    
    if _workflow_manager_instance is not None:
        _workflow_manager_instance.clear_cache()
        _workflow_manager_instance = None
        logger.info("全局工作流管理器实例已清理")
