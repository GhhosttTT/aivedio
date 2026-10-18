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
    COMFYUI_WORKFLOW_PATH: str = "./configs/comfyui_workflow_juggernaut.json"
    COMFYUI_REFERENCE_WORKFLOW_PATH: str = "./configs/comfyui_workflow_ipadapter_sdxl.json"
    COMFYUI_MULTI_REFERENCE_WORKFLOW_PATH: str = ""
    COMFYUI_VIDEO_WORKFLOW_PATH: str = ""
    COMFYUI_VIDEO_OUTPUT_NODE: str = ""
    COMFYUI_PRODUCTION_PROFILE_PATH: str = "./configs/production_workflow_profile.json"
    COMFYUI_TIMEOUT: int = 900
    GENERATION_WIDTH: int = 768
    GENERATION_HEIGHT: int = 1344
    GENERATION_STEPS: int = 40
    GENERATION_CFG: float = 6.0
    GENERATION_STEP_VARIATION: int = 0  # 新增：Steps变化量，0表示固定
    GENERATION_CFG_VARIATION: float = 0.0  # 新增：CFG变化量，0表示固定
    GENERATION_IMAGE_CANDIDATES: int = 5
    GENERATION_IMAGE_REFINEMENT_PASSES: int = 2
    GENERATION_MAX_IMAGE_CANDIDATES: int = 12
    GENERATION_MIN_QUALITY_PASSES: int = 2
    GENERATION_REPAIR_IMAGE_CANDIDATE_MULTIPLIER: float = 1.5
    GENERATION_REPAIR_EXTRA_REFINEMENT_PASSES: int = 1
    GENERATION_IMAGE_MIN_SCORE: float = 4.0
    GENERATION_IMAGE_IDENTITY_MIN_SCORE: float = 4.0
    GENERATION_CHARACTER_DISTINCTIVENESS_MIN_SCORE: float = 4.0
    GENERATION_IMAGE_PLATFORM_MIN_SCORE: float = 4.1
    GENERATION_IMAGE_AESTHETIC_FEATURE_MIN_SCORE: float = 4.0
    GENERATION_TURNAROUND_FEATURE_MIN_SCORE: float = 4.0
    GENERATION_REQUIRE_IMAGE_REVIEW: bool = True
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
    LOCAL_REVIEW_PROBE_TIMEOUT: float = 2.0

    # SVD 配置
    SVD_MODEL_PATH: str = "./models/stable-video-diffusion-img2vid-xt"
    SVD_NUM_FRAMES: int = 25
    SVD_FPS: int = 8
    GENERATION_VIDEO_CANDIDATES: int = 4
    GENERATION_VIDEO_REFINEMENT_PASSES: int = 2
    GENERATION_MAX_VIDEO_CANDIDATES: int = 8
    GENERATION_REPAIR_VIDEO_CANDIDATE_MULTIPLIER: float = 1.5
    GENERATION_VIDEO_MIN_SCORE: float = 4.0
    GENERATION_VIDEO_IDENTITY_MIN_SCORE: float = 4.0
    GENERATION_VIDEO_TEMPORAL_MIN_SCORE: float = 4.0
    GENERATION_VIDEO_CHARACTER_DISTINCTIVENESS_MIN_SCORE: float = 4.0
    GENERATION_VIDEO_PERFORMANCE_MIN_SCORE: float = 4.0
    GENERATION_VIDEO_PLATFORM_MIN_SCORE: float = 4.1
    GENERATION_VIDEO_TECHNICAL_MIN_SCORE: float = 3.0
    # When a locked source/keyframe is available, reject obvious opening-frame drift.
    GENERATION_VIDEO_START_FRAME_REFERENCE_MIN_SCORE: float = 2.5
    GENERATION_VIDEO_AESTHETIC_FEATURE_MIN_SCORE: float = 4.0
    GENERATION_REQUIRE_VIDEO_REVIEW: bool = True
    GENERATION_VIDEO_TARGET_SECONDS: float = 3.6
    GENERATION_VIDEO_MAX_SECONDS: float = 6.0
    GENERATION_VIDEO_MODEL_FPS: int = 8
    GENERATION_VIDEO_MAX_FRAMES: int = 40
    GENERATION_VIDEO_MAX_FREEZE_SECONDS: float = 0.2
    GENERATION_VIDEO_MAX_STATIC_RUN_SECONDS: float = 1.8
    GENERATION_VIDEO_MAX_BLACK_SECONDS: float = 0.2
    # Mobile short-drama output should fill the target canvas; ``contain`` is
    # available for workflows that explicitly prefer letterboxing.
    GENERATION_VIDEO_FRAME_FIT_MODE: str = "cover"
    # Hard final-publish floors for obvious temporal instability. These are
    # deliberately stricter than the weighted technical score: a high average
    # must not hide visible flicker or cadence breaks in a finished shot.
    GENERATION_VIDEO_MAX_BRIGHTNESS_STEP_P95: float = 36.0
    GENERATION_VIDEO_MAX_MOTION_JITTER_RATIO: float = 1.5
    GENERATION_VIDEO_OUTPUT_FPS: int = 24
    GENERATION_VIDEO_POSTPROCESS: bool = True
    GENERATION_ALLOW_SVD_PRODUCTION_FALLBACK: bool = False
    GENERATION_VIDEO_END_FRAME_ENABLED: bool = True
    GENERATION_PREFER_NATIVE_VIDEO_AUDIO: bool = False
    SUBTITLE_MAX_READING_UNITS_PER_SECOND: float = 18.0

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
    SUBTITLE_RENDER_FONT_SIZE: int = 38
    SUBTITLE_RENDER_MARGIN_V: int = 64
    SUBTITLE_RENDER_OUTLINE: int = 3
    SUBTITLE_RENDER_SHADOW: int = 1
    SUBTITLE_RENDER_BOLD: bool = True
    SUBTITLE_RENDER_TIMEOUT_SECONDS: int = 7200
    MODERATION_BACKEND: str = "rules"
    LOCALIZATION_CONCURRENCY: int = 1

    # AI 生成短剧质量配置
    GENERATION_PROVIDER: str = "local_comfyui"
    GENERATION_PRIMARY_PROVIDER: str = "jimeng_api"
    GENERATION_QUALITY_PROFILE: str = "seed_dance_reference"
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
    HTTP_VIDEO_RESULT_ENDPOINT: str = ""
    HTTP_VIDEO_TIMEOUT_SECONDS: int = 1800
    HTTP_VIDEO_POLL_INTERVAL_SECONDS: float = 5.0
    HTTP_VIDEO_MAX_POLLS: int = 240
    HTTP_VIDEO_MAX_RETRIES: int = 2
    HTTP_VIDEO_RETRY_BACKOFF_SECONDS: float = 1.0
    HTTP_VIDEO_AUTH_HEADER: str = "Authorization"
    HTTP_VIDEO_AUTH_SCHEME: str = "Bearer"
    HTTP_VIDEO_NATIVE_AUDIO: bool = False
    HTTP_VIDEO_MULTI_SHOT: bool = False
    HTTP_VIDEO_MAX_REFERENCE_IMAGES: int = 9
    HTTP_VIDEO_MAX_REFERENCE_VIDEOS: int = 3
    HTTP_VIDEO_MAX_REFERENCE_AUDIOS: int = 3
    SEEDANCE_ENDPOINT: str = ""
    SEEDANCE_API_KEY: str = ""
    SEEDANCE_STATUS_ENDPOINT: str = ""
    SEEDANCE_RESULT_ENDPOINT: str = ""
    SEEDANCE_MODEL: str = "doubao-seedance-2-5-260628"
    # ``legacy`` keeps compatibility with generic gateways; ``ark_v3`` emits
    # Volcano Ark's native content[] request contract.
    SEEDANCE_API_FORMAT: str = "legacy"
    SEEDANCE_MEDIA_URL_TEMPLATE: str = ""
    SEEDANCE_REQUEST_MODE: str = "reference_to_video"
    # Production default; Draft mode still forces the native 480p preview.
    SEEDANCE_RESOLUTION: str = "1080p"
    SEEDANCE_TIMEOUT_SECONDS: int = 1800
    SEEDANCE_POLL_INTERVAL_SECONDS: float = 5.0
    SEEDANCE_MAX_POLLS: int = 240
    SEEDANCE_CALLBACK_URL: str = ""
    SEEDANCE_CALLBACK_SECRET: str = ""
    # Keep the public callback receiver authenticated by default. This is only
    # useful for local gateways that cannot attach a callback header.
    SEEDANCE_CALLBACK_ALLOW_UNSIGNED: bool = False
    SEEDANCE_MAX_RETRIES: int = 2
    SEEDANCE_RETRY_BACKOFF_SECONDS: float = 1.0
    SEEDANCE_AUTH_HEADER: str = "Authorization"
    SEEDANCE_AUTH_SCHEME: str = "Bearer"
    SEEDANCE_BITRATE_MODE: str = "high"
    SEEDANCE_CODEC: str = "H264"
    SEEDANCE_INCLUDE_EXPERIMENTAL_FIELDS: bool = False
    SEEDANCE_NATIVE_AUDIO: bool = True
    SEEDANCE_MULTI_SHOT: bool = True
    # False keeps each atomic scene at its planned duration while still
    # passing bounded previous/current/next continuity context. Enable only
    # when a caller intentionally owns a full 30-second sequence output.
    SEEDANCE_SEQUENCE_LEVEL_MULTI_SHOT: bool = False
    SEEDANCE_RETURN_LAST_FRAME: bool = True
    SEEDANCE_CAMERA_FIXED: bool = False
    SEEDANCE_WATERMARK: bool = False
    SEEDANCE_OUTPUT_FORMAT: str = "mp4"
    SEEDANCE_VALIDATE_OUTPUT: bool = True
    SEEDANCE_DRAFT: bool = False
    SEEDANCE_MULTI_SHOT_DURATION_SECONDS: int = 30
    # Seedance 2.0 defaults; raise to 30/10/10 only for a confirmed 2.5 gateway.
    SEEDANCE_MAX_REFERENCE_IMAGES: int = 9
    SEEDANCE_MAX_REFERENCE_VIDEOS: int = 3
    SEEDANCE_MAX_REFERENCE_AUDIOS: int = 3

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
