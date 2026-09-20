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

    model_config = ConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # 数据库配置
    DATABASE_URL: str = "sqlite:///./short_drama.db"

    # Redis 配置
    REDIS_URL: str = "redis://localhost:6379/0"

    # Celery 配置
    CELERY_BROKER_URL: str = "redis://localhost:6379/1"
    CELERY_RESULT_BACKEND: str = "redis://localhost:6379/2"
    CELERY_WORKER_CONCURRENCY: int = 1

    # LLM 配置
    LLM_MODEL_PATH: str = "./models/qwen2.5-14b-instruct-q4_k_m.gguf"
    LLM_N_GPU_LAYERS: int = 20
    LLM_N_CTX: int = 4096
    LLM_N_THREADS: int = 8

    # ComfyUI 配置
    COMFYUI_BASE_URL: str = "http://127.0.0.1:8188"
    COMFYUI_WORKFLOW_PATH: str = "./configs/comfyui_workflow.json"
    COMFYUI_REFERENCE_WORKFLOW_PATH: str = ""
    COMFYUI_VIDEO_WORKFLOW_PATH: str = ""
    COMFYUI_PRODUCTION_PROFILE_PATH: str = "./configs/production_workflow_profile.json"
    COMFYUI_TIMEOUT: int = 900
    GENERATION_WIDTH: int = 1344
    GENERATION_HEIGHT: int = 768
    GENERATION_STEPS: int = 28
    GENERATION_CFG: float = 6.0
    GENERATION_STEP_VARIATION: int = 0  # 新增：Steps变化量，0表示固定
    GENERATION_CFG_VARIATION: float = 0.0  # 新增：CFG变化量，0表示固定
    GENERATION_IMAGE_CANDIDATES: int = 3
    GENERATION_IMAGE_REFINEMENT_PASSES: int = 1
    GENERATION_IMAGE_MIN_SCORE: float = 4.0
    GENERATION_IMAGE_IDENTITY_MIN_SCORE: float = 4.0
    GENERATION_IMAGE_PLATFORM_MIN_SCORE: float = 4.1
    GENERATION_IMAGE_AESTHETIC_FEATURE_MIN_SCORE: float = 4.0
    GENERATION_TURNAROUND_FEATURE_MIN_SCORE: float = 4.0
    GENERATION_REQUIRE_IMAGE_REVIEW: bool = False
    GENERATION_IMAGE_POSTPROCESS_COMMAND: str = ""
    GENERATION_REQUIRE_IMAGE_POSTPROCESS: bool = False
    GENERATION_IMAGE_POSTPROCESS_TIMEOUT_SECONDS: int = 1800
    GENERATION_BLOCK_COMPLEX_SHOTS: bool = False
    GENERATION_QUALITY_PROMPT_APPEND: str = "clean cinematic composition, coherent anatomy, readable main action, balanced lighting, polished short-drama keyframe"
    GENERATION_QUALITY_NEGATIVE_APPEND: str = "amateur snapshot, dull composition, muddy lighting, deformed face, deformed hands, broken fingers, extra people, random text, logo, watermark, bad crop, messy background"
    GENERATION_ENABLE_PROMPT_OPTIMIZATION: bool = True
    GENERATION_ENABLE_PARAMETER_OPTIMIZATION: bool = True

    # IP-Adapter FaceID配置
    FACEID_WEIGHT: float = 0.85
    FACEID_START_AT: float = 0.0
    FACEID_END_AT: float = 1.0

    # FaceDetailer配置
    FACE_DETAILER_ENABLED: bool = False
    FACE_DETAILER_TARGET: str = "face"
    FACE_DETAILER_GUIDE_SIZE: int = 768
    FACE_DETAILER_MAX_SIZE: int = 1024
    FACE_DETAILER_STEPS: int = 22
    FACE_DETAILER_CFG: float = 5.0
    FACE_DETAILER_SAMPLER: str = "dpmpp_2m_sde"
    FACE_DETAILER_SCHEDULER: str = "karras"
    FACE_DETAILER_DENOISE: float = 0.24
    FACE_DETAILER_FACEID_WEIGHT: float = 0.35
    FACE_DETAILER_FACEID_END_AT: float = 0.65

    # 提示词后缀配置
    POSITIVE_PROMPT_SUFFIX: str = ""
    NEGATIVE_PROMPT_SUFFIX: str = ""

    LOCAL_REVIEW_BACKEND: str = "llama_cpp"
    LOCAL_REVIEW_BASE_URL: str = "http://127.0.0.1:8080/v1"
    LOCAL_REVIEW_MODEL: str = "local-vlm"
    LOCAL_REVIEW_TIMEOUT: int = 300

    # SVD 配置
    SVD_MODEL_PATH: str = "./models/stable-video-diffusion-img2vid-xt"
    SVD_NUM_FRAMES: int = 25
    SVD_FPS: int = 8
    GENERATION_VIDEO_CANDIDATES: int = 2
    GENERATION_VIDEO_REFINEMENT_PASSES: int = 1
    GENERATION_VIDEO_MIN_SCORE: float = 4.0
    GENERATION_VIDEO_IDENTITY_MIN_SCORE: float = 4.0
    GENERATION_VIDEO_TEMPORAL_MIN_SCORE: float = 4.0
    GENERATION_VIDEO_PLATFORM_MIN_SCORE: float = 4.1
    GENERATION_VIDEO_AESTHETIC_FEATURE_MIN_SCORE: float = 4.0
    GENERATION_REQUIRE_VIDEO_REVIEW: bool = False
    GENERATION_VIDEO_TARGET_SECONDS: float = 3.6
    GENERATION_VIDEO_MAX_SECONDS: float = 6.0
    GENERATION_VIDEO_MODEL_FPS: int = 8
    GENERATION_VIDEO_MAX_FRAMES: int = 40
    GENERATION_VIDEO_OUTPUT_FPS: int = 24
    GENERATION_VIDEO_POSTPROCESS: bool = True
    GENERATION_ALLOW_SVD_PRODUCTION_FALLBACK: bool = False
    GENERATION_VIDEO_END_FRAME_ENABLED: bool = True

    # TTS 配置
    TTS_API_KEY: str = ""
    TTS_BASE_URL: str = "https://mimo.xiaomi.com/api/v2/tts"

    # 源片出海译制配置
    LOCALIZATION_TARGET_LANGUAGES: str = "en,es,pt,ar,id,th,vi,ja,ko"
    SUBTITLE_REMOVAL_BACKEND: str = "manual_mask"
    OCCLUSION_REMOVAL_BACKEND: str = "detect_only"
    OCCLUSION_MASK_DETECTOR_COMMAND: str = ""
    OCCLUSION_AUTO_MASK_MIN_CONFIDENCE: float = 0.65
    OCCLUSION_MIN_QUALITY_SCORE: float = 0.92
    OCCLUSION_REMOVAL_TIMEOUT_SECONDS: int = 7200
    AUTO_VIDEO_INPAINT_COMMAND: str = ""
    PROPINTER_COMMAND: str = ""
    VSR_COMMAND: str = ""
    ASR_BACKEND: str = "faster_whisper"
    ASR_MODEL_PATH: str = "./models/faster-whisper-large-v3"
    ASR_MODEL_SIZE: str = "small"
    ASR_COMMAND: str = ""
    ASR_DEVICE: str = "cuda"
    ASR_COMPUTE_TYPE: str = "float16"
    ASR_LANGUAGE: str = "zh"
    ASR_TIMEOUT_SECONDS: int = 7200
    OCR_BACKEND: str = "disabled"
    OCR_COMMAND: str = ""
    OCR_MIN_CONFIDENCE: float = 0.55
    OCR_TIMEOUT_SECONDS: int = 7200
    OCR_ASR_MAX_GAP_SECONDS: float = 0.35
    TRANSLATION_BACKEND: str = "local_llm"
    TRANSLATION_COMMAND: str = ""
    TRANSLATION_TIMEOUT_SECONDS: int = 7200
    TRANSLATION_MAX_SEGMENTS_PER_BATCH: int = 30
    DEEPSEEK_API_KEY: str = ""
    DEEPSEEK_BASE_URL: str = "https://api.deepseek.com"
    DEEPSEEK_MODEL: str = "deepseek-chat"
    DEEPSEEK_TIMEOUT_SECONDS: int = 120
    SUBTITLE_RENDER_FONT: str = "Arial"
    SUBTITLE_RENDER_FONT_SIZE: int = 26
    SUBTITLE_RENDER_MARGIN_V: int = 48
    SUBTITLE_RENDER_TIMEOUT_SECONDS: int = 7200
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
    HTTP_VIDEO_ENDPOINT: str = ""
    HTTP_VIDEO_API_KEY: str = ""
    HTTP_VIDEO_STATUS_ENDPOINT: str = ""
    HTTP_VIDEO_TIMEOUT_SECONDS: int = 1800
    HTTP_VIDEO_POLL_INTERVAL_SECONDS: float = 5.0
    HTTP_VIDEO_MAX_POLLS: int = 240
    HTTP_VIDEO_AUTH_HEADER: str = "Authorization"
    HTTP_VIDEO_AUTH_SCHEME: str = "Bearer"

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
