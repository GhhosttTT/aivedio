"""Workflow configuration models for ComfyUI workflows."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional


class WorkflowType(str, Enum):
    BASIC = "basic"
    FAST = "fast"
    HIGH_QUALITY = "high_quality"
    REALISM = "realism"
    CHARACTER_CONSISTENCY = "character_consistency"
    IPADAPTER = "ipadapter"
    TXT2IMG = "txt2img"
    PRO = "pro"
    SDXL = "sdxl"
    SDXL_NATIVE = "sdxl_native"
    JUGGERNAUT = "juggernaut"


class NodeType(str, Enum):
    CHECKPOINT_LOADER = "CheckpointLoaderSimple"
    KSAMPLER = "KSampler"
    IPADAPTER_FACEID = "IPAdapterFaceID"
    FACE_DETAILER = "FaceDetailer"
    CONTROLNET = "ControlNet"


@dataclass
class WorkflowMetadata:
    name: str
    version: str = "1.0"
    description: str = ""
    author: Optional[str] = None
    tags: List[str] = field(default_factory=list)
    适用场景: List[str] = field(default_factory=list)

    def validate(self) -> List[str]:
        errors = []
        if not self.name:
            errors.append("工作流名称不能为空")
        if not self.version:
            errors.append("工作流版本不能为空")
        return errors


@dataclass
class NodeConfig:
    class_type: str
    inputs: Dict[str, Any] = field(default_factory=dict)

    def validate(self) -> List[str]:
        errors = []
        if not self.class_type:
            errors.append("节点 class_type 不能为空")
        if not isinstance(self.inputs, dict):
            errors.append("节点 inputs 必须是字典")
        return errors


@dataclass
class ParameterConfig:
    default: Dict[str, Any] = field(default_factory=dict)
    ranges: Dict[str, Any] = field(default_factory=dict)

    def validate(self) -> List[str]:
        errors = []
        steps = self.default.get("steps")
        if steps is not None and steps <= 0:
            errors.append("steps 必须大于 0")
        cfg_scale = self.default.get("cfg_scale")
        if cfg_scale is not None and cfg_scale <= 0:
            errors.append("cfg_scale 必须大于 0")
        for key in ("width", "height"):
            value = self.default.get(key)
            if value is not None and value % 8 != 0:
                errors.append(f"{key} 必须是 8 的倍数")
        return errors


@dataclass
class NegativePromptConfig:
    default: str = ""
    realism: str = ""
    quality: str = ""

    def validate(self) -> List[str]:
        errors = []
        for field_name in ("default", "realism", "quality"):
            if not isinstance(getattr(self, field_name), str):
                errors.append(f"{field_name} 必须是字符串")
        return errors


@dataclass
class WorkflowConfig:
    workflow: WorkflowMetadata
    nodes: Dict[str, NodeConfig]
    parameters: ParameterConfig = field(default_factory=ParameterConfig)
    negative_prompt: NegativePromptConfig = field(default_factory=NegativePromptConfig)
    version: str = "1.0"

    def validate(self) -> List[str]:
        errors = []
        errors.extend(self.workflow.validate())
        if not self.nodes:
            errors.append("工作流节点不能为空")
        for node_name, node in self.nodes.items():
            errors.extend([f"{node_name}: {error}" for error in node.validate()])
            for input_value in node.inputs.values():
                if isinstance(input_value, list) and len(input_value) == 2:
                    ref_name = input_value[0]
                    if isinstance(ref_name, str) and ref_name not in self.nodes:
                        errors.append(f"节点 {node_name} 引用了不存在的节点 {ref_name}")
        errors.extend(self.parameters.validate())
        errors.extend(self.negative_prompt.validate())
        return errors

    def is_valid(self) -> bool:
        return not self.validate()

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "WorkflowConfig":
        workflow_data = data.get("workflow", {})
        nodes_data = data.get("nodes", {})
        params_data = data.get("parameters", {})
        negative_data = data.get("negative_prompt", {})

        workflow = WorkflowMetadata(**workflow_data)
        nodes = {
            name: NodeConfig(
                class_type=node_data.get("class_type", ""),
                inputs=node_data.get("inputs", {}),
            )
            for name, node_data in nodes_data.items()
        }
        parameters = ParameterConfig(
            default=params_data.get("default", {}),
            ranges=params_data.get("ranges", {}),
        )
        negative_prompt = NegativePromptConfig(
            default=negative_data.get("default", ""),
            realism=negative_data.get("realism", ""),
            quality=negative_data.get("quality", ""),
        )
        return cls(
            version=data.get("version", "1.0"),
            workflow=workflow,
            nodes=nodes,
            parameters=parameters,
            negative_prompt=negative_prompt,
        )

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_json_file(cls, path: str) -> "WorkflowConfig":
        with Path(path).open("r", encoding="utf-8") as file:
            return cls.from_dict(json.load(file))

    def to_json_file(self, path: str) -> None:
        with Path(path).open("w", encoding="utf-8") as file:
            json.dump(self.to_dict(), file, ensure_ascii=False, indent=2)


def validate_config_with_schema(data: Dict[str, Any]) -> List[str]:
    try:
        return WorkflowConfig.from_dict(data).validate()
    except Exception as exc:
        return [str(exc)]
