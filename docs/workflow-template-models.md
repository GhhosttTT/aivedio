# 工作流模板模型配置说明

本文档说明每个工作流模板使用的 Checkpoint 模型和 LoRA 模型。

---

## 模板列表

### 1. 基础文生图模板 (`basic-txt2img`)

**Checkpoint 模型**: `dreamshaper_8.safetensors`

**LoRA 模型**: 无

**模型说明**:
- DreamShaper 8 是一个通用的 SDXL 模型
- 适合各种场景的图像生成
- 平衡了质量和速度
- 适合快速生成和测试

**下载地址**:
- Civitai: https://civitai.com/models/112902/dreamshaper-xl

---

### 2. IP-Adapter 模板 (`ipadapter-template`)

**Checkpoint 模型**: `juggernautXL_v9Rundiffusionphoto2.safetensors`

**LoRA 模型**: 无

**模型说明**:
- Juggernaut XL 是一个专门优化的人物生成模型
- 特别适合人物特写和全身照
- 与 IP-Adapter 配合效果极佳
- 能够保持人物一致性

**下载地址**:
- Civitai: https://civitai.com/models/133005/juggernaut-xl

---

### 3. 真实感增强模板 (`realism-enhanced`)

**Checkpoint 模型**: `RealVisXL_V4.0.safetensors`

**LoRA 模型**: 
- `FilmGrain.safetensors` - Film Grain 效果

**模型说明**:
- RealVisXL V4.0 是目前最真实的 SDXL 模型之一
- 专门优化了真实感和自然光照
- 配合 Film Grain LoRA 可以模拟胶片质感
- 适合需要极高真实感的场景

**下载地址**:
- Checkpoint: https://civitai.com/models/139562/realvisxl-v40
- Film Grain LoRA: https://civitai.com/models/123456/film-grain-lora (示例链接)

---

### 4. 高清修复模板 (`hires-fix`)

**Checkpoint 模型**: `dreamshaper_8.safetensors`

**LoRA 模型**: 
- `add_detail.safetensors` - 细节增强

**模型说明**:
- 使用 DreamShaper 8 作为基础模型
- 配合 Add Detail LoRA 增强细节
- 适合放大和高清修复
- 可以提升图像分辨率和细节

**下载地址**:
- Checkpoint: https://civitai.com/models/112902/dreamshaper-xl
- Add Detail LoRA: https://civitai.com/models/122359/detail-tweaker-xl

---

### 5. 快速生成模板 (`fast-generation`)

**Checkpoint 模型**: `sd_xl_turbo_1.0.safetensors`

**LoRA 模型**: 无

**模型说明**:
- SDXL Turbo 是 Stability AI 官方的快速生成模型
- 只需 4-8 步即可生成高质量图像
- 速度比标准 SDXL 快 5-10 倍
- 适合快速预览和迭代

**下载地址**:
- Hugging Face: https://huggingface.co/stabilityai/sdxl-turbo

---

## 模型下载和安装

### 1. 下载模型

所有模型都需要下载到 ComfyUI 的 `models` 目录：

```
ComfyUI/
├── models/
│   ├── checkpoints/          # Checkpoint 模型放这里
│   │   ├── dreamshaper_8.safetensors
│   │   ├── juggernautXL_v9Rundiffusionphoto2.safetensors
│   │   ├── RealVisXL_V4.0.safetensors
│   │   └── sd_xl_turbo_1.0.safetensors
│   └── loras/                # LoRA 模型放这里
│       ├── FilmGrain.safetensors
│       └── add_detail.safetensors
```

### 2. 使用脚本下载

可以使用项目提供的下载脚本：

**Windows (PowerShell)**:
```powershell
.\scripts\download_models.ps1
```

**Linux/Mac (Bash)**:
```bash
bash scripts/download_models.sh
```

### 3. 手动下载

如果脚本下载失败，可以手动从 Civitai 或 Hugging Face 下载模型文件，然后放到对应目录。

---

## 模型配置说明

### Checkpoint 模型

Checkpoint 模型是 Stable Diffusion 的主模型，决定了生成图像的整体风格和质量。

**选择建议**:
- **通用场景**: DreamShaper 8
- **人物生成**: Juggernaut XL
- **真实感**: RealVisXL V4.0
- **快速生成**: SDXL Turbo

### LoRA 模型

LoRA 是轻量级的微调模型，可以在不改变主模型的情况下添加特定效果。

**常用 LoRA**:
- **Film Grain**: 添加胶片颗粒感，增强真实感
- **Add Detail**: 增强细节，提升图像清晰度
- **Style LoRA**: 添加特定艺术风格

### 模型权重

LoRA 模型通常有一个权重参数（0.0-1.0）：
- **0.3-0.5**: 轻微效果
- **0.6-0.8**: 中等效果
- **0.9-1.0**: 强烈效果

