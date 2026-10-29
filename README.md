# AI 短剧自动化生产平台

[![contract-tests](https://github.com/GhhosttTT/aivedio/actions/workflows/contract-tests.yml/badge.svg)](https://github.com/GhhosttTT/aivedio/actions/workflows/contract-tests.yml)

基于 AI 的短剧自动化生产系统，支持剧本生成、角色管理、图像生成、视频合成等功能。

本地生成的最新流程、情节二次审核、抽帧评分与 RTX 3060 12GB 验收步骤见 [本地生成与验收](docs/local-generation-3060.md)。默认已关闭占位媒体兜底；真实模型和审核未就绪时任务会明确失败。

## 🚀 快速开始

### 启动所有服务

```bash
cd aivedio
pip install -r requirements.txt
python start_services.py
```

可选运行时依赖：

```bash
pip install -e ".[api]"      # 使用 DeepSeek/OpenAI 兼容 API 生成剧本或翻译
pip install -e ".[asr]"      # faster-whisper 本地语音识别
pip install -e ".[metrics]"  # GPUtil GPU 指标
```

脚本会自动：
- ✅ 检测 Python 环境和虚拟环境
- ✅ 检查并更新数据库结构
- ✅ 启动 Redis（若本机已安装 `redis-server` 且 6379 未被占用）
- ✅ 启动 ComfyUI (端口 8188)
- ✅ 启动 FastAPI 后端 (端口 8000)
- ✅ 启动 Celery Worker
- ✅ 启动前端开发服务器 (端口 5173)

### 访问地址

- **前端界面**: http://localhost:5173
- **后端 API**: http://localhost:8000
- **API 文档**: http://localhost:8000/docs
- **ComfyUI**: http://localhost:8188

### Seedance 生产视频

项目支持把本地 SVD/ComfyUI 替换为 Seedance-compatible 视频网关。先复制配置并填写真实网关信息：

```bash
cp .env.example .env
```

```env
GENERATION_PROVIDER=seedance_api
SEEDANCE_ENDPOINT=https://your-gateway.example/v1/video/generations
SEEDANCE_API_KEY=your_api_key
SEEDANCE_STATUS_ENDPOINT=https://your-gateway.example/v1/video/generations/{job_id}
SEEDANCE_RESULT_ENDPOINT=https://your-gateway.example/v1/video/generations/{request_id}/result
SEEDANCE_API_FORMAT=legacy
SEEDANCE_REQUEST_MODE=reference_to_video
```

严格兼容 reference-to-video 网关时使用 `reference_to_video`；确认网关支持
Seedance 2.5 多镜头协议后再改为 `multi_shot`。启动后可在
`GET /projects/video-engine/preflight` 检查 endpoint、密钥、轮询和结果地址是否齐全。
没有真实 API key 时，项目不会伪造生产视频，会明确失败或按配置使用本地 draft fallback。

当分镜带有锁定首帧时，系统会在候选和最终归一化视频阶段检查开场帧；可通过
`GENERATION_VIDEO_START_FRAME_REFERENCE_MIN_SCORE` 调整硬门槛（默认 `2.5`）。
当分镜启用末帧目标时，系统也会在候选和最终归一化视频阶段检查收束画面；可通过
`GENERATION_VIDEO_END_FRAME_REFERENCE_MIN_SCORE` 调整末帧硬门槛（默认 `2.5`）。
项目级边界一致性报告还会检查上一镜头尾帧到当前镜头开场的连续性；可通过
`GENERATION_VIDEO_CONTINUITY_REFERENCE_MIN_SCORE` 调整复查门槛（默认 `2.0`）。
当生成视频包含音频时，候选还会记录音频活动与画面动作的时间相关性；在其他质量分接近时，优先保留音画活动更同步的候选。该指标是对白/动作同步的自动筛查，不替代最终人工或 VLM 复核。

执行“优化对白音频”返修后，最终合成会采用该镜头通过审核的新对白，即使项目原先使用视频原生音频；其他镜头仍保留原生音轨。新对白必须通过文件版本、对白内容及音视频时长检查。替换整条镜头音轨也会替换该镜头原有的环境声，最终音画同步仍需通过成片审核。

多语言字幕 QA 在存在已渲染视频时，还会抽查字幕 cue 中点与邻近无字幕帧的下方安全区边缘密度，提示字幕未烧录或对比度不足的问题；这是一层视觉筛查，不等同于 OCR 或人脸遮挡检测。

正式生成前的生产就绪检查还会扫描实际剧本和分镜中的高风险内容词，并把命中分镜、字段、风险类别和政策备注覆盖情况写入报告；关键词只是风险证据，命中后仍需人工内容安全复核，不会被自动当作合规结论。

如果使用火山方舟原生视频任务接口，改为：

```env
SEEDANCE_ENDPOINT=https://ark.cn-beijing.volces.com/api/v3/contents/generations/tasks
SEEDANCE_STATUS_ENDPOINT=https://ark.cn-beijing.volces.com/api/v3/contents/generations/tasks/{job_id}
SEEDANCE_API_FORMAT=ark_v3
SEEDANCE_MODEL=doubao-seedance-2-5-260628
SEEDANCE_REQUEST_MODE=reference
SEEDANCE_VALIDATE_OUTPUT=true
# If local video/audio references are used, expose them through a public HTTPS CDN.
# The template must contain {filename} or {path}.
SEEDANCE_MEDIA_URL_TEMPLATE=https://cdn.example.com/aivideo/{filename}
```

该模式发送原生 `content[]`，明确区分参考图、参考视频、参考音频和首尾帧模式。
本地图片可直接走 Base64；本地视频必须配置公网 URL 模板或预先上传为 `asset://` 素材。
本地图片单张超过 30MB 或图片集合超过安全请求体预算时，也会自动要求并切换到该公网 URL 模板。

需要启用跨镜头连续性时，将 `SEEDANCE_REQUEST_MODE=multi_shot`；默认每个原子分镜仍按导演计划时长生成，同时把前一镜、当前镜和后一镜作为有界连续性上下文。`SEEDANCE_SEQUENCE_LEVEL_MULTI_SHOT=true` 会对整个项目只请求一次完整序列（默认 30 秒），再按对白时长/分镜时间轴切回原子分镜，避免每个分镜重复生成 30 秒视频。该模式应在真实 Ark 样片验证后用于生产。
原生 Ark 2.5 还可设置 `SEEDANCE_REQUEST_MODE=auto`，让模型根据提示词自动判断参考、编辑或延长任务；含参考视频时系统会自动使用 `adaptive + duration=-1` 以满足编辑/延长约束；2.0/1.0 不支持该模式。

工作台的“本次视频生成配置”可以覆盖单次生产任务的 provider、Seedance 模型、任务模式、原生音频和多镜头开关；provider 或模型留空时分别沿用 `.env` 中的 `GENERATION_PROVIDER` / `SEEDANCE_MODEL`，不会修改全局配置。单次模型选择会同步执行对应的 4K、MOV、Draft 和引用上限校验。
Seedance 2.5 选择 1080p + MP4 时会执行 10-bit HEVC 校验；选择 MOV 时会保留官方 H.264 4:4:4 色彩路径，并在后续归一化、拼接和字幕阶段继续保留色彩采样精度。
单镜头时长默认按导演分镜计划和对白实测时长自动决定；只有显式选择 5/10/15/30 秒时才会覆盖该计划。

Seedance 2.5 原生模式还支持 Draft 样片：勾选“先生成 Draft 样片”会以 480p 请求预览；确认后可通过 `draft_task_id` 基于同一份样片提交正式任务。`return_last_frame` 默认开启，用于把上一段尾帧衔接到下一段。
首尾帧模式会自动使用 `adaptive + 1080p`；Draft 提升正式片也会按 Ark 两步协议使用 `1080p`，不会重复提交 Draft 阶段已经锁定的时长、比例和参考素材参数。

正式跑片前可先做不扣额度的请求检查：

```bash
python3 scripts/validate_seedance_gateway.py --mode reference_to_video
# 火山方舟原生协议
python3 scripts/validate_seedance_gateway.py --dry-run --api-format ark_v3 --mode reference_to_video
# 验证指定模型的模型级限制（不会修改 .env）
python3 scripts/validate_seedance_gateway.py --dry-run --api-format ark_v3 \
  --model doubao-seedance-2-5-260628 --resolution 1080p --duration 5
```

长任务可配置 `SEEDANCE_CALLBACK_URL`，Ark 会在任务状态变化时回调该地址；本项目提供
`POST /api/webhooks/seedance` 接收器。生产环境请同时设置
`SEEDANCE_CALLBACK_SECRET`，并通过 `X-Seedance-Callback-Secret` 请求头或 URL 的
`?token=` 传递密钥；未配置密钥时 webhook 默认拒绝请求。仅本地无法发送签名的网关可显式设置
`SEEDANCE_CALLBACK_ALLOW_UNSIGNED=true`，生产环境不要开启。回调会按远端 task ID 写入 pending sidecar，provider 在终态回调到达时优先使用它，轮询仍作为兜底。
本地任务仍保留轮询兜底，因此回调暂时不可用不会影响已有流程。

异步 HTTP 视频网关可配置 `HTTP_VIDEO_CANCEL_ENDPOINT`，Seedance 网关可配置
`SEEDANCE_CANCEL_ENDPOINT`，地址必须包含 `{job_id}` 或 `{request_id}`。本地任务取消时
会尝试向该地址发送 `DELETE`，避免远端任务继续占用额度；未配置时原生 Ark 仍默认对状态
地址执行取消。

取消请求先被确认后，最终合成与 Draft 收尾不会再覆盖已有结果；如果收尾已完成，取消接口会保留结果并返回无法取消。
最终合成的中间视频、混音与字幕时间轴按每次执行隔离，避免重复投递或旧任务清理干扰新任务；候选成片会使用同一份字幕时间轴执行可见性检查。审核抽帧证据独立留存在 `reviews/composition_attempts/`，不随渲染临时文件清理。

拿到真实样片后，可用 `scripts/compare_video_baseline.py` 对候选视频和 Seedance
基准视频做本地证据对比；除了分辨率、时长、清晰度和运动量，还会拦截黑帧、冻结段、
曝光跳变和运动节奏失稳。该报告是技术门禁，不替代角色一致性、表演和叙事的人工/VLM审核。

网关检查默认使用移动短剧竖屏 `9:16`；调试横屏时显式传入 `--aspect-ratio 16:9`。

最终视频默认使用 `GENERATION_VIDEO_FRAME_FIT_MODE=cover` 填满目标画幅，避免
横屏本地 draft 归一化成竖屏时出现黑边；需要保留完整原始画面时可改为 `contain`。

只有明确加上 `--live` 才会提交真实生成任务。
`--live` 默认还会检查下载结果是否是可读视频、是否有有效分辨率和时长；请求了音频时也会检查解码后的音频信号。仅在调试网关返回格式时使用
`--skip-output-validation` 跳过这一步。
显式请求时长时，返回视频与请求的时长偏差超过 `max(0.35s, 8%)` 也会被拒绝，避免字幕和镜头时间轴错位。

## 📁 项目结构

```
aivedio/
├── start_services.py          # 主启动脚本（本机各服务）
├── start_services_with_logs.py # 当前终端实时日志启动
├── start_all_services.py      # 备用启动脚本
├── main.py                    # FastAPI 应用入口
├── src/                       # 后端源代码
│   ├── api/                   # API 路由
│   ├── services/              # 业务逻辑
│   ├── tasks/                 # Celery 任务
│   └── database/              # 数据库模型
├── frontend/                  # 前端代码
├── configs/                   # ComfyUI 工作流与质量配置
├── scripts/                   # 运维、校验与辅助脚本
├── tests/                     # 单元/契约/真实媒体测试
├── docs/                      # 文档
├── storage/                   # 生成的媒体与报告
└── data/                      # Docker 部署时共享的 SQLite 数据
```

> ComfyUI 需要单独安装（默认监听 8188），不属于本仓库内容。

## 🧪 测试

```bash
# 全量测试（需要按 requirements.txt 安装依赖）
pytest -q

# 只需轻量契约环境
pip install -r requirements-contract-tests.txt
pytest -q tests/test_config_reference.py tests/test_celery_queue_contract.py

# 真实 ffmpeg 媒体测试（需要系统 ffmpeg）
pip install -r requirements-media-tests.txt
pytest -q tests/test_services/test_video_quality_metrics.py
```

## 🎯 核心功能

### 1. 剧本生成
- 基于 LLM 自动生成剧本
- 支持角色和分镜自动识别
- 可重新生成单个分镜

### 2. 角色一致性
- 自动检测和管理角色
- IP-Adapter 面部一致性技术
- 首次生成自动保存参考图
- 后续生成自动保持一致

### 3. 图像生成
- 基于 ComfyUI + Stable Diffusion XL
- 支持角色面部一致性
- 批量并行生成
- 实时进度推送

### 4. 视频合成
- 图像转视频
- 音频合成
- 字幕添加
- 完整短剧输出

## 📖 文档

- [快速开始](docs/quick-start.md)
- [角色一致性指南](docs/character-consistency.md)
- [用户手册](docs/user-manual.md)
- [部署指南](docs/deployment-guide.md)
- [缓存与失效语义](docs/caching-and-invalidation.md)
- [配置项参考](docs/configuration-reference.md)

## 🔧 技术栈

**后端**:
- FastAPI + Python 3.10+
- SQLAlchemy + SQLite
- Celery + Redis
- llama-cpp-python (LLM)

**前端**:
- React + TypeScript
- Vite
- Ant Design
- Zustand

**AI 模型**:
- Stable Diffusion XL (图像)
- IP-Adapter FaceID (角色一致性)
- Qwen2.5 (剧本生成)

## ⚙️ 环境要求

- Python 3.10+（Docker 镜像与测试均使用 3.10）
- Node.js 18+
- Redis
- NVIDIA GPU (推荐 RTX 3060+)
- CUDA 11.8+

## 📝 许可证

MIT License

---

**祝您创作愉快！** 🎬✨
