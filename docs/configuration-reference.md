# 配置项参考

本文件由 `scripts/generate_config_reference.py` 从 `src/config.py` 自动生成。
完整默认值以 `Settings` 模型为准；`.env.example` 只列出常用项。

加载优先级：进程环境变量 > `.env` > 代码默认值。

另有少量由脚本或适配器直接读取、不属于 `Settings` 的变量（如 `DEFAULT_ADMIN_*`、`ENCRYPTION_KEY`），见 `.env.example`。

共 273 项，按变量前缀分组。

## 目录

- [API](#api)（4 项）
- [ASR](#asr)（8 项）
- [AUTO](#auto)（1 项）
- [CELERY](#celery)（3 项）
- [COMFYUI](#comfyui)（9 项）
- [CORS](#cors)（1 项）
- [DATABASE](#database)（1 项）
- [DEEPSEEK](#deepseek)（6 项）
- [ENABLE](#enable)（1 项）
- [ENVIRONMENT](#environment)（1 项）
- [FACE](#face)（11 项）
- [FACEID](#faceid)（3 项）
- [GENERATION_ALLOW](#generation_allow)（1 项）
- [GENERATION_BLOCK](#generation_block)（1 项）
- [GENERATION_CFG](#generation_cfg)（2 项）
- [GENERATION_CHARACTER](#generation_character)（4 项）
- [GENERATION_ENABLE](#generation_enable)（2 项）
- [GENERATION_EPISODE](#generation_episode)（10 项）
- [GENERATION_HEIGHT](#generation_height)（1 项）
- [GENERATION_HYBRID](#generation_hybrid)（1 项）
- [GENERATION_IMAGE](#generation_image)（8 项）
- [GENERATION_MAX](#generation_max)（2 项）
- [GENERATION_MIN](#generation_min)（1 项）
- [GENERATION_PREFER](#generation_prefer)（1 项）
- [GENERATION_PRIMARY](#generation_primary)（1 项）
- [GENERATION_PROVIDER](#generation_provider)（1 项）
- [GENERATION_QUALITY](#generation_quality)（3 项）
- [GENERATION_REPAIR](#generation_repair)（3 项）
- [GENERATION_REQUIRE](#generation_require)（3 项）
- [GENERATION_RHYTHM](#generation_rhythm)（5 项）
- [GENERATION_SEED](#generation_seed)（1 项）
- [GENERATION_STEP](#generation_step)（1 项）
- [GENERATION_STEPS](#generation_steps)（1 项）
- [GENERATION_TURNAROUND](#generation_turnaround)（1 项）
- [GENERATION_VIDEO](#generation_video)（52 项）
- [GENERATION_WIDTH](#generation_width)（1 项）
- [GPU](#gpu)（1 项）
- [HAILUO](#hailuo)（2 项）
- [HTTP](#http)（17 项）
- [JIMENG](#jimeng)（2 项）
- [JWT](#jwt)（4 项）
- [KLING](#kling)（2 项）
- [LLM](#llm)（4 项）
- [LOCAL](#local)（5 项）
- [LOCALIZATION](#localization)（3 项）
- [LOG](#log)（2 项）
- [MAX](#max)（1 项）
- [MODERATION](#moderation)（1 项）
- [NEGATIVE](#negative)（1 项）
- [OCCLUSION](#occlusion)（5 项）
- [OCR](#ocr)（5 项）
- [POSITIVE](#positive)（1 项）
- [PROPINTER](#propinter)（1 项）
- [READINESS](#readiness)（1 项）
- [REDIS](#redis)（1 项）
- [SEEDANCE](#seedance)（36 项）
- [STORAGE](#storage)（1 项）
- [SUBTITLE](#subtitle)（9 项）
- [SVD](#svd)（3 项）
- [TRANSLATION](#translation)（5 项）
- [TRUST](#trust)（1 项）
- [TTS](#tts)（2 项）
- [VSR](#vsr)（1 项）

## API

| 变量 | 类型 | 默认值 |
| --- | --- | --- |
| `API_HOST` | `str` | `0.0.0.0` |
| `API_PORT` | `int` | `8000` |
| `API_RATE_LIMIT` | `str` | `60/minute` |
| `API_RELOAD` | `bool` | `False` |

## ASR

| 变量 | 类型 | 默认值 |
| --- | --- | --- |
| `ASR_BACKEND` | `str` | `faster_whisper` |
| `ASR_COMMAND` | `str` | `""` |
| `ASR_COMPUTE_TYPE` | `str` | `float16` |
| `ASR_DEVICE` | `str` | `cuda` |
| `ASR_LANGUAGE` | `str` | `zh` |
| `ASR_MODEL_PATH` | `str` | `./models/faster-whisper-large-v3` |
| `ASR_MODEL_SIZE` | `str` | `small` |
| `ASR_TIMEOUT_SECONDS` | `int` | `7200` |

## AUTO

| 变量 | 类型 | 默认值 |
| --- | --- | --- |
| `AUTO_VIDEO_INPAINT_COMMAND` | `str` | `""` |

## CELERY

| 变量 | 类型 | 默认值 |
| --- | --- | --- |
| `CELERY_BROKER_URL` | `str` | `redis://localhost:6379/1` |
| `CELERY_RESULT_BACKEND` | `str` | `redis://localhost:6379/2` |
| `CELERY_WORKER_CONCURRENCY` | `int` | `1` |

## COMFYUI

| 变量 | 类型 | 默认值 |
| --- | --- | --- |
| `COMFYUI_BASE_URL` | `str` | `http://127.0.0.1:8188` |
| `COMFYUI_DEFAULT_WORKFLOW_TYPE` | `str` | `juggernaut` |
| `COMFYUI_MULTI_REFERENCE_WORKFLOW_PATH` | `str` | `""` |
| `COMFYUI_PRODUCTION_PROFILE_PATH` | `str` | `./configs/production_workflow_profile.json` |
| `COMFYUI_REFERENCE_WORKFLOW_PATH` | `str` | `./configs/comfyui_workflow_ipadapter_sdxl.json` |
| `COMFYUI_TIMEOUT` | `int` | `900` |
| `COMFYUI_VIDEO_OUTPUT_NODE` | `str` | `""` |
| `COMFYUI_VIDEO_WORKFLOW_PATH` | `str` | `""` |
| `COMFYUI_WORKFLOW_PATH` | `str` | `./configs/comfyui_workflow_juggernaut.json` |

## CORS

| 变量 | 类型 | 默认值 |
| --- | --- | --- |
| `CORS_ORIGINS` | `str` | `*` |

## DATABASE

| 变量 | 类型 | 默认值 |
| --- | --- | --- |
| `DATABASE_URL` | `str` | `sqlite:///./short_drama.db` |

## DEEPSEEK

| 变量 | 类型 | 默认值 |
| --- | --- | --- |
| `DEEPSEEK_API_KEY` | `str` | 通过环境变量设置，勿提交 |
| `DEEPSEEK_BASE_URL` | `str` | `https://api.deepseek.com` |
| `DEEPSEEK_MAX_RETRIES` | `int` | `2` |
| `DEEPSEEK_MODEL` | `str` | `deepseek-chat` |
| `DEEPSEEK_RETRY_BACKOFF_SECONDS` | `float` | `1.0` |
| `DEEPSEEK_TIMEOUT_SECONDS` | `int` | `120` |

## ENABLE

| 变量 | 类型 | 默认值 |
| --- | --- | --- |
| `ENABLE_GPU_CACHE_CLEAR` | `bool` | `True` |

## ENVIRONMENT

| 变量 | 类型 | 默认值 |
| --- | --- | --- |
| `ENVIRONMENT` | `str` | `development` |

## FACE

| 变量 | 类型 | 默认值 |
| --- | --- | --- |
| `FACE_DETAILER_CFG` | `float` | `5.0`（预留，当前代码未读取） |
| `FACE_DETAILER_DENOISE` | `float` | `0.24`（预留，当前代码未读取） |
| `FACE_DETAILER_ENABLED` | `bool` | `False`（预留，当前代码未读取） |
| `FACE_DETAILER_FACEID_END_AT` | `float` | `0.65`（预留，当前代码未读取） |
| `FACE_DETAILER_FACEID_WEIGHT` | `float` | `0.35`（预留，当前代码未读取） |
| `FACE_DETAILER_GUIDE_SIZE` | `int` | `768`（预留，当前代码未读取） |
| `FACE_DETAILER_MAX_SIZE` | `int` | `1024`（预留，当前代码未读取） |
| `FACE_DETAILER_SAMPLER` | `str` | `dpmpp_2m_sde`（预留，当前代码未读取） |
| `FACE_DETAILER_SCHEDULER` | `str` | `karras`（预留，当前代码未读取） |
| `FACE_DETAILER_STEPS` | `int` | `22`（预留，当前代码未读取） |
| `FACE_DETAILER_TARGET` | `str` | `face`（预留，当前代码未读取） |

## FACEID

| 变量 | 类型 | 默认值 |
| --- | --- | --- |
| `FACEID_END_AT` | `float` | `1.0`（预留，当前代码未读取） |
| `FACEID_START_AT` | `float` | `0.0`（预留，当前代码未读取） |
| `FACEID_WEIGHT` | `float` | `0.85`（预留，当前代码未读取） |

## GENERATION_ALLOW

| 变量 | 类型 | 默认值 |
| --- | --- | --- |
| `GENERATION_ALLOW_SVD_PRODUCTION_FALLBACK` | `bool` | `False` |

## GENERATION_BLOCK

| 变量 | 类型 | 默认值 |
| --- | --- | --- |
| `GENERATION_BLOCK_COMPLEX_SHOTS` | `bool` | `False` |

## GENERATION_CFG

| 变量 | 类型 | 默认值 |
| --- | --- | --- |
| `GENERATION_CFG` | `float` | `6.0` |
| `GENERATION_CFG_VARIATION` | `float` | `0.0` |

## GENERATION_CHARACTER

| 变量 | 类型 | 默认值 |
| --- | --- | --- |
| `GENERATION_CHARACTER_DISTINCTIVENESS_MIN_SCORE` | `float` | `4.0` |
| `GENERATION_CHARACTER_IDENTITY_MAX_SCORE_SPREAD` | `float` | `1.5` |
| `GENERATION_CHARACTER_IDENTITY_MIN_OBSERVATIONS` | `int` | `2` |
| `GENERATION_CHARACTER_IDENTITY_MIN_SCORE` | `float` | `4.0` |

## GENERATION_ENABLE

| 变量 | 类型 | 默认值 |
| --- | --- | --- |
| `GENERATION_ENABLE_PARAMETER_OPTIMIZATION` | `bool` | `True` |
| `GENERATION_ENABLE_PROMPT_OPTIMIZATION` | `bool` | `True` |

## GENERATION_EPISODE

| 变量 | 类型 | 默认值 |
| --- | --- | --- |
| `GENERATION_EPISODE_STYLE_ASPECT_RATIO_BLOCKER` | `float` | `0.16` |
| `GENERATION_EPISODE_STYLE_ASPECT_RATIO_WARNING` | `float` | `0.08` |
| `GENERATION_EPISODE_STYLE_BRIGHTNESS_BLOCKER` | `float` | `45.0` |
| `GENERATION_EPISODE_STYLE_BRIGHTNESS_WARNING` | `float` | `24.0` |
| `GENERATION_EPISODE_STYLE_CONTRAST_BLOCKER` | `float` | `52.0` |
| `GENERATION_EPISODE_STYLE_CONTRAST_WARNING` | `float` | `28.0` |
| `GENERATION_EPISODE_STYLE_SATURATION_BLOCKER` | `float` | `0.24` |
| `GENERATION_EPISODE_STYLE_SATURATION_WARNING` | `float` | `0.14` |
| `GENERATION_EPISODE_STYLE_SHARPNESS_RATIO_BLOCKER` | `float` | `3.5` |
| `GENERATION_EPISODE_STYLE_SHARPNESS_RATIO_WARNING` | `float` | `2.2` |

## GENERATION_HEIGHT

| 变量 | 类型 | 默认值 |
| --- | --- | --- |
| `GENERATION_HEIGHT` | `int` | `1344` |

## GENERATION_HYBRID

| 变量 | 类型 | 默认值 |
| --- | --- | --- |
| `GENERATION_HYBRID_LOCAL_SHOT_ROLES` | `str` | `establishing` |

## GENERATION_IMAGE

| 变量 | 类型 | 默认值 |
| --- | --- | --- |
| `GENERATION_IMAGE_AESTHETIC_FEATURE_MIN_SCORE` | `float` | `4.0` |
| `GENERATION_IMAGE_CANDIDATES` | `int` | `5` |
| `GENERATION_IMAGE_IDENTITY_MIN_SCORE` | `float` | `4.0` |
| `GENERATION_IMAGE_MIN_SCORE` | `float` | `4.0` |
| `GENERATION_IMAGE_PLATFORM_MIN_SCORE` | `float` | `4.1` |
| `GENERATION_IMAGE_POSTPROCESS_COMMAND` | `str` | `""` |
| `GENERATION_IMAGE_POSTPROCESS_TIMEOUT_SECONDS` | `int` | `1800` |
| `GENERATION_IMAGE_REFINEMENT_PASSES` | `int` | `2` |

## GENERATION_MAX

| 变量 | 类型 | 默认值 |
| --- | --- | --- |
| `GENERATION_MAX_IMAGE_CANDIDATES` | `int` | `12` |
| `GENERATION_MAX_VIDEO_CANDIDATES` | `int` | `8` |

## GENERATION_MIN

| 变量 | 类型 | 默认值 |
| --- | --- | --- |
| `GENERATION_MIN_QUALITY_PASSES` | `int` | `2` |

## GENERATION_PREFER

| 变量 | 类型 | 默认值 |
| --- | --- | --- |
| `GENERATION_PREFER_NATIVE_VIDEO_AUDIO` | `bool` | `False` |

## GENERATION_PRIMARY

| 变量 | 类型 | 默认值 |
| --- | --- | --- |
| `GENERATION_PRIMARY_PROVIDER` | `str` | `jimeng_api` |

## GENERATION_PROVIDER

| 变量 | 类型 | 默认值 |
| --- | --- | --- |
| `GENERATION_PROVIDER` | `str` | `local_comfyui` |

## GENERATION_QUALITY

| 变量 | 类型 | 默认值 |
| --- | --- | --- |
| `GENERATION_QUALITY_NEGATIVE_APPEND` | `str` | `amateur snapshot, dull composition, muddy lighting, deformed face, deformed hands, broken fingers, extra people, random text, logo, watermark, bad crop, messy background` |
| `GENERATION_QUALITY_PROFILE` | `str` | `seed_dance_reference` |
| `GENERATION_QUALITY_PROMPT_APPEND` | `str` | `clean cinematic composition, coherent anatomy, readable main action, balanced lighting, polished short-drama keyframe` |

## GENERATION_REPAIR

| 变量 | 类型 | 默认值 |
| --- | --- | --- |
| `GENERATION_REPAIR_EXTRA_REFINEMENT_PASSES` | `int` | `1` |
| `GENERATION_REPAIR_IMAGE_CANDIDATE_MULTIPLIER` | `float` | `1.5` |
| `GENERATION_REPAIR_VIDEO_CANDIDATE_MULTIPLIER` | `float` | `1.5` |

## GENERATION_REQUIRE

| 变量 | 类型 | 默认值 |
| --- | --- | --- |
| `GENERATION_REQUIRE_IMAGE_POSTPROCESS` | `bool` | `False` |
| `GENERATION_REQUIRE_IMAGE_REVIEW` | `bool` | `True` |
| `GENERATION_REQUIRE_VIDEO_REVIEW` | `bool` | `True` |

## GENERATION_RHYTHM

| 变量 | 类型 | 默认值 |
| --- | --- | --- |
| `GENERATION_RHYTHM_MAX_DIALOGUE_MARGIN_SECONDS` | `float` | `0.3` |
| `GENERATION_RHYTHM_MAX_HOOK_LATENCY_SECONDS` | `float` | `8.0` |
| `GENERATION_RHYTHM_MAX_SILENT_SHOT_SECONDS` | `float` | `6.0` |
| `GENERATION_RHYTHM_MIN_SHOT_SECONDS` | `float` | `1.2` |
| `GENERATION_RHYTHM_SAME_ROLE_WARNING_RUN` | `int` | `3` |

## GENERATION_SEED

| 变量 | 类型 | 默认值 |
| --- | --- | --- |
| `GENERATION_SEED_DANCE_BASELINE_REGRESSION_TOLERANCE` | `float` | `0.05` |

## GENERATION_STEP

| 变量 | 类型 | 默认值 |
| --- | --- | --- |
| `GENERATION_STEP_VARIATION` | `int` | `0` |

## GENERATION_STEPS

| 变量 | 类型 | 默认值 |
| --- | --- | --- |
| `GENERATION_STEPS` | `int` | `40` |

## GENERATION_TURNAROUND

| 变量 | 类型 | 默认值 |
| --- | --- | --- |
| `GENERATION_TURNAROUND_FEATURE_MIN_SCORE` | `float` | `4.0` |

## GENERATION_VIDEO

| 变量 | 类型 | 默认值 |
| --- | --- | --- |
| `GENERATION_VIDEO_AESTHETIC_FEATURE_MIN_SCORE` | `float` | `4.0` |
| `GENERATION_VIDEO_AUDIO_CLIPPING_PEAK_DB` | `float` | `-0.1` |
| `GENERATION_VIDEO_AUDIO_INTEGRATED_LUFS_MAX` | `float` | `-12.0` |
| `GENERATION_VIDEO_AUDIO_INTEGRATED_LUFS_MIN` | `float` | `-24.0` |
| `GENERATION_VIDEO_AUDIO_NEAR_SILENT_PEAK_DB` | `float` | `-55.0` |
| `GENERATION_VIDEO_AUDIO_RMS_MAX_DB` | `float` | `-8.0` |
| `GENERATION_VIDEO_AUDIO_RMS_MIN_DB` | `float` | `-35.0` |
| `GENERATION_VIDEO_AUDIO_SILENCE_RATIO` | `float` | `0.95` |
| `GENERATION_VIDEO_AUDIO_SYNC_TOLERANCE_SECONDS` | `float` | `0.35` |
| `GENERATION_VIDEO_AUDIO_TRUE_PEAK_MAX_DB` | `float` | `-1.0` |
| `GENERATION_VIDEO_AUDIO_VISUAL_ALIGNMENT_MIN_SCORE` | `float` | `2.5` |
| `GENERATION_VIDEO_BASELINE_MAX_ASPECT_RATIO_DELTA` | `float` | `0.08` |
| `GENERATION_VIDEO_BASELINE_MAX_AUDIO_PEAK_DELTA_DB` | `float` | `12.0` |
| `GENERATION_VIDEO_BASELINE_MAX_AUDIO_RMS_DELTA_DB` | `float` | `12.0` |
| `GENERATION_VIDEO_BASELINE_MAX_DURATION_DELTA_SECONDS` | `float` | `0.5` |
| `GENERATION_VIDEO_BASELINE_MAX_EXPOSURE_DELTA` | `float` | `45.0` |
| `GENERATION_VIDEO_BASELINE_MAX_FPS_DELTA` | `float` | `2.0` |
| `GENERATION_VIDEO_BASELINE_MIN_VISUAL_STRUCTURE_SIMILARITY` | `float` | `0.3` |
| `GENERATION_VIDEO_BLACK_PIXEL_LUMA_THRESHOLD` | `float` | `12.0` |
| `GENERATION_VIDEO_BLACK_PIXEL_RATIO_THRESHOLD` | `float` | `0.98` |
| `GENERATION_VIDEO_CANDIDATES` | `int` | `4` |
| `GENERATION_VIDEO_CHARACTER_DISTINCTIVENESS_MIN_SCORE` | `float` | `4.0` |
| `GENERATION_VIDEO_CONTINUITY_REFERENCE_MIN_SCORE` | `float` | `2.0` |
| `GENERATION_VIDEO_DIALOGUE_PRELAP_SECONDS` | `float` | `0.08` |
| `GENERATION_VIDEO_DURATION_SYNC_TOLERANCE_SECONDS` | `float` | `0.35` |
| `GENERATION_VIDEO_END_FRAME_ENABLED` | `bool` | `True` |
| `GENERATION_VIDEO_END_FRAME_REFERENCE_MIN_SCORE` | `float` | `2.5` |
| `GENERATION_VIDEO_FRAME_FIT_MODE` | `str` | `cover` |
| `GENERATION_VIDEO_IDENTITY_MIN_SCORE` | `float` | `4.0` |
| `GENERATION_VIDEO_MAX_BLACK_FRAME_RATIO` | `float` | `0.05` |
| `GENERATION_VIDEO_MAX_BLACK_SECONDS` | `float` | `0.2` |
| `GENERATION_VIDEO_MAX_BRIGHTNESS_STEP_P95` | `float` | `36.0` |
| `GENERATION_VIDEO_MAX_FRAMES` | `int` | `40` |
| `GENERATION_VIDEO_MAX_FREEZE_SECONDS` | `float` | `0.2` |
| `GENERATION_VIDEO_MAX_MOTION_JITTER_RATIO` | `float` | `1.5` |
| `GENERATION_VIDEO_MAX_SECONDS` | `float` | `6.0` |
| `GENERATION_VIDEO_MAX_STATIC_RUN_SECONDS` | `float` | `1.8` |
| `GENERATION_VIDEO_MAX_TEMPORAL_JUMP_P95` | `float` | `0.75` |
| `GENERATION_VIDEO_MAX_TEMPORAL_JUMP_RATIO` | `float` | `0.35` |
| `GENERATION_VIDEO_MIN_COMPARISON_SAMPLES` | `int` | `4` |
| `GENERATION_VIDEO_MIN_SCORE` | `float` | `4.0` |
| `GENERATION_VIDEO_MIN_TEMPORAL_SAMPLES` | `int` | `4` |
| `GENERATION_VIDEO_MODEL_FPS` | `int` | `8` |
| `GENERATION_VIDEO_OUTPUT_FPS` | `int` | `24` |
| `GENERATION_VIDEO_PERFORMANCE_MIN_SCORE` | `float` | `4.0` |
| `GENERATION_VIDEO_PLATFORM_MIN_SCORE` | `float` | `4.1` |
| `GENERATION_VIDEO_POSTPROCESS` | `bool` | `True` |
| `GENERATION_VIDEO_REFINEMENT_PASSES` | `int` | `2` |
| `GENERATION_VIDEO_START_FRAME_REFERENCE_MIN_SCORE` | `float` | `2.5` |
| `GENERATION_VIDEO_TARGET_SECONDS` | `float` | `3.6` |
| `GENERATION_VIDEO_TECHNICAL_MIN_SCORE` | `float` | `3.0` |
| `GENERATION_VIDEO_TEMPORAL_MIN_SCORE` | `float` | `4.0` |

## GENERATION_WIDTH

| 变量 | 类型 | 默认值 |
| --- | --- | --- |
| `GENERATION_WIDTH` | `int` | `768` |

## GPU

| 变量 | 类型 | 默认值 |
| --- | --- | --- |
| `GPU_MEMORY_FRACTION` | `float` | `0.95`（预留，当前代码未读取） |

## HAILUO

| 变量 | 类型 | 默认值 |
| --- | --- | --- |
| `HAILUO_API_KEY` | `str` | 通过环境变量设置，勿提交 |
| `HAILUO_ENDPOINT` | `str` | `""` |

## HTTP

| 变量 | 类型 | 默认值 |
| --- | --- | --- |
| `HTTP_VIDEO_API_KEY` | `str` | 通过环境变量设置，勿提交 |
| `HTTP_VIDEO_AUTH_HEADER` | `str` | `Authorization` |
| `HTTP_VIDEO_AUTH_SCHEME` | `str` | `Bearer` |
| `HTTP_VIDEO_CANCEL_ENDPOINT` | `str` | `""` |
| `HTTP_VIDEO_ENDPOINT` | `str` | `""` |
| `HTTP_VIDEO_MAX_POLLS` | `int` | `240` |
| `HTTP_VIDEO_MAX_REFERENCE_AUDIOS` | `int` | `3` |
| `HTTP_VIDEO_MAX_REFERENCE_IMAGES` | `int` | `9` |
| `HTTP_VIDEO_MAX_REFERENCE_VIDEOS` | `int` | `3` |
| `HTTP_VIDEO_MAX_RETRIES` | `int` | `2` |
| `HTTP_VIDEO_MULTI_SHOT` | `bool` | `False` |
| `HTTP_VIDEO_NATIVE_AUDIO` | `bool` | `False` |
| `HTTP_VIDEO_POLL_INTERVAL_SECONDS` | `float` | `5.0` |
| `HTTP_VIDEO_RESULT_ENDPOINT` | `str` | `""` |
| `HTTP_VIDEO_RETRY_BACKOFF_SECONDS` | `float` | `1.0` |
| `HTTP_VIDEO_STATUS_ENDPOINT` | `str` | `""` |
| `HTTP_VIDEO_TIMEOUT_SECONDS` | `int` | `1800` |

## JIMENG

| 变量 | 类型 | 默认值 |
| --- | --- | --- |
| `JIMENG_API_KEY` | `str` | 通过环境变量设置，勿提交 |
| `JIMENG_ENDPOINT` | `str` | `""` |

## JWT

| 变量 | 类型 | 默认值 |
| --- | --- | --- |
| `JWT_ALGORITHM` | `str` | `HS256` |
| `JWT_EXPIRATION_HOURS` | `int` | `24` |
| `JWT_REFRESH_EXPIRATION_DAYS` | `int` | `7` |
| `JWT_SECRET_KEY` | `str` | 通过环境变量设置，勿提交 |

## KLING

| 变量 | 类型 | 默认值 |
| --- | --- | --- |
| `KLING_API_KEY` | `str` | 通过环境变量设置，勿提交 |
| `KLING_ENDPOINT` | `str` | `""` |

## LLM

| 变量 | 类型 | 默认值 |
| --- | --- | --- |
| `LLM_MODEL_PATH` | `str` | `./models/qwen2.5-14b-instruct-q4_k_m.gguf` |
| `LLM_N_CTX` | `int` | `4096` |
| `LLM_N_GPU_LAYERS` | `int` | `20` |
| `LLM_N_THREADS` | `int` | `8` |

## LOCAL

| 变量 | 类型 | 默认值 |
| --- | --- | --- |
| `LOCAL_REVIEW_BACKEND` | `str` | `llama_cpp` |
| `LOCAL_REVIEW_BASE_URL` | `str` | `http://127.0.0.1:8080/v1` |
| `LOCAL_REVIEW_MODEL` | `str` | `local-vlm` |
| `LOCAL_REVIEW_PROBE_TIMEOUT` | `float` | `2.0` |
| `LOCAL_REVIEW_TIMEOUT` | `int` | `300` |

## LOCALIZATION

| 变量 | 类型 | 默认值 |
| --- | --- | --- |
| `LOCALIZATION_CONCURRENCY` | `int` | `1`（预留，当前代码未读取） |
| `LOCALIZATION_MAX_SOURCE_VIDEO_SIZE_MB` | `int` | `2048` |
| `LOCALIZATION_TARGET_LANGUAGES` | `str` | `en,es,pt,ar,id,th,vi,ja,ko` |

## LOG

| 变量 | 类型 | 默认值 |
| --- | --- | --- |
| `LOG_FILE_PATH` | `str` | `./logs/app.log` |
| `LOG_LEVEL` | `str` | `INFO` |

## MAX

| 变量 | 类型 | 默认值 |
| --- | --- | --- |
| `MAX_STORAGE_SIZE_GB` | `int` | `500` |

## MODERATION

| 变量 | 类型 | 默认值 |
| --- | --- | --- |
| `MODERATION_BACKEND` | `str` | `rules`（预留，当前代码未读取） |

## NEGATIVE

| 变量 | 类型 | 默认值 |
| --- | --- | --- |
| `NEGATIVE_PROMPT_SUFFIX` | `str` | `""` |

## OCCLUSION

| 变量 | 类型 | 默认值 |
| --- | --- | --- |
| `OCCLUSION_AUTO_MASK_MIN_CONFIDENCE` | `float` | `0.65` |
| `OCCLUSION_MASK_DETECTOR_COMMAND` | `str` | `""` |
| `OCCLUSION_MIN_QUALITY_SCORE` | `float` | `0.92` |
| `OCCLUSION_REMOVAL_BACKEND` | `str` | `detect_only` |
| `OCCLUSION_REMOVAL_TIMEOUT_SECONDS` | `int` | `7200` |

## OCR

| 变量 | 类型 | 默认值 |
| --- | --- | --- |
| `OCR_ASR_MAX_GAP_SECONDS` | `float` | `0.35` |
| `OCR_BACKEND` | `str` | `disabled` |
| `OCR_COMMAND` | `str` | `""` |
| `OCR_MIN_CONFIDENCE` | `float` | `0.55` |
| `OCR_TIMEOUT_SECONDS` | `int` | `7200` |

## POSITIVE

| 变量 | 类型 | 默认值 |
| --- | --- | --- |
| `POSITIVE_PROMPT_SUFFIX` | `str` | `""` |

## PROPINTER

| 变量 | 类型 | 默认值 |
| --- | --- | --- |
| `PROPINTER_COMMAND` | `str` | `""` |

## READINESS

| 变量 | 类型 | 默认值 |
| --- | --- | --- |
| `READINESS_REQUIRE_REDIS` | `bool` | `False` |

## REDIS

| 变量 | 类型 | 默认值 |
| --- | --- | --- |
| `REDIS_URL` | `str` | `redis://localhost:6379/0` |

## SEEDANCE

| 变量 | 类型 | 默认值 |
| --- | --- | --- |
| `SEEDANCE_API_FORMAT` | `str` | `legacy` |
| `SEEDANCE_API_KEY` | `str` | 通过环境变量设置，勿提交 |
| `SEEDANCE_AUTH_HEADER` | `str` | `Authorization` |
| `SEEDANCE_AUTH_SCHEME` | `str` | `Bearer` |
| `SEEDANCE_BITRATE_MODE` | `str` | `high` |
| `SEEDANCE_CALLBACK_ALLOW_UNSIGNED` | `bool` | `False` |
| `SEEDANCE_CALLBACK_SECRET` | `str` | 通过环境变量设置，勿提交 |
| `SEEDANCE_CALLBACK_URL` | `str` | `""` |
| `SEEDANCE_CAMERA_FIXED` | `bool` | `False` |
| `SEEDANCE_CANCEL_ENDPOINT` | `str` | `""` |
| `SEEDANCE_CODEC` | `str` | `H264` |
| `SEEDANCE_DRAFT` | `bool` | `False` |
| `SEEDANCE_ENDPOINT` | `str` | `""` |
| `SEEDANCE_INCLUDE_EXPERIMENTAL_FIELDS` | `bool` | `False` |
| `SEEDANCE_MAX_POLLS` | `int` | `240` |
| `SEEDANCE_MAX_REFERENCE_AUDIOS` | `int` | `3` |
| `SEEDANCE_MAX_REFERENCE_IMAGES` | `int` | `9` |
| `SEEDANCE_MAX_REFERENCE_VIDEOS` | `int` | `3` |
| `SEEDANCE_MAX_RETRIES` | `int` | `2` |
| `SEEDANCE_MEDIA_URL_TEMPLATE` | `str` | `""` |
| `SEEDANCE_MODEL` | `str` | `doubao-seedance-2-5-260628` |
| `SEEDANCE_MULTI_SHOT` | `bool` | `True` |
| `SEEDANCE_MULTI_SHOT_DURATION_SECONDS` | `int` | `30` |
| `SEEDANCE_NATIVE_AUDIO` | `bool` | `True` |
| `SEEDANCE_OUTPUT_FORMAT` | `str` | `mp4` |
| `SEEDANCE_POLL_INTERVAL_SECONDS` | `float` | `5.0` |
| `SEEDANCE_REQUEST_MODE` | `str` | `reference_to_video` |
| `SEEDANCE_RESOLUTION` | `str` | `1080p` |
| `SEEDANCE_RESULT_ENDPOINT` | `str` | `""` |
| `SEEDANCE_RETRY_BACKOFF_SECONDS` | `float` | `1.0` |
| `SEEDANCE_RETURN_LAST_FRAME` | `bool` | `True` |
| `SEEDANCE_SEQUENCE_LEVEL_MULTI_SHOT` | `bool` | `False` |
| `SEEDANCE_STATUS_ENDPOINT` | `str` | `""` |
| `SEEDANCE_TIMEOUT_SECONDS` | `int` | `1800` |
| `SEEDANCE_VALIDATE_OUTPUT` | `bool` | `True` |
| `SEEDANCE_WATERMARK` | `bool` | `False` |

## STORAGE

| 变量 | 类型 | 默认值 |
| --- | --- | --- |
| `STORAGE_PATH` | `str` | `./storage` |

## SUBTITLE

| 变量 | 类型 | 默认值 |
| --- | --- | --- |
| `SUBTITLE_MAX_READING_UNITS_PER_SECOND` | `float` | `18.0` |
| `SUBTITLE_REMOVAL_BACKEND` | `str` | `manual_mask`（预留，当前代码未读取） |
| `SUBTITLE_RENDER_BOLD` | `bool` | `True` |
| `SUBTITLE_RENDER_FONT` | `str` | `Arial` |
| `SUBTITLE_RENDER_FONT_SIZE` | `int` | `38` |
| `SUBTITLE_RENDER_MARGIN_V` | `int` | `64` |
| `SUBTITLE_RENDER_OUTLINE` | `int` | `3` |
| `SUBTITLE_RENDER_SHADOW` | `int` | `1` |
| `SUBTITLE_RENDER_TIMEOUT_SECONDS` | `int` | `7200` |

## SVD

| 变量 | 类型 | 默认值 |
| --- | --- | --- |
| `SVD_FPS` | `int` | `8` |
| `SVD_MODEL_PATH` | `str` | `./models/stable-video-diffusion-img2vid-xt` |
| `SVD_NUM_FRAMES` | `int` | `25` |

## TRANSLATION

| 变量 | 类型 | 默认值 |
| --- | --- | --- |
| `TRANSLATION_BACKEND` | `str` | `local_llm` |
| `TRANSLATION_COMMAND` | `str` | `""` |
| `TRANSLATION_MAX_CONCURRENCY` | `int` | `2` |
| `TRANSLATION_MAX_SEGMENTS_PER_BATCH` | `int` | `30` |
| `TRANSLATION_TIMEOUT_SECONDS` | `int` | `7200` |

## TRUST

| 变量 | 类型 | 默认值 |
| --- | --- | --- |
| `TRUST_X_FORWARDED_FOR` | `bool` | `False` |

## TTS

| 变量 | 类型 | 默认值 |
| --- | --- | --- |
| `TTS_API_KEY` | `str` | 通过环境变量设置，勿提交 |
| `TTS_BASE_URL` | `str` | `https://mimo.xiaomi.com/api/v2/tts` |

## VSR

| 变量 | 类型 | 默认值 |
| --- | --- | --- |
| `VSR_COMMAND` | `str` | `""` |
