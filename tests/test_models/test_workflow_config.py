"""
工作流配置数据模型测试
"""

import pytest
import json
import tempfile
from pathlib import Path

from src.models.workflow_config import (
    WorkflowConfig,
    WorkflowMetadata,
    NodeConfig,
    ParameterConfig,
    NegativePromptConfig,
    WorkflowType,
    NodeType,
    validate_config_with_schema
)


class TestWorkflowMetadata:
    """测试工作流元数据"""
    
    def test_validate_success(self):
        """测试验证成功"""
        metadata = WorkflowMetadata(
            name="测试工作流",
            version="1.0",
            description="测试描述"
        )
        errors = metadata.validate()
        assert len(errors) == 0
    
    def test_validate_missing_name(self):
        """测试缺少名称"""
        metadata = WorkflowMetadata(
            name="",
            version="1.0"
        )
        errors = metadata.validate()
        assert len(errors) > 0
        assert any("名称" in err for err in errors)
    
    def test_validate_missing_version(self):
        """测试缺少版本"""
        metadata = WorkflowMetadata(
            name="测试工作流",
            version=""
        )
        errors = metadata.validate()
        assert len(errors) > 0
        assert any("版本" in err for err in errors)


class TestNodeConfig:
    """测试节点配置"""
    
    def test_validate_success(self):
        """测试验证成功"""
        node = NodeConfig(
            class_type="KSampler",
            inputs={"seed": 42, "steps": 20}
        )
        errors = node.validate()
        assert len(errors) == 0
    
    def test_validate_missing_class_type(self):
        """测试缺少 class_type"""
        node = NodeConfig(
            class_type="",
            inputs={}
        )
        errors = node.validate()
        assert len(errors) > 0
        assert any("class_type" in err for err in errors)
    
    def test_validate_invalid_inputs(self):
        """测试无效的 inputs"""
        node = NodeConfig(
            class_type="KSampler",
            inputs="invalid"  # type: ignore
        )
        errors = node.validate()
        assert len(errors) > 0
        assert any("inputs" in err for err in errors)


class TestParameterConfig:
    """测试参数配置"""
    
    def test_validate_success(self):
        """测试验证成功"""
        params = ParameterConfig(
            default={
                "steps": 20,
                "cfg_scale": 7.0,
                "width": 1024,
                "height": 1024
            }
        )
        errors = params.validate()
        assert len(errors) == 0
    
    def test_validate_invalid_steps(self):
        """测试无效的 steps"""
        params = ParameterConfig(
            default={"steps": -1}
        )
        errors = params.validate()
        assert len(errors) > 0
        assert any("steps" in err for err in errors)
    
    def test_validate_invalid_cfg_scale(self):
        """测试无效的 cfg_scale"""
        params = ParameterConfig(
            default={"cfg_scale": 0}
        )
        errors = params.validate()
        assert len(errors) > 0
        assert any("cfg_scale" in err for err in errors)
    
    def test_validate_invalid_width(self):
        """测试无效的 width（不是 8 的倍数）"""
        params = ParameterConfig(
            default={"width": 1023}
        )
        errors = params.validate()
        assert len(errors) > 0
        assert any("width" in err for err in errors)
    
    def test_validate_invalid_height(self):
        """测试无效的 height（不是 8 的倍数）"""
        params = ParameterConfig(
            default={"height": 1023}
        )
        errors = params.validate()
        assert len(errors) > 0
        assert any("height" in err for err in errors)


class TestNegativePromptConfig:
    """测试负面提示词配置"""
    
    def test_validate_success(self):
        """测试验证成功"""
        neg_prompt = NegativePromptConfig(
            default="low quality, blurry",
            realism="CGI, 3D render",
            quality="worst quality"
        )
        errors = neg_prompt.validate()
        assert len(errors) == 0
    
    def test_validate_invalid_type(self):
        """测试无效的类型"""
        neg_prompt = NegativePromptConfig(
            default=123  # type: ignore
        )
        errors = neg_prompt.validate()
        assert len(errors) > 0


