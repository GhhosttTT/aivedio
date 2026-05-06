"""
工作流管理器测试
"""

import pytest
import json
import tempfile
import time
from pathlib import Path
from unittest.mock import Mock, patch

from src.services.workflow_manager import (
    WorkflowManager,
    WorkflowManagerError,
    get_workflow_manager,
    cleanup_workflow_manager
)
from src.models.workflow_config import WorkflowConfig, WorkflowType, WorkflowMetadata, NodeConfig, ParameterConfig, NegativePromptConfig


@pytest.fixture
def temp_config_dir():
    """创建临时配置目录"""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield tmpdir


@pytest.fixture
def sample_workflow_config():
    """创建示例工作流配置"""
    return {
        "version": "1.0",
        "workflow": {
            "name": "测试工作流",
            "version": "1.0",
            "description": "用于测试的工作流",
            "tags": ["test"]
        },
        "nodes": {
            "checkpoint_loader": {
                "class_type": "CheckpointLoaderSimple",
                "inputs": {"ckpt_name": "model.safetensors"}
            },
            "ksampler": {
                "class_type": "KSampler",
                "inputs": {
                    "model": ["checkpoint_loader", 0],
                    "seed": 42,
                    "steps": 20
                }
            }
        },
        "parameters": {
            "default": {
                "steps": 20,
                "cfg_scale": 7.0,
                "width": 1024,
                "height": 1024
            },
            "ranges": {}
        },
        "negative_prompt": {
            "default": "low quality, blurry",
            "realism": "",
            "quality": ""
        }
    }


@pytest.fixture
def create_workflow_file(temp_config_dir, sample_workflow_config):
    """创建工作流配置文件"""
    def _create(filename="test_workflow.json", config=None):
        if config is None:
            config = sample_workflow_config
        
        filepath = Path(temp_config_dir) / filename
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(config, f)
        
        return str(filepath)
    
    return _create


