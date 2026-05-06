# ComfyUI 最佳实践配置目录

本文档列出了所有可用的最佳实践配置，包括来源、适用场景、关键参数和效果评分。

## 配置概览

总共 **10** 个最佳实践配置，平均评分 **84.78**

### 按来源分类
- **Civitai**: 5 个
- **GitHub**: 2 个
- **Official**: 2 个
- **Community**: 1 个

### 按场景分类
- **人物特写 (Portrait)**: 3 个
- **全身照 (Full Body)**: 2 个
- **近景 (Close Up)**: 2 个
- **远景 (Wide Shot)**: 2 个
- **动作场景 (Action)**: 2 个
- **室内场景 (Indoor)**: 1 个
- **户外场景 (Outdoor)**: 3 个
- **夜景 (Night)**: 1 个
- **风景 (Landscape)**: 1 个
- **通用 (General)**: 3 个

---

## 配置详情

### 1. RealVisXL 人物特写高质量 ⭐⭐⭐⭐⭐

**ID**: `realvisxl-portrait-hq-001`  
**来源**: Civitai  
**作者**: SG_161222  
**综合评分**: 91.3

#### 适用场景
- 人物特写 (Portrait)
- 近景 (Close Up)

#### 关键参数
- **Checkpoint**: RealVisXL_V4.0.safetensors
- **LoRA**: FilmGrain.safetensors
- **采样步数**: 30
- **CFG Scale**: 6.5
- **采样器**: dpmpp_2m
- **调度器**: karras
- **分辨率**: 1024x1024
- **IP-Adapter 权重**: 0.85

#### 提示词模板
```
raw photo, candid shot, {subject}, natural lighting, film grain, professional photography, DSLR, 85mm lens, f/1.8, shallow depth of field
```

#### 负面提示词
```
CGI, 3D render, cartoon, anime, illustration, painting, drawing, art, sketch, plastic skin, airbrushed, smooth skin, fake, artificial, oversaturated, high contrast, HDR
```

#### 评分
- 质量评分: 95.0
- 真实感评分: 98.0
- 一致性评分: 90.0
- 速度评分: 70.0

#### 特点
- 真实感极强，适合专业人像摄影
- 使用 Film Grain LoRA 增强真实感
- 支持 FaceDetailer 面部优化

---

### 2. IP-Adapter FaceID 人物一致性 ⭐⭐⭐⭐⭐

**ID**: `ipadapter-faceid-portrait-005`  
**来源**: GitHub  
**作者**: cubiq  
**综合评分**: 90.9

#### 适用场景
- 人物特写 (Portrait)
- 近景 (Close Up)
- 全身照 (Full Body)

#### 关键参数
- **Checkpoint**: RealVisXL_V4.0.safetensors
- **采样步数**: 25
- **CFG Scale**: 6.0
- **采样器**: dpmpp_2m
- **调度器**: karras
- **分辨率**: 1024x1024
- **IP-Adapter 权重**: 0.90
- **IP-Adapter 模型**: ip-adapter-faceid-plusv2_sdxl.bin

#### 提示词模板
```
{subject}, consistent character, same person, professional photo
```

#### 负面提示词
```
different person, multiple people, inconsistent face, morphed face
```

#### 评分
- 质量评分: 88.0
- 真实感评分: 92.0
- 一致性评分: 98.0
- 速度评分: 75.0

#### 特点
- 极高的人物面部一致性
- 适合角色生成和多场景一致性
- 使用 IP-Adapter FaceID Plus V2

---

### 3. Realistic Vision 室内场景 ⭐⭐⭐⭐

**ID**: `realistic-vision-indoor-006`  
**来源**: Civitai  
**作者**: SG_161222  
**综合评分**: 87.1

#### 适用场景
- 室内场景 (Indoor)
- 人物特写 (Portrait)

#### 关键参数
- **Checkpoint**: realisticVisionV60B1_v51.safetensors
- **LoRA**: add_detail.safetensors
- **采样步数**: 25
- **CFG Scale**: 7.0
- **采样器**: dpmpp_2m
- **调度器**: karras
- **分辨率**: 768x1024
- **IP-Adapter 权重**: 0.75

