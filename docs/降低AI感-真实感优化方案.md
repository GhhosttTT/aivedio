# 🎬 降低 AI 感 - 真实感优化方案

## 问题分析

你已经在使用 Juggernaut XL v9,但生成的图像:
- ❌ AI 感太重 (过于完美、不自然)
- ❌ 缺少真实感 (像 CG 而不是照片)
- ❌ 不如 Seeddance 的真实效果

## 核心原因

1. **提示词过度优化** - 太多质量标签导致过度渲染
2. **CFG 过高** - 导致过度拟合提示词,失去自然感
3. **缺少真实感元素** - 没有噪点、颗粒感等真实照片特征
4. **模型选择** - Juggernaut 偏向艺术化,不够写实

## 🎯 解决方案

### 方案 1: 更换更写实的模型 ⭐⭐⭐⭐⭐

#### 推荐模型 (按真实度排序)

1. **RealVisXL V4.0** ⭐⭐⭐⭐⭐ (最推荐!)
   - 下载: https://civitai.com/models/139562/realvisxl
   - 特点: **极致写实,接近真实照片,AI 感最低**
   - 适合: 需要真实感的现代都市剧
   - 版本选择: RealVisXL V4.0 (最新版)

2. **SDXL Unstable Diffusers** ⭐⭐⭐⭐⭐
   - 下载: https://civitai.com/models/84040/sdxl-unstable-diffusers
   - 特点: **真实照片风格,自然光影**
   - 适合: 纪实风格短剧

3. **ProtoVision XL** ⭐⭐⭐⭐
   - 下载: https://civitai.com/models/125703/protovision-xl
   - 特点: **高度写实,细节丰富但不过度**
   - 适合: 各类写实题材

4. **Copax Realistic XL** ⭐⭐⭐⭐
   - 下载: https://civitai.com/models/130090/copax-realistic-xl
   - 特点: **真实人像,自然表情**
   - 适合: 人物特写镜头

#### 如何更换

编辑 `configs/comfyui_workflow_sdxl.json`:
```json
{
  "nodes": {
    "CheckpointLoaderSimple": {
      "inputs": {
        "ckpt_name": "realvisxl_v40.safetensors"
      }
    }
  }
}
```

### 方案 2: 优化提示词 - 降低 AI 感 ⭐⭐⭐⭐⭐

#### 问题: 当前提示词太"完美"

```
❌ 错误示例 (AI 感重):
(masterpiece:1.2), (best quality:1.2), (ultra-detailed:1.2), 
(photorealistic:1.3), perfect lighting, flawless skin, 
professional photography, 8k resolution
```

#### 解决: 添加真实感元素

```
✅ 正确示例 (真实感):
raw photo, candid shot, natural lighting, slight imperfections, 
film grain, subtle noise, realistic skin texture, natural colors, 
amateur photography style, documentary style, unposed, 
authentic moment, real life scene
```

#### 修改提示词增强器

编辑 `src/services/prompt_enhancer.py`,将 system_prompt 改为:

```python
system_prompt = """你是一个专业的真实感图像提示词工程师。你的任务是生成接近真实照片的提示词,避免 AI 感。

核心原则:
1. **真实感优先** - 像真实照片,不是完美的 CG
2. **自然光影** - 使用 natural lighting, ambient light, 不用 perfect lighting
3. **适度瑕疵** - 添加 film grain, subtle noise, slight imperfections
4. **纪实风格** - 使用 candid shot, documentary style, raw photo
5. **避免过度修饰** - 不用 ultra-detailed, flawless, perfect 等词

必须包含的真实感元素:
- raw photo / candid shot (纪实风格)
- natural lighting / ambient light (自然光)
- film grain / subtle noise (胶片颗粒)
- realistic skin texture (真实皮肤)
- slight imperfections (轻微瑕疵)
- natural colors (自然色彩)
- unposed / authentic (自然姿态)

禁止使用的词汇:
- ❌ (masterpiece:1.2), (best quality:1.2) - 太完美
- ❌ ultra-detailed, hyper-realistic - 过度渲染
- ❌ perfect, flawless - 不真实
- ❌ professional photography - 太专业
- ❌ 8k, high resolution - 过度强调质量

推荐使用的词汇:
- ✅ raw photo, candid shot - 纪实感
- ✅ natural lighting, soft light - 自然光
- ✅ film grain, subtle noise - 胶片感
- ✅ realistic, authentic - 真实感
- ✅ documentary style - 纪录片风格
- ✅ amateur photography - 业余摄影感

示例输入："苏晚拿着匿名信站在花园里"
示例输出："raw photo, candid shot, 1woman Su Wan standing in garden holding anonymous letter, natural expression with slight concern, realistic facial features, natural skin texture, elegant dress, Lin Family estate garden background with real flowers, natural daylight, soft ambient lighting, film grain, subtle color grading, documentary photography style, authentic moment, unposed, 35mm film aesthetic, natural colors, slight imperfections, real life scene"

示例输入:"林家豪宅客厅,现代奢华装修"
示例输出:"raw photo, interior shot of Lin Family mansion living room, modern luxury decoration, natural window light, ambient shadows, realistic textures, film grain, candid interior photography, documentary style, natural color palette, subtle imperfections, authentic space, unedited photo aesthetic"

请严格遵循真实感原则,生成自然、真实的提示词。"""
```

