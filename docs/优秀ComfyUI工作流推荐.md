# 🎨 优秀 ComfyUI 工作流推荐与集成

## 📊 当前工作流问题分析

### 现有工作流的不足

1. **基础功能** - 只有简单的文生图
2. **缺少高级特性** - 没有高清修复、细节增强
3. **角色一致性弱** - IP-Adapter 配置可能不够优化
4. **真实感不足** - 缺少专业的后处理流程

## 🌟 市面上优秀的工作流

### 1. SDXL 真实感人像工作流 ⭐⭐⭐⭐⭐

**来源**: Civitai 社区热门工作流

**特点**:
- ✅ 极致真实感
- ✅ 完整的后处理流程
- ✅ 面部细节优化
- ✅ 高清放大

**核心节点**:
```
CheckpointLoader (RealVisXL)
  ↓
CLIPTextEncode (正面提示词)
  ↓
CLIPTextEncode (负面提示词)
  ↓
EmptyLatentImage (1024x576)
  ↓
KSampler (DPM++ 2M Karras, 28步, CFG 6.0)
  ↓
VAEDecode
  ↓
FaceDetailer (面部细节优化) ⭐
  ↓
UltimateSDUpscale (高清放大 1.5x) ⭐
  ↓
SaveImage
```

**下载**: https://civitai.com/models/workflows

### 2. IP-Adapter 角色一致性工作流 ⭐⭐⭐⭐⭐

**来源**: ComfyUI 官方示例

**特点**:
- ✅ 强大的角色一致性
- ✅ 支持多角色
- ✅ 面部 + 风格双重控制
- ✅ 权重可调

**核心节点**:
```
CheckpointLoader
  ↓
IPAdapterModelLoader (FaceID Plus V2) ⭐
  ↓
LoadImage (参考图像)
  ↓
IPAdapterFaceID (weight: 0.8) ⭐
  ↓
CLIPVisionLoader (CLIP 视觉编码器) ⭐
  ↓
KSampler
  ↓
VAEDecode
  ↓
SaveImage
```

**下载**: https://github.com/cubiq/ComfyUI_IPAdapter_plus

### 3. 电影级光影工作流 ⭐⭐⭐⭐

**来源**: 专业摄影师分享

**特点**:
- ✅ 电影级光影效果
- ✅ 色彩分级
- ✅ 景深控制
- ✅ 胶片质感

**核心节点**:
```
CheckpointLoader
  ↓
LoraLoader (Cinematic Lighting LoRA) ⭐
  ↓
LoraLoader (Film Grain LoRA) ⭐
  ↓
KSampler
  ↓
VAEDecode
  ↓
ColorCorrection (色彩分级) ⭐
  ↓
FilmGrain (胶片颗粒) ⭐
  ↓
SaveImage
```

### 4. 快速生成优化工作流 ⭐⭐⭐⭐

**来源**: 性能优化社区

**特点**:
- ✅ 针对 RTX 3060 优化
- ✅ 生成速度快 (15-20秒)
- ✅ 显存占用低
- ✅ 质量不降低

**核心节点**:
```
CheckpointLoader (Turbo 版本)
  ↓
KSampler (LCM 采样器, 8步) ⭐
  ↓
VAEDecode
  ↓
SaveImage
```

**注意**: 需要 SDXL Turbo 或 LCM LoRA

## 🎯 推荐集成方案

### 方案 A: 真实感增强工作流 (强烈推荐!)

**适用场景**: 现代都市短剧,需要真实感