#### 提示词模板
```
{subject}, indoor scene, natural window light, soft shadows, cozy atmosphere, realistic, photorealistic
```

#### 负面提示词
```
outdoor, harsh lighting, artificial, fake, CGI, 3D render
```

#### 评分
- 质量评分: 87.0
- 真实感评分: 90.0
- 一致性评分: 85.0
- 速度评分: 80.0

#### 特点
- 光线自然，氛围感强
- 适合室内人物和场景
- 支持 FaceDetailer

---

### 4. DreamShaper XL 风景摄影 ⭐⭐⭐⭐

**ID**: `dreamshaper-xl-landscape-004`  
**来源**: Civitai  
**作者**: Lykon  
**综合评分**: 86.3

#### 适用场景
- 风景 (Landscape)
- 户外场景 (Outdoor)
- 远景 (Wide Shot)

#### 关键参数
- **Checkpoint**: dreamshaperXL_v21.safetensors
- **LoRA**: DetailTweaker.safetensors
- **采样步数**: 28
- **CFG Scale**: 7.5
- **采样器**: dpmpp_2m
- **调度器**: karras
- **分辨率**: 1536x864
- **支持 2x 放大**

#### 提示词模板
```
{subject}, landscape photography, golden hour, vibrant colors, sharp focus, high detail, professional photography, wide angle lens
```

#### 负面提示词
```
people, person, human, portrait, blurry, low quality, oversaturated, HDR, overprocessed
```

#### 评分
- 质量评分: 90.0
- 真实感评分: 88.0
- 一致性评分: 85.0
- 速度评分: 72.0

#### 特点
- 色彩饱和度高，细节丰富
- 适合壮丽的风景照片
- 支持 2x 放大

---

### 5. 平衡通用配置 ⭐⭐⭐⭐

**ID**: `balanced-general-010`  
**来源**: Official  
**作者**: ComfyUI Official  
**综合评分**: 86.0

#### 适用场景
- 通用 (General)

#### 关键参数
- **Checkpoint**: RealVisXL_V4.0.safetensors
- **采样步数**: 25
- **CFG Scale**: 7.0
- **采样器**: dpmpp_2m
- **调度器**: karras
- **分辨率**: 1024x1024
- **IP-Adapter 权重**: 0.75

#### 提示词模板
```
{subject}, high quality, detailed, professional
```

#### 负面提示词
```
low quality, blurry, distorted, bad anatomy
```

#### 评分
- 质量评分: 85.0
- 真实感评分: 85.0
- 一致性评分: 90.0
- 速度评分: 85.0

#### 特点
- 平衡的通用配置
- 质量、速度、一致性都不错
- 适合大多数场景
- **推荐作为默认配置**

---

### 6. Juggernaut XL 电影级画面 ⭐⭐⭐⭐

**ID**: `juggernaut-xl-cinematic-003`  
**来源**: Civitai  
**作者**: KandooAI  
**综合评分**: 85.5

#### 适用场景
- 动作场景 (Action)
- 户外场景 (Outdoor)
- 远景 (Wide Shot)

#### 关键参数
- **Checkpoint**: juggernautXL_v9.safetensors
- **LoRA**: add-detail-xl.safetensors
- **采样步数**: 35
- **CFG Scale**: 8.0
- **采样器**: dpmpp_2m_sde
- **调度器**: karras
- **分辨率**: 1280x720
- **IP-Adapter 权重**: 0.70
- **支持 1.5x 放大**

#### 提示词模板
```
cinematic shot, {subject}, dramatic lighting, volumetric fog, epic scene, movie still, professional color grading, film grain
```

#### 负面提示词
```
amateur, snapshot, casual photo, flat lighting, boring composition, static, dull colors
```

#### 评分
- 质量评分: 92.0
- 真实感评分: 85.0
- 一致性评分: 88.0
- 速度评分: 65.0

#### 特点
- 电影级画面效果
- 色彩丰富，光影效果出色
- 适合动作和史诗场景

---

