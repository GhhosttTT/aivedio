# AI 短剧自动化生产平台 - 模型部署指南

本指南详细说明如何下载、配置和部署所有 AI 模型。

## 目录

- [系统要求](#系统要求)
- [模型清单](#模型清单)
- [模型下载](#模型下载)
- [模型配置](#模型配置)
- [GPU 配置](#gpu-配置)
- [ComfyUI 部署](#comfyui-部署)
- [服务启动顺序](#服务启动顺序)
- [常见问题排查](#常见问题排查)

---

## 系统要求

### 硬件要求

| 组件 | 最低配置 | 推荐配置 |
|------|---------|---------|
| CPU | 8 核 | 16 核+ |
| 内存 | 32GB | 64GB+ |
| GPU | NVIDIA RTX 3090 (24GB) | NVIDIA RTX 4090 (24GB) |
| 存储 | 100GB SSD | 500GB+ NVMe SSD |
| 网络 | 100Mbps | 1Gbps+ |

### 软件要求

| 软件 | 版本要求 | 说明 |
|------|---------|------|
| 操作系统 | Ubuntu 22.04 LTS | 推荐使用 Linux |
| Python | 3.10+ | 必需 |
| CUDA | 11.8+ | GPU 加速必需 |
| cuDNN | 8.6+ | GPU 加速必需 |
| Docker | 20.10+ | 容器化部署 |
| Docker Compose | 2.0+ | 服务编排 |
| NVIDIA Docker | 2.0+ | GPU 容器支持 |

---

## 模型清单

### 1. Qwen2.5-14B-Instruct（剧本生成）

- **用途**：生成短剧剧本、对话和场景描述
- **模型格式**：GGUF（量化格式）
- **推荐版本**：Q4_K_M（4-bit 量化）
- **文件大小**：约 8.5GB
- **显存占用**：4-6GB（使用 CPU offload）
- **下载链接**：
  - HuggingFace: https://huggingface.co/Qwen/Qwen2.5-14B-Instruct-GGUF
  - ModelScope: https://modelscope.cn/models/Qwen/Qwen2.5-14B-Instruct-GGUF

### 2. Stable Diffusion XL Base 1.0（图像生成）

- **用途**：根据文本提示词生成分镜图像
- **模型格式**：SafeTensors
- **文件大小**：约 6.9GB
- **显存占用**：8-10GB
- **下载链接**：
  - HuggingFace: https://huggingface.co/stabilityai/stable-diffusion-xl-base-1.0
  - Civitai: https://civitai.com/models/101055/sd-xl

### 3. Stable Video Diffusion XT（图生视频）

- **用途**：将静态图像转换为短视频
- **模型格式**：SafeTensors
- **文件大小**：约 3.8GB
- **显存占用**：8-10GB
- **下载链接**：
  - HuggingFace: https://huggingface.co/stabilityai/stable-video-diffusion-img2vid-xt

### 4. MiMo-V2-TTS（配音生成）

- **用途**：生成角色配音
- **类型**：在线 API 服务
- **无需下载**：通过 API 调用
- **需要**：API 密钥
- **申请地址**：https://mimo.xiaomi.com/

---

## 模型下载

### 方法 1：使用下载脚本（推荐）

我们提供了自动下载脚本：

```bash
# 下载所有模型
bash scripts/download_models.sh

# 下载特定模型
bash scripts/download_models.sh --model qwen
bash scripts/download_models.sh --model sdxl
bash scripts/download_models.sh --model svd
```

### 方法 2：手动下载

#### 2.1 下载 Qwen2.5-14B-Instruct

```bash
# 创建模型目录
mkdir -p models/qwen

# 使用 huggingface-cli 下载
pip install huggingface-hub
huggingface-cli download Qwen/Qwen2.5-14B-Instruct-GGUF \
    qwen2.5-14b-instruct-q4_k_m.gguf \
    --local-dir models/qwen

# 或使用 wget
wget -P models/qwen \
    https://huggingface.co/Qwen/Qwen2.5-14B-Instruct-GGUF/resolve/main/qwen2.5-14b-instruct-q4_k_m.gguf
```

#### 2.2 下载 Stable Diffusion XL

```bash
# 创建模型目录
mkdir -p models/sdxl

# 使用 huggingface-cli 下载
huggingface-cli download stabilityai/stable-diffusion-xl-base-1.0 \
    sd_xl_base_1.0.safetensors \
    --local-dir models/sdxl

# 或使用 git-lfs
git lfs install
git clone https://huggingface.co/stabilityai/stable-diffusion-xl-base-1.0 models/sdxl
```

#### 2.3 下载 Stable Video Diffusion

```bash
# 创建模型目录
mkdir -p models/svd

# 使用 huggingface-cli 下载
huggingface-cli download stabilityai/stable-video-diffusion-img2vid-xt \
    svd_xt.safetensors \
    --local-dir models/svd

# 或使用 git-lfs
git clone https://huggingface.co/stabilityai/stable-video-diffusion-img2vid-xt models/svd
```

### 验证下载

下载完成后，验证文件完整性：

```bash
# 检查文件大小
ls -lh models/qwen/qwen2.5-14b-instruct-q4_k_m.gguf
ls -lh models/sdxl/sd_xl_base_1.0.safetensors
ls -lh models/svd/svd_xt.safetensors

# 计算 MD5 校验和（可选）
md5sum models/qwen/qwen2.5-14b-instruct-q4_k_m.gguf
md5sum models/sdxl/sd_xl_base_1.0.safetensors
md5sum models/svd/svd_xt.safetensors
```

---

## 模型配置

### 配置文件

在 `.env` 文件中配置模型路径：

```bash
# LLM 配置
LLM_MODEL_PATH=./models/qwen/qwen2.5-14b-instruct-q4_k_m.gguf
LLM_N_GPU_LAYERS=20          # GPU 加速层数（0-40）
LLM_N_CTX=4096               # 上下文长度
LLM_N_THREADS=8              # CPU 线程数

# ComfyUI 配置
COMFYUI_BASE_URL=http://127.0.0.1:8188
COMFYUI_WORKFLOW_PATH=./configs/comfyui_workflow.json

# SVD 配置
SVD_MODEL_PATH=./models/svd/svd_xt.safetensors
SVD_NUM_FRAMES=16            # 视频帧数（14-25）
SVD_FPS=8                    # 帧率

# TTS 配置
TTS_API_KEY=your_mimo_api_key_here
TTS_BASE_URL=https://mimo.xiaomi.com/api/v2/tts
```

### 模型参数说明

#### Qwen2.5-14B 参数

| 参数 | 说明 | 推荐值 | 范围 |
|------|------|--------|------|
| `LLM_N_GPU_LAYERS` | GPU 加速层数 | 20 | 0-40 |
| `LLM_N_CTX` | 上下文长度 | 4096 | 512-8192 |
| `LLM_N_THREADS` | CPU 线程数 | 8 | 4-16 |
| `temperature` | 生成随机性 | 0.7 | 0.0-2.0 |
| `top_p` | 核采样概率 | 0.9 | 0.0-1.0 |

**显存优化建议：**
- `n_gpu_layers=0`：纯 CPU 模式，显存占用 0GB，速度慢
- `n_gpu_layers=20`：混合模式，显存占用 4-6GB，速度适中（推荐）
- `n_gpu_layers=40`：纯 GPU 模式，显存占用 12-15GB，速度快

#### Stable Diffusion XL 参数

| 参数 | 说明 | 推荐值 | 范围 |
|------|------|--------|------|
| `steps` | 采样步数 | 20 | 10-50 |
| `cfg_scale` | 提示词引导强度 | 7.0 | 1.0-20.0 |
| `width` | 图像宽度 | 1024 | 512-2048 |
| `height` | 图像高度 | 768 | 512-2048 |

#### Stable Video Diffusion 参数

| 参数 | 说明 | 推荐值 | 范围 |
|------|------|--------|------|
| `num_frames` | 视频帧数 | 16 | 14-25 |
| `fps` | 帧率 | 8 | 6-12 |
| `motion_bucket_id` | 运动强度 | 127 | 1-255 |
| `noise_aug_strength` | 噪声增强 | 0.02 | 0.0-1.0 |

---

## GPU 配置

### 检查 CUDA 安装

```bash
# 检查 CUDA 版本
nvcc --version

# 检查 GPU 信息
nvidia-smi

# 检查 PyTorch GPU 支持
python3 -c "import torch; print(f'CUDA available: {torch.cuda.is_available()}'); print(f'CUDA version: {torch.version.cuda}')"
```

### 安装 CUDA（如果未安装）

```bash
# Ubuntu 22.04
wget https://developer.download.nvidia.com/compute/cuda/repos/ubuntu2204/x86_64/cuda-keyring_1.0-1_all.deb
sudo dpkg -i cuda-keyring_1.0-1_all.deb
sudo apt-get update
sudo apt-get install cuda-11-8

# 添加到环境变量
echo 'export PATH=/usr/local/cuda-11.8/bin:$PATH' >> ~/.bashrc
echo 'export LD_LIBRARY_PATH=/usr/local/cuda-11.8/lib64:$LD_LIBRARY_PATH' >> ~/.bashrc
source ~/.bashrc
```

### GPU 显存分配策略

**单张 RTX 4090 (24GB) 配置：**

| 服务 | 显存占用 | 说明 |
|------|---------|------|
| LLM (Qwen2.5-14B) | 4-6GB | 使用 CPU offload |
| SD (SDXL) | 8-10GB | 图像生成时 |
| SVD | 8-10GB | 视频生成时 |
| 系统预留 | 2-4GB | 避免 OOM |

**优化策略：**
1. LLM 和 SD/SVD 可以同时运行（LLM 使用 CPU offload）
2. SD 和 SVD 必须串行执行（通过任务调度）
3. 任务切换时清理 GPU 缓存

### GPU 监控

```bash
# 实时监控 GPU 使用
watch -n 1 nvidia-smi

# 查看详细信息
nvidia-smi --query-gpu=index,name,temperature.gpu,utilization.gpu,memory.used,memory.total --format=csv

# 清理 GPU 缓存（Python）
python3 -c "import torch; torch.cuda.empty_cache(); print('GPU cache cleared')"
```

---

## ComfyUI 部署

### 安装 ComfyUI

```bash
# 克隆仓库
git clone https://github.com/comfyanonymous/ComfyUI.git
cd ComfyUI

# 安装依赖
pip install -r requirements.txt

# 链接模型文件
ln -s ../models/sdxl/sd_xl_base_1.0.safetensors models/checkpoints/
```

### 配置工作流

创建 `configs/comfyui_workflow.json`：

```json
{
  "workflow": {
    "nodes": [
      {
        "id": 1,
        "type": "CheckpointLoaderSimple",
        "inputs": {
          "ckpt_name": "sd_xl_base_1.0.safetensors"
        }
      },
      {
        "id": 2,
        "type": "CLIPTextEncode",
        "inputs": {
          "text": "{{positive_prompt}}",
          "clip": ["1", 1]
        }
      },
      {
        "id": 3,
        "type": "CLIPTextEncode",
        "inputs": {
          "text": "{{negative_prompt}}",
          "clip": ["1", 1]
        }
      },
      {
        "id": 4,
        "type": "KSampler",
        "inputs": {
          "seed": "{{seed}}",
          "steps": 20,
          "cfg": 7.0,
          "sampler_name": "euler",
          "scheduler": "normal",
          "denoise": 1.0,
          "model": ["1", 0],
          "positive": ["2", 0],
          "negative": ["3", 0],
          "latent_image": ["5", 0]
        }
      },
      {
        "id": 5,
        "type": "EmptyLatentImage",
        "inputs": {
          "width": 1024,
          "height": 768,
          "batch_size": 1
        }
      },
      {
        "id": 6,
        "type": "VAEDecode",
        "inputs": {
          "samples": ["4", 0],
          "vae": ["1", 2]
        }
      },
      {
        "id": 7,
        "type": "SaveImage",
        "inputs": {
          "filename_prefix": "short_drama",
          "images": ["6", 0]
        }
      }
    ]
  }
}
```

### 启动 ComfyUI

```bash
# 启动服务（默认端口 8188）
python main.py --listen 0.0.0.0 --port 8188

# 后台运行
nohup python main.py --listen 0.0.0.0 --port 8188 > comfyui.log 2>&1 &

# 验证服务
curl http://localhost:8188/
```

---

## 服务启动顺序

### 1. 启动 Redis

```bash
# 使用 Docker
docker run -d --name short-drama-redis -p 6379:6379 redis:7-alpine

# 或使用系统服务
sudo systemctl start redis
```

### 2. 启动 ComfyUI

```bash
cd ComfyUI
python main.py --listen 0.0.0.0 --port 8188
```

### 3. 启动 Celery Worker

```bash
celery -A src.tasks.celery_app worker \
    --loglevel=info \
    --concurrency=2 \
    --queues=default,image,video,audio
```

### 4. 启动 FastAPI 应用

```bash
python main.py
```

### 使用 Docker Compose（推荐）

```bash
# 启动所有服务
docker-compose up -d

# 查看日志
docker-compose logs -f

# 停止服务
docker-compose down
```

---

## 常见问题排查

### 问题 1：LLM 模型加载失败

**症状**：
```
FileNotFoundError: Model file not found
```

**解决方案**：
1. 检查模型文件是否存在：`ls -lh models/qwen/qwen2.5-14b-instruct-q4_k_m.gguf`
2. 检查文件权限：`chmod 644 models/qwen/*.gguf`
3. 验证文件完整性：`md5sum models/qwen/*.gguf`
4. 检查 `.env` 中的路径配置

### 问题 2：GPU 显存不足

**症状**：
```
RuntimeError: CUDA out of memory
```

**解决方案**：
1. 减少 LLM GPU 层数：`LLM_N_GPU_LAYERS=15`（从 20 降到 15）
2. 降低图像分辨率：`width=768, height=512`（从 1024x768 降低）
3. 减少视频帧数：`SVD_NUM_FRAMES=14`（从 16 降到 14）
4. 清理 GPU 缓存：`torch.cuda.empty_cache()`
5. 重启服务释放显存

### 问题 3：ComfyUI 连接失败

**症状**：
```
ConnectionError: Failed to connect to ComfyUI
```

**解决方案**：
1. 检查 ComfyUI 是否启动：`curl http://localhost:8188/`
2. 检查防火墙设置：`sudo ufw allow 8188`
3. 检查 SD 模型是否正确加载
4. 查看 ComfyUI 日志：`tail -f comfyui.log`

### 问题 4：视频生成速度慢

**症状**：
- 单个视频生成时间超过 5 分钟

**解决方案**：
1. 检查 GPU 利用率：`nvidia-smi`
2. 减少视频帧数：`SVD_NUM_FRAMES=14`
3. 降低分辨率：使用 512x512 输入图像
4. 检查磁盘 I/O 性能：使用 SSD
5. 优化 SVD 参数：`motion_bucket_id=100`

### 问题 5：TTS API 调用失败

**症状**：
```
HTTPError: 401 Unauthorized
```

**解决方案**：
1. 检查 API 密钥是否正确：`.env` 中的 `TTS_API_KEY`
2. 检查网络连接：`curl https://mimo.xiaomi.com/`
3. 检查 API 配额：登录 MiMo 平台查看
4. 查看 API 错误日志

### 问题 6：模型下载速度慢

**解决方案**：
1. 使用国内镜像：
   ```bash
   export HF_ENDPOINT=https://hf-mirror.com
   ```
2. 使用代理：
   ```bash
   export HTTP_PROXY=http://proxy:port
   export HTTPS_PROXY=http://proxy:port
   ```
3. 使用多线程下载工具：`aria2c`
4. 使用 ModelScope 镜像站

---

## 性能基准

### 单个分镜生成时间（RTX 4090）

| 步骤 | 时间 | 说明 |
|------|------|------|
| 剧本生成 | 10-30秒 | 取决于剧本长度 |
| 图像生成 | 5-10秒 | SDXL, 20 steps |
| 视频生成 | 30-60秒 | SVD, 16 frames |
| 配音生成 | 2-5秒 | TTS API |
| 字幕生成 | 1-2秒 | FFmpeg |
| **总计** | **48-107秒** | 约 1-2 分钟 |

### 完整项目生成时间（10 个分镜）

| 配置 | 时间 | 说明 |
|------|------|------|
| 串行处理 | 8-18 分钟 | 单个 Worker |
| 并行处理 | 3-6 分钟 | 多个 Worker |

---

## 下一步

- 阅读 [部署文档](deployment-guide.md) 了解完整部署流程
- 阅读 [用户手册](user-manual.md) 了解如何使用系统
- 阅读 [最佳实践](best-practices.md) 了解性能优化建议

---

**更新日期**：2026-04-29  
**版本**：1.0.0
