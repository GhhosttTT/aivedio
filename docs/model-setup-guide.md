# AI 模型下载和配置指南

本文档详细说明如何下载和配置 AI 短剧自动化生产平台所需的所有 AI 模型。

## 📋 模型清单

| 模型 | 大小 | 用途 | 下载链接 |
|------|------|------|----------|
| Qwen2.5-14B-Instruct (Q4_K_M) | ~8GB | 剧本生成 | [HuggingFace](https://huggingface.co/Qwen/Qwen2.5-14B-Instruct-GGUF) |
| Stable Diffusion XL Base 1.0 | ~6.9GB | 图像生成 | [HuggingFace](https://huggingface.co/stabilityai/stable-diffusion-xl-base-1.0) |
| Stable Video Diffusion XT | ~3.8GB | 图生视频 | [HuggingFace](https://huggingface.co/stabilityai/stable-video-diffusion-img2vid-xt) |

**总大小**: 约 18-20GB

## 🚀 快速开始

### 方法 1: 使用自动下载脚本（推荐）

```bash
# 1. 运行下载脚本
bash scripts/download_models.sh

# 2. 验证模型文件
python scripts/verify_models.py

# 3. 检查 .env 文件配置
cat .env
```

### 方法 2: 手动下载

如果自动脚本失败或网络不稳定，可以手动下载模型。

#### 1. 创建模型目录

```bash
mkdir -p models/stable-diffusion-xl-base-1.0
mkdir -p models/stable-video-diffusion-img2vid-xt
```

#### 2. 下载 Qwen2.5-14B 模型

```bash
# 使用 wget
wget https://huggingface.co/Qwen/Qwen2.5-14B-Instruct-GGUF/resolve/main/qwen2.5-14b-instruct-q4_k_m.gguf \
  -O models/qwen2.5-14b-instruct-q4_k_m.gguf

# 或使用 curl
curl -L https://huggingface.co/Qwen/Qwen2.5-14B-Instruct-GGUF/resolve/main/qwen2.5-14b-instruct-q4_k_m.gguf \
  -o models/qwen2.5-14b-instruct-q4_k_m.gguf
```

#### 3. 下载 Stable Diffusion XL 模型

```bash
# 使用 wget
wget https://huggingface.co/stabilityai/stable-diffusion-xl-base-1.0/resolve/main/sd_xl_base_1.0.safetensors \
  -O models/stable-diffusion-xl-base-1.0/sd_xl_base_1.0.safetensors

# 或使用 curl
curl -L https://huggingface.co/stabilityai/stable-diffusion-xl-base-1.0/resolve/main/sd_xl_base_1.0.safetensors \
  -o models/stable-diffusion-xl-base-1.0/sd_xl_base_1.0.safetensors
```

#### 4. 下载 Stable Video Diffusion 模型

```bash
# 使用 wget
wget https://huggingface.co/stabilityai/stable-video-diffusion-img2vid-xt/resolve/main/svd_xt.safetensors \
  -O models/stable-video-diffusion-img2vid-xt/svd_xt.safetensors

# 或使用 curl
curl -L https://huggingface.co/stabilityai/stable-video-diffusion-img2vid-xt/resolve/main/svd_xt.safetensors \
  -o models/stable-video-diffusion-img2vid-xt/svd_xt.safetensors
```

#### 5. 配置环境变量

复制 `.env.example` 到 `.env` 并更新模型路径：

```bash
cp .env.example .env
```

编辑 `.env` 文件，确保以下配置正确：

```bash
# LLM 配置
LLM_MODEL_PATH=./models/qwen2.5-14b-instruct-q4_k_m.gguf

# SDXL 配置
SDXL_MODEL_PATH=./models/stable-diffusion-xl-base-1.0/sd_xl_base_1.0.safetensors

# SVD 配置
SVD_MODEL_PATH=./models/stable-video-diffusion-img2vid-xt
```

## 🔍 验证模型文件

运行验证脚本检查模型文件是否完整：

```bash
python scripts/verify_models.py
```

验证脚本会检查：
- ✅ 文件是否存在
- ✅ 文件大小是否正常
- ✅ 文件完整性（可选）

## 📦 模型详细信息

### 1. Qwen2.5-14B-Instruct (Q4_K_M)

**用途**: 剧本生成和文本处理

**特点**:
- 14B 参数的大语言模型
- Q4_K_M 量化版本，平衡性能和质量
- 支持 CPU offload，降低显存需求

**配置参数**:
```bash
LLM_MODEL_PATH=./models/qwen2.5-14b-instruct-q4_k_m.gguf
LLM_N_GPU_LAYERS=20        # GPU 加载的层数
LLM_N_CTX=4096             # 上下文窗口大小
LLM_N_THREADS=8            # CPU 线程数
```

**显存需求**: 4-6GB（n_gpu_layers=20）

### 2. Stable Diffusion XL Base 1.0

**用途**: 高质量图像生成

**特点**:
- SDXL 基础模型
- 支持 1024x1024 分辨率
- 通过 ComfyUI 调用

**配置参数**:
```bash
SDXL_MODEL_PATH=./models/stable-diffusion-xl-base-1.0/sd_xl_base_1.0.safetensors
COMFYUI_BASE_URL=http://127.0.0.1:8188
```

**显存需求**: 8-10GB

### 3. Stable Video Diffusion (SVD-XT)

**用途**: 图像转视频

**特点**:
- 基于图像生成短视频
- 支持 16-25 帧
- XT 版本支持更长视频

**配置参数**:
```bash
SVD_MODEL_PATH=./models/stable-video-diffusion-img2vid-xt
SVD_NUM_FRAMES=16          # 视频帧数
SVD_FPS=8                  # 视频帧率
```

**显存需求**: 8-10GB

## 💾 存储要求

### 磁盘空间

- **模型文件**: ~18-20GB
- **生成文件**: 建议预留 100GB+
- **总计**: 建议至少 150GB 可用空间

### 推荐配置

- **SSD**: 强烈推荐，可显著提高模型加载速度
- **HDD**: 可用，但模型加载会较慢

## 🎮 GPU 显存分配

### 单张 RTX 4090 (24GB)

```
┌─────────────────────────────────────┐
│ GPU 显存分配 (24GB)                  │
├─────────────────────────────────────┤
│ LLM (Qwen2.5-14B)    │ 4-6GB        │
│ SD (SDXL)            │ 8-10GB       │
│ SVD                  │ 8-10GB       │
│ 系统预留              │ 2-4GB        │
└─────────────────────────────────────┘
```

**优化策略**:
- LLM 使用 CPU offload（n_gpu_layers=20）
- SD 和 SVD 串行执行，避免显存冲突
- 任务切换时清理 GPU 缓存

### 显存不足时的优化

如果遇到显存不足，可以尝试：

1. **减少 LLM GPU 层数**:
   ```bash
   LLM_N_GPU_LAYERS=15  # 从 20 降到 15
   ```

2. **降低图像分辨率**:
   ```bash
   # 从 1024x1024 降到 768x768
   ```

3. **减少视频帧数**:
   ```bash
   SVD_NUM_FRAMES=12  # 从 16 降到 12
   ```

4. **启用 FP16 精度**:
   ```bash
   GPU_MEMORY_FRACTION=0.95
   ```

## 🔧 故障排查

### 问题 1: 下载速度慢

**原因**: HuggingFace 服务器在国外

**解决方案**:
1. 使用 HuggingFace 镜像站
2. 使用下载工具（如 aria2c）
3. 使用代理或 VPN

### 问题 2: 下载中断

**原因**: 网络不稳定

**解决方案**:
1. 重新运行下载脚本（支持断点续传）
2. 使用 `wget -c` 或 `curl -C -` 继续下载

### 问题 3: 文件完整性验证失败

**原因**: 文件下载不完整或损坏

**解决方案**:
1. 删除损坏的文件
2. 重新下载
3. 检查磁盘空间

### 问题 4: 模型加载失败

**原因**: 文件路径错误或权限问题

**解决方案**:
1. 检查 `.env` 文件中的路径配置
2. 确保文件有读取权限
3. 使用绝对路径

## 📚 参考资源

- [Qwen2.5 官方文档](https://github.com/QwenLM/Qwen2.5)
- [Stable Diffusion XL 文档](https://huggingface.co/stabilityai/stable-diffusion-xl-base-1.0)
- [Stable Video Diffusion 文档](https://huggingface.co/stabilityai/stable-video-diffusion-img2vid-xt)
- [ComfyUI 文档](https://github.com/comfyanonymous/ComfyUI)

## ✅ 下一步

模型下载和配置完成后，继续以下步骤：

1. **配置 ComfyUI 服务** (任务 1.1.6)
2. **测试 GPU 环境** (任务 1.6)
3. **实现 LLM 服务** (任务 3.1)

---

**提示**: 首次加载模型会较慢（可能需要几分钟），这是正常现象。建议实现模型预热功能以优化用户体验。