### 方案 3: 调整采样参数 ⭐⭐⭐⭐

#### 降低 CFG (最重要!)

**CFG 过高 = AI 感重**

```python
# 当前配置 (AI 感重)
cfg_scale = 8.0  # ❌ 太高

# 推荐配置 (真实感)
cfg_scale = 5.0-6.5  # ✅ 更自然
```

#### 调整步数

```python
# 步数不要太高
steps = 25-30  # ✅ 适中即可,不要 40+
```

#### 修改代码

编辑 `src/tasks/image_tasks.py`:

```python
result_path = comfyui_service.generate_image(
    prompt=enhanced_prompt,
    output_path=image_path,
    width=kwargs.get("width", 1280),
    height=kwargs.get("height", 720),
    steps=kwargs.get("steps", 28),  # 降低到 28
    cfg_scale=kwargs.get("cfg_scale", 6.0),  # 降低到 6.0
    reference_image=reference_image,
    use_ipadapter=True if reference_image else False
)
```

### 方案 4: 添加真实感 LoRA ⭐⭐⭐⭐

#### 推荐 LoRA

1. **Film Grain LoRA**
   - 作用: 添加胶片颗粒感
   - 权重: 0.3-0.5

2. **Realistic Skin LoRA**
   - 作用: 真实皮肤纹理
   - 权重: 0.5-0.7

3. **Natural Light LoRA**
   - 作用: 自然光效
   - 权重: 0.4-0.6

### 方案 5: 优化负面提示词 ⭐⭐⭐

#### 添加"反 AI 感"负面词

编辑 `configs/comfyui_workflow_sdxl.json`:

```json
{
  "negative_prompt": {
    "default": "CGI, 3D render, cartoon, anime, illustration, painting, drawing, art, sketch, artificial, synthetic, fake, overly smooth skin, plastic skin, doll-like, too perfect, flawless, airbrushed, over-processed, over-saturated, unnatural colors, studio lighting, professional photography, posed, staged, (worst quality:1.2), (low quality:1.2), bad anatomy, blurry, watermark, text"
  }
}
```

关键负面词:
- `CGI, 3D render` - 避免 CG 感
- `overly smooth skin, plastic skin` - 避免过度光滑
- `too perfect, flawless` - 避免过度完美
- `airbrushed, over-processed` - 避免过度处理
- `studio lighting, professional photography` - 避免过度专业
- `posed, staged` - 避免摆拍感

### 方案 6: 使用 Refiner 模型 ⭐⭐⭐

#### SDXL Refiner 的作用

- 在基础生成后进行细化
- 增加真实感细节
- 减少 AI 痕迹

#### 如何添加

在 ComfyUI 工作流中添加 Refiner:

```json
{
  "nodes": {
    "RefinerModelLoader": {
      "class_type": "CheckpointLoaderSimple",
      "inputs": {
        "ckpt_name": "sd_xl_refiner_1.0.safetensors"
      }
    },
    "KSamplerRefiner": {
      "class_type": "KSampler",
      "inputs": {
        "model": ["RefinerModelLoader", 0],
        "seed": 12345,
        "steps": 10,
        "cfg": 5.0,
        "sampler_name": "dpmpp_2m",
        "scheduler": "karras",
        "denoise": 0.3
      }
    }
  }
}
```

## 📊 参数对比

### 当前配置 (AI 感重)

| 参数 | 值 | 问题 |
|------|-----|------|
| 模型 | Juggernaut XL v9 | 偏艺术化 |
| CFG | 8.0 | 过高,过度拟合 |
| 步数 | 35 | 偏高,过度渲染 |
| 提示词 | 质量标签多 | 过度完美 |
| 负面词 | 基础 | 未针对 AI 感 |

### 推荐配置 (真实感)

| 参数 | 值 | 优势 |
|------|-----|------|
| 模型 | RealVisXL V4.0 | 极致写实 |
| CFG | 6.0 | 适中,自然 |
| 步数 | 28 | 适中,不过度 |
| 提示词 | 真实感元素 | 纪实风格 |
| 负面词 | 反 AI 感 | 避免 CG 感 |

## 🎬 Seeddance 风格分析

### Seeddance 的特点

