"""
SVD 服务（Stable Video Diffusion Service）

负责使用 Stable Video Diffusion 模型将图像转换为视频，
管理 GPU 显存，实现重试逻辑和错误处理
"""

import os
import time
from typing import Optional
from pathlib import Path

try:
    import torch
    from diffusers import StableVideoDiffusionPipeline
    from diffusers.utils import load_image, export_to_video
    DIFFUSERS_AVAILABLE = True
except ImportError:
    DIFFUSERS_AVAILABLE = False
    torch = None
    StableVideoDiffusionPipeline = None

from src.utils.logger import logger
from src.utils.gpu_utils import (
    is_gpu_available,
    get_gpu_memory_info,
    clear_gpu_cache,
    check_gpu_memory_threshold
)


class SVDError(Exception):
    """SVD 服务错误"""
    pass


class SVDService:
    """SVD 服务（Stable Video Diffusion 图生视频）"""
    
    def __init__(
        self,
        model_path: Optional[str] = None,
        num_frames: int = 16,
        fps: int = 8,
        motion_bucket_id: int = 127,
        noise_aug_strength: float = 0.02,
        max_retries: int = 3
    ):
        """
        初始化 SVD 服务
        
        Args:
            model_path: SVD 模型路径（默认从环境变量读取）
            num_frames: 生成视频帧数（默认 16）
            fps: 视频帧率（默认 8）
            motion_bucket_id: 运动强度（默认 127，范围 1-255）
            noise_aug_strength: 噪声增强强度（默认 0.02）
            max_retries: 最大重试次数（默认 3）
        """
        if not DIFFUSERS_AVAILABLE:
            raise RuntimeError(
                "diffusers 未安装，请运行: pip install diffusers transformers accelerate"
            )
        
        # 从环境变量读取配置
        self.model_path = model_path or os.getenv(
            "SVD_MODEL_PATH",
            "./models/stable-video-diffusion-img2vid-xt"
        )
        self.num_frames = int(os.getenv("SVD_NUM_FRAMES", str(num_frames)))
        self.fps = int(os.getenv("SVD_FPS", str(fps)))
        self.motion_bucket_id = motion_bucket_id
        self.noise_aug_strength = noise_aug_strength
        self.max_retries = max_retries
        
        # 模型实例
        self.pipeline: Optional[StableVideoDiffusionPipeline] = None
        self.is_loaded = False
        
        # 检查 GPU 可用性
        self.device = "cuda" if is_gpu_available() else "cpu"
        
        if self.device == "cpu":
            logger.warning("GPU 不可用，将使用 CPU（速度会很慢）")
        
        logger.info(f"SVD 服务初始化完成: device={self.device}")
    
    def load_model(self):
        """
        加载 SVD 模型
        
        Raises:
            SVDError: 如果模型加载失败或显存不足
        """
        if self.is_loaded:
            logger.info("SVD 模型已加载，跳过")
            return
        
        try:
            logger.info(f"开始加载 SVD 模型: {self.model_path}")
            
            # 检查 GPU 显存
            if self.device == "cuda":
                memory_info = get_gpu_memory_info()
                logger.info(
                    f"GPU 显存: {memory_info['used']:.2f}MB / "
                    f"{memory_info['total']:.2f}MB"
                )
                
                # 检查显存是否足够（SVD 需要约 8-10GB = 8192-10240MB）
                if memory_info['free'] < 8192.0:
                    logger.warning(
                        f"GPU 显存不足（可用: {memory_info['free']:.2f}MB），"
                        "尝试清理缓存..."
                    )
                    clear_gpu_cache()
                    
                    # 再次检查
                    memory_info = get_gpu_memory_info()
                    if memory_info['free'] < 8192.0:
                        raise SVDError(
                            f"GPU 显存不足（可用: {memory_info['free']:.2f}MB），"
                            "需要至少 8GB (8192MB) 可用显存"
                        )
            
            # 加载模型
            self.pipeline = StableVideoDiffusionPipeline.from_pretrained(
                self.model_path,
                torch_dtype=torch.float16 if self.device == "cuda" else torch.float32,
                variant="fp16" if self.device == "cuda" else None
            )
            
            # 移动到设备
            self.pipeline = self.pipeline.to(self.device)
            
            # 启用内存优化
            if self.device == "cuda":
                self.pipeline.enable_model_cpu_offload()
                logger.info("已启用 CPU offload 优化")
            
            self.is_loaded = True
            
            logger.info("SVD 模型加载成功")
            
            # 记录显存使用
            if self.device == "cuda":
                memory_info = get_gpu_memory_info()
                logger.info(
                    f"模型加载后 GPU 显存: {memory_info['used']:.2f}MB / "
                    f"{memory_info['total']:.2f}MB"
                )
            
        except Exception as e:
            error_msg = f"SVD 模型加载失败: {e}"
            logger.error(error_msg)
            
            # 检查是否是显存不足错误
            if "out of memory" in str(e).lower() or "cuda" in str(e).lower():
                logger.warning("可能是显存不足，建议清理其他 GPU 任务")
                raise SVDError(
                    "显存不足，无法加载 SVD 模型。"
                    "请确保有至少 8GB 可用显存"
                ) from e
            
            raise SVDError(error_msg) from e
    
    def unload_model(self):
        """
        卸载模型释放资源
        
        释放 GPU 显存和内存
        """
        try:
            if self.pipeline is not None:
                logger.info("开始卸载 SVD 模型...")
                
                # 删除模型实例
                del self.pipeline
                self.pipeline = None
                self.is_loaded = False
                
                # 强制垃圾回收
                import gc
                gc.collect()
                
                # 清理 GPU 缓存
                if self.device == "cuda":
                    clear_gpu_cache()
                    logger.info("GPU 缓存已清理")
                
                logger.info("SVD 模型卸载完成")
            else:
                logger.warning("模型未加载，无需卸载")
                
        except Exception as e:
            logger.error(f"卸载模型失败: {e}")
            raise
    
    def check_gpu_memory(self, required_gb: float = 8.0) -> bool:
        """
        检查 GPU 显存是否足够
        
        Args:
            required_gb: 需要的显存大小（GB，默认 8.0）
            
        Returns:
            显存是否足够
        """
        if self.device == "cpu":
            return True
        
        try:
            memory_info = get_gpu_memory_info()
            available_mb = memory_info['free']
            required_mb = required_gb * 1024
            
            logger.debug(
                f"GPU 显存检查: 可用 {available_mb:.2f}MB, "
                f"需要 {required_mb:.2f}MB ({required_gb:.2f}GB)"
            )
            
            return available_mb >= required_mb
            
        except Exception as e:
            logger.warning(f"检查 GPU 显存失败: {e}")
            return False
    
    def generate_video(
        self,
        image_path: str,
        output_path: Optional[str] = None,
        num_frames: Optional[int] = None,
        fps: Optional[int] = None,
        motion_bucket_id: Optional[int] = None,
        noise_aug_strength: Optional[float] = None,
        decode_chunk_size: int = 8
    ) -> str:
        """
        生成视频（图生视频）
        
        Args:
            image_path: 输入图像路径
            output_path: 输出视频路径（可选）
            num_frames: 生成视频帧数（可选，使用默认值）
            fps: 视频帧率（可选，使用默认值）
            motion_bucket_id: 运动强度（可选，使用默认值）
            noise_aug_strength: 噪声增强强度（可选，使用默认值）
            decode_chunk_size: 解码块大小（默认 8，减少显存占用）
            
        Returns:
            生成的视频文件路径
            
        Raises:
            SVDError: 如果生成失败
        """
        if not os.path.exists(image_path):
            raise FileNotFoundError(f"输入图像不存在: {image_path}")
        
        # 使用默认参数
        num_frames = num_frames or self.num_frames
        fps = fps or self.fps
        motion_bucket_id = motion_bucket_id or self.motion_bucket_id
        noise_aug_strength = noise_aug_strength or self.noise_aug_strength
        
        logger.info(
            f"开始生成视频: frames={num_frames}, fps={fps}, "
            f"motion={motion_bucket_id}"
        )
        logger.debug(f"输入图像: {image_path}")
        
        # 加载模型（如果未加载）
        if not self.is_loaded:
            self.load_model()
        
        # 生成视频（带重试）
        for attempt in range(self.max_retries):
            try:
                # 检查 GPU 显存
                if self.device == "cuda" and not self.check_gpu_memory():
                    logger.warning("GPU 显存不足，尝试清理缓存...")
                    clear_gpu_cache()
                    time.sleep(1)
                    
                    if not self.check_gpu_memory():
                        raise SVDError("GPU 显存不足，无法生成视频")
                
                # 加载输入图像
                image = load_image(image_path)
                image = image.resize((1024, 576))  # SVD 推荐分辨率
                
                logger.info("开始推理...")
                start_time = time.time()
                
                # 生成视频帧
                frames = self.pipeline(
                    image,
                    num_frames=num_frames,
                    motion_bucket_id=motion_bucket_id,
                    noise_aug_strength=noise_aug_strength,
                    decode_chunk_size=decode_chunk_size
                ).frames[0]
                
                elapsed_time = time.time() - start_time
                logger.info(f"推理完成，耗时: {elapsed_time:.2f} 秒")
                
                # 确定输出路径
                if not output_path:
                    output_dir = Path("./storage/temp")
                    output_dir.mkdir(parents=True, exist_ok=True)
                    output_path = str(
                        output_dir / f"video_{int(time.time())}.mp4"
                    )
                
                # 导出视频
                export_to_video(frames, output_path, fps=fps)
                
                logger.info(f"视频生成成功: {output_path}")
                
                # 记录显存使用
                if self.device == "cuda":
                    memory_info = get_gpu_memory_info()
                    logger.info(
                        f"生成后 GPU 显存: {memory_info['used']:.2f}MB / "
                        f"{memory_info['total']:.2f}MB"
                    )
                
                return output_path
                
            except Exception as e:
                if attempt < self.max_retries - 1:
                    wait_time = 2 ** attempt  # 指数退避
                    logger.warning(
                        f"生成失败（第 {attempt + 1} 次尝试），"
                        f"{wait_time} 秒后重试: {e}"
                    )
                    
                    # 清理 GPU 缓存后重试
                    if self.device == "cuda":
                        clear_gpu_cache()
                    
                    time.sleep(wait_time)
                else:
                    error_msg = f"视频生成失败（已重试 {self.max_retries} 次）: {e}"
                    logger.error(error_msg)
                    raise SVDError(error_msg) from e
    
    def get_model_info(self) -> dict:
        """
        获取模型信息
        
        Returns:
            包含模型配置信息的字典
        """
        return {
            "model_path": self.model_path,
            "device": self.device,
            "num_frames": self.num_frames,
            "fps": self.fps,
            "motion_bucket_id": self.motion_bucket_id,
            "noise_aug_strength": self.noise_aug_strength,
            "is_loaded": self.is_loaded
        }
    
    def __del__(self):
        """
        析构函数，确保资源被释放
        """
        try:
            if self.is_loaded:
                self.unload_model()
        except Exception:
            pass


# 全局 SVD 服务实例（单例模式）
_svd_service_instance: Optional[SVDService] = None


def get_svd_service() -> SVDService:
    """
    获取全局 SVD 服务实例（单例模式）
    
    Returns:
        SVD 服务实例
        
    Raises:
        SVDError: 如果服务初始化失败
    """
    global _svd_service_instance
    
    if _svd_service_instance is None:
        try:
            _svd_service_instance = SVDService()
            logger.info("全局 SVD 服务实例创建成功")
            
        except Exception as e:
            logger.error(f"创建全局 SVD 服务实例失败: {e}")
            raise SVDError(f"SVD 服务初始化失败: {e}") from e
    
    return _svd_service_instance


def cleanup_svd_service():
    """
    清理全局 SVD 服务实例
    
    用于应用关闭时释放资源
    """
    global _svd_service_instance
    
    if _svd_service_instance is not None:
        try:
            _svd_service_instance.unload_model()
            _svd_service_instance = None
            logger.info("全局 SVD 服务实例已清理")
        except Exception as e:
            logger.error(f"清理全局 SVD 服务实例失败: {e}")
