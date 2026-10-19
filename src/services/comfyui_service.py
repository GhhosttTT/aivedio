"""
ComfyUI 服务（ComfyUIService）

负责调用 ComfyUI API 生成图像，管理工作流配置，
实现重试逻辑和错误处理
"""

import copy
import json
import time
import tempfile
import uuid
from typing import Any, Optional, Dict, List
from pathlib import Path

import httpx

from src.utils.logger import logger
from src.config import settings
from src.services.workflow_manager import WorkflowManager
from src.models.workflow_config import WorkflowType
from src.services.image_workflow_graph import ImageWorkflowGraph, ImageWorkflowGraphError, stage_seed
from src.services.parameter_optimizer import (
    get_parameter_optimizer,
    SceneType,
    QualityMode
)
from src.services.prompt_optimizer import (
    get_prompt_optimizer,
    OptimizationMode
)


class ComfyUIError(Exception):
    """ComfyUI 服务错误"""
    pass


class ComfyUIWaitTimeout(ComfyUIError):
    """The server may still be generating; do not submit the same shot again."""

    def __init__(self, message: str, *, prompt_id: str | None = None, client_id: str | None = None):
        super().__init__(message)
        self.prompt_id = prompt_id
        self.client_id = client_id


class ComfyUIService:
    """ComfyUI 服务（Stable Diffusion 图像生成）"""
    
    def __init__(
        self,
        base_url: Optional[str] = None,
        workflow_path: Optional[str] = None,
        timeout: Optional[int] = None,
        max_retries: int = 3
    ):
        """
        初始化 ComfyUI 服务
        
        Args:
            base_url: ComfyUI 服务地址（默认从环境变量读取）
            workflow_path: 工作流配置文件路径（默认从环境变量读取，已弃用，使用 WorkflowManager）
            timeout: 请求超时时间（秒，默认 300）
            max_retries: 最大重试次数（默认 3）
        """
        self.base_url = (base_url or settings.COMFYUI_BASE_URL).rstrip("/")
        self.timeout = timeout if timeout is not None else settings.COMFYUI_TIMEOUT
        self.max_retries = max(1, int(max_retries))
        
        # HTTP 客户端（禁用代理，直接连接本地服务）
        # httpx 0.24+ 版本使用 trust_env=False 来忽略环境变量中的代理设置
        self.client = httpx.Client(timeout=self.timeout, trust_env=False)
        
        # 使用 WorkflowManager 管理工作流配置
        self.workflow_manager = WorkflowManager()
        self.workflow_path = workflow_path or settings.COMFYUI_WORKFLOW_PATH
        self.default_workflow_type = WorkflowType(settings.COMFYUI_DEFAULT_WORKFLOW_TYPE)
        
        # 初始化参数优化器
        self.parameter_optimizer = get_parameter_optimizer()
        
        # 初始化提示词优化器
        self.prompt_optimizer = get_prompt_optimizer()
        
        # 当前工作流类型（用于向后兼容）
        self.current_workflow_type: Optional[WorkflowType] = None
        
        # 加载默认工作流配置
        try:
            self.workflow_manager.load_workflow(
                workflow_path=self.workflow_path,
                workflow_type=None if self.workflow_path else self.default_workflow_type,
                allow_fallback=False,
            )
            self.current_workflow_type = (
                self.workflow_manager.get_current_workflow_type()
                or (self.default_workflow_type if workflow_path is None else None)
            )
            logger.info(f"ComfyUI 服务初始化完成: {self.base_url}")
        except Exception as e:
            raise ComfyUIError(f"加载工作流配置失败: {e}") from e
    
    def load_workflow(self, workflow_type: Optional[WorkflowType] = None):
        """
        加载工作流配置文件（使用 WorkflowManager）
        
        Args:
            workflow_type: 工作流类型（WorkflowType 枚举）
            
        Raises:
            ComfyUIError: 如果配置文件格式错误
        """
        try:
            if workflow_type is None:
                # 如果没有指定类型，使用当前类型或默认类型
                workflow_type = self.current_workflow_type or WorkflowType.BASIC

            if (
                self.current_workflow_type == workflow_type
                and self.workflow_manager.current_workflow is not None
            ):
                return self.workflow_manager.current_workflow
            
            # 使用 WorkflowManager 加载工作流
            config = self.workflow_manager.switch_workflow(workflow_type)
            
            self.current_workflow_type = workflow_type
            logger.info(f"工作流配置加载成功: {config.workflow.name} (类型: {workflow_type})")
            
        except Exception as e:
            error_msg = f"加载工作流配置失败: {e}"
            logger.error(error_msg)
            raise ComfyUIError(error_msg) from e
    
    def switch_workflow(self, workflow_type: WorkflowType):
        """
        切换工作流类型
        
        Args:
            workflow_type: 目标工作流类型
            
        Raises:
            ComfyUIError: 如果切换失败
        """
        try:
            config = self.workflow_manager.switch_workflow(workflow_type)
            self.current_workflow_type = workflow_type
            logger.info(f"工作流切换成功: {config.workflow.name}")
        except Exception as e:
            error_msg = f"切换工作流失败: {e}"
            logger.error(error_msg)
            raise ComfyUIError(error_msg) from e
    
    def check_status(self) -> bool:
        """
        检查 ComfyUI 服务可用性
        
        Returns:
            服务是否可用
        """
        try:
            response = self.client.get(f"{self.base_url}/system_stats")
            
            if response.status_code == 200:
                logger.info("ComfyUI 服务可用")
                return True
            else:
                logger.warning(f"ComfyUI 服务响应异常: {response.status_code}")
                return False
                
        except Exception as e:
            logger.error(f"ComfyUI 服务不可用: {e}")
            return False
    
    def generate_image(
        self,
        prompt: str,
        negative_prompt: Optional[str] = None,
        width: int = 1024,
        height: int = 1024,
        steps: int = 20,
        cfg_scale: float = 7.0,
        seed: int = -1,
        output_path: Optional[str] = None,
        reference_image: Optional[str] = None,  # 新增参数
        use_ipadapter: bool = True,  # 新增参数
        # 优化器相关参数
        scene_type: Optional[str] = None,  # 场景类型（portrait, landscape, action等）
        quality_mode: Optional[str] = None,  # 质量模式（fast, normal, high_quality, ultra）
        enable_prompt_optimization: bool = False,
        enable_parameter_optimization: bool = False,
        enable_realism: bool = False,  # 是否启用真实感模式
        gpu_vram_gb: Optional[int] = None,  # GPU 显存大小（GB）
        optimization_mode: Optional[str] = None,  # 提示词优化模式（quality, realism, artistic, balanced）
        character_references: Optional[List[Dict]] = None,
        spatial_plan: Optional[Dict] = None,
        spatial_control_references: Optional[Dict] = None,
        spatial_asset_pack: Optional[Dict] = None,
    ) -> str:
        """
        生成图像
        
        Args:
            prompt: 正面提示词
            negative_prompt: 负面提示词（可选，使用默认值）
            width: 图像宽度（默认 1024）
            height: 图像高度（默认 1024）
            steps: 采样步数（默认 20）
            cfg_scale: CFG 强度（默认 7.0）
            seed: 随机种子（-1 表示随机，默认 -1）
            output_path: 输出文件路径（可选）
            reference_image: 参考图像路径（用于 IP-Adapter 角色一致性）
            use_ipadapter: 是否使用 IP-Adapter（默认 True）
            scene_type: 场景类型（portrait, landscape, action等，用于参数优化）
            quality_mode: 质量模式（fast, normal, high_quality, ultra，用于参数优化）
            enable_prompt_optimization: 是否启用提示词优化（默认 True）
            enable_parameter_optimization: 是否启用参数优化（默认 True）
            enable_realism: 是否启用真实感模式（默认 False）
            gpu_vram_gb: GPU 显存大小（GB，用于分辨率优化）
            optimization_mode: 提示词优化模式（quality, realism, artistic, balanced）
            
        Returns:
            生成的图像文件路径
            
        Raises:
            ComfyUIError: 如果生成失败
        """
        if not prompt or len(prompt.strip()) == 0:
            raise ValueError("提示词不能为空")
        if width <= 0 or height <= 0 or width % 8 or height % 8:
            raise ValueError("Image dimensions must be positive multiples of eight")

        # Choose the graph before reading its defaults. Never swap model families implicitly.
        multiple_references = bool(character_references and len(character_references) > 1)
        if multiple_references or (reference_image and use_ipadapter):
            base = self.workflow_manager.load_workflow(
                workflow_path=self.workflow_path,
                workflow_type=None if self.workflow_path else self.default_workflow_type,
                allow_fallback=False,
            )
            checkpoints = {n.inputs["ckpt_name"] for n in base.nodes.values() if n.class_type == "CheckpointLoaderSimple"}
            reference_path = (
                settings.COMFYUI_MULTI_REFERENCE_WORKFLOW_PATH if multiple_references
                else settings.COMFYUI_REFERENCE_WORKFLOW_PATH
            )
            if not reference_path:
                setting = "COMFYUI_MULTI_REFERENCE_WORKFLOW_PATH" if multiple_references else "COMFYUI_REFERENCE_WORKFLOW_PATH"
                raise ComfyUIError(f"Configure {setting} for the selected model family")
            reference = self.workflow_manager.load_workflow(workflow_path=reference_path, allow_fallback=False)
            reference_checkpoints = {n.inputs["ckpt_name"] for n in reference.nodes.values() if n.class_type == "CheckpointLoaderSimple"}
            if checkpoints != reference_checkpoints:
                raise ComfyUIError("Reference and text workflows must use the same checkpoint")
            self.current_workflow_type = WorkflowType.IPADAPTER
        else:
            self.workflow_manager.load_workflow(
                workflow_path=self.workflow_path,
                workflow_type=None if self.workflow_path else self.default_workflow_type,
                allow_fallback=False,
            )
            self.current_workflow_type = None if self.workflow_path else self.default_workflow_type
        
        # 保存原始提示词
        original_prompt = prompt
        
        # ==================== 提示词优化 ====================
        if enable_prompt_optimization:
            try:
                # 根据场景类型和真实感模式优化提示词
                if scene_type:
                    optimized_result = self.prompt_optimizer.optimize_for_scene(
                        prompt=prompt,
                        scene_type=scene_type,
                        enable_realism=enable_realism
                    )
                else:
                    # 使用指定的优化模式或默认模式
                    if optimization_mode:
                        mode = OptimizationMode(optimization_mode)
                    elif enable_realism:
                        mode = OptimizationMode.REALISM
                    else:
                        mode = OptimizationMode.BALANCED
                    
                    optimized_result = self.prompt_optimizer.optimize(
                        prompt=prompt,
                        mode=mode
                    )
                
                # 使用优化后的提示词
                prompt = optimized_result.positive_prompt
                
                # 如果没有提供负面提示词，使用优化后的负面提示词
                if not negative_prompt:
                    negative_prompt = optimized_result.negative_prompt
                
                logger.info(f"提示词优化完成 - 模式: {optimized_result.optimization_mode}, 单词数: {optimized_result.word_count}")
                logger.debug(f"原始提示词: {original_prompt}")
                logger.debug(f"优化后提示词: {prompt}")
                
            except Exception as e:
                logger.warning(f"提示词优化失败，使用原始提示词: {e}")
                prompt = original_prompt
        
        # 使用默认负面提示词（如果仍然没有）
        if negative_prompt is None:
            workflow_config = self.workflow_manager.get_current_workflow()
            if workflow_config:
                negative_prompt = workflow_config.negative_prompt.default or next((
                    str(node.inputs.get("text", "")) for name, node in workflow_config.nodes.items()
                    if "negative" in name and node.class_type == "CLIPTextEncode"
                ), "")
            else:
                negative_prompt = ""
        
        # ==================== 参数优化 ====================
        if enable_parameter_optimization:
            try:
                # 转换场景类型和质量模式
                scene_type_enum = None
                if scene_type:
                    try:
                        scene_type_enum = SceneType(scene_type.lower())
                    except ValueError:
                        logger.warning(f"无效的场景类型: {scene_type}，使用默认值")
                
                quality_mode_enum = None
                if quality_mode:
                    try:
                        quality_mode_enum = QualityMode(quality_mode.lower())
                    except ValueError:
                        logger.warning(f"无效的质量模式: {quality_mode}，使用默认值")
                
                custom_params = {"cfg_scale": cfg_scale}
                if quality_mode_enum not in {QualityMode.HIGH_QUALITY, QualityMode.ULTRA}:
                    custom_params["steps"] = steps

                # 优化参数
                optimized_params = self.parameter_optimizer.optimize(
                    scene_type=scene_type_enum,
                    quality_mode=quality_mode_enum,
                    has_reference_image=(reference_image is not None),
                    gpu_vram_gb=gpu_vram_gb,
                    base_width=width,
                    base_height=height,
                    custom_params=custom_params
                )
                
                # 应用优化后的参数。高质量模式允许优化器把采样步数抬高，
                # 但保留任务层返修已经提高过的更强参数。
                optimized_steps = optimized_params.steps
                if quality_mode_enum in {QualityMode.HIGH_QUALITY, QualityMode.ULTRA}:
                    steps = max(steps, optimized_steps)
                else:
                    steps = optimized_steps
                cfg_scale = optimized_params.cfg_scale
                width = optimized_params.width
                height = optimized_params.height
                
                logger.info(f"参数优化完成 - steps: {steps}, cfg: {cfg_scale}, 分辨率: {width}x{height}")
                logger.debug(f"优化决策: {optimized_params.decision_reasons}")
                
            except Exception as e:
                logger.warning(f"参数优化失败，使用原始参数: {e}")
        
        # 生成随机种子
        if seed == -1:
            seed = int(time.time() * 1000) % (2**32)
        
        logger.info(f"开始生成图像: {width}x{height}, steps={steps}, cfg={cfg_scale}, workflow={self.current_workflow_type}")
        logger.debug(f"提示词: {prompt[:100]}...")
        
        # 构建工作流
        workflow = self._build_workflow(
            prompt=prompt,
            negative_prompt=negative_prompt,
            width=width,
            height=height,
            steps=steps,
            cfg_scale=cfg_scale,
            seed=seed,
            reference_image=reference_image,
            use_ipadapter=use_ipadapter,
            character_references=character_references,
            spatial_plan=spatial_plan,
            spatial_control_references=spatial_control_references,
            spatial_asset_pack=spatial_asset_pack,
        )
        
        # Only pre-connection failures and artifact downloads are safe to retry.
        self.preflight(workflow)
        if output_path:
            artifact = Path(output_path).with_suffix(".workflow.json")
            artifact.parent.mkdir(parents=True, exist_ok=True)
            artifact.write_text(json.dumps(workflow, ensure_ascii=False, indent=2), encoding="utf-8")
        try:
            image_path = self._submit_and_wait(workflow, output_path)
            logger.info(f"图像生成成功: {image_path}")
            return image_path
        except ComfyUIWaitTimeout:
            raise
        except ComfyUIError as exc:
            if "No face detected" in str(exc) and reference_image:
                raise ComfyUIError("Reference face was not detected; select another reference image") from exc
            raise
    
    def _build_workflow(
        self,
        prompt: str,
        negative_prompt: str,
        width: int,
        height: int,
        steps: int,
        cfg_scale: float,
        seed: int,
        reference_image: Optional[str] = None,
        use_ipadapter: bool = True,
        character_references: Optional[List[Dict]] = None,
        spatial_plan: Optional[Dict] = None,
        spatial_control_references: Optional[Dict] = None,
        spatial_asset_pack: Optional[Dict] = None,
    ) -> Dict:
        """
        构建 ComfyUI 工作流
        
        Args:
            prompt: 正面提示词
            negative_prompt: 负面提示词
            width: 图像宽度
            height: 图像高度
            steps: 采样步数
            cfg_scale: CFG 强度
            seed: 随机种子
            reference_image: 参考图像路径（用于 IP-Adapter）
            use_ipadapter: 是否使用 IP-Adapter
            
        Returns:
            工作流字典（ComfyUI API 格式）
        """
        # 从 WorkflowManager 获取当前工作流配置
        workflow_config = self.workflow_manager.get_current_workflow()
        if not workflow_config:
            raise ComfyUIError("未加载工作流配置")
        
        # 深拷贝工作流配置的节点
        workflow_nodes = {
            name: {
                "class_type": node.class_type,
                "inputs": json.loads(json.dumps(node.inputs))
            }
            for name, node in workflow_config.nodes.items()
        }
        
        # 将节点名称映射转换为 ComfyUI API 需要的数字 ID 格式
        node_name_to_id = {name: str(idx + 1) for idx, name in enumerate(workflow_nodes.keys())}
        workflow_api = {}
        
        for node_name, node_data in workflow_nodes.items():
            node_id = node_name_to_id[node_name]
            workflow_api[node_id] = {
                "class_type": node_data["class_type"],
                "inputs": {}
            }
            
            # 转换输入参数
            for input_key, input_value in node_data["inputs"].items():
                if isinstance(input_value, list) and len(input_value) == 2:
                    # 这是节点引用 [node_name, output_index]
                    ref_node_name, output_idx = input_value
                    if ref_node_name in node_name_to_id:
                        # 转换为 [node_id, output_index]
                        workflow_api[node_id]["inputs"][input_key] = [
                            node_name_to_id[ref_node_name],
                            output_idx
                        ]
                    else:
                        workflow_api[node_id]["inputs"][input_key] = input_value
                else:
                    workflow_api[node_id]["inputs"][input_key] = input_value
        
        workflow = self._replace_workflow_placeholders(workflow_api, {
            "spatial_plan_json": json.dumps(spatial_plan or {}, ensure_ascii=False, sort_keys=True),
            "spatial_control_references_json": json.dumps(
                spatial_control_references or {}, ensure_ascii=False, sort_keys=True,
            ),
            "spatial_asset_pack_json": json.dumps(spatial_asset_pack or {}, ensure_ascii=False, sort_keys=True),
            "spatial_scene_contract_hash": str((spatial_asset_pack or {}).get("scene_contract_hash") or ""),
        })
        
        graph = ImageWorkflowGraph(workflow)
        configured_output = workflow_config.parameters.default.get("output_node")
        if configured_output and configured_output not in node_name_to_id:
            raise ComfyUIError(f"Unknown configured output_node: {configured_output}")
        try:
            save_image_id = graph.output_node(node_name_to_id.get(configured_output))
            ksampler_id = graph.base_sampler(save_image_id)
            active = graph.ancestors(save_image_id)
            positive_nodes: set[str] = set()
            negative_nodes: set[str] = set()
            for node_id in active:
                node = workflow[node_id]
                if node["class_type"] in {"KSampler", "FaceDetailer"}:
                    positive_nodes.update(graph.prompt_nodes(node_id, "positive"))
                    negative_nodes.update(graph.prompt_nodes(node_id, "negative"))
            if positive_nodes & negative_nodes:
                raise ImageWorkflowGraphError("Positive and negative conditioning share a text node")
            for nodes, value in ((positive_nodes, prompt), (negative_nodes, negative_prompt)):
                for node_id in nodes:
                    workflow[node_id]["inputs"]["text"] = value
            for node_name, node_id in node_name_to_id.items():
                if node_id not in active:
                    continue
                node = workflow[node_id]
                if node["class_type"] == "EmptyLatentImage":
                    node["inputs"].update({"width": width, "height": height, "batch_size": 1})
                if node["class_type"] in {"KSampler", "FaceDetailer"}:
                    node["inputs"]["seed"] = seed if node_id == ksampler_id else stage_seed(seed, node_name)
            workflow[ksampler_id]["inputs"].update({"steps": steps, "cfg": cfg_scale})
            sampling_stages = {
                node_id for node_id in active
                if workflow[node_id]["class_type"] in {"KSampler", "FaceDetailer"}
            }
            if character_references and len(character_references) > 1:
                self._bind_regional_references(
                    workflow, graph, ksampler_id, node_name_to_id,
                    workflow_config.parameters.default.get("reference_slots"),
                    character_references, width, height, sampling_stages,
                )
            elif use_ipadapter and reference_image:
                adapter_id, loader_id = graph.reference_binding(ksampler_id)
                graph.require_identity_stages(sampling_stages, {adapter_id})
                workflow[loader_id]["inputs"]["image"] = self._upload_reference_image(reference_image)
                weight = workflow_config.parameters.default.get("ipadapter_weight")
                if weight is not None:
                    workflow[adapter_id]["inputs"]["weight"] = weight
            workflow[save_image_id]["inputs"]["filename_prefix"] = f"short_drama_{uuid.uuid4().hex[:8]}"
        except ImageWorkflowGraphError as exc:
            raise ComfyUIError(str(exc)) from exc
        
        return workflow

    def _bind_regional_references(
        self, workflow, graph, sampler_id, mapping, slots, references, width, height, sampling_stages,
    ) -> None:
        if not isinstance(slots, list) or len(slots) != len(references):
            raise ComfyUIError("Regional workflow reference_slots must match the visible character count")
        active = graph.model_ancestors(sampler_id)
        bound_adapters = set()
        bound_loaders = set()
        bindings = []
        regions = []
        for index, (slot, reference) in enumerate(zip(slots, references)):
            if not isinstance(slot, dict) or not isinstance(reference, dict) or not reference.get("path"):
                raise ComfyUIError(f"Missing regional character reference at slot {index}")
            adapter_id = mapping.get(slot.get("adapter"))
            image_id = mapping.get(slot.get("image"))
            mask_id = mapping.get(slot.get("mask"))
            if adapter_id not in active or adapter_id in bound_adapters:
                raise ComfyUIError("Regional identity adapters must be unique and connected to the sampler")
            adapter = workflow[adapter_id]
            if adapter["class_type"] not in {"IPAdapterFaceID", "IPAdapterAdvanced"}:
                raise ComfyUIError("Regional adapter must support IPAdapter attention masks")
            image_link = graph.link(adapter["inputs"].get("image"))
            mask_link = graph.link(adapter["inputs"].get("attn_mask"))
            if image_id != image_link or not mask_link:
                raise ComfyUIError("Regional reference or attention mask is not connected to its adapter")
            mask_node = workflow[mask_link]
            if mask_node["class_type"] != "ImageToMask" or mask_node["inputs"].get("channel") != "red":
                raise ComfyUIError("Regional mask must use ImageToMask with the red channel")
            if mask_id != graph.link(mask_node["inputs"].get("image")):
                raise ComfyUIError("Regional mask loader is not connected to ImageToMask")
            for loader in (image_id, mask_id):
                if loader in bound_loaders or loader not in workflow or workflow[loader]["class_type"] != "LoadImage":
                    raise ComfyUIError("Regional references and masks need distinct LoadImage nodes")
                bound_loaders.add(loader)
            region = slot.get("region")
            self._region_pixel_bounds(width, height, region)
            if any(min(region[2], other[2]) > max(region[0], other[0])
                   and min(region[3], other[3]) > max(region[1], other[1]) for other in regions):
                raise ComfyUIError("Regional identity masks overlap; use separate character regions")
            regions.append(region)
            bound_adapters.add(adapter_id)
            bindings.append((image_id, mask_id, reference["path"], region))
        active_adapters = {node_id for node_id in active
                           if workflow[node_id]["class_type"] in {"IPAdapterFaceID", "IPAdapterAdvanced"}}
        if active_adapters != bound_adapters:
            raise ComfyUIError("Every active identity adapter needs an explicit regional reference slot")
        graph.require_identity_stages(sampling_stages, bound_adapters)
        for image_id, mask_id, reference_path, region in bindings:
            workflow[image_id]["inputs"]["image"] = self._upload_reference_image(str(reference_path))
            workflow[mask_id]["inputs"]["image"] = self._upload_region_mask(width, height, region)

    @staticmethod
    def _region_pixel_bounds(width: int, height: int, region) -> tuple[int, int, int, int]:
        import math

        if (
            not isinstance(region, list) or len(region) != 4
            or any(isinstance(value, bool) or not isinstance(value, (int, float))
                   or not math.isfinite(value) or not 0 <= value <= 1 for value in region)
            or region[0] >= region[2] or region[1] >= region[3]
        ):
            raise ComfyUIError("Regional mask requires normalized [left, top, right, bottom] bounds")
        left, top, right, bottom = (
            round(region[0] * width), round(region[1] * height),
            round(region[2] * width), round(region[3] * height),
        )
        if right <= left or bottom <= top:
            raise ComfyUIError("Regional mask has no pixels at the requested resolution")
        return left, top, right, bottom

    def _upload_region_mask(self, width: int, height: int, region) -> str:
        from PIL import Image, ImageDraw

        left, top, right, bottom = self._region_pixel_bounds(width, height, region)
        with tempfile.TemporaryDirectory(prefix="aivedio-mask-") as directory:
            path = Path(directory) / "region.png"
            mask = Image.new("RGB", (width, height), "black")
            ImageDraw.Draw(mask).rectangle((left, top, right - 1, bottom - 1), fill="white")
            mask.save(path)
            return self._upload_reference_image(str(path))
    
    def _upload_reference_image(self, reference_image: str) -> str:
        path = Path(reference_image)
        if not path.is_file():
            raise ComfyUIError(f"Reference image does not exist: {path}")
        with path.open("rb") as stream:
            response = self.client.post(
                f"{self.base_url}/upload/image",
                files={"image": (path.name, stream, "application/octet-stream")},
                data={"type": "input", "overwrite": "false"},
            )
        response.raise_for_status()
        data = response.json()
        if not data.get("name"):
            raise ComfyUIError("ComfyUI upload did not return an image name")
        return "/".join(part for part in (data.get("subfolder", ""), data["name"]) if part)

    def preflight(self, workflow: Dict) -> None:
        response = self.client.get(f"{self.base_url}/object_info", timeout=15)
        response.raise_for_status()
        info = response.json()
        errors = []
        for node in workflow.values():
            name = node["class_type"]
            if name not in info:
                errors.append(f"missing node: {name}")
                continue
            required = info[name].get("input", {}).get("required", {})
            for key in ("ckpt_name", "lora_name", "clip_name"):
                value = node["inputs"].get(key)
                spec = required.get(key)
                if value and spec and isinstance(spec[0], list) and value not in spec[0]:
                    errors.append(f"missing model: {key}={value}")
        if errors:
            raise ComfyUIError("ComfyUI preflight failed: " + "; ".join(errors))

    def free_memory(self) -> None:
        response = self.client.post(f"{self.base_url}/free", json={"unload_models": True, "free_memory": True})
        response.raise_for_status()

    def release_generation_resources(self) -> None:
        self.free_memory()

    def _submit_and_wait(
        self,
        workflow: Dict,
        output_path: Optional[str] = None
    ) -> str:
        """
        提交工作流并等待完成
        
        Args:
            workflow: 工作流字典
            output_path: 输出文件路径（可选）
            
        Returns:
            生成的图像文件路径
            
        Raises:
            ComfyUIError: 如果提交或执行失败
        """
        try:
            config = self.workflow_manager.get_current_workflow()
            configured_output = config.parameters.default.get("output_node") if config else None
            mapping = {name: str(index + 1) for index, name in enumerate(config.nodes)} if config else {}
            output_node = ImageWorkflowGraph(workflow).output_node(mapping.get(configured_output))
            return self._run_submitted_job(
                workflow, output_path, "image", output_node,
                lambda result: self._get_generated_image(result, output_path, output_node),
            )
            
        except ComfyUIError:
            raise
        except Exception as e:
            raise ComfyUIError(f"工作流执行失败: {e}") from e

    def generate_video(
        self,
        prompt: str,
        reference_image: str,
        output_path: str,
        end_image: Optional[str] = None,
        negative_prompt: str = "",
        width: int = 1024,
        height: int = 576,
        duration_seconds: float = 5.0,
        fps: int = 8,
        seed: int = -1,
        workflow_path: Optional[str] = None,
        motion_bucket_id: int = 127,
        noise_aug_strength: float = 0.02,
        quality_mode: Optional[str] = None,
        repair_action: Optional[str] = None,
        quality_pipeline: Optional[dict] = None,
        shot_plan: Optional[dict] = None,
    ) -> str:
        """Run a user-supplied ComfyUI image-to-video API workflow."""
        path = workflow_path or settings.COMFYUI_VIDEO_WORKFLOW_PATH
        if not path:
            raise ComfyUIError("未配置 COMFYUI_VIDEO_WORKFLOW_PATH，无法使用 ComfyUI 视频工作流")
        if not reference_image:
            raise ComfyUIError("ComfyUI 视频生成需要 reference_image")
        workflow_file = Path(path)
        if not workflow_file.is_absolute():
            workflow_file = Path.cwd() / workflow_file
        if not workflow_file.is_file():
            raise ComfyUIError(f"ComfyUI 视频工作流不存在: {workflow_file}")
        workflow = json.loads(workflow_file.read_text(encoding="utf-8"))
        uploaded_reference = self._upload_reference_image(reference_image)
        uploaded_end = self._upload_reference_image(end_image) if end_image else uploaded_reference
        pipeline = quality_pipeline if isinstance(quality_pipeline, dict) else {}
        plan = shot_plan if isinstance(shot_plan, dict) else {}
        spatial_plan = plan.get("spatial_plan") if isinstance(plan.get("spatial_plan"), dict) else {}
        spatial_asset_pack = plan.get("spatial_asset_pack") if isinstance(plan.get("spatial_asset_pack"), dict) else {}
        replacements = {
            "prompt": prompt,
            "positive_prompt": prompt,
            "negative_prompt": negative_prompt or "",
            "reference_image": uploaded_reference,
            "start_image": uploaded_reference,
            "first_frame": uploaded_reference,
            "end_image": uploaded_end,
            "last_frame": uploaded_end,
            "image": uploaded_reference,
            "width": width,
            "height": height,
            "duration_seconds": duration_seconds,
            "fps": fps,
            "seed": seed,
            "output_prefix": Path(output_path).stem,
            "motion_bucket_id": motion_bucket_id,
            "noise_aug_strength": noise_aug_strength,
            "quality_mode": quality_mode or "",
            "quality_profile": quality_mode or "",
            "repair_action": repair_action or "",
            "quality_pipeline": pipeline,
            "quality_pipeline_json": json.dumps(pipeline, ensure_ascii=False),
            "quality_pipeline_stages": ", ".join(str(item) for item in pipeline.get("stages", []) or []),
            "quality_pipeline_prompt": str(pipeline.get("prompt_directive") or ""),
            "quality_pipeline_negative": str(pipeline.get("negative_directive") or ""),
            # These JSON placeholders let a ComfyUI workflow consume the same
            # spatial contract as the remote provider. Workflows that do not
            # use the placeholders remain backwards-compatible.
            "shot_plan_json": json.dumps(plan, ensure_ascii=False, sort_keys=True),
            "spatial_plan_json": json.dumps(spatial_plan, ensure_ascii=False, sort_keys=True),
            "spatial_control_references_json": json.dumps(
                spatial_plan.get("control_references") or {}, ensure_ascii=False, sort_keys=True,
            ),
            "spatial_asset_pack_json": json.dumps(spatial_asset_pack, ensure_ascii=False, sort_keys=True),
            "spatial_scene_contract_hash": str(spatial_asset_pack.get("scene_contract_hash") or ""),
        }
        workflow = self._replace_workflow_placeholders(workflow, replacements)
        output_node = settings.COMFYUI_VIDEO_OUTPUT_NODE.strip() or None
        if output_node and output_node not in workflow:
            raise ComfyUIError(f"Configured video output node does not exist: {output_node}")
        if output_node is None:
            save_nodes = [key for key, node in workflow.items()
                          if node.get("class_type") in {"VHS_VideoCombine", "SaveVideo"}]
            if len(save_nodes) == 1:
                output_node = save_nodes[0]
            elif len(save_nodes) > 1:
                raise ComfyUIError("Video graph has several save nodes; configure COMFYUI_VIDEO_OUTPUT_NODE")
        self.preflight(workflow)
        artifact = Path(output_path).with_suffix(".workflow.json")
        artifact.parent.mkdir(parents=True, exist_ok=True)
        artifact.write_text(json.dumps(workflow, ensure_ascii=False, indent=2), encoding="utf-8")
        return self._run_submitted_job(
            workflow, output_path, "video", output_node,
            lambda result: self._get_generated_media(
                result, output_path, media_keys=("videos", "gifs", "images"), output_node_id=output_node,
            ),
        )

    def _run_submitted_job(self, workflow, output_path, kind, output_node, download):
        from src.services.generation_review import fingerprint, write_report

        workflow_sha256 = fingerprint(workflow)
        existing_job = None
        if output_path:
            job_path = Path(output_path).with_suffix(".job.json")
            try:
                candidate = json.loads(job_path.read_text(encoding="utf-8"))
            except (OSError, ValueError, TypeError):
                candidate = None
            if (
                isinstance(candidate, dict)
                and candidate.get("workflow_sha256") == workflow_sha256
                and candidate.get("kind") == kind
                and candidate.get("server") == self.base_url
                and candidate.get("status") in {"observing", "observation_required", "downloading"}
                and isinstance(candidate.get("prompt_id"), str)
                and candidate.get("prompt_id")
            ):
                existing_job = candidate

        job = {
            "status": "submitting", "kind": kind, "server": self.base_url,
            "output_path": str(output_path) if output_path else None,
            "output_node": output_node, "workflow_sha256": workflow_sha256,
        }
        if existing_job:
            job.update(existing_job)
            job.update(status="resuming", output_node=output_node)

        def record():
            if output_path:
                try:
                    write_report(Path(output_path).with_suffix(".job.json"), job)
                except OSError as exc:
                    logger.warning("Cannot persist ComfyUI job state: {}", exc)

        record()
        try:
            prompt_id = str(existing_job["prompt_id"]) if existing_job else self._submit_workflow(workflow)
            job.update(status="observing", prompt_id=prompt_id)
            record()
            result = self._wait_for_completion(prompt_id)
            job["status"] = "downloading"
            record()
            for attempt in range(self.max_retries):
                try:
                    path = download(result)
                    job["status"] = "completed"
                    record()
                    return path
                except (ComfyUIError, OSError):
                    if attempt + 1 == self.max_retries:
                        raise
                    time.sleep(2 ** attempt)
        except ComfyUIWaitTimeout as exc:
            job.update(status="observation_required", error=str(exc))
            if exc.prompt_id:
                job["prompt_id"] = exc.prompt_id
            if exc.client_id:
                job["client_id"] = exc.client_id
            record()
            raise
        except Exception as exc:
            job.update(status="failed", error=str(exc))
            record()
            raise

    def _replace_workflow_placeholders(self, value: Any, replacements: Dict[str, Any]) -> Any:
        if isinstance(value, dict):
            replaced = {}
            for key, item in value.items():
                if key in replacements and not isinstance(item, (dict, list)):
                    replaced[key] = replacements[key]
                else:
                    replaced[key] = self._replace_workflow_placeholders(item, replacements)
            return replaced
        if isinstance(value, list):
            return [self._replace_workflow_placeholders(item, replacements) for item in value]
        if isinstance(value, str):
            result = value
            for key, replacement in replacements.items():
                result = result.replace("{" + key + "}", str(replacement))
            return result
        return copy.deepcopy(value)
    
    def _submit_workflow(self, workflow: Dict) -> str:
        """
        提交工作流到 ComfyUI
        
        Args:
            workflow: 工作流字典
            
        Returns:
            Prompt ID
            
        Raises:
            ComfyUIError: 如果提交失败
        """
        data = {"prompt": workflow, "client_id": str(uuid.uuid4())}
        for attempt in range(self.max_retries):
            try:
                response = self.client.post(f"{self.base_url}/prompt", json=data)
                break
            except (httpx.ConnectError, httpx.ConnectTimeout) as exc:
                if attempt + 1 == self.max_retries:
                    raise ComfyUIError(f"Cannot connect to ComfyUI: {exc}") from exc
                time.sleep(2 ** attempt)
            except httpx.RequestError as exc:
                raise ComfyUIWaitTimeout(
                    f"Submission outcome is unknown; inspect ComfyUI queue/history for client_id={data['client_id']} before retrying",
                    client_id=data["client_id"],
                ) from exc
        try:
            if response.status_code >= 500:
                raise ComfyUIWaitTimeout(
                    f"Submission returned HTTP {response.status_code}; inspect queue/history before retrying client_id={data['client_id']}",
                    client_id=data["client_id"],
                )
            if response.status_code != 200:
                raise ComfyUIError(f"提交工作流失败: HTTP {response.status_code}: {response.text[:2000]}")
            
            result = response.json()
            prompt_id = result.get("prompt_id") if isinstance(result, dict) else None
            
            if not isinstance(prompt_id, str) or not prompt_id:
                raise ComfyUIWaitTimeout(
                    f"Missing prompt_id after submission; inspect queue/history before retrying client_id={data['client_id']}",
                    client_id=data["client_id"],
                )
            
            logger.debug(f"工作流已提交: prompt_id={prompt_id}")
            
            return prompt_id
            
        except ComfyUIError:
            raise
        except ValueError as exc:
            raise ComfyUIWaitTimeout(
                f"Invalid submission response; inspect queue/history before retrying client_id={data['client_id']}",
                client_id=data["client_id"],
            ) from exc
        except Exception as e:
            raise ComfyUIError(f"提交工作流异常: {e}") from e
    
    def _wait_for_completion(self, prompt_id: str, poll_interval: int = 2) -> Dict:
        """
        等待工作流完成
        
        Args:
            prompt_id: Prompt ID
            poll_interval: 轮询间隔（秒，默认 2）
            
        Returns:
            执行结果
            
        Raises:
            ComfyUIError: 如果执行失败或超时
        """
        start_time = time.monotonic()
        
        while True:
            # 检查超时
            if time.monotonic() - start_time > self.timeout:
                raise ComfyUIWaitTimeout(
                    f"ComfyUI job {prompt_id} observation timed out; inspect /history/{prompt_id} before retrying",
                    prompt_id=prompt_id,
                )
            
            try:
                # 查询历史记录
                remaining = self.timeout - (time.monotonic() - start_time)
                response = self.client.get(
                    f"{self.base_url}/history/{prompt_id}",
                    timeout=min(15.0, max(0.1, remaining)),
                )
                
                if response.status_code != 200:
                    logger.warning(f"查询历史记录失败: HTTP {response.status_code}")
                    time.sleep(poll_interval)
                    continue
                
                history = response.json()
                
                # 检查是否完成
                if prompt_id in history:
                    result = history[prompt_id]
                    
                    # 检查状态
                    status = result.get("status", {})
                    
                    if status.get("status_str") == "error":
                        raise ComfyUIError(f"工作流执行失败: {status.get('messages', [])}")
                    if status.get("completed"):
                        logger.debug(f"工作流执行完成: prompt_id={prompt_id}")
                        return result
                    
                
                # 继续等待
                time.sleep(poll_interval)
                
            except ComfyUIError:
                raise
            except Exception as e:
                logger.warning(f"查询工作流状态异常: {e}")
                time.sleep(poll_interval)
    
    def _get_generated_image(
        self,
        result: Dict,
        output_path: Optional[str] = None,
        output_node_id: Optional[str] = None,
    ) -> str:
        """
        获取生成的图像
        
        Args:
            result: 执行结果
            output_path: 输出文件路径（可选）
            
        Returns:
            图像文件路径
            
        Raises:
            ComfyUIError: 如果获取失败
        """
        try:
            # 从结果中提取图像信息
            outputs = result.get("outputs", {})
            
            # 查找 SaveImage 节点的输出
            for node_id, node_output in outputs.items():
                if output_node_id is not None and str(node_id) != output_node_id:
                    continue
                if "images" in node_output:
                    images = node_output["images"]
                    
                    if images and len(images) > 0:
                        image_info = images[0]
                        filename = image_info.get("filename")
                        subfolder = image_info.get("subfolder", "")
                        
                        if not filename:
                            raise ComfyUIError("未找到生成的图像文件名")
                        
                        # 下载图像
                        image_path = self._download_image(
                            filename=filename,
                            subfolder=subfolder,
                            output_path=output_path
                        )
                        
                        return image_path
            
            raise ComfyUIError("未找到生成的图像")
            
        except ComfyUIError:
            raise
        except Exception as e:
            raise ComfyUIError(f"获取生成的图像失败: {e}") from e

    def _get_generated_media(
        self,
        result: Dict,
        output_path: Optional[str] = None,
        media_keys: tuple[str, ...] = ("videos", "gifs", "images"),
        output_node_id: Optional[str] = None,
    ) -> str:
        try:
            outputs = result.get("outputs", {})
            candidates = []
            for key_index, key in enumerate(media_keys):
                for _node_id, node_output in outputs.items():
                    if output_node_id is not None and str(_node_id) != output_node_id:
                        continue
                    for media_info in node_output.get(key, []) or []:
                        filename = media_info.get("filename")
                        subfolder = media_info.get("subfolder", "")
                        media_type = media_info.get("type", "output")
                        if not filename:
                            raise ComfyUIError("未找到生成的媒体文件名")
                        if Path(filename).suffix.lower() not in {".mp4", ".webm", ".mov", ".mkv", ".avi", ".gif"}:
                            continue
                        candidates.append((Path(filename).suffix.lower() == ".gif", key_index, filename, subfolder, media_type))
            if candidates:
                _animated, _key_index, filename, subfolder, media_type = min(candidates, key=lambda item: item[:2])
                return self._download_media(
                    filename=filename, subfolder=subfolder, media_type=media_type, output_path=output_path,
                )
            raise ComfyUIError("未找到生成的视频或媒体输出")
        except ComfyUIError:
            raise
        except Exception as e:
            raise ComfyUIError(f"获取生成的视频失败: {e}") from e
    
    def _download_image(
        self,
        filename: str,
        subfolder: str = "",
        output_path: Optional[str] = None
    ) -> str:
        """
        下载生成的图像
        
        Args:
            filename: 文件名
            subfolder: 子文件夹
            output_path: 输出文件路径（可选）
            
        Returns:
            本地文件路径
            
        Raises:
            ComfyUIError: 如果下载失败
        """
        try:
            # 构建下载 URL
            params = {
                "filename": filename,
                "subfolder": subfolder,
                "type": "output"
            }
            
            # 下载图像
            response = self.client.get(
                f"{self.base_url}/view",
                params=params
            )
            
            if response.status_code != 200:
                raise ComfyUIError(f"下载图像失败: HTTP {response.status_code}")
            
            # 确定输出路径
            if not output_path:
                # 使用临时目录
                output_dir = Path("./storage/temp")
                output_dir.mkdir(parents=True, exist_ok=True)
                output_path = str(output_dir / Path(filename).name)
            
            # 保存图像
            self._save_download(response.content, Path(output_path), verify_image=True)
            
            logger.debug(f"图像已保存: {output_path}")
            
            return output_path
            
        except Exception as e:
            raise ComfyUIError(f"下载图像失败: {e}") from e

    def _download_media(
        self,
        filename: str,
        subfolder: str = "",
        media_type: str = "output",
        output_path: Optional[str] = None,
    ) -> str:
        try:
            response = self.client.get(
                f"{self.base_url}/view",
                params={"filename": filename, "subfolder": subfolder, "type": media_type or "output"},
            )
            if response.status_code != 200:
                raise ComfyUIError(f"下载媒体失败: HTTP {response.status_code}")
            if not output_path:
                output_dir = Path("./storage/temp")
                output_dir.mkdir(parents=True, exist_ok=True)
                output_path = str(output_dir / Path(filename).name)
            self._save_download(response.content, Path(output_path))
            logger.debug(f"媒体已保存: {output_path}")
            return output_path
        except Exception as e:
            raise ComfyUIError(f"下载媒体失败: {e}") from e

    @staticmethod
    def _save_download(content: bytes, target: Path, *, verify_image: bool = False) -> None:
        if not content:
            raise ComfyUIError("Downloaded media is empty")
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.with_name(f"{target.name}.{uuid.uuid4().hex}.download")
        try:
            temporary.write_bytes(content)
            if verify_image:
                from PIL import Image
                with Image.open(temporary) as decoded:
                    decoded.verify()
            temporary.replace(target)
        finally:
            temporary.unlink(missing_ok=True)
    
    def generate_batch(
        self,
        prompts: List[str],
        **kwargs
    ) -> List[str]:
        """
        批量生成图像
        
        Args:
            prompts: 提示词列表
            **kwargs: 其他参数（传递给 generate_image）
            
        Returns:
            生成的图像文件路径列表
            
        Raises:
            ComfyUIError: 如果生成失败
        """
        if not prompts:
            raise ValueError("提示词列表不能为空")
        
        logger.info(f"开始批量生成图像: {len(prompts)} 张")
        
        image_paths = []
        
        for i, prompt in enumerate(prompts):
            try:
                logger.info(f"生成第 {i + 1}/{len(prompts)} 张图像...")
                
                image_path = self.generate_image(prompt=prompt, **kwargs)
                image_paths.append(image_path)
                
            except ComfyUIWaitTimeout:
                raise
            except Exception as e:
                logger.error(f"生成第 {i + 1} 张图像失败: {e}")
                # 继续生成其他图像
                image_paths.append(None)
        
        success_count = sum(1 for p in image_paths if p is not None)
        logger.info(f"批量生成完成: {success_count}/{len(prompts)} 张成功")
        
        return image_paths
    
    def __del__(self):
        """
        析构函数，关闭 HTTP 客户端
        """
        try:
            if hasattr(self, 'client'):
                self.client.close()
        except Exception:
            pass


# 全局 ComfyUI 服务实例（单例模式）
_comfyui_service_instance: Optional[ComfyUIService] = None


def get_comfyui_service() -> ComfyUIService:
    """
    获取全局 ComfyUI 服务实例（单例模式）
    
    Returns:
        ComfyUI 服务实例
        
    Raises:
        ComfyUIError: 如果服务初始化失败
    """
    global _comfyui_service_instance
    
    if _comfyui_service_instance is None:
        try:
            _comfyui_service_instance = ComfyUIService()
            logger.info("全局 ComfyUI 服务实例创建成功")
            
        except Exception as e:
            logger.error(f"创建全局 ComfyUI 服务实例失败: {e}")
            raise ComfyUIError(f"ComfyUI 服务初始化失败: {e}") from e
    
    return _comfyui_service_instance


def cleanup_comfyui_service():
    """
    清理全局 ComfyUI 服务实例
    
    用于应用关闭时释放资源
    """
    global _comfyui_service_instance
    
    if _comfyui_service_instance is not None:
        try:
            del _comfyui_service_instance
            _comfyui_service_instance = None
            logger.info("全局 ComfyUI 服务实例已清理")
        except Exception as e:
            logger.error(f"清理全局 ComfyUI 服务实例失败: {e}")