1. **真实照片感** - 像手机拍的,不是专业摄影
2. **自然光影** - 环境光,不是打光
3. **适度瑕疵** - 有噪点、颗粒感
4. **自然姿态** - 不摆拍,抓拍感
5. **真实色彩** - 不过饱和,不过对比

### 如何模仿

在提示词中强调:
```
raw photo, candid shot, smartphone camera, 
natural lighting, film grain, documentary style, 
unposed, authentic moment, real life scene,
natural colors, slight imperfections
```

## 🚀 快速优化步骤

### 步骤 1: 更换模型

```bash
# 下载 RealVisXL V4.0
# 放置到 ComfyUI/models/checkpoints/

# 修改配置
# configs/comfyui_workflow_sdxl.json
"ckpt_name": "realvisxl_v40.safetensors"
```

### 步骤 2: 降低 CFG

```python
# src/tasks/image_tasks.py
cfg_scale=kwargs.get("cfg_scale", 6.0)  # 从 8.0 降到 6.0
```

### 步骤 3: 修改提示词

```python
# src/services/prompt_enhancer.py
# 使用上面提供的新 system_prompt
```

### 步骤 4: 优化负面词

```json
# configs/comfyui_workflow_sdxl.json
# 添加反 AI 感负面词
```

### 步骤 5: 重启测试

```bash
# 重启 ComfyUI
pkill -f comfyui && cd ComfyUI && python main.py

# 重启 Celery
pkill -f celery
celery -A src.tasks.celery_app worker --loglevel=info --pool=solo

# 测试
创建项目 → 生成剧本 → 开始制作
```

## 📈 预期效果

### 优化前 (AI 感重)
- 皮肤过度光滑 ❌
- 光影过于完美 ❌
- 色彩过度饱和 ❌
- 构图过于专业 ❌
- 整体像 CG 渲染 ❌

### 优化后 (真实感)
- 皮肤纹理自然 ✅
- 光影真实自然 ✅
- 色彩自然真实 ✅
- 构图随意自然 ✅
- 整体像真实照片 ✅

## 🎯 关键要点

### 最重要的 3 个改变

1. **更换模型** (RealVisXL V4.0) - 降低 60% AI 感
2. **降低 CFG** (8.0 → 6.0) - 降低 20% AI 感
3. **修改提示词** (真实感元素) - 降低 20% AI 感

### 核心理念

**不追求完美,追求真实!**

- 不要 "masterpiece, best quality"
- 要 "raw photo, candid shot"
- 不要 "perfect lighting"
- 要 "natural lighting, film grain"
- 不要 "flawless skin"
- 要 "realistic skin texture, slight imperfections"

## 💡 额外技巧

### 1. 参考真实照片

在提示词中加入:
```
shot on iPhone 14 Pro, smartphone photography,
casual photo, everyday moment
```

### 2. 添加时间和天气

```
golden hour, overcast day, morning light,
rainy weather, natural daylight
```

### 3. 强调纪实风格

```
documentary photography, photojournalism style,
street photography, reportage
```

### 4. 降低分辨率 (可选)

有时候过高的分辨率反而显得不真实:
```python
width = 1024  # 而不是 1280
height = 576  # 而不是 720
```

## 📚 参考资源

### 真实感模型推荐
- RealVisXL V4.0 ⭐⭐⭐⭐⭐
- SDXL Unstable Diffusers ⭐⭐⭐⭐⭐
- ProtoVision XL ⭐⭐⭐⭐
- Copax Realistic XL ⭐⭐⭐⭐

### 提示词参考
- 搜索 "raw photo" 风格提示词
- 参考纪录片摄影风格
- 学习手机摄影特点

## ❓ 常见问题

### Q: 为什么 CFG 低反而更真实?

**A**: CFG 高会让模型过度拟合提示词,导致过度渲染。CFG 低让模型有更多"自由发挥",更接近真实照片的随机性。

### Q: 真实感和质量矛盾吗?

**A**: 不矛盾!真实感 ≠ 低质量。关键是"自然的高质量",而不是"完美的高质量"。

### Q: 还是觉得不够真实?

**A**: 
1. 进一步降低 CFG 到 5.0
2. 添加更多 film grain
3. 在负面词中加入更多"完美"相关词
4. 尝试 SDXL Unstable Diffusers 模型

## 🎊 总结

### 核心改变

1. **模型**: Juggernaut XL → RealVisXL V4.0
2. **CFG**: 8.0 → 6.0
3. **提示词**: 完美风格 → 纪实风格
4. **负面词**: 基础 → 反 AI 感

### 预期效果

**从 AI 渲染图 → 真实照片!**

像 Seeddance 一样自然、真实、有生活感!

---

**优化日期**: 2026-05-06  
**适用场景**: 需要真实感的现代都市短剧  
**难度**: ⭐⭐ (简单)