---

## 模型兼容性

### SDXL 模型

所有模板都使用 SDXL 系列模型，确保兼容性：
- 分辨率: 1024x1024 或更高
- VAE: 内置或使用 sdxl_vae.safetensors
- CLIP: SDXL CLIP 模型

### SD 1.5 模型

如果需要使用 SD 1.5 模型，需要：
1. 修改模板配置中的 checkpoint 字段
2. 调整分辨率为 512x512 或 768x768
3. 使用对应的 VAE 和 CLIP 模型

---

## 模型性能对比

| 模型 | 质量 | 速度 | 显存占用 | 适用场景 |
|------|------|------|----------|----------|
| DreamShaper 8 | ⭐⭐⭐⭐ | ⭐⭐⭐⭐ | 6-8 GB | 通用 |
| Juggernaut XL | ⭐⭐⭐⭐⭐ | ⭐⭐⭐ | 8-10 GB | 人物 |
| RealVisXL V4.0 | ⭐⭐⭐⭐⭐ | ⭐⭐⭐ | 8-10 GB | 真实感 |
| SDXL Turbo | ⭐⭐⭐ | ⭐⭐⭐⭐⭐ | 6-8 GB | 快速预览 |

---

## 自定义模型配置

### 修改模板使用的模型

如果你想使用其他模型，可以在创建配置时覆盖：

```python
from src.services.workflow_template import get_workflow_template_manager

manager = get_workflow_template_manager()
template = manager.get_template("basic-txt2img")

# 使用自定义模型
config = template.create_config({
    "checkpoint": "my_custom_model.safetensors",
    "lora_models": ["my_lora.safetensors"],
    "sampling_steps": 25
})
```

### 添加新模板

如果你有自己喜欢的模型组合，可以创建自定义模板：

```python
from src.services.workflow_template import (
    WorkflowTemplate,
    TemplateCategory,
    get_workflow_template_manager
)
from src.models.workflow_config import WorkflowType

# 创建自定义模板
custom_template = WorkflowTemplate(
    id="my-custom-template",
    name="我的自定义模板",
    description="使用我喜欢的模型组合",
    category=TemplateCategory.CUSTOM,
    workflow_type=WorkflowType.BASIC,
    base_config={
        "name": "自定义",
        "version": "1.0",
        "nodes": {},
        "parameters": {
            "sampling_steps": 25,
            "cfg_scale": 7.5,
            "checkpoint": "my_favorite_model.safetensors",
            "lora_models": ["my_lora1.safetensors", "my_lora2.safetensors"],
        },
        "negative_prompt": "low quality"
    }
)

# 添加到管理器
manager = get_workflow_template_manager()
manager.add_template(custom_template)

# 保存到文件
manager.save_template(custom_template)
```

---

## 常见问题

### Q: 模型文件太大，下载很慢怎么办？

A: 可以使用以下方法：
1. 使用国内镜像站下载（如 HuggingFace 镜像）
2. 使用下载工具（如 aria2c）多线程下载
3. 只下载必需的模型，其他模型按需下载

### Q: 显存不够，无法加载模型怎么办？

A: 可以：
1. 使用 SDXL Turbo 等轻量级模型
2. 降低分辨率（768x768 或更低）
3. 启用 ComfyUI 的低显存模式
4. 减少 LoRA 数量

### Q: 如何知道模型是否兼容？

A: 检查以下几点：
1. 模型类型（SDXL 或 SD 1.5）
2. 模型格式（.safetensors 或 .ckpt）
3. 模型大小（SDXL 约 6-7 GB，SD 1.5 约 2-4 GB）
4. 在 ComfyUI 中测试加载

### Q: 可以混用不同版本的模型吗？

A: 一般不建议：
- SDXL 模型应该配合 SDXL LoRA
- SD 1.5 模型应该配合 SD 1.5 LoRA
- 混用可能导致效果不佳或报错

---

## 推荐模型组合

### 人物特写（高质量）
- Checkpoint: RealVisXL V4.0
- LoRA: FilmGrain.safetensors
- 采样步数: 30-35
- CFG Scale: 5.5-6.5

### 人物全身（一致性）
- Checkpoint: Juggernaut XL
- LoRA: 无
- 采样步数: 25-30
- CFG Scale: 6.0-7.0
- 使用 IP-Adapter

### 风景场景
- Checkpoint: DreamShaper 8
- LoRA: Add Detail
- 采样步数: 25-30
- CFG Scale: 7.0-8.0

### 快速预览
- Checkpoint: SDXL Turbo
- LoRA: 无
- 采样步数: 4-8
- CFG Scale: 1.0-2.0

---

## 更新日志

- **2026-05-06**: 初始版本，添加 5 个预定义模板的模型配置

---

*文档版本: 1.0*  
*最后更新: 2026-05-06*
