# AI 短剧自动化生产平台

基于 AI 的短剧自动化生产系统，支持剧本生成、角色管理、图像生成、视频合成等功能。

## 🚀 快速开始

### 启动所有服务

```bash
cd F:\study\aishortmovie\aivedio
python start_services.py
```

脚本会自动：
- ✅ 检测 Python 环境和虚拟环境
- ✅ 检查并更新数据库结构
- ✅ 启动 ComfyUI (端口 8188)
- ✅ 启动 FastAPI 后端 (端口 8000)
- ✅ 启动 Celery Worker
- ✅ 启动前端开发服务器 (端口 5173)

### 访问地址

- **前端界面**: http://localhost:5173
- **后端 API**: http://localhost:8000
- **API 文档**: http://localhost:8000/docs
- **ComfyUI**: http://localhost:8188

## 📁 项目结构

```
aivedio/
├── start_services.py          # 服务启动脚本（唯一入口）
├── main.py                    # FastAPI 应用入口
├── src/                       # 后端源代码
│   ├── api/                   # API 路由
│   ├── services/              # 业务逻辑
│   ├── tasks/                 # Celery 任务
│   └── database/              # 数据库模型
├── frontend/                  # 前端代码
├── ComfyUI/                   # ComfyUI 图像生成
├── configs/                   # 配置文件
├── docs/                      # 文档
└── storage/                   # 数据存储
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

## 🔧 技术栈

**后端**:
- FastAPI + Python 3.12
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

- Python 3.12+
- Node.js 18+
- Redis
- NVIDIA GPU (推荐 RTX 3060+)
- CUDA 11.8+

## 📝 许可证

MIT License

---

**祝您创作愉快！** 🎬✨
