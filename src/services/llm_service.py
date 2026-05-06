"""
LLM 服务（Qwen2.5-14B + llama.cpp）

负责封装 llama.cpp 调用逻辑，管理 LLM 模型加载和卸载，
优化 CPU offload 配置，提供剧本生成的 Prompt 模板
"""

import os
from typing import Optional, Dict, Callable

try:
    from llama_cpp import Llama
    LLAMA_CPP_AVAILABLE = True
except ImportError:
    LLAMA_CPP_AVAILABLE = False
    Llama = None

from src.utils.logger import logger


class LLMService:
    """LLM 服务（Qwen2.5-14B + llama.cpp）"""
    
    def __init__(
        self,
        model_path: Optional[str] = None,
        n_gpu_layers: int = 20,
        n_ctx: int = 4096,
        n_threads: int = 8,
        n_batch: int = 512,
        verbose: bool = False
    ):
        """
        初始化 LLM 服务
        
        Args:
            model_path: GGUF 模型文件路径（默认从环境变量读取）
            n_gpu_layers: GPU 加载的层数（剩余层 offload 到 CPU，默认 20 层）
            n_ctx: 上下文窗口大小（默认 4096）
            n_threads: CPU 线程数（默认 8）
            n_batch: 批处理大小（默认 512）
            verbose: 是否输出详细日志（默认 False）
            
        Raises:
            FileNotFoundError: 如果模型文件不存在
            RuntimeError: 如果模型加载失败
        """
        # 从环境变量读取配置
        self.model_path = model_path or os.getenv("LLM_MODEL_PATH")
        self.n_gpu_layers = n_gpu_layers
        self.n_ctx = n_ctx
        self.n_threads = n_threads
        self.n_batch = n_batch
        self.verbose = verbose
        
        # 模型实例
        self.model: Optional[Llama] = None
        self.is_loaded = False
        
        # 验证模型路径
        if not self.model_path:
            raise ValueError("未配置 LLM 模型路径，请设置环境变量 LLM_MODEL_PATH")
        
        if not os.path.exists(self.model_path):
            raise FileNotFoundError(f"LLM 模型文件不存在: {self.model_path}")
        
        # 加载模型
        self._load_model()
    
    def _load_model(self):
        """
        加载 LLM 模型
        
        Raises:
            RuntimeError: 如果模型加载失败或显存不足
        """
        if not LLAMA_CPP_AVAILABLE:
            raise RuntimeError(
                "llama-cpp-python 未安装，请运行: pip install llama-cpp-python"
            )
        
        try:
            logger.info(f"开始加载 LLM 模型: {self.model_path}")
            logger.info(
                f"配置参数: n_gpu_layers={self.n_gpu_layers}, "
                f"n_ctx={self.n_ctx}, n_threads={self.n_threads}"
            )
            
            # 加载模型
            self.model = Llama(
                model_path=self.model_path,
                n_gpu_layers=self.n_gpu_layers,
                n_ctx=self.n_ctx,
                n_threads=self.n_threads,
                n_batch=self.n_batch,
                verbose=self.verbose
            )
            
            self.is_loaded = True
            
            logger.info("LLM 模型加载成功")
            
            # 模型预热（首次加载优化）
            self._warmup_model()
            
        except Exception as e:
            error_msg = f"LLM 模型加载失败: {e}"
            logger.error(error_msg)
            
            # 检查是否是显存不足错误
            if "out of memory" in str(e).lower() or "cuda" in str(e).lower():
                logger.warning(
                    f"可能是显存不足，当前 GPU 层数: {self.n_gpu_layers}，"
                    "建议减少 n_gpu_layers 参数"
                )
                raise RuntimeError(
                    f"显存不足，无法加载模型。当前 GPU 层数: {self.n_gpu_layers}，"
                    "请减少 LLM_N_GPU_LAYERS 环境变量的值"
                ) from e
            
            raise RuntimeError(error_msg) from e
    
    def _warmup_model(self):
        """
        模型预热（首次加载优化）
        
        通过生成一个简短的测试文本来预热模型，
        避免首次实际调用时的延迟
        """
        try:
            logger.info("开始模型预热...")
            
            # 生成一个简短的测试文本
            warmup_prompt = "你好"
            self.model(
                warmup_prompt,
                max_tokens=5,
                temperature=0.7,
                echo=False
            )
            
            logger.info("模型预热完成")
            
        except Exception as e:
            logger.warning(f"模型预热失败（不影响正常使用）: {e}")
    
    def generate(
        self,
        prompt: str,
        max_tokens: int = 2048,
        temperature: float = 0.7,
        top_p: float = 0.9,
        top_k: int = 40,
        repeat_penalty: float = 1.1,
        stop: Optional[list] = None,
        stream: bool = False,
        callback: Optional[Callable[[str], None]] = None
    ) -> str:
        """
        生成文本
        
        Args:
            prompt: 输入提示词
            max_tokens: 最大生成 token 数（默认 2048）
            temperature: 温度参数，控制随机性（默认 0.7，范围 0.0-2.0）
            top_p: Top-p 采样参数（默认 0.9，范围 0.0-1.0）
            top_k: Top-k 采样参数（默认 40）
            repeat_penalty: 重复惩罚（默认 1.1）
            stop: 停止词列表（可选）
            stream: 是否流式输出（默认 False）
            callback: 流式输出回调函数（可选，仅在 stream=True 时有效）
            
        Returns:
            生成的文本
            
        Raises:
            RuntimeError: 如果模型未加载或生成失败
        """
        if not self.is_loaded or self.model is None:
            raise RuntimeError("LLM 模型未加载，请先初始化服务")
        
        if not prompt or len(prompt.strip()) == 0:
            raise ValueError("输入提示词不能为空")
        
        try:
            logger.info(f"开始生成文本，提示词长度: {len(prompt)} 字符")
            logger.debug(
                f"生成参数: max_tokens={max_tokens}, "
                f"temperature={temperature}, top_p={top_p}"
            )
            
            # 构建停止词列表
            stop_sequences = stop or []
            
            if stream:
                # 流式生成
                return self._generate_stream(
                    prompt=prompt,
                    max_tokens=max_tokens,
                    temperature=temperature,
                    top_p=top_p,
                    top_k=top_k,
                    repeat_penalty=repeat_penalty,
                    stop=stop_sequences,
                    callback=callback
                )
            else:
                # 非流式生成
                output = self.model(
                    prompt,
                    max_tokens=max_tokens,
                    temperature=temperature,
                    top_p=top_p,
                    top_k=top_k,
                    repeat_penalty=repeat_penalty,
                    stop=stop_sequences,
                    echo=False
                )
                
                # 提取生成的文本
                generated_text = output["choices"][0]["text"]
                
                logger.info(f"文本生成完成，输出长度: {len(generated_text)} 字符")
                logger.debug(f"生成的文本: {generated_text[:100]}...")
                
                return generated_text
            
        except Exception as e:
            error_msg = f"文本生成失败: {e}"
            logger.error(error_msg)
            raise RuntimeError(error_msg) from e
    
    def _generate_stream(
        self,
        prompt: str,
        max_tokens: int,
        temperature: float,
        top_p: float,
        top_k: int,
        repeat_penalty: float,
        stop: list,
        callback: Optional[Callable[[str], None]]
    ) -> str:
        """
        流式生成文本
        
        Args:
            prompt: 输入提示词
            max_tokens: 最大生成 token 数
            temperature: 温度参数
            top_p: Top-p 采样参数
            top_k: Top-k 采样参数
            repeat_penalty: 重复惩罚
            stop: 停止词列表
            callback: 流式输出回调函数
            
        Returns:
            完整的生成文本
        """
        generated_text = ""
        
        try:
            # 流式生成
            stream = self.model(
                prompt,
                max_tokens=max_tokens,
                temperature=temperature,
                top_p=top_p,
                top_k=top_k,
                repeat_penalty=repeat_penalty,
                stop=stop,
                stream=True,
                echo=False
            )
            
            # 逐个处理生成的 token
            for output in stream:
                token_text = output["choices"][0]["text"]
                generated_text += token_text
                
                # 调用回调函数
                if callback:
                    callback(token_text)
            
            logger.info(f"流式生成完成，输出长度: {len(generated_text)} 字符")
            
            return generated_text
            
        except Exception as e:
            error_msg = f"流式生成失败: {e}"
            logger.error(error_msg)
            raise RuntimeError(error_msg) from e
    
    def generate_script_prompt(
        self,
        theme: Optional[str] = None,
        outline: Optional[str] = None,
        num_scenes: int = 10,
        num_characters: int = 2,
        style: str = "现代都市"
    ) -> str:
        """
        构建剧本生成的 Prompt
        
        Args:
            theme: 主题关键词（可选）
            outline: 故事大纲（可选）
            num_scenes: 分镜数量（默认 10）
            num_characters: 角色数量（默认 2）
            style: 风格偏好（默认"现代都市"）
            
        Returns:
            完整的 Prompt 文本
            
        Raises:
            ValueError: 如果 theme 和 outline 都为空
        """
        if not theme and not outline:
            raise ValueError("主题和大纲至少需要提供一个")
        
        # 构建 Prompt 模板
        prompt_template = """你是一位专业的短剧编剧和视觉导演。请根据以下要求创作一个短剧剧本：

主题：{theme}
故事大纲：{outline}
分镜数量：{num_scenes}
角色数量：{num_characters}
风格：{style}

请按照以下格式输出：

【剧本】
（完整的剧本文本，包含对话、场景描述、角色动作）

【角色】
- 角色1：描述（年龄、性别、外貌特征、服装风格、性格特点）
- 角色2：描述（年龄、性别、外貌特征、服装风格、性格特点）

【分镜】
分镜1：
- 环境描述：[详细的时间和空间信息，例如：夜晚的城市街道，霓虹灯闪烁，细雨绵绵，远处传来车流声]
- 人物描述：[角色的具体位置、姿态、表情，例如：男主角站在路灯下，双手插兜，眉头紧锁，眼神忧郁地看向远方]
- 镜头描述：[拍摄角度和构图，例如：中景镜头，从侧后方45度角拍摄，前景虚化]
- 光线描述：[光线类型和氛围，例如：冷色调的霓虹灯光，背景温暖的路灯形成对比]
- 氛围描述：[情绪氛围和视觉效果，例如：孤独、沉思的氛围，雨滴在地面形成倒影]
- 出现角色：[角色1]
- 对话：xxx
- 说话人：角色1
- 情感：忧郁

分镜2：
- 环境描述：[详细场景]
- 人物描述：[详细人物状态]
- 镜头描述：[拍摄角度]
- 光线描述：[光线效果]
- 氛围描述：[情绪氛围]
- 出现角色：[角色1, 角色2]
- 对话：xxx
- 说话人：角色1
- 情感：温暖

...

重要要求：
1. 剧本要有完整的故事结构（开端、发展、高潮、结局）
2. 每个分镜的环境描述必须包含：时间、地点、天气、具体物品、背景元素
3. 每个分镜的人物描述必须包含：位置、姿势、表情、动作、服装细节
4. 每个分镜的镜头描述必须包含：拍摄角度（特写/中景/全景）、视角（正面/侧面/背面）
5. 每个分镜的光线描述必须包含：光线类型（自然光/人造光）、色温（暖色/冷色）、光源位置
6. 每个分镜的氛围描述必须包含：情绪基调、视觉效果、色彩倾向
7. 对话要自然流畅，符合角色性格
8. 每个分镜时长约 3-5 秒
9. 风格要符合“{style}”的特点
10. 严格按照上述格式输出，不要添加额外的说明文字
11. 所有描述都要详细具体，便于 AI 绘画准确理解场景
"""
        
        # 填充模板
        prompt = prompt_template.format(
            theme=theme or "未指定",
            outline=outline or "未指定",
            num_scenes=num_scenes,
            num_characters=num_characters,
            style=style
        )
        
        logger.debug(f"构建剧本生成 Prompt，长度: {len(prompt)} 字符")
        
        return prompt
    
    def unload_model(self):
        """
        卸载模型释放资源
        
        释放 GPU 和 CPU 资源，清理内存
        """
        try:
            if self.model is not None:
                logger.info("开始卸载 LLM 模型...")
                
                # 删除模型实例
                del self.model
                self.model = None
                self.is_loaded = False
                
                # 强制垃圾回收
                import gc
                gc.collect()
                
                # 清理 GPU 缓存（如果使用了 GPU）
                if self.n_gpu_layers > 0:
                    try:
                        import torch
                        if torch.cuda.is_available():
                            torch.cuda.empty_cache()
                            logger.info("GPU 缓存已清理")
                    except ImportError:
                        pass
                
                logger.info("LLM 模型卸载完成")
            else:
                logger.warning("模型未加载，无需卸载")
                
        except Exception as e:
            logger.error(f"卸载模型失败: {e}")
            raise
    
    def __del__(self):
        """
        析构函数，确保资源被释放
        """
        try:
            if self.is_loaded:
                self.unload_model()
        except Exception:
            pass
    
    def get_model_info(self) -> Dict:
        """
        获取模型信息
        
        Returns:
            包含模型配置信息的字典
        """
        return {
            "model_path": self.model_path,
            "n_gpu_layers": self.n_gpu_layers,
            "n_ctx": self.n_ctx,
            "n_threads": self.n_threads,
            "n_batch": self.n_batch,
            "is_loaded": self.is_loaded
        }


