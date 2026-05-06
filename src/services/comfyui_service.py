"""
ComfyUI 服务（ComfyUIService）

负责调用 ComfyUI API 生成图像，管理工作流配置，
实现重试逻辑和错误处理
"""

import os
import json
import time
import uuid
from typing import Optional, Dict, List
from pathlib import Path

import httpx

from src.utils.logger import logger
from src.services.workflow_manager import WorkflowManager, get_workflow_manager
from src.models.workflow_config import WorkflowType
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


class ComfyUIService:
    """ComfyUI 服务（Stable Diffusion 图像生成）"""
    
    def __init__(
        self,
        base_url: Optional[str] = None,
        workflow_path: Optional[str] = None,
        timeout: int = 300,
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
        self.base_url = (base_url or os.getenv("COMFYUI_BASE_URL", "http://127.0.0.1:8188")).rstrip("/")
        self.timeout = timeout
        self.max_retries = max_retries
        
        # HTTP 客户端（禁用代理，直接连接本地服务）
        # httpx 0.24+ 版本使用 trust_env=False 来忽略环境变量中的代理设置
        self.client = httpx.Client(timeout=timeout, trust_env=False)
        
        # 使用 WorkflowManager 管理工作流配置
        self.workflow_manager = get_workflow_manager()
        
        # 初始化参数优化器
        self.parameter_optimizer = get_parameter_optimizer()
        
        # 初始化提示词优化器
        self.prompt_optimizer = get_prompt_optimizer()
        
        # 当前工作流类型（用于向后兼容）
        self.current_workflow_type: Optional[WorkflowType] = None
        
        # 加载默认工作流配置
        try:
            self.workflow_manager.load_workflow(workflow_type=WorkflowType.BASIC)
            self.current_workflow_type = WorkflowType.BASIC
            logger.info(f"ComfyUI 服务初始化完成: {self.base_url}")
        except Exception as e:
            logger.warning(f"加载默认工作流失败: {e}，将在首次使用时加载")
            logger.info(f"ComfyUI 服务初始化完成: {self.base_url} (未加载工作流)")
    
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
        enable_prompt_optimization: bool = True,  # 是否启用提示词优化
        enable_parameter_optimization: bool = True,  # 是否启用参数优化
        enable_realism: bool = False,  # 是否启用真实感模式
        gpu_vram_gb: Optional[int] = None,  # GPU 显存大小（GB）
        optimization_mode: Optional[str] = None  # 提示词优化模式（quality, realism, artistic, balanced）
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
        
        # 保存原始提示词
        original_prompt = prompt
        original_negative_prompt = negative_prompt
        
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
        if not negative_prompt:
            workflow_config = self.workflow_manager.get_current_workflow()
            if workflow_config:
                negative_prompt = workflow_config.negative_prompt.default
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
                
                # 优化参数
                optimized_params = self.parameter_optimizer.optimize(
                    scene_type=scene_type_enum,
                    quality_mode=quality_mode_enum,
                    has_reference_image=(reference_image is not None),
                    gpu_vram_gb=gpu_vram_gb,
                    base_width=width,
                    base_height=height,
                    custom_params={
                        "steps": steps,
                        "cfg_scale": cfg_scale
                    }
                )
                
                # 应用优化后的参数
                steps = optimized_params.steps
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
        
        # 根据是否有参考图像选择工作流类型
        if use_ipadapter and reference_image:
            target_workflow_type = WorkflowType.IPADAPTER
        else:
            target_workflow_type = WorkflowType.TXT2IMG
        
        # 切换到目标工作流（如果需要）
        if self.current_workflow_type != target_workflow_type:
            self.load_workflow(target_workflow_type)
        
        logger.info(f"开始生成图像: {width}x{height}, steps={steps}, cfg={cfg_scale}, workflow={target_workflow_type}")
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
            use_ipadapter=use_ipadapter
        )
        
        # 提交任务并等待完成（带重试）
        for attempt in range(self.max_retries):
            try:
                image_path = self._submit_and_wait(workflow, output_path)
                logger.info(f"图像生成成功: {image_path}")
                return image_path
                
            except Exception as e:
                error_str = str(e)
                # 如果是人脸检测失败，自动切换到纯文生图模式
                if "InsightFace: No face detected" in error_str and reference_image:
                    logger.warning(f"参考图像中未检测到人脸，切换到纯文生图模式")
                    # 重新加载纯文生图工作流
                    self.load_workflow(WorkflowType.TXT2IMG)
                    # 重新构建工作流（不使用 IP-Adapter）
                    workflow = self._build_workflow(
                        prompt=prompt,
                        negative_prompt=negative_prompt,
                        width=width,
                        height=height,
                        steps=steps,
                        cfg_scale=cfg_scale,
                        seed=seed,
                        reference_image=None,  # 移除参考图像
                        use_ipadapter=False  # 禁用 IP-Adapter
                    )
                    # 继续重试（不增加 attempt 计数）
                    continue
                
                if attempt < self.max_retries - 1:
                    wait_time = 2 ** attempt  # 指数退避
                    logger.warning(f"生成失败（第 {attempt + 1} 次尝试），{wait_time} 秒后重试: {e}")
                    time.sleep(wait_time)
                else:
                    error_msg = f"图像生成失败（已重试 {self.max_retries} 次）: {e}"
                    logger.error(error_msg)
                    raise ComfyUIError(error_msg) from e
    
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
        use_ipadapter: bool = True
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
        
        workflow = workflow_api
        
        # 动态查找节点 ID（根据 class_type）
        def find_node_id(class_type: str) -> Optional[str]:
            for node_id, node_data in workflow.items():
                if node_data.get("class_type") == class_type:
                    return node_id
            return None
        
        clip_text_positive_id = find_node_id("CLIPTextEncode")
        empty_latent_id = find_node_id("EmptyLatentImage")
        ksampler_id = find_node_id("KSampler")
        save_image_id = find_node_id("SaveImage")
        load_image_id = find_node_id("LoadImage")
        ipadapter_faceid_id = find_node_id("IPAdapterFaceID")
        checkpoint_loader_id = find_node_id("CheckpointLoaderSimple")
        lora_loader_id = find_node_id("LoraLoader")
        
        # 设置提示词（可能有两个 CLIPTextEncode 节点）
        if clip_text_positive_id:
            # 找到所有 CLIPTextEncode 节点
            clip_nodes = [nid for nid, ndata in workflow.items() if ndata.get("class_type") == "CLIPTextEncode"]
            if len(clip_nodes) >= 2:
                # 按节点 ID 排序，确保第一个是正面，第二个是负面
                clip_nodes.sort()
                workflow[clip_nodes[0]]["inputs"]["text"] = prompt
                workflow[clip_nodes[1]]["inputs"]["text"] = negative_prompt
                logger.debug(f"设置提示词 - 正面节点: {clip_nodes[0]}, 负面节点: {clip_nodes[1]}")
        
        # 设置图像尺寸
        if empty_latent_id:
            workflow[empty_latent_id]["inputs"]["width"] = width
            workflow[empty_latent_id]["inputs"]["height"] = height
        
        # 设置采样参数
        if ksampler_id:
            workflow[ksampler_id]["inputs"]["seed"] = seed
            workflow[ksampler_id]["inputs"]["steps"] = steps
            workflow[ksampler_id]["inputs"]["cfg"] = cfg_scale
        
        # 启用 IP-Adapter（如果有参考图像且启用了IP-Adapter）
        if use_ipadapter and reference_image and ipadapter_faceid_id:
            logger.info(f"启用 IP-Adapter，使用参考图像: {reference_image}")
            # 连接 KSampler 到 IP-Adapter 应用节点
            if ksampler_id:
                workflow[ksampler_id]["inputs"]["model"] = [ipadapter_faceid_id, 0]
            
            # 将参考图像路径转换为 ComfyUI 可识别的格式
            import os
            from pathlib import Path
            ref_image_path = Path(reference_image)
            if not ref_image_path.is_absolute():
                # 转换为绝对路径
                ref_image_path = Path.cwd() / ref_image_path
            
            # 设置参考图像路径（使用绝对路径）
            if load_image_id:
                workflow[load_image_id]["inputs"]["image"] = str(ref_image_path)
                logger.debug(f"参考图像绝对路径: {ref_image_path}")
            
            # 设置 IP-Adapter 权重（从配置中获取或使用默认值）
            ipadapter_weight = workflow_config.parameters.default.get("ipadapter_weight", 0.8)
            workflow[ipadapter_faceid_id]["inputs"]["weight"] = ipadapter_weight
            
            # 配置 FaceID Plus V2 模式（面部 + 全身一致性）
            # 注意：ipadapter_config 可能不在 parameters.default 中，需要单独处理
            if "weight_faceidv2" in workflow[ipadapter_faceid_id]["inputs"]:
                workflow[ipadapter_faceid_id]["inputs"]["weight_faceidv2"] = 1.0
                logger.info(f"IP-Adapter FaceID Plus V2 已配置，权重: {ipadapter_weight}")
                logger.info("将保持角色面部、服装、体型的整体一致性（FaceID + LoRA 增强）")
            else:
                logger.info(f"IP-Adapter 已配置，权重: {ipadapter_weight}")
        else:
            logger.debug("未启用 IP-Adapter")
            # 如果没有参考图像或禁用IP-Adapter，直接连接到checkpoint_loader或lora_loader
            if ksampler_id:
                # 优先使用 LoraLoader（如果存在），否则使用 CheckpointLoader
                model_source_id = lora_loader_id if lora_loader_id else checkpoint_loader_id
                if model_source_id:
                    workflow[ksampler_id]["inputs"]["model"] = [model_source_id, 0]
        
        # 设置输出文件名前缀
        if save_image_id:
            filename_prefix = f"short_drama_{uuid.uuid4().hex[:8]}"
            workflow[save_image_id]["inputs"]["filename_prefix"] = filename_prefix
        
        return workflow
    
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
            # 提交工作流
            prompt_id = self._submit_workflow(workflow)
            
            # 等待完成
            result = self._wait_for_completion(prompt_id)
            
            # 获取生成的图像
            image_path = self._get_generated_image(result, output_path)
            
            return image_path
            
        except Exception as e:
            raise ComfyUIError(f"工作流执行失败: {e}") from e
    
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
        try:
            # 构建请求数据
            data = {
                "prompt": workflow,
                "client_id": str(uuid.uuid4())
            }
            
            # 提交工作流
            response = self.client.post(
                f"{self.base_url}/prompt",
                json=data
            )
            
            if response.status_code != 200:
                raise ComfyUIError(f"提交工作流失败: HTTP {response.status_code}")
            
            result = response.json()
            prompt_id = result.get("prompt_id")
            
            if not prompt_id:
                raise ComfyUIError("未获取到 prompt_id")
            
            logger.debug(f"工作流已提交: prompt_id={prompt_id}")
            
            return prompt_id
            
        except httpx.TimeoutException as e:
            raise ComfyUIError(f"提交工作流超时: {e}") from e
        except httpx.ConnectError as e:
            raise ComfyUIError(f"无法连接到 ComfyUI 服务: {e}") from e
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
        start_time = time.time()
        
        while True:
            # 检查超时
            if time.time() - start_time > self.timeout:
                raise ComfyUIError(f"等待工作流完成超时（{self.timeout} 秒）")
            
            try:
                # 查询历史记录
                response = self.client.get(f"{self.base_url}/history/{prompt_id}")
                
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
                    
                    if status.get("completed"):
                        logger.debug(f"工作流执行完成: prompt_id={prompt_id}")
                        return result
                    
                    if status.get("status_str") == "error":
                        error_msg = status.get("messages", ["未知错误"])
                        raise ComfyUIError(f"工作流执行失败: {error_msg}")
                
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
        output_path: Optional[str] = None
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
                output_path = str(output_dir / filename)
            
            # 保存图像
            with open(output_path, 'wb') as f:
                f.write(response.content)
            
            logger.debug(f"图像已保存: {output_path}")
            
            return output_path
            
        except Exception as e:
            raise ComfyUIError(f"下载图像失败: {e}") from e
    
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
