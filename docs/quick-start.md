# 快速开始指南

欢迎使用 AI 短剧自动化生产平台！本指南将帮助您快速上手，在几分钟内创建您的第一个 AI 短剧项目。

## 目录

- [系统要求](#系统要求)
- [安装步骤](#安装步骤)
- [启动服务](#启动服务)
- [创建第一个项目](#创建第一个项目)
- [常见问题](#常见问题)

## 系统要求

### 硬件要求

- **CPU**: 8 核心或以上（推荐）
- **内存**: 32GB 或以上（推荐）
- **GPU**: NVIDIA RTX 4090 24GB 或同等性能（必需）
- **存储**: 500GB 可用空间（用于模型和生成文件）

### 软件要求

- **操作系统**: Windows 10/11、Linux（Ubuntu 20.04+）、macOS（实验性支持）
- **Python**: 3.10 或以上
- **CUDA**: 11.8 或以上（GPU 加速必需）
- **FFmpeg**: 4.4 或以上（视频处理必需）
- **Redis**: 6.0 或以上（任务队列必需）

## 安装步骤

### 1. 克隆项目

```bash
git clone https://github.com/your-org/ai-short-drama-production.git
cd ai-short-drama-production
```

### 2. 创建虚拟环境

```bash
python -m venv venv

# Windows
venv\Scripts\activate

# Linux/macOS
source venv/bin/activate
```

### 3. 安装依赖

```bash
pip install -r requirements.txt
```

### 4. 下载 AI 模型

系统需要以下 AI 模型（总大小约 20GB）：

#### 4.1 Qwen2.5-14B GGUF 模型（约 8GB）

```bash
# 创建模型目录
mkdir -p models

# 下载模型（使用 huggingface-cli 或浏览器下载）
huggingface-cli download Qwen/Qwen2.5-14B-Instruct-GGUF \
    qwen2.5-14b-instruct-q4_k_m.gguf \
    --local-dir models
```

或访问：https://huggingface.co/Qwen/Qwen2.5-14B-Instruct-GGUF

#### 4.2 Stable Diffusion XL 模型（约 6.9GB）

```bash
huggingface-cli download stabilityai/stable-diffusion-xl-base-1.0 \
    sd_xl_base_1.0.safetensors \
    --local-dir models/stable-diffusion-xl-base-1.0
```

或访问：https://huggingface.co/stabilityai/stable-diffusion-xl-base-1.0

#### 4.3 Stable Video Diffusion 模型（约 3.8GB）

```bash
huggingface-cli download stabilityai/stable-video-diffusion-img2vid-xt \
    --local-dir models/stable-video-diffusion-img2vid-xt
```

或访问：https://huggingface.co/stabilityai/stable-video-diffusion-img2vid-xt

### 5. 配置环境变量

复制环境变量模板并编辑：

```bash
cp .env.example .env
```

编辑 `.env` 文件，配置以下关键参数：

```bash
# LLM 模型路径
LLM_MODEL_PATH=./models/qwen2.5-14b-instruct-q4_k_m.gguf

# ComfyUI 配置
COMFYUI_BASE_URL=http://127.0.0.1:8188

# SVD 模型路径
SVD_MODEL_PATH=./models/stable-video-diffusion-img2vid-xt

# TTS API 密钥（需要申请）
TTS_API_KEY=your_mimo_api_key_here

# 数据库配置
DATABASE_URL=sqlite:///./short_drama.db

# Redis 配置
REDIS_URL=redis://localhost:6379/0

# JWT 密钥（生产环境请更改）
JWT_SECRET_KEY=your_jwt_secret_key_here
```

### 6. 初始化数据库

```bash
python scripts/init_db.py
```

### 7. 安装和配置 ComfyUI

ComfyUI 用于图像生成，需要单独安装：

```bash
# 克隆 ComfyUI
git clone https://github.com/comfyanonymous/ComfyUI.git
cd ComfyUI

# 安装依赖
pip install -r requirements.txt

# 链接 SD 模型到 ComfyUI
# Windows
mklink /D models\checkpoints ..\models\stable-diffusion-xl-base-1.0

# Linux/macOS
ln -s ../models/stable-diffusion-xl-base-1.0 models/checkpoints

cd ..
```

## 启动服务

系统需要启动多个服务，建议按以下顺序启动：

### 1. 启动 Redis

```bash
# Windows（使用 WSL 或 Redis for Windows）
redis-server

# Linux/macOS
redis-server
```

### 2. 启动 ComfyUI

```bash
cd ComfyUI
python main.py

# 验证 ComfyUI 是否启动成功
# 访问 http://127.0.0.1:8188
```

### 3. 启动 Celery Worker

在新的终端窗口中：

```bash
# 激活虚拟环境
source venv/bin/activate  # Linux/macOS
# 或 venv\Scripts\activate  # Windows

# 启动 Celery Worker
celery -A src.tasks.celery_app worker --loglevel=info --concurrency=2
```

### 4. 启动 FastAPI 服务

在新的终端窗口中：

```bash
# 激活虚拟环境
source venv/bin/activate  # Linux/macOS
# 或 venv\Scripts\activate  # Windows

# 启动 FastAPI
python main.py
```

服务启动后，访问：
- **API 文档**: http://localhost:8000/docs
- **健康检查**: http://localhost:8000/health

## 创建第一个项目

### 方式 1：使用 API 文档（推荐）

1. 访问 http://localhost:8000/docs
2. 点击 **POST /api/auth/register** 注册用户
3. 点击 **POST /api/auth/login** 登录获取 Token
4. 点击右上角 **Authorize** 按钮，输入 Token
5. 点击 **POST /api/projects** 创建项目
6. 点击 **POST /api/projects/{id}/generate-script** 生成剧本
7. 点击 **POST /api/projects/{id}/produce** 提交生产任务
8. 点击 **GET /api/tasks/{id}/status** 查询任务状态

### 方式 2：使用 curl 命令

#### 1. 注册用户

```bash
curl -X POST "http://localhost:8000/api/auth/register" \
  -H "Content-Type: application/json" \
  -d '{
    "username": "demo_user",
    "email": "demo@example.com",
    "password": "demo123456"
  }'
```

#### 2. 登录获取 Token

```bash
curl -X POST "http://localhost:8000/api/auth/login" \
  -H "Content-Type: application/json" \
  -d '{
    "username": "demo_user",
    "password": "demo123456"
  }'
```

保存返回的 `access_token`。

#### 3. 创建项目

```bash
curl -X POST "http://localhost:8000/api/projects" \
  -H "Authorization: Bearer YOUR_ACCESS_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "我的第一个短剧",
    "description": "一个关于友情的温馨故事",
    "theme": "友情、成长、温馨",
    "outline": "讲述两个好朋友在困难时期互相帮助的故事"
  }'
```

保存返回的 `project_id`。

#### 4. 生成剧本

```bash
curl -X POST "http://localhost:8000/api/projects/{project_id}/generate-script" \
  -H "Authorization: Bearer YOUR_ACCESS_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "theme": "友情、成长、温馨",
    "outline": "讲述两个好朋友在困难时期互相帮助的故事"
  }'
```

#### 5. 提交生产任务

```bash
curl -X POST "http://localhost:8000/api/projects/{project_id}/produce" \
  -H "Authorization: Bearer YOUR_ACCESS_TOKEN"
```

保存返回的 `task_id`。

#### 6. 查询任务状态

```bash
curl -X GET "http://localhost:8000/api/tasks/{task_id}/status" \
  -H "Authorization: Bearer YOUR_ACCESS_TOKEN"
```

### 方式 3：使用 Python 脚本

创建 `example.py` 文件：

```python
import requests
import time

# 配置
BASE_URL = "http://localhost:8000"
USERNAME = "demo_user"
PASSWORD = "demo123456"
EMAIL = "demo@example.com"

# 1. 注册用户
response = requests.post(
    f"{BASE_URL}/api/auth/register",
    json={
        "username": USERNAME,
        "email": EMAIL,
        "password": PASSWORD
    }
)
print(f"注册结果: {response.status_code}")

# 2. 登录获取 Token
response = requests.post(
    f"{BASE_URL}/api/auth/login",
    json={
        "username": USERNAME,
        "password": PASSWORD
    }
)
token = response.json()["access_token"]
print(f"登录成功，Token: {token[:20]}...")

# 设置认证头
headers = {"Authorization": f"Bearer {token}"}

# 3. 创建项目
response = requests.post(
    f"{BASE_URL}/api/projects",
    headers=headers,
    json={
        "name": "我的第一个短剧",
        "description": "一个关于友情的温馨故事",
        "theme": "友情、成长、温馨",
        "outline": "讲述两个好朋友在困难时期互相帮助的故事"
    }
)
project = response.json()
project_id = project["id"]
print(f"项目创建成功，ID: {project_id}")

# 4. 生成剧本
response = requests.post(
    f"{BASE_URL}/api/projects/{project_id}/generate-script",
    headers=headers,
    json={
        "theme": "友情、成长、温馨",
        "outline": "讲述两个好朋友在困难时期互相帮助的故事"
    }
)
print(f"剧本生成成功")

# 5. 提交生产任务
response = requests.post(
    f"{BASE_URL}/api/projects/{project_id}/produce",
    headers=headers
)
task = response.json()
task_id = task["task_id"]
print(f"生产任务提交成功，任务 ID: {task_id}")

# 6. 轮询任务状态
while True:
    response = requests.get(
        f"{BASE_URL}/api/tasks/{task_id}/status",
        headers=headers
    )
    status = response.json()
    print(f"任务状态: {status['status']}, 进度: {status['progress']}%")
    
    if status["status"] in ["completed", "failed"]:
        break
    
    time.sleep(10)  # 每 10 秒查询一次

print("任务完成！")
```

运行脚本：

```bash
python example.py
```

## 常见问题

### Q1: 模型下载速度慢怎么办？

**A**: 可以使用镜像站点或代理：

```bash
# 使用 HuggingFace 镜像
export HF_ENDPOINT=https://hf-mirror.com

# 或使用代理
export HTTP_PROXY=http://your-proxy:port
export HTTPS_PROXY=http://your-proxy:port
```

### Q2: GPU 显存不足怎么办？

**A**: 调整 GPU 层数配置：

```bash
# 在 .env 文件中调整
LLM_N_GPU_LAYERS=15  # 从 20 降到 15
```

或降低图像/视频分辨率：

```bash
# 在 ComfyUI 工作流中调整分辨率
# 从 768x768 降到 512x512
```

### Q3: ComfyUI 启动失败怎么办？

**A**: 检查以下几点：

1. 确认 SD 模型已正确链接到 ComfyUI models 目录
2. 确认端口 8188 未被占用
3. 查看 ComfyUI 日志输出

```bash
# 检查端口占用
netstat -ano | findstr 8188  # Windows
lsof -i :8188  # Linux/macOS
```

### Q4: Celery Worker 无法连接 Redis？

**A**: 确认 Redis 服务已启动：

```bash
# 测试 Redis 连接
redis-cli ping
# 应该返回 PONG
```

检查 Redis URL 配置：

```bash
# 在 .env 文件中
REDIS_URL=redis://localhost:6379/0
```

### Q5: 生成的视频质量不好怎么办？

**A**: 可以调整以下参数：

1. **增加采样步数**（提高图像质量）：
   - 在 ComfyUI 工作流中调整 `steps` 参数（从 20 增加到 30-50）

2. **增加视频帧数**（提高视频流畅度）：
   ```bash
   # 在 .env 文件中
   SVD_NUM_FRAMES=25  # 从 16 增加到 25
   ```

3. **调整 CFG Scale**（提高图像细节）：
   - 在 ComfyUI 工作流中调整 `cfg_scale` 参数（从 7.0 增加到 8.0-9.0）

### Q6: TTS API 配额不足怎么办？

**A**: 

1. 申请更多配额：访问 https://mimo.xiaomi.com 申请
2. 使用本地 TTS 服务（需要额外配置）
3. 减少生成的分镜数量

### Q7: 任务执行失败怎么办？

**A**: 查看日志文件：

```bash
# 查看 FastAPI 日志
tail -f logs/app.log

# 查看 Celery Worker 日志
# 在 Celery Worker 终端查看输出
```

常见失败原因：
- GPU 显存不足：降低并发任务数或调整模型配置
- 模型加载失败：检查模型文件路径和完整性
- API 调用失败：检查网络连接和 API 密钥

### Q8: 如何查看生成的视频？

**A**: 生成的文件保存在 `storage/` 目录：

```
storage/
├── projects/
│   └── {project_id}/
│       ├── images/      # 生成的图像
│       ├── videos/      # 生成的视频片段
│       ├── audios/      # 生成的音频
│       ├── subtitles/   # 生成的字幕
│       └── final_video.mp4  # 最终合成的视频
```

也可以通过 API 获取文件 URL：

```bash
curl -X GET "http://localhost:8000/api/projects/{project_id}" \
  -H "Authorization: Bearer YOUR_ACCESS_TOKEN"
```

## 下一步

- 阅读 [用户手册](user-manual.md) 了解更多功能
- 查看 [API 文档](api-documentation.md) 了解所有 API 端点
- 阅读 [最佳实践指南](best-practices.md) 优化生成质量
- 加入社区讨论：[GitHub Discussions](https://github.com/your-org/ai-short-drama-production/discussions)

## 获取帮助

如果遇到问题，可以：

1. 查看 [常见问题解答（FAQ）](faq.md)
2. 搜索 [GitHub Issues](https://github.com/your-org/ai-short-drama-production/issues)
3. 提交新的 Issue
4. 加入 Discord 社区

祝您使用愉快！🎬