**工作流结构**:
```json
{
  "workflow_name": "真实感增强工作流",
  "nodes": {
    "1": {
      "class_type": "CheckpointLoaderSimple",
      "inputs": {
        "ckpt_name": "realvisxl_v40.safetensors"
      }
    },
    "2": {
      "class_type": "LoraLoader",
      "inputs": {
        "lora_name": "detail_tweaker_xl.safetensors",
        "strength_model": 0.7,
        "strength_clip": 0.7,
        "model": ["1", 0],
        "clip": ["1", 1]
      }
    },
    "3": {
      "class_type": "CLIPTextEncode",
      "inputs": {
        "text": "raw photo, {prompt}",
        "clip": ["2", 1]
      }
    },
    "4": {
      "class_type": "CLIPTextEncode",
      "inputs": {
        "text": "CGI, 3D render, plastic skin, too perfect",
        "clip": ["2", 1]
      }
    },
    "5": {
      "class_type": "EmptyLatentImage",
      "inputs": {
        "width": 1024,
        "height": 576,
        "batch_size": 1
      }
    },
    "6": {
      "class_type": "KSampler",
      "inputs": {
        "seed": -1,
        "steps": 28,
        "cfg": 6.0,
        "sampler_name": "dpmpp_2m_karras",
        "scheduler": "karras",
        "denoise": 1.0,
        "model": ["2", 0],
        "positive": ["3", 0],
        "negative": ["4", 0],
        "latent_image": ["5", 0]
      }
    },
    "7": {
      "class_type": "VAEDecode",
      "inputs": {
        "samples": ["6", 0],
        "vae": ["1", 2]
      }
    },
    "8": {
      "class_type": "FaceDetailer",
      "inputs": {
        "image": ["7", 0],
        "model": ["2", 0],
        "clip": ["2", 1],
        "vae": ["1", 2],
        "guide_size": 512,
        "guide_size_for": true,
        "max_size": 1024,
        "seed": -1,
        "steps": 20,
        "cfg": 6.0,
        "sampler_name": "dpmpp_2m_karras",
        "scheduler": "karras",
        "denoise": 0.4,
        "feather": 5,
        "crop_factor": 3.0,
        "drop_size": 10,
        "refiner_ratio": 0.2
      }
    },
    "9": {
      "class_type": "SaveImage",
      "inputs": {
        "images": ["8", 0],
        "filename_prefix": "short_drama"
      }
    }
  }
}
```

**关键特性**:
1. **FaceDetailer** - 自动检测并优化面部细节
2. **Detail Tweaker LoRA** - 增强整体细节
3. **真实感提示词** - raw photo 风格
4. **反 AI 感负面词** - 避免 CG 感

### 方案 B: IP-Adapter 角色一致性工作流

**适用场景**: 需要保持角色一致性

**工作流结构**:
```json
{
  "workflow_name": "IP-Adapter 角色一致性",
  "nodes": {
    "1": {
      "class_type": "CheckpointLoaderSimple",
      "inputs": {
        "ckpt_name": "realvisxl_v40.safetensors"
      }
    },
    "2": {
      "class_type": "IPAdapterModelLoader",
      "inputs": {
        "ipadapter_file": "ip-adapter-faceid-plusv2_sdxl.bin"
      }
    },
    "3": {
      "class_type": "CLIPVisionLoader",
      "inputs": {
        "clip_name": "CLIP-ViT-H-14-laion2B-s32B-b79K.safetensors"
      }
    },
    "4": {
      "class_type": "LoadImage",
      "inputs": {
        "image": "{reference_image_path}"
      }
    },
    "5": {
      "class_type": "IPAdapterFaceID",
      "inputs": {
        "weight": 0.8,
        "weight_faceidv2": 1.0,
        "combine_embeds": "concat",
        "start_at": 0.0,
        "end_at": 1.0,
        "embeds_scaling": "V only",
        "model": ["1", 0],
        "ipadapter": ["2", 0],
        "image": ["4", 0],
        "clip_vision": ["3", 0]
      }
    },
    "6": {
      "class_type": "KSampler",
      "inputs": {
        "model": ["5", 0],
        "seed": -1,
        "steps": 28,
        "cfg": 6.5,
        "sampler_name": "dpmpp_2m_karras",
        "scheduler": "karras",
        "denoise": 1.0
      }
    }
  }
}
```

**关键特性**:
1. **FaceID Plus V2** - 最强的面部一致性
2. **CLIP Vision** - 视觉特征提取
3. **权重可调** - 灵活控制一致性强度

### 方案 C: 混合工作流 (最佳方案!)

**结合方案 A + 方案 B**

**工作流结构**:
```
CheckpointLoader (RealVisXL)
  ↓
LoraLoader (Detail Tweaker)
  ↓
IPAdapterFaceID (如果有参考图)
  ↓
CLIPTextEncode (真实感提示词)
  ↓
KSampler (优化参数)
  ↓
VAEDecode
  ↓
FaceDetailer (面部优化)
  ↓
SaveImage
```

## 📥 如何获取这些工作流

### 方法 1: Civitai 下载

1. 访问: https://civitai.com/
2. 搜索: "SDXL workflow realistic"
3. 筛选: ComfyUI 工作流
4. 下载 JSON 文件

### 方法 2: GitHub 仓库

**推荐仓库**:

1. **ComfyUI Examples**
   - https://github.com/comfyanonymous/ComfyUI_examples
   - 官方示例工作流

