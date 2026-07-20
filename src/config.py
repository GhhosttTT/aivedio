"""
应用配置模块

从环境变量加载配置
"""
import os
from typing import Optional

from pydantic_settings import BaseSettings
from pydantic import ConfigDict


class Settings(BaseSettings):
    """应用配置"""
    
    model_config = ConfigDict(env_file=".env", env_file_encoding="utf-8")
    
    # 数据库配置
    DATABASE_URL: str = "sqlite:///./short_drama.db"
    
    # Redis 配置
    REDIS_URL: str = "redis://localhost:6379/0"
    
    # Celery 配置
    CELERY_BROKER_URL: str = "redis://localhost:6379/1"
    CELERY_RESULT_BACKEND: str = "redis://localhost:6379/2"
    CELERY_WORKER_CONCURRENCY: int = 2
    
    # LLM 配置
    LLM_MODEL_PATH: str = "./models/qwen2.5-14b-instruct-q4_k_m.gguf"
    LLM_N_GPU_LAYERS: int = 20
    LLM_N_CTX: int = 4096
    LLM_N_THREADS: int = 8
    
    # ComfyUI 配置
    COMFYUI_BASE_URL: str = "http://127.0.0.1:8188"
    COMFYUI_WORKFLOW_PATH: str = "./configs/comfyui_workflow.json"
    
    # SVD 配置
    SVD_MODEL_PATH: str = "./models/stable-video-diffusion-img2vid-xt"
    SVD_NUM_FRAMES: int = 16
    SVD_FPS: int = 8
    
    # TTS 配置
    TTS_API_KEY: str = ""
    TTS_BASE_URL: str = "https://mimo.xiaomi.com/api/v2/tts"

    # 源片出海译制配置
    LOCALIZATION_TARGET_LANGUAGES: str = "en,es,pt,ar,id,th,vi,ja,ko"
    SUBTITLE_REMOVAL_BACKEND: str = "manual_mask"
    OCCLUSION_REMOVAL_BACKEND: str = "auto_video_inpaint"
    OCCLUSION_MIN_QUALITY_SCORE: float = 0.92
    OCCLUSION_REMOVAL_TIMEOUT_SECONDS: int = 7200
    AUTO_VIDEO_INPAINT_COMMAND: str = ""
    PROPINTER_COMMAND: str = ""
    VSR_COMMAND: str = ""
    ASR_BACKEND: str = "faster_whisper"
    ASR_MODEL_PATH: str = "./models/faster-whisper-large-v3"
    TRANSLATION_BACKEND: str = "local_llm"
    MODERATION_BACKEND: str = "rules"
    LOCALIZATION_CONCURRENCY: int = 1

    # AI 生成短剧质量配置
    GENERATION_PROVIDER: str = "local_comfyui"
    GENERATION_PRIMARY_PROVIDER: str = "jimeng_api"
    GENERATION_QUALITY_PROFILE: str = "hongguo_reference"
    COMFYUI_DEFAULT_WORKFLOW_TYPE: str = "juggernaut"
    JIMENG_ENDPOINT: str = ""
    JIMENG_API_KEY: str = ""
    KLING_ENDPOINT: str = ""
    KLING_API_KEY: str = ""
    HAILUO_ENDPOINT: str = ""
    HAILUO_API_KEY: str = ""
    
    # 文件存储配置
    STORAGE_PATH: str = "./storage"
    MAX_STORAGE_SIZE_GB: int = 500
    
    # GPU 配置
    GPU_MEMORY_FRACTION: float = 0.95
    ENABLE_GPU_CACHE_CLEAR: bool = True
    
    # API 配置
    API_HOST: str = "0.0.0.0"
    API_PORT: int = 8000
    API_RELOAD: bool = False
    CORS_ORIGINS: str = "*"
    
    # JWT 配置
    JWT_SECRET_KEY: str = "your-secret-key-change-this-in-production"
    JWT_ALGORITHM: str = "HS256"
    JWT_EXPIRATION_HOURS: int = 24
    JWT_REFRESH_EXPIRATION_DAYS: int = 7
    
    # 速率限制配置
    API_RATE_LIMIT: str = "10/minute"
    
    # 日志配置
    LOG_LEVEL: str = "INFO"
    LOG_FILE: str = "./logs/app.log"


# 全局配置实例
settings = Settings()
