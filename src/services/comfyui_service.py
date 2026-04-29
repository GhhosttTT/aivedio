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
            workflow_path: 工作流配置文件路径（默认从环境变量读取）
            timeout: 请求超时时间（秒，默认 300）
            max_retries: 最大重试次数（默认 3）
        """
        self.base_url = (base_url or os.getenv("COMFYUI_BASE_URL", "http://127.0.0.1:8188")).rstrip("/")
        self.workflow_path = workflow_path or os.getenv("COMFYUI_WORKFLOW_PATH", "./configs/comfyui_workflow.json")
        self.timeout = timeout
        self.max_retries = max_retries
        
        # HTTP 客户端
        self.client = httpx.Client(timeout=timeout)
        
        # 工作流配置
        self.workflow_config: Optional[Dict] = None
        
        # 加载工作流配置
        self.load_workflow()
        
        logger.info(f"ComfyUI 服务初始化完成: {self.base_url}")
    
    def load_workflow(self):
        """
        加载工作流配置文件
        
        Raises:
            FileNotFoundError: 如果配置文件不存在
            ComfyUIError: 如果配置文件格式错误
        """
        try:
            if not os.path.exists(self.workflow_path):
                raise FileNotFoundError(f"工作流配置文件不存在: {self.workflow_path}")
            
            with open(self.workflow_path, 'r', encoding='utf-8') as f:
                self.workflow_config = json.load(f)
            
            logger.info(f"工作流配置加载成功: {self.workflow_path}")
            logger.debug(f"工作流名称: {self.workflow_config.get('workflow', {}).get('name')}")
            
        except json.JSONDecodeError as e:
            error_msg = f"工作流配置文件格式错误: {e}"
            logger.error(error_msg)
            raise ComfyUIError(error_msg) from e
        except Exception as e:
            error_msg = f"加载工作流配置失败: {e}"
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
        output_path: Optional[str] = None
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
            
        Returns:
            生成的图像文件路径
            
        Raises:
            ComfyUIError: 如果生成失败
        """
        if not prompt or len(prompt.strip()) == 0:
            raise ValueError("提示词不能为空")
        
        # 使用默认负面提示词
        if not negative_prompt:
            negative_prompt = self.workflow_config.get("negative_prompt", {}).get("default", "")
        
        # 生成随机种子
        if seed == -1:
            seed = int(time.time() * 1000) % (2**32)
        
        logger.info(f"开始生成图像: {width}x{height}, steps={steps}, cfg={cfg_scale}")
        logger.debug(f"提示词: {prompt[:100]}...")
        
        # 构建工作流
        workflow = self._build_workflow(
            prompt=prompt,
            negative_prompt=negative_prompt,
            width=width,
            height=height,
            steps=steps,
            cfg_scale=cfg_scale,
            seed=seed
        )
        
        # 提交任务并等待完成（带重试）
        for attempt in range(self.max_retries):
            try:
                image_path = self._submit_and_wait(workflow, output_path)
                logger.info(f"图像生成成功: {image_path}")
                return image_path
                
            except Exception as e:
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
        seed: int
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
            
        Returns:
            工作流字典
        """
        # 深拷贝工作流配置
        workflow = json.loads(json.dumps(self.workflow_config.get("nodes", {})))
        
        # 设置提示词
        workflow["clip_text_encode_positive"]["inputs"]["text"] = prompt
        workflow["clip_text_encode_negative"]["inputs"]["text"] = negative_prompt
        
        # 设置图像尺寸
        workflow["empty_latent_image"]["inputs"]["width"] = width
        workflow["empty_latent_image"]["inputs"]["height"] = height
        
        # 设置采样参数
        workflow["ksampler"]["inputs"]["seed"] = seed
        workflow["ksampler"]["inputs"]["steps"] = steps
        workflow["ksampler"]["inputs"]["cfg"] = cfg_scale
        
        # 设置输出文件名前缀
        filename_prefix = f"short_drama_{uuid.uuid4().hex[:8]}"
        workflow["save_image"]["inputs"]["filename_prefix"] = filename_prefix
        
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
