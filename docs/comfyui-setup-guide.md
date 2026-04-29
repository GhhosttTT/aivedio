# ComfyUI 安装和配置指南

本文档详细说明如何安装和配置 ComfyUI 服务，用于 AI 短剧自动化生产平台的图像生成功能。

## 📋 概述

ComfyUI 是一个强大的 Stable Diffusion 图形界面，支持节点式工作流。我们使用它来生成短剧分镜图像。

**功能**:
- 使用 Stable Diffusion XL 生成高质量图像
- 支持自定义工作流
- 提供 REST API 接口
- 支持批量生成

## 🚀 快速开始

### 方法 1: 使用自动安装脚本（推荐）

```bash
# 1. 运行安装脚本
bash scripts/setup_comfyui.sh

# 2. 启动 ComfyUI 服务
bash scripts/start_comfyui.sh

# 3. 访问 Web 界面
# http://127.0.0.1:8188
```

### 方法 2: 手动安装

如果自动脚本失败，可以手动安装。

#### 1. 克隆 ComfyUI 仓库

```bash
git clone https://github.com/comfyanonymous/ComfyUI.git comfyui
cd comfyui
```

#### 2. 创建 Python 虚拟环境

```bash
python3 -m venv venv

# Linux/Mac
source venv/bin/activate

# Windows
venv\Scripts\activate
```

#### 3. 安装依赖

```bash
# 升级 pip
pip install --upgrade pip

# 安装 ComfyUI 依赖
pip install -r requirements.txt

# 安装 PyTorch (CUDA 11.8)
pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu118
```

#### 4. 链接模型文件

```bash
# Linux/Mac
ln -s $(pwd)/../models/stable-diffusion-xl-base-1.0/sd_xl_base_1.0.safetensors \
      models/checkpoints/sd_xl_base_1.0.safetensors

# Windows (以管理员身份运行)
mklink models\checkpoints\sd_xl_base_1.0.safetensors \
      ..\models\stable-diffusion-xl-base-1.0\sd_xl_base_1.0.safetensors
```

#### 5. 启动 ComfyUI

```bash
python main.py --listen 0.0.0.0 --port 8188
```

## 🔧 配置说明

### 工作流配置文件

工作流配置文件位于 `configs/comfyui_workflow.json`，定义了图像生成的节点和参数。

**主要配置项**:

```json
{
  "parameters": {
    "default": {
      "width": 1024,
      "height": 1024,
      "steps": 20,
      "cfg_scale": 7.0,
      "sampler": "euler",
      "scheduler": "normal"
    }
  }
}
```

### 预设配置

系统提供三种预设配置：

| 预设 | 步数 | CFG Scale | 描述 |
|------|------|-----------|------|
| fast | 15 | 6.0 | 快速生成，质量略低 |
| balanced | 20 | 7.0 | 平衡质量和速度（推荐） |
| quality | 30 | 8.0 | 高质量生成，速度较慢 |

### 分辨率预设

| 预设 | 宽度 | 高度 | 比例 | 用途 |
|------|------|------|------|------|
| square_1024 | 1024 | 1024 | 1:1 | 正方形图像 |
| landscape_16_9 | 1344 | 768 | 16:9 | 横屏视频 |
| portrait_9_16 | 768 | 1344 | 9:16 | 竖屏视频 |

### 负面提示词

默认负面提示词用于排除不需要的内容：

```
nsfw, nude, lowres, bad anatomy, bad hands, text, error, 
missing fingers, extra digit, fewer digits, cropped, 
worst quality, low quality, normal quality, jpeg artifacts, 
signature, watermark, username, blurry
```

## 🌐 API 使用

### 检查服务状态

```bash
curl http://127.0.0.1:8188/system_stats
```

### 生成图像

```bash
curl -X POST http://127.0.0.1:8188/prompt \
  -H "Content-Type: application/json" \
  -d '{
    "prompt": {
      "3": {
        "inputs": {
          "text": "a beautiful landscape with mountains and lake",
          "clip": ["4", 1]
        },
        "class_type": "CLIPTextEncode"
      }
    }
  }'
```

### 查询任务状态

```bash
curl http://127.0.0.1:8188/history/{prompt_id}
```

## 📊 性能优化

### GPU 显存优化

ComfyUI 使用 SDXL 模型需要约 8-10GB 显存。

**优化建议**:

1. **降低分辨率**:
   ```json
   {
     "width": 768,
     "height": 768
   }
   ```