2. **IP-Adapter Plus**
   - https://github.com/cubiq/ComfyUI_IPAdapter_plus
   - IP-Adapter 工作流

3. **FaceDetailer**
   - https://github.com/Gourieff/comfyui-reactor-node
   - 面部细节优化

### 方法 3: 社区分享

**推荐社区**:

1. **Reddit r/StableDiffusion**
   - 用户分享的工作流

2. **Discord ComfyUI 服务器**
   - 实时交流和分享

3. **B站/YouTube**
   - 视频教程 + 工作流下载

## 🛠️ 集成步骤

### 步骤 1: 安装必要的自定义节点

```bash
cd ComfyUI/custom_nodes

# 1. IP-Adapter Plus
git clone https://github.com/cubiq/ComfyUI_IPAdapter_plus

# 2. FaceDetailer (Impact Pack)
git clone https://github.com/ltdrdata/ComfyUI-Impact-Pack

# 3. Ultimate SD Upscale
git clone https://github.com/ssitu/ComfyUI_UltimateSDUpscale

# 4. ControlNet Preprocessors
git clone https://github.com/Fannovel16/comfyui_controlnet_aux

# 安装依赖
pip install -r ComfyUI_IPAdapter_plus/requirements.txt
pip install -r ComfyUI-Impact-Pack/requirements.txt
```

### 步骤 2: 下载必要的模型

```bash
# IP-Adapter 模型
cd ComfyUI/models/ipadapter
wget https://huggingface.co/h94/IP-Adapter/resolve/main/sdxl_models/ip-adapter-faceid-plusv2_sdxl.bin

# CLIP Vision 模型
cd ComfyUI/models/clip_vision
wget https://huggingface.co/h94/IP-Adapter/resolve/main/models/image_encoder/model.safetensors

# InsightFace 模型 (FaceID)
cd ComfyUI/models/insightface
wget https://github.com/deepinsight/insightface/releases/download/v0.7/buffalo_l.zip
unzip buffalo_l.zip
```

### 步骤 3: 创建新的工作流配置

创建 `configs/comfyui_workflow_enhanced.json`:

```json
{
  "workflow": {
    "name": "增强真实感工作流",
    "version": "2.0",
    "description": "集成 FaceDetailer + IP-Adapter + 真实感优化"
  },
  "nodes": {
    "CheckpointLoaderSimple": {
      "class_type": "CheckpointLoaderSimple",
      "inputs": {
        "ckpt_name": "realvisxl_v40.safetensors"
      }
    },
    "LoraLoader": {
      "class_type": "LoraLoader",
      "inputs": {
        "lora_name": "detail_tweaker_xl.safetensors",
        "strength_model": 0.7,
        "strength_clip": 0.7,
        "model": ["CheckpointLoaderSimple", 0],
        "clip": ["CheckpointLoaderSimple", 1]
      }
    },
    "IPAdapterModelLoader": {
      "class_type": "IPAdapterModelLoader",
      "inputs": {
        "ipadapter_file": "ip-adapter-faceid-plusv2_sdxl.bin"
      }
    },
    "CLIPVisionLoader": {
      "class_type": "CLIPVisionLoader",
      "inputs": {
        "clip_name": "CLIP-ViT-H-14-laion2B-s32B-b79K.safetensors"
      }
    },
    "LoadImage": {
      "class_type": "LoadImage",
      "inputs": {
        "image": ""
      }
    },
    "IPAdapterFaceID": {
      "class_type": "IPAdapterFaceID",
      "inputs": {
        "weight": 0.8,
        "weight_faceidv2": 1.0,
        "combine_embeds": "concat",
        "start_at": 0.0,
        "end_at": 1.0,
        "embeds_scaling": "V only",
        "model": ["LoraLoader", 0],
        "ipadapter": ["IPAdapterModelLoader", 0],
        "image": ["LoadImage", 0],
        "clip_vision": ["CLIPVisionLoader", 0]
      }
    },
    "CLIPTextEncodePositive": {
      "class_type": "CLIPTextEncode",
      "inputs": {
        "text": "",
        "clip": ["LoraLoader", 1]
      }
    },
    "CLIPTextEncodeNegative": {
      "class_type": "CLIPTextEncode",
      "inputs": {
        "text": "CGI, 3D render, cartoon, anime, plastic skin, too perfect, flawless, airbrushed, over-processed, studio lighting, posed",
        "clip": ["LoraLoader", 1]
      }
    },
    "EmptyLatentImage": {
      "class_type": "EmptyLatentImage",
      "inputs": {
        "width": 1024,
        "height": 576,
        "batch_size": 1
      }
    },
    "KSampler": {
      "class_type": "KSampler",
      "inputs": {
        "seed": -1,
        "steps": 28,
        "cfg": 6.0,
        "sampler_name": "dpmpp_2m_karras",
        "scheduler": "karras",
        "denoise": 1.0,
        "model": ["IPAdapterFaceID", 0],
        "positive": ["CLIPTextEncodePositive", 0],
        "negative": ["CLIPTextEncodeNegative", 0],
        "latent_image": ["EmptyLatentImage", 0]
      }
    },
    "VAEDecode": {
      "class_type": "VAEDecode",
      "inputs": {
        "samples": ["KSampler", 0],
        "vae": ["CheckpointLoaderSimple", 2]
      }
    },
    "FaceDetailer": {
      "class_type": "FaceDetailer",
      "inputs": {
        "image": ["VAEDecode", 0],
        "model": ["LoraLoader", 0],
        "clip": ["LoraLoader", 1],
        "vae": ["CheckpointLoaderSimple", 2],
        "guide_size": 512,
        "guide_size_for": true,
        "max_size": 1024,
        "seed": -1,
        "steps": 20,
        "cfg": 6.0,
        "sampler_name": "dpmpp_2m_karras",
        "scheduler": "karras",
        "denoise": 0.4,
        "feather": 5,
        "crop_factor": 3.0,
        "drop_size": 10
      }
    },
    "SaveImage": {
      "class_type": "SaveImage",
      "inputs": {
        "images": ["FaceDetailer", 0],
        "filename_prefix": "short_drama"
      }
    }
  },
  "parameters": {
    "default": {
      "width": 1024,
      "height": 576,
      "steps": 28,
      "cfg_scale": 6.0,
      "sampler_name": "dpmpp_2m_karras",
      "scheduler": "karras",
      "ipadapter_weight": 0.8,
      "face_detailer_denoise": 0.4
    }
  },
  "negative_prompt": {
    "default": "CGI, 3D render, cartoon, anime, illustration, painting, drawing, art, sketch, artificial, synthetic, fake, overly smooth skin, plastic skin, doll-like, too perfect, flawless, airbrushed, over-processed, over-saturated, unnatural colors, studio lighting, professional photography, posed, staged, (worst quality:1.2), (low quality:1.2), bad anatomy, blurry, watermark, text"
  }
}
```