### 7. 全身动作场景 ⭐⭐⭐⭐

**ID**: `full-body-action-008`  
**来源**: GitHub  
**作者**: ComfyUI Community  
**综合评分**: 83.8

#### 适用场景
- 全身照 (Full Body)
- 动作场景 (Action)

#### 关键参数
- **Checkpoint**: juggernautXL_v9.safetensors
- **LoRA**: ActionPose.safetensors
- **采样步数**: 28
- **CFG Scale**: 7.5
- **采样器**: dpmpp_2m
- **调度器**: karras
- **分辨率**: 768x1280
- **IP-Adapter 权重**: 0.75

#### 提示词模板
```
{subject}, full body shot, dynamic pose, action scene, professional photography, motion blur
```

#### 负面提示词
```
static, boring pose, cropped, cut off, close up, portrait only
```

#### 评分
- 质量评分: 84.0
- 真实感评分: 82.0
- 一致性评分: 88.0
- 速度评分: 78.0

#### 特点
- 适合全身动作场景
- 动态感强，构图合理
- 支持 FaceDetailer

---

### 8. 夜景摄影专用 ⭐⭐⭐⭐

**ID**: `night-photography-007`  
**来源**: Community  
**作者**: Community  
**综合评分**: 83.2

#### 适用场景
- 夜景 (Night)
- 户外场景 (Outdoor)

#### 关键参数
- **Checkpoint**: RealVisXL_V4.0.safetensors
- **LoRA**: LowLightEnhancer.safetensors
- **采样步数**: 32
- **CFG Scale**: 7.5
- **采样器**: dpmpp_2m_sde
- **调度器**: karras
- **分辨率**: 1280x720
- **IP-Adapter 权重**: 0.70
- **支持 1.5x 放大**

#### 提示词模板
```
{subject}, night photography, low light, ambient lighting, city lights, long exposure, professional photography
```

#### 负面提示词
```
daylight, bright, overexposed, noisy, grainy, low quality
```

#### 评分
- 质量评分: 85.0
- 真实感评分: 88.0
- 一致性评分: 82.0
- 速度评分: 68.0

#### 特点
- 专门优化的夜景配置
- 低光环境表现出色
- 噪点控制好

---

### 9. 艺术风格创作 ⭐⭐⭐⭐

**ID**: `artistic-style-009`  
**来源**: Civitai  
**作者**: Stability AI  
**综合评分**: 79.6

#### 适用场景
- 通用 (General)

#### 关键参数
- **Checkpoint**: sd_xl_base_1.0.safetensors
- **LoRA**: ArtisticStyle.safetensors, ColorEnhancer.safetensors
- **采样步数**: 30
- **CFG Scale**: 9.0
- **采样器**: dpmpp_2m_sde
- **调度器**: karras
- **分辨率**: 1024x1024
- **支持 Refiner（10 步）**

#### 提示词模板
```
{subject}, artistic style, vibrant colors, creative composition, masterpiece, award winning
```

#### 负面提示词
```
realistic, photorealistic, plain, boring, dull colors, amateur
```

#### 评分
- 质量评分: 88.0
- 真实感评分: 70.0
- 一致性评分: 80.0
- 速度评分: 72.0

#### 特点
- 艺术风格创作
- 色彩丰富，创意性强
- 适合艺术创作

---

### 10. SDXL Turbo 快速生成 ⭐⭐⭐

**ID**: `sdxl-turbo-fast-002`  
**来源**: Official  
**作者**: Stability AI  
**综合评分**: 74.1

#### 适用场景
- 通用 (General)

#### 关键参数
- **Checkpoint**: sd_xl_turbo_1.0.safetensors
- **采样步数**: 4
- **CFG Scale**: 1.0
- **采样器**: euler_ancestral
- **调度器**: normal
- **分辨率**: 768x768

#### 提示词模板
```
{subject}, high quality, detailed
```

#### 负面提示词
```
blurry, low quality, distorted
```

#### 评分
- 质量评分: 70.0
- 真实感评分: 65.0
- 一致性评分: 75.0
- 速度评分: 98.0