2. **减少采样步数**:
   ```json
   {
     "steps": 15
   }
   ```

3. **使用 FP16 精度**:
   ComfyUI 默认使用 FP16，无需额外配置

4. **批量生成优化**:
   ```json
   {
     "batch_size": 1  // 避免批量生成以节省显存
   }
   ```

### 生成速度优化

| 配置 | 生成时间 | 质量 |
|------|----------|------|
| 768x768, 15 steps | ~10秒 | 中等 |
| 1024x1024, 20 steps | ~15秒 | 良好 |
| 1024x1024, 30 steps | ~25秒 | 优秀 |

*基于 RTX 4090 测试数据*

## 🔍 故障排查

### 问题 1: ComfyUI 启动失败

**症状**: 运行 `python main.py` 报错

**可能原因**:
- Python 版本不兼容（需要 3.10+）
- PyTorch 未正确安装
- 缺少依赖包

**解决方案**:
```bash
# 检查 Python 版本
python --version

# 重新安装 PyTorch
pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu118

# 重新安装依赖
pip install -r requirements.txt
```

### 问题 2: 模型加载失败

**症状**: Web 界面显示"模型未找到"

**可能原因**:
- 模型文件未正确链接
- 模型文件路径错误

**解决方案**:
```bash
# 检查模型文件是否存在
ls -l comfyui/models/checkpoints/

# 重新链接模型
ln -s $(pwd)/models/stable-diffusion-xl-base-1.0/sd_xl_base_1.0.safetensors \
      comfyui/models/checkpoints/sd_xl_base_1.0.safetensors
```

### 问题 3: GPU 显存不足

**症状**: 生成图像时报 CUDA out of memory

**可能原因**:
- 分辨率过高
- 其他程序占用显存

**解决方案**:
1. 降低分辨率（从 1024 降到 768）
2. 关闭其他占用 GPU 的程序
3. 清理 GPU 缓存:
   ```python
   import torch
   torch.cuda.empty_cache()
   ```

### 问题 4: API 连接失败

**症状**: 无法访问 http://127.0.0.1:8188

**可能原因**:
- ComfyUI 未启动
- 端口被占用
- 防火墙阻止

**解决方案**:
```bash
# 检查 ComfyUI 是否运行
ps aux | grep "python main.py"

# 检查端口占用
netstat -an | grep 8188

# 尝试使用其他端口
python main.py --listen 0.0.0.0 --port 8189
```

### 问题 5: 生成速度慢

**可能原因**:
- GPU 未正确使用
- 采样步数过多
- 分辨率过高

**解决方案**:
```bash
# 检查 GPU 使用情况
nvidia-smi

# 使用快速预设
# 在工作流中设置: steps=15, cfg_scale=6.0

# 降低分辨率
# 在工作流中设置: width=768, height=768
```

## 📚 参考资源

- [ComfyUI 官方仓库](https://github.com/comfyanonymous/ComfyUI)
- [ComfyUI 文档](https://github.com/comfyanonymous/ComfyUI/wiki)
- [Stable Diffusion XL 文档](https://huggingface.co/stabilityai/stable-diffusion-xl-base-1.0)
- [ComfyUI 工作流示例](https://comfyanonymous.github.io/ComfyUI_examples/)

## ✅ 验证安装

安装完成后，执行以下步骤验证：

### 1. 检查服务状态

```bash
curl http://127.0.0.1:8188/system_stats
```

预期输出：
```json
{
  "system": {
    "os": "...",
    "python_version": "...",
    "pytorch_version": "..."
  },
  "devices": [
    {
      "name": "NVIDIA GeForce RTX 4090",
      "type": "cuda",
      "vram_total": 25769803776,
      "vram_free": 24000000000
    }
  ]
}
```

### 2. 访问 Web 界面

打开浏览器访问: http://127.0.0.1:8188

应该看到 ComfyUI 的节点编辑器界面。

### 3. 测试图像生成

在 Web 界面中：
1. 加载默认工作流
2. 在 CLIP Text Encode 节点输入提示词
3. 点击 "Queue Prompt" 生成图像
4. 等待生成完成（约 15-20 秒）

## 🎯 下一步

ComfyUI 安装和配置完成后，继续以下步骤：

1. **实现 ComfyUI 服务类** (任务 3.6)
2. **测试图像生成功能** (任务 3.6.5)
3. **集成到生产流程** (任务 5.1)

---

**提示**: ComfyUI 首次启动会下载一些额外的模型文件（如 VAE），这是正常现象。