### 步骤 4: 修改代码以支持新工作流

编辑 `src/services/comfyui_service.py`,添加工作流选择:

```python
def __init__(self, workflow_type="enhanced"):
    """
    初始化 ComfyUI 服务
    
    Args:
        workflow_type: 工作流类型
            - "basic": 基础工作流
            - "enhanced": 增强工作流 (推荐)
            - "fast": 快速工作流
    """
    self.workflow_type = workflow_type
    
    # 根据类型选择工作流
    workflow_files = {
        "basic": "./configs/comfyui_workflow_sdxl.json",
        "enhanced": "./configs/comfyui_workflow_enhanced.json",
        "fast": "./configs/comfyui_workflow_fast.json"
    }
    
    self.workflow_path = workflow_files.get(workflow_type, workflow_files["enhanced"])
```

## 📊 工作流对比

| 工作流 | 质量 | 速度 | 显存 | 真实感 | 角色一致性 |
|--------|------|------|------|--------|------------|
| 当前基础 | ⭐⭐⭐ | 快 | 7GB | ⭐⭐⭐ | ⭐⭐⭐ |
| 增强工作流 | ⭐⭐⭐⭐⭐ | 中等 | 9GB | ⭐⭐⭐⭐⭐ | ⭐⭐⭐⭐⭐ |
| 快速工作流 | ⭐⭐⭐⭐ | 很快 | 6GB | ⭐⭐⭐⭐ | ⭐⭐⭐ |

## 🎊 总结

### 推荐方案

**使用"增强工作流" (方案 C)**

**优势**:
1. ✅ 真实感极强 (FaceDetailer + 真实感提示词)
2. ✅ 角色一致性好 (IP-Adapter FaceID Plus V2)
3. ✅ 面部细节优化 (自动检测并优化)
4. ✅ RTX 3060 可以跑 (显存 9GB)

**实施步骤**:
1. 安装自定义节点
2. 下载必要模型
3. 使用新的工作流配置
4. 测试效果

---

**文档日期**: 2026-05-06  
**推荐工作流**: 增强真实感工作流  
**适用显卡**: RTX 3060 及以上