#### 特点
- 超快速图像生成
- 适合快速预览和迭代
- 只需 4 步采样

---

## 使用建议

### 按场景选择

#### 人物摄影
1. **人物特写**: RealVisXL 人物特写高质量 (91.3)
2. **人物一致性**: IP-Adapter FaceID 人物一致性 (90.9)
3. **室内人物**: Realistic Vision 室内场景 (87.1)

#### 风景摄影
1. **风景**: DreamShaper XL 风景摄影 (86.3)
2. **夜景**: 夜景摄影专用 (83.2)

#### 动作场景
1. **电影级**: Juggernaut XL 电影级画面 (85.5)
2. **全身动作**: 全身动作场景 (83.8)

#### 通用场景
1. **平衡配置**: 平衡通用配置 (86.0) ⭐ 推荐
2. **艺术创作**: 艺术风格创作 (79.6)
3. **快速预览**: SDXL Turbo 快速生成 (74.1)

### 按需求选择

#### 优先质量
1. RealVisXL 人物特写高质量 (质量评分: 95.0)
2. Juggernaut XL 电影级画面 (质量评分: 92.0)
3. DreamShaper XL 风景摄影 (质量评分: 90.0)

#### 优先真实感
1. RealVisXL 人物特写高质量 (真实感评分: 98.0)
2. IP-Adapter FaceID 人物一致性 (真实感评分: 92.0)
3. Realistic Vision 室内场景 (真实感评分: 90.0)

#### 优先一致性
1. IP-Adapter FaceID 人物一致性 (一致性评分: 98.0)
2. 平衡通用配置 (一致性评分: 90.0)
3. RealVisXL 人物特写高质量 (一致性评分: 90.0)

#### 优先速度
1. SDXL Turbo 快速生成 (速度评分: 98.0)
2. 平衡通用配置 (速度评分: 85.0)
3. Realistic Vision 室内场景 (速度评分: 80.0)

---

## 如何使用

### 通过代码使用

```python
from src.services.best_practice_library import get_best_practice_library
from src.models.best_practice import SceneCategory

# 获取库实例
library = get_best_practice_library()

# 加载配置
library.load_from_directory()

# 获取推荐配置
recommended = library.get_recommended_practice(
    SceneCategory.PORTRAIT,
    prefer_quality=True
)

print(f"推荐配置: {recommended.name}")
print(f"Checkpoint: {recommended.checkpoint}")
print(f"采样步数: {recommended.sampling_steps}")
print(f"CFG Scale: {recommended.cfg_scale}")
```

### 通过 API 使用

```bash
# 获取所有配置
GET /api/best-practices

# 获取特定场景的配置
GET /api/best-practices?scene=portrait&min_score=85

# 获取推荐配置
GET /api/best-practices/recommend?scene=portrait&prefer_quality=true
```

---

## 贡献新配置

如果你有优秀的工作流配置想要分享，请按照以下格式创建 JSON 文件：

```json
{
  "id": "your-config-id",
  "name": "配置名称",
  "description": "配置描述",
  "source": "civitai|github|community|official|custom",
  "source_url": "来源 URL",
  "author": "作者名称",
  "applicable_scenes": ["portrait", "landscape", ...],
  "tags": ["标签1", "标签2"],
  "workflow_type": "basic|fast|pro|ipadapter|sdxl",
  "checkpoint": "模型文件名",
  "lora_models": ["LoRA1", "LoRA2"],
  "sampling_steps": 25,
  "cfg_scale": 7.0,
  "sampler": "dpmpp_2m",
  "scheduler": "karras",
  "resolution": "1024x1024",
  "ipadapter_weight": 0.75,
  "prompt_template": "提示词模板",
  "negative_prompt": "负面提示词",
  "quality_score": 85.0,
  "realism_score": 85.0,
  "consistency_score": 85.0,
  "speed_score": 85.0,
  "version": "1.0"
}
```

将文件保存到 `configs/best_practices/` 目录即可。

---

*文档版本: 1.0*  
*最后更新: 2026-05-06*  
*维护者: AI Short Drama Production Team*
