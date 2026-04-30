# AI 短剧自动化生产平台

> 基于 AI 的全自动短剧生产系统，从创意到成品一键生成

[![Python](https://img.shields.io/badge/Python-3.10+-blue.svg)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.136+-green.svg)](https://fastapi.tiangolo.com/)
[![License](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Tests](https://img.shields.io/badge/Tests-271+-brightgreen.svg)](tests/)

---

## 📖 项目简介

AI 短剧自动化生产平台是一个完整的端到端解决方案，能够自动化生成短剧视频。用户只需提供主题或大纲，系统将自动完成：

- 📝 **剧本生成**：使用 Qwen2.5-14B 大语言模型生成完整剧本
- 🎨 **图像生成**：使用 Stable Diffusion XL 生成分镜图像
- 🎬 **视频生成**：使用 Stable Video Diffusion 将图像转换为视频
- 🎤 **配音生成**：使用 MiMo-V2-TTS 生成角色配音
- 📺 **视频合成**：自动合成最终短剧视频

---

## ✨ 核心特性

### 🤖 AI 驱动
- **Qwen2.5-14B**：智能剧本生成
- **Stable Diffusion XL**：高质量图像生成
- **Stable Video Diffusion**：图生视频
- **MiMo-V2-TTS**：自然语音合成

### 🚀 高性能
- **异步任务处理**：Celery + Redis
- **GPU 加速**：支持 NVIDIA GPU
- **并行处理**：多任务并行执行
- **智能缓存**：减少重复计算

### 🔒 安全可靠
- **JWT 认证**：安全的用户认证
- **API 速率限制**：防止滥用
- **数据加密**：敏感数据加密存储
- **全面测试**：271+ 个测试用例

### 📊 实时监控
- **WebSocket 通信**：实时进度更新
- **Prometheus 指标**：性能监控
- **结构化日志**：便于问题排查
- **健康检查**：服务状态监控

---

## 🏗️ 系统架构

```
┌─────────────────────────────────────────────────────────────┐
│                         用户界面                              │
│                    (Web / API 客户端)                         │
└────────────────────┬────────────────────────────────────────┘
                     │
                     ▼
┌─────────────────────────────────────────────────────────────┐
│                      FastAPI 服务                             │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐   │
│  │ 项目管理 │  │ 剧本生成 │  │ 任务编排 │  │ WebSocket│   │
│  └──────────┘  └──────────┘  └──────────┘  └──────────┘   │
└────────────────────┬────────────────────────────────────────┘
                     │
                     ▼
┌─────────────────────────────────────────────────────────────┐
│                    Celery 任务队列                            │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐   │
│  │ 图像任务 │  │ 视频任务 │  │ 音频任务 │  │ 合成任务 │   │
│  └──────────┘  └──────────┘  └──────────┘  └──────────┘   │
└────────────────────┬────────────────────────────────────────┘
                     │
                     ▼
┌─────────────────────────────────────────────────────────────┐
│                      AI 服务层                                │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐   │
│  │   LLM    │  │ ComfyUI  │  │   SVD    │  │   TTS    │   │
│  │ (Qwen)   │  │  (SDXL)  │  │          │  │ (MiMo)   │   │
│  └──────────┘  └──────────┘  └──────────┘  └──────────┘   │
└─────────────────────────────────────────────────────────────┘
```

---

## 🚀 快速开始

### 前置要求

- **操作系统**：Ubuntu 22.04 LTS / Windows 10+
- **Python**：3.10+
- **GPU**：NVIDIA RTX 3090/4090（24GB 显存）
- **存储**：100GB+ SSD
- **内存**：32GB+

### 使用 Docker（推荐）

```bash
# 1. 克隆项目
git clone https://github.com/your-org/ai-short-drama-production.git
cd ai-short-drama-production

# 2. 配置环境变量
cp .env.example .env
# 编辑 .env 文件，配置 API 密钥等

# 3. 下载 AI 模型
bash scripts/download_models.sh

# 4. 启动所有服务
docker-compose up -d

# 5. 访问 API 文档
# http://localhost:8000/docs
```

### 裸机部署

```bash
# 1. 创建虚拟环境
python3.10 -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate

# 2. 安装依赖
pip install -r requirements.txt

# 3. 配置环境变量
cp .env.example .env

# 4. 初始化数据库
python -c "from src.database.session import engine; from src.database.models import Base; Base.metadata.create_all(engine)"

# 5. 启动服务
# 终端 1: Redis
redis-server

# 终端 2: ComfyUI
cd ComfyUI && python main.py

# 终端 3: Celery Worker
celery -A src.tasks.celery_app worker --loglevel=info

# 终端 4: FastAPI
python main.py
```

---

## 📚 文档

- [快速开始指南](docs/quick-start.md)
- [用户手册](docs/user-manual.md)
- [部署指南](docs/deployment-guide.md)
- [模型部署指南](docs/model-deployment-guide.md)
- [服务监控和维护](docs/monitoring-and-maintenance.md)
- [最佳实践](docs/best-practices.md)
- [API 文档](http://localhost:8000/docs)

---

## 🧪 测试

```bash
# 运行所有测试
python -m pytest tests/ -v

# 运行特定测试
python -m pytest tests/test_services/ -v

# 运行属性测试
python -m pytest tests/ -k "properties" -v

# 生成测试覆盖率报告
python -m pytest tests/ --cov=src --cov-report=html
```

**测试统计**：
- ✅ 271+ 个测试用例
- ✅ 单元测试：145+ 个
- ✅ 属性测试：48+ 个
- ✅ API 测试：78+ 个

---

## 📊 性能指标

### 单个分镜生成时间（RTX 4090）

| 步骤 | 时间 | 说明 |
|------|------|------|
| 图像生成 | 5-10 秒 | SDXL，20 步采样 |
| 视频生成 | 15-30 秒 | SVD，16 帧 |
| 配音生成 | 2-5 秒 | MiMo-V2-TTS API |
| 字幕生成 | <1 秒 | FFmpeg |
| **总计** | **22-46 秒** | 单个分镜 |

### 完整项目生成时间

| 分镜数 | 预计时间 | 说明 |
|--------|----------|------|
| 5 个分镜 | 2-4 分钟 | 并行处理 |
| 10 个分镜 | 4-8 分钟 | 并行处理 |
| 20 个分镜 | 8-16 分钟 | 并行处理 |

---

## 🛠️ 技术栈

### 后端
- **FastAPI**：现代 Web 框架
- **Celery**：异步任务队列
- **Redis**：缓存和消息队列
- **SQLAlchemy**：ORM
- **Alembic**：数据库迁移

### AI 模型
- **Qwen2.5-14B**：大语言模型（剧本生成）
- **Stable Diffusion XL**：图像生成
- **Stable Video Diffusion**：视频生成
- **MiMo-V2-TTS**：语音合成

### 工具
- **FFmpeg**：视频处理
- **Docker**：容器化
- **pytest**：测试框架
- **Hypothesis**：属性测试
- **Prometheus**：监控

---

## 📁 项目结构

```
ai-short-drama-production/
├── src/                      # 源代码
│   ├── api/                  # FastAPI 应用
│   ├── services/             # 业务服务
│   ├── tasks/                # Celery 任务
│   ├── database/             # 数据库模型
│   └── utils/                # 工具函数
├── tests/                    # 测试代码
│   ├── test_services/        # 服务测试
│   ├── test_api/             # API 测试
│   └── test_utils/           # 工具测试
├── docs/                     # 文档
├── scripts/                  # 脚本
├── models/                   # AI 模型
├── storage/                  # 生成文件
├── docker-compose.yml        # Docker 配置
├── Dockerfile                # Docker 镜像
├── requirements.txt          # Python 依赖
└── README.md                 # 本文件
```

---

## 🤝 贡献

欢迎贡献！请查看 [CONTRIBUTING.md](CONTRIBUTING.md) 了解详情。

---

## 📄 许可证

本项目采用 MIT 许可证。详见 [LICENSE](LICENSE) 文件。

---

## 🙏 致谢

- [Qwen](https://github.com/QwenLM/Qwen) - 大语言模型
- [Stable Diffusion](https://github.com/Stability-AI/stablediffusion) - 图像生成
- [ComfyUI](https://github.com/comfyanonymous/ComfyUI) - SD 工作流
- [FastAPI](https://fastapi.tiangolo.com/) - Web 框架
- [Celery](https://docs.celeryq.dev/) - 任务队列

---

## 📞 联系方式

- **项目主页**：https://github.com/your-org/ai-short-drama-production
- **问题反馈**：https://github.com/your-org/ai-short-drama-production/issues
- **邮箱**：your-email@example.com

---

**⭐ 如果这个项目对你有帮助，请给我们一个 Star！**