class TestWorkflowManager:
    """测试工作流管理器"""
    
    def test_init(self, temp_config_dir):
        """测试初始化"""
        manager = WorkflowManager(config_dir=temp_config_dir)
        
        assert manager.config_dir == Path(temp_config_dir)
        assert manager.current_workflow is None
        assert manager.current_workflow_type is None
        assert len(manager.workflow_cache) == 0
    
    def test_load_workflow_success(self, create_workflow_file):
        """测试加载工作流成功"""
        filepath = create_workflow_file()
        manager = WorkflowManager()
        
        config = manager.load_workflow(workflow_path=filepath)
        
        assert config is not None
        assert config.workflow.name == "测试工作流"
        assert manager.current_workflow == config
        assert manager.current_workflow_path == filepath
    
    def test_load_workflow_with_cache(self, create_workflow_file):
        """测试使用缓存加载工作流"""
        filepath = create_workflow_file()
        manager = WorkflowManager()
        
        # 第一次加载
        config1 = manager.load_workflow(workflow_path=filepath)
        
        # 第二次加载（应该使用缓存）
        start_time = time.time()
        config2 = manager.load_workflow(workflow_path=filepath, use_cache=True)
        elapsed_time = time.time() - start_time
        
        assert config1 == config2
        assert elapsed_time < 0.1  # 缓存加载应该很快
    
    def test_load_workflow_file_not_found(self):
        """测试加载不存在的文件"""
        manager = WorkflowManager()
        
        # 当加载不存在的文件时，会自动回退到默认工作流
        # 只有当默认工作流也不存在时才会抛出异常
        # 这里我们测试回退行为
        config = manager.load_workflow(workflow_path="non_existent_file.json")
        
        # 应该成功加载默认工作流
        assert config is not None
        assert manager.current_workflow_type == WorkflowType.BASIC
    
    def test_load_workflow_invalid_json(self, temp_config_dir):
        """测试加载无效的 JSON 文件"""
        filepath = Path(temp_config_dir) / "invalid.json"
        with open(filepath, 'w') as f:
            f.write("invalid json content")
        
        manager = WorkflowManager()
        
        # 当加载无效 JSON 时，会自动回退到默认工作流
        config = manager.load_workflow(workflow_path=str(filepath))
        
        # 应该成功加载默认工作流
        assert config is not None
        assert manager.current_workflow_type == WorkflowType.BASIC
    
    def test_load_workflow_validation_error(self, temp_config_dir):
        """测试加载验证失败的配置"""
        # 创建缺少必需字段的配置
        invalid_config = {
            "version": "1.0",
            "workflow": {
                "name": "",  # 名称为空，验证失败
                "version": "1.0"
            },
            "nodes": {
                "test": {
                    "class_type": "Test",
                    "inputs": {}
                }
            },
            "parameters": {"default": {}},
            "negative_prompt": {"default": ""}
        }
        
        filepath = Path(temp_config_dir) / "invalid_config.json"
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(invalid_config, f)
        
        manager = WorkflowManager()
        
        with pytest.raises(WorkflowManagerError):
            manager.load_workflow(workflow_path=str(filepath))
    
    def test_switch_workflow(self, create_workflow_file):
        """测试切换工作流"""
        # 创建两个不同的工作流文件
        config1 = {
            "version": "1.0",
            "workflow": {"name": "工作流1", "version": "1.0"},
            "nodes": {"test": {"class_type": "Test", "inputs": {}}},
            "parameters": {"default": {}},
            "negative_prompt": {"default": ""}
        }
        config2 = {
            "version": "1.0",
            "workflow": {"name": "工作流2", "version": "1.0"},
            "nodes": {"test": {"class_type": "Test", "inputs": {}}},
            "parameters": {"default": {}},
            "negative_prompt": {"default": ""}
        }
        
        filepath1 = create_workflow_file("workflow1.json", config1)
        filepath2 = create_workflow_file("workflow2.json", config2)
        
        # 模拟预定义工作流
        manager = WorkflowManager()
        manager.PREDEFINED_WORKFLOWS = {
            WorkflowType.BASIC: filepath1,
            WorkflowType.FAST: filepath2
        }
        
        # 切换到工作流1
        start_time = time.time()
        config = manager.switch_workflow(WorkflowType.BASIC)
        elapsed_time = time.time() - start_time
        
        assert config.workflow.name == "工作流1"
        assert manager.current_workflow_type == WorkflowType.BASIC
        assert elapsed_time < 2.0  # 应该在 2 秒内完成
        
        # 切换到工作流2
        start_time = time.time()
        config = manager.switch_workflow(WorkflowType.FAST)
        elapsed_time = time.time() - start_time
        
        assert config.workflow.name == "工作流2"
        assert manager.current_workflow_type == WorkflowType.FAST
        assert elapsed_time < 2.0  # 应该在 2 秒内完成
    
    def test_switch_workflow_same_type(self, create_workflow_file):
        """测试切换到相同的工作流类型"""
        filepath = create_workflow_file()
        
        manager = WorkflowManager()
        manager.PREDEFINED_WORKFLOWS = {WorkflowType.BASIC: filepath}
        
        # 第一次切换
        config1 = manager.switch_workflow(WorkflowType.BASIC)
        
        # 第二次切换到相同类型（应该直接返回）
        start_time = time.time()
        config2 = manager.switch_workflow(WorkflowType.BASIC)
        elapsed_time = time.time() - start_time
        
        assert config1 == config2
        assert elapsed_time < 0.1  # 应该很快
    
    def test_validate_workflow(self, sample_workflow_config):
        """测试验证工作流"""
        manager = WorkflowManager()
        config = WorkflowConfig.from_dict(sample_workflow_config)
        
        errors = manager.validate_workflow(config)
        
        assert len(errors) == 0
    
    def test_validate_workflow_with_errors(self):
        """测试验证有错误的工作流"""
        manager = WorkflowManager()
        
        # 创建有错误的配置
        config = WorkflowConfig(
            workflow=WorkflowMetadata(name="", version="1.0"),  # 名称为空
            nodes={},  # 没有节点
            parameters=ParameterConfig(),
            negative_prompt=NegativePromptConfig()
        )
        
        errors = manager.validate_workflow(config)
        
        assert len(errors) > 0
    
    def test_get_current_workflow(self, create_workflow_file):
        """测试获取当前工作流"""
        filepath = create_workflow_file()
        manager = WorkflowManager()
        
        # 未加载时
        assert manager.get_current_workflow() is None
        
        # 加载后
        config = manager.load_workflow(workflow_path=filepath)
        assert manager.get_current_workflow() == config
    
    def test_get_current_workflow_type(self, create_workflow_file):
        """测试获取当前工作流类型"""
        filepath = create_workflow_file()
        manager = WorkflowManager()
        manager.PREDEFINED_WORKFLOWS = {WorkflowType.BASIC: filepath}
        
        # 未加载时
        assert manager.get_current_workflow_type() is None
        
        # 加载后
        manager.switch_workflow(WorkflowType.BASIC)
        assert manager.get_current_workflow_type() == WorkflowType.BASIC
    
    def test_list_available_workflows(self):
        """测试列出可用工作流"""
        manager = WorkflowManager()
        
        workflows = manager.list_available_workflows()
        
        assert len(workflows) > 0
        assert all("type" in w for w in workflows)
        assert all("name" in w for w in workflows)
        assert all("path" in w for w in workflows)
    
    def test_register_custom_workflow(self, create_workflow_file):
        """测试注册自定义工作流"""
        filepath = create_workflow_file()
        manager = WorkflowManager()
        
        manager.register_custom_workflow("my_workflow", filepath)
        
        assert "my_workflow" in manager.custom_workflows
        assert manager.custom_workflows["my_workflow"] == filepath
    
    def test_register_custom_workflow_file_not_found(self):
        """测试注册不存在的文件"""
        manager = WorkflowManager()
        
        with pytest.raises(WorkflowManagerError):
            manager.register_custom_workflow("my_workflow", "non_existent.json")
    
    def test_unregister_custom_workflow(self, create_workflow_file):
        """测试注销自定义工作流"""
        filepath = create_workflow_file()
        manager = WorkflowManager()
        
        manager.register_custom_workflow("my_workflow", filepath)
        assert "my_workflow" in manager.custom_workflows
        
        manager.unregister_custom_workflow("my_workflow")
        assert "my_workflow" not in manager.custom_workflows
    
    def test_load_custom_workflow(self, create_workflow_file):
        """测试加载自定义工作流"""
        filepath = create_workflow_file()
        manager = WorkflowManager()
        
        manager.register_custom_workflow("my_workflow", filepath)
        config = manager.load_custom_workflow("my_workflow")
        
        assert config.workflow.name == "测试工作流"
    
    def test_load_custom_workflow_not_registered(self):
        """测试加载未注册的自定义工作流"""
        manager = WorkflowManager()
        
        with pytest.raises(WorkflowManagerError):
            manager.load_custom_workflow("non_existent")
    
    def test_clear_cache(self, create_workflow_file):
        """测试清除缓存"""
        filepath = create_workflow_file()
        manager = WorkflowManager()
        
        # 加载工作流（会缓存）
        manager.load_workflow(workflow_path=filepath)
        assert len(manager.workflow_cache) > 0
        
        # 清除缓存
        manager.clear_cache()
        assert len(manager.workflow_cache) == 0
    
    def test_reload_current_workflow(self, create_workflow_file):
        """测试重新加载当前工作流"""
        filepath = create_workflow_file()
        manager = WorkflowManager()
        
        # 加载工作流
        config1 = manager.load_workflow(workflow_path=filepath)
        
        # 重新加载
        config2 = manager.reload_current_workflow()
        
        assert config2.workflow.name == config1.workflow.name
    
    def test_reload_current_workflow_not_loaded(self):
        """测试重新加载未加载的工作流"""
        manager = WorkflowManager()
        
        with pytest.raises(WorkflowManagerError):
            manager.reload_current_workflow()
    
    def test_get_workflow_info_current(self, create_workflow_file):
        """测试获取当前工作流信息"""
        filepath = create_workflow_file()
        manager = WorkflowManager()
        
        manager.load_workflow(workflow_path=filepath)
        info = manager.get_workflow_info()
        
        assert info["name"] == "测试工作流"
        assert info["version"] == "1.0"
        assert "node_count" in info
        assert "parameters" in info
    
    def test_get_workflow_info_not_loaded(self):
        """测试获取未加载工作流的信息"""
        manager = WorkflowManager()
        
        with pytest.raises(WorkflowManagerError):
            manager.get_workflow_info()


class TestSingletonPattern:
    """测试单例模式"""
    
    def test_get_workflow_manager_singleton(self):
        """测试获取单例实例"""
        manager1 = get_workflow_manager()
        manager2 = get_workflow_manager()
        
        assert manager1 is manager2
    
    def test_cleanup_workflow_manager(self):
        """测试清理单例实例"""
        manager = get_workflow_manager()
        assert manager is not None
        
        cleanup_workflow_manager()
        
        # 清理后再次获取应该是新实例
        new_manager = get_workflow_manager()
        assert new_manager is not manager