class TestWorkflowConfig:
    """测试工作流配置"""
    
    def test_validate_success(self):
        """测试验证成功"""
        config = WorkflowConfig(
            workflow=WorkflowMetadata(
                name="测试工作流",
                version="1.0"
            ),
            nodes={
                "checkpoint_loader": NodeConfig(
                    class_type="CheckpointLoaderSimple",
                    inputs={"ckpt_name": "model.safetensors"}
                ),
                "ksampler": NodeConfig(
                    class_type="KSampler",
                    inputs={
                        "model": ["checkpoint_loader", 0],
                        "seed": 42,
                        "steps": 20
                    }
                )
            },
            parameters=ParameterConfig(
                default={"steps": 20, "cfg_scale": 7.0}
            ),
            negative_prompt=NegativePromptConfig(
                default="low quality"
            )
        )
        errors = config.validate()
        assert len(errors) == 0
        assert config.is_valid()
    
    def test_validate_missing_nodes(self):
        """测试缺少节点"""
        config = WorkflowConfig(
            workflow=WorkflowMetadata(
                name="测试工作流",
                version="1.0"
            ),
            nodes={},
            parameters=ParameterConfig(),
            negative_prompt=NegativePromptConfig()
        )
        errors = config.validate()
        assert len(errors) > 0
        assert any("节点" in err for err in errors)
    
    def test_validate_invalid_node_reference(self):
        """测试无效的节点引用"""
        config = WorkflowConfig(
            workflow=WorkflowMetadata(
                name="测试工作流",
                version="1.0"
            ),
            nodes={
                "ksampler": NodeConfig(
                    class_type="KSampler",
                    inputs={
                        "model": ["non_existent_node", 0]
                    }
                )
            },
            parameters=ParameterConfig(),
            negative_prompt=NegativePromptConfig()
        )
        errors = config.validate()
        assert len(errors) > 0
        assert any("引用了不存在的节点" in err for err in errors)
    
    def test_from_dict(self):
        """测试从字典创建"""
        data = {
            "version": "1.0",
            "workflow": {
                "name": "测试工作流",
                "version": "1.0",
                "description": "测试描述",
                "tags": ["test", "basic"]
            },
            "nodes": {
                "checkpoint_loader": {
                    "class_type": "CheckpointLoaderSimple",
                    "inputs": {"ckpt_name": "model.safetensors"}
                }
            },
            "parameters": {
                "default": {"steps": 20},
                "ranges": {}
            },
            "negative_prompt": {
                "default": "low quality",
                "realism": "",
                "quality": ""
            }
        }
        
        config = WorkflowConfig.from_dict(data)
        
        assert config.workflow.name == "测试工作流"
        assert config.workflow.version == "1.0"
        assert len(config.nodes) == 1
        assert "checkpoint_loader" in config.nodes
        assert config.parameters.default["steps"] == 20
        assert config.negative_prompt.default == "low quality"
    
    def test_to_dict(self):
        """测试转换为字典"""
        config = WorkflowConfig(
            workflow=WorkflowMetadata(
                name="测试工作流",
                version="1.0",
                tags=["test"]
            ),
            nodes={
                "checkpoint_loader": NodeConfig(
                    class_type="CheckpointLoaderSimple",
                    inputs={"ckpt_name": "model.safetensors"}
                )
            },
            parameters=ParameterConfig(
                default={"steps": 20}
            ),
            negative_prompt=NegativePromptConfig(
                default="low quality"
            )
        )
        
        data = config.to_dict()
        
        assert data["workflow"]["name"] == "测试工作流"
        assert data["workflow"]["version"] == "1.0"
        assert "checkpoint_loader" in data["nodes"]
        assert data["parameters"]["default"]["steps"] == 20
        assert data["negative_prompt"]["default"] == "low quality"
    
    def test_from_json_file(self):
        """测试从 JSON 文件加载"""
        data = {
            "version": "1.0",
            "workflow": {
                "name": "测试工作流",
                "version": "1.0"
            },
            "nodes": {
                "checkpoint_loader": {
                    "class_type": "CheckpointLoaderSimple",
                    "inputs": {}
                }
            },
            "parameters": {
                "default": {},
                "ranges": {}
            },
            "negative_prompt": {
                "default": ""
            }
        }
        
        # 创建临时文件
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False, encoding='utf-8') as f:
            json.dump(data, f)
            temp_path = f.name
        
        try:
            config = WorkflowConfig.from_json_file(temp_path)
            assert config.workflow.name == "测试工作流"
            assert len(config.nodes) == 1
        finally:
            Path(temp_path).unlink()
    
    def test_from_json_file_not_found(self):
        """测试文件不存在"""
        with pytest.raises(FileNotFoundError):
            WorkflowConfig.from_json_file("non_existent_file.json")
    
    def test_to_json_file(self):
        """测试保存为 JSON 文件"""
        config = WorkflowConfig(
            workflow=WorkflowMetadata(
                name="测试工作流",
                version="1.0"
            ),
            nodes={
                "checkpoint_loader": NodeConfig(
                    class_type="CheckpointLoaderSimple",
                    inputs={}
                )
            },
            parameters=ParameterConfig(),
            negative_prompt=NegativePromptConfig()
        )
        
        # 创建临时文件
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            temp_path = f.name
        
        try:
            config.to_json_file(temp_path)
            
            # 验证文件存在且可以加载
            assert Path(temp_path).exists()
            loaded_config = WorkflowConfig.from_json_file(temp_path)
            assert loaded_config.workflow.name == "测试工作流"
        finally:
            Path(temp_path).unlink()


class TestWorkflowType:
    """测试工作流类型枚举"""
    
    def test_workflow_types(self):
        """测试工作流类型"""
        assert WorkflowType.BASIC == "basic"
        assert WorkflowType.FAST == "fast"
        assert WorkflowType.HIGH_QUALITY == "high_quality"
        assert WorkflowType.REALISM == "realism"
        assert WorkflowType.CHARACTER_CONSISTENCY == "character_consistency"
        assert WorkflowType.IPADAPTER == "ipadapter"
        assert WorkflowType.TXT2IMG == "txt2img"


class TestNodeType:
    """测试节点类型枚举"""
    
    def test_node_types(self):
        """测试节点类型"""
        assert NodeType.CHECKPOINT_LOADER == "CheckpointLoaderSimple"
        assert NodeType.KSAMPLER == "KSampler"
        assert NodeType.IPADAPTER_FACEID == "IPAdapterFaceID"
        assert NodeType.FACE_DETAILER == "FaceDetailer"
        assert NodeType.CONTROLNET == "ControlNet"


class TestSchemaValidation:
    """测试 Schema 验证"""
    
    def test_validate_config_with_schema(self):
        """测试使用 Schema 验证配置"""
        data = {
            "version": "1.0",
            "workflow": {
                "name": "测试工作流",
                "version": "1.0"
            },
            "nodes": {
                "checkpoint_loader": {
                    "class_type": "CheckpointLoaderSimple",
                    "inputs": {}
                }
            },
            "parameters": {
                "default": {},
                "ranges": {}
            },
            "negative_prompt": {
                "default": ""
            }
        }
        
        errors = validate_config_with_schema(data)
        assert len(errors) == 0
