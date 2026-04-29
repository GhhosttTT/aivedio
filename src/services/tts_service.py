"""
TTS 服务（Text-to-Speech Service）

负责调用 MiMo-V2-TTS API 生成配音，
管理 API 配额，实现重试逻辑和错误处理
"""

import os
import time
from typing import Optional, List, Dict
from pathlib import Path

try:
    import httpx
    HTTPX_AVAILABLE = True
except ImportError:
    HTTPX_AVAILABLE = False
    httpx = None

from src.utils.logger import logger


class TTSError(Exception):
    """TTS 服务错误"""
    pass


class TTSQuotaError(TTSError):
    """TTS 配额不足错误"""
    pass


class TTSService:
    """TTS 服务（文本转语音）"""
    
    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        timeout: int = 30,
        max_retries: int = 3
    ):
        """
        初始化 TTS 服务
        
        Args:
            api_key: API 密钥（默认从环境变量读取）
            base_url: API 基础 URL（默认从环境变量读取）
            timeout: 请求超时时间（秒，默认 30）
            max_retries: 最大重试次数（默认 3）
        """
        if not HTTPX_AVAILABLE:
            raise RuntimeError(
                "httpx 未安装，请运行: pip install httpx"
            )
        
        # 从环境变量读取配置
        self.api_key = api_key or os.getenv("TTS_API_KEY")
        if not self.api_key:
            raise ValueError("TTS API 密钥未配置，请设置 TTS_API_KEY 环境变量")
        
        self.base_url = base_url or os.getenv(
            "TTS_BASE_URL",
            "https://mimo.xiaomi.com/api/v2/tts"
        )
        self.timeout = timeout
        self.max_retries = max_retries
        
        # 创建 HTTP 客户端
        self.client = httpx.Client(
            timeout=timeout,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json"
            }
        )
        
        logger.info(f"TTS 服务初始化完成: base_url={self.base_url}")
    
    def generate_speech(
        self,
        text: str,
        speaker: str = "default",
        emotion: str = "neutral",
        speed: float = 1.0,
        output_path: Optional[str] = None
    ) -> str:
        """
        生成语音（文本转语音）
        
        Args:
            text: 输入文本
            speaker: 说话人 ID（默认 "default"）
            emotion: 情感类型（默认 "neutral"）
            speed: 语速（默认 1.0，范围 0.5-2.0）
            output_path: 输出音频路径（可选）
            
        Returns:
            生成的音频文件路径
            
        Raises:
            TTSError: 如果生成失败
            TTSQuotaError: 如果配额不足
        """
        if not text or not text.strip():
            raise ValueError("输入文本不能为空")
        
        if not 0.5 <= speed <= 2.0:
            raise ValueError("语速必须在 0.5-2.0 之间")
        
        logger.info(
            f"开始生成语音: text_len={len(text)}, speaker={speaker}, "
            f"emotion={emotion}, speed={speed}"
        )
        
        # 生成语音（带重试）
        for attempt in range(self.max_retries):
            try:
                # 构建请求数据
                request_data = {
                    "text": text,
                    "speaker": speaker,
                    "emotion": emotion,
                    "speed": speed,
                    "format": "mp3"
                }
                
                logger.debug(f"发送 TTS 请求（第 {attempt + 1} 次尝试）")
                
                # 发送请求
                response = self.client.post(
                    f"{self.base_url}/generate",
                    json=request_data
                )
                
                # 检查响应状态
                if response.status_code == 429:
                    # 配额不足
                    raise TTSQuotaError("TTS API 配额不足，请稍后重试")
                
                response.raise_for_status()
                
                # 解析响应
                result = response.json()
                
                if result.get("status") != "success":
                    error_msg = result.get("message", "未知错误")
                    raise TTSError(f"TTS API 返回错误: {error_msg}")
                
                # 获取音频 URL
                audio_url = result.get("audio_url")
                if not audio_url:
                    raise TTSError("TTS API 未返回音频 URL")
                
                # 下载音频文件
                audio_path = self._download_audio(audio_url, output_path)
                
                logger.info(f"语音生成成功: {audio_path}")
                
                return audio_path
                
            except TTSQuotaError:
                # 配额不足，不重试
                raise
                
            except Exception as e:
                if attempt < self.max_retries - 1:
                    wait_time = 2 ** attempt  # 指数退避
                    logger.warning(
                        f"生成失败（第 {attempt + 1} 次尝试），"
                        f"{wait_time} 秒后重试: {e}"
                    )
                    time.sleep(wait_time)
                else:
                    error_msg = f"语音生成失败（已重试 {self.max_retries} 次）: {e}"
                    logger.error(error_msg)
                    raise TTSError(error_msg) from e
    
    def _download_audio(
        self,
        audio_url: str,
        output_path: Optional[str] = None
    ) -> str:
        """
        下载音频文件
        
        Args:
            audio_url: 音频 URL
            output_path: 输出路径（可选）
            
        Returns:
            下载的音频文件路径
        """
        try:
            logger.debug(f"开始下载音频: {audio_url}")
            
            # 下载音频
            response = self.client.get(audio_url)
            response.raise_for_status()
            
            # 确定输出路径
            if not output_path:
                output_dir = Path("./storage/temp")
                output_dir.mkdir(parents=True, exist_ok=True)
                output_path = str(
                    output_dir / f"audio_{int(time.time())}.mp3"
                )
            
            # 保存音频文件
            with open(output_path, "wb") as f:
                f.write(response.content)
            
            logger.debug(f"音频下载完成: {output_path}")
            
            return output_path
            
        except Exception as e:
            raise TTSError(f"下载音频失败: {e}") from e
    
    def list_speakers(self) -> List[Dict[str, str]]:
        """
        获取可用说话人列表
        
        Returns:
            说话人列表，每个元素包含 id、name、description
            
        Raises:
            TTSError: 如果获取失败
        """
        try:
            logger.debug("获取说话人列表")
            
            response = self.client.get(f"{self.base_url}/speakers")
            response.raise_for_status()
            
            result = response.json()
            
            if result.get("status") != "success":
                error_msg = result.get("message", "未知错误")
                raise TTSError(f"获取说话人列表失败: {error_msg}")
            
            speakers = result.get("speakers", [])
            
            logger.info(f"获取到 {len(speakers)} 个说话人")
            
            return speakers
            
        except Exception as e:
            error_msg = f"获取说话人列表失败: {e}"
            logger.error(error_msg)
            raise TTSError(error_msg) from e
    
    def check_quota(self) -> Dict[str, int]:
        """
        检查 API 配额
        
        Returns:
            配额信息字典，包含 total、used、remaining
            
        Raises:
            TTSError: 如果检查失败
        """
        try:
            logger.debug("检查 API 配额")
            
            response = self.client.get(f"{self.base_url}/quota")
            response.raise_for_status()
            
            result = response.json()
            
            if result.get("status") != "success":
                error_msg = result.get("message", "未知错误")
                raise TTSError(f"检查配额失败: {error_msg}")
            
            quota = result.get("quota", {})
            
            logger.info(
                f"API 配额: {quota.get('used', 0)}/{quota.get('total', 0)} "
                f"(剩余: {quota.get('remaining', 0)})"
            )
            
            return quota
            
        except Exception as e:
            error_msg = f"检查配额失败: {e}"
            logger.error(error_msg)
            raise TTSError(error_msg) from e
    
    def close(self):
        """
        关闭 HTTP 客户端
        """
        try:
            if self.client:
                self.client.close()
                logger.info("TTS 服务已关闭")
        except Exception as e:
            logger.error(f"关闭 TTS 服务失败: {e}")
    
    def __del__(self):
        """
        析构函数，确保资源被释放
        """
        try:
            self.close()
        except Exception:
            pass


# 全局 TTS 服务实例（单例模式）
_tts_service_instance: Optional[TTSService] = None


def get_tts_service() -> TTSService:
    """
    获取全局 TTS 服务实例（单例模式）
    
    Returns:
        TTS 服务实例
        
    Raises:
        TTSError: 如果服务初始化失败
    """
    global _tts_service_instance
    
    if _tts_service_instance is None:
        try:
            _tts_service_instance = TTSService()
            logger.info("全局 TTS 服务实例创建成功")
            
        except Exception as e:
            logger.error(f"创建全局 TTS 服务实例失败: {e}")
            raise TTSError(f"TTS 服务初始化失败: {e}") from e
    
    return _tts_service_instance


def cleanup_tts_service():
    """
    清理全局 TTS 服务实例
    
    用于应用关闭时释放资源
    """
    global _tts_service_instance
    
    if _tts_service_instance is not None:
        try:
            _tts_service_instance.close()
            _tts_service_instance = None
            logger.info("全局 TTS 服务实例已清理")
        except Exception as e:
            logger.error(f"清理全局 TTS 服务实例失败: {e}")