# 全局 LLM 服务实例（单例模式）
_llm_service_instance: Optional[LLMService] = None


def get_llm_service() -> LLMService:
    """
    获取全局 LLM 服务实例（单例模式）
    
    Returns:
        LLM 服务实例
        
    Raises:
        RuntimeError: 如果服务初始化失败
    """
    global _llm_service_instance
    
    if _llm_service_instance is None:
        try:
            # 从环境变量读取配置
            n_gpu_layers = int(os.getenv("LLM_N_GPU_LAYERS", "20"))
            n_ctx = int(os.getenv("LLM_N_CTX", "4096"))
            n_threads = int(os.getenv("LLM_N_THREADS", "8"))
            
            # 创建服务实例
            _llm_service_instance = LLMService(
                n_gpu_layers=n_gpu_layers,
                n_ctx=n_ctx,
                n_threads=n_threads
            )
            
            logger.info("全局 LLM 服务实例创建成功")
            
        except Exception as e:
            logger.error(f"创建全局 LLM 服务实例失败: {e}")
            raise RuntimeError(f"LLM 服务初始化失败: {e}") from e
    
    return _llm_service_instance


def cleanup_llm_service():
    """
    清理全局 LLM 服务实例
    
    用于应用关闭时释放资源
    """
    global _llm_service_instance
    
    if _llm_service_instance is not None:
        try:
            _llm_service_instance.unload_model()
            _llm_service_instance = None
            logger.info("全局 LLM 服务实例已清理")
        except Exception as e:
            logger.error(f"清理全局 LLM 服务实例失败: {e}")
