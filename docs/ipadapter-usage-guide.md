# IP-Adapter 全身一致性使用指南

## 概述

IP-Adapter 已成功集成到您的工作流中，用于保持角色**全身一致性**（包括面部、服装、体型、姿态）。系统会自动在生成图像时使用参考图像来确保角色的整体外观保持一致。

## 配置状态

✅ **IP-Adapter 全身一致性模式已启用**
- 工作流配置文件: `configs/comfyui_workflow_ipadapter.json`
- IP-Adapter 模型: `ip-adapter-plus_sdxl_vit-h.safetensors` (PLUS FACE 模式)
- CLIP Vision 模型: `CLIP-ViT-H-14-laion2B-s32B-b79K.safetensors`
- 默认权重: 0.8（可调整范围: 0.5-1.0）
- 一致性模式: **全身一致性**（面部 + 服装 + 体型 + 姿态）

## 如何使用

### 1. 通过 API 使用

在调用图像生成 API 时，提供 `reference_image` 参数：

```python
from src.services.comfyui_service import ComfyUIService

service = ComfyUIService()

# 生成带有角色一致性的图像
image_path = service.generate_image(
    prompt="一个年轻女性在公园里微笑，阳光明媚",
    reference_image="./storage/characters/char_001/reference_01.jpg",  # 角色参考图像
    use_ipadapter=True,  # 启用 IP-Adapter（默认已启用）
    width=1024,
    height=1024,
    steps=20,
    cfg_scale=7.0
)
```

### 2. 调整 IP-Adapter 权重

权重控制角色一致性的强度：
- **0.5-0.7**: 较弱的一致性，更多遵循提示词
- **0.8**: 平衡模式（推荐）
- **0.9-1.0**: 强一致性，但可能影响图像质量

可以在工作流配置文件中修改默认权重：

```json
{
  "parameters": {
    "default": {
      "ipadapter_weight": 0.8
    }
  }
}
```

### 3. 准备参考图像（全身一致性）

为了获得最佳全身一致性效果：

#### 必需的参考图像类型

1. **全身照**（必须）
   - 展示完整的服装、体型、姿态
   - 从头到脚的完整视角
   - 清晰的服装细节

2. **半身照**（推荐）
   - 展示上半身服装和体型特征
   - 腰部以上的清晰视角

3. **面部特写**（推荐）
   - 清晰的面部特征
   - 用于保证面部一致性

#### 多角度参考

为每个角色准备以下角度的图像：
- **正面**: 标准视角
- **侧面**: 展示侧面轮廓
- **四分之三视角**: 最常用的角度

#### 图像质量要求

1. **高分辨率**: 至少 1024x1024 像素
2. **光线充足**: 避免过暗或过曝
3. **背景简洁**: 便于提取角色特征
4. **姿势自然**: 符合角色设定的姿态

建议的参考图像存储结构：
```
storage/
└── characters/
    ├── char_001/
    │   ├── full_body_front.jpg      # 全身正面
    │   ├── full_body_side.jpg       # 全身侧面
    │   ├── half_body.jpg            # 半身照
    │   ├── face_closeup.jpg         # 面部特写
    │   └── three_quarter.jpg        # 四分之三视角
    ├── char_002/
    │   └── ...
    └── ...
```

## 工作流节点说明

当前工作流包含以下关键节点（全身一致性模式）：

1. **checkpoint_loader**: 加载 SDXL 基础模型
2. **ipadapter_loader**: 加载 IP-Adapter Plus Face 模型（全身模式）
3. **clip_vision_loader**: 加载 CLIP Vision 编码器
4. **load_reference_image**: 加载角色参考图像（支持全身照）
5. **apply_ipadapter**: 应用 IP-Adapter 到模型（使用 concat 组合嵌入）
6. **ksampler**: 采样生成图像（连接到 IP-Adapter 输出）

### 全身一致性关键技术

- **combine_embeds=concat**: 组合多张参考图像的特征嵌入
- **embeds_scaling=V only**: 优化值向量缩放，保持整体特征
- **weight_type=linear**: 线性权重分布，均匀影响所有层

## 性能优化建议

### 速度 vs 质量预设

工作流提供了三种预设：

- **fast** (快速): 15 步，权重 0.7
- **balanced** (平衡): 20 步，权重 0.8 ⭐ 推荐
- **quality** (高质量): 30 步，权重 0.9

### GPU 优化

IP-Adapter 会增加显存使用。对于 RTX 3060 12GB：
- 建议同时生成的批次大小: 1
- 如遇到显存不足，可降低权重或减少步骤数

## 故障排除

### 问题 1: IP-Adapter 未生效

**检查项**:
1. 确认环境变量已设置: `COMFYUI_WORKFLOW_PATH=./configs/comfyui_workflow_ipadapter.json`
2. 确认提供了 `reference_image` 参数
3. 确认 `use_ipadapter=True`

### 问题 2: 生成的图像与参考图像差异大

**解决方案**:

#### 面部不一致
1. 提高 IP-Adapter 权重（尝试 0.9-1.0）
2. 添加面部特写参考图像
3. 增加采样步数（25-30 步）

#### 服装/体型不一致
1. 确保提供清晰的全身照参考图像
2. 提高权重至 0.85-0.95
3. 在提示词中详细描述服装特征
4. 使用多张不同角度的全身照

#### 姿态不一致
1. 使用与目标姿态相似的参考图像
2. 在提示词中明确描述姿态
3. 尝试调整 weight_type 为 "ease in-out"

### 问题 3: 显存不足

**解决方案**:
1. 降低图像分辨率（如 768x768）
2. 减少采样步数
3. 降低 IP-Adapter 权重
4. 关闭其他占用显存的程序

## 验证安装

运行测试脚本验证 IP-Adapter 配置：

```bash
cd F:\study\aishortmovie\aivedio
python scripts/test_ipadapter.py
```

预期输出：
```
✓ 工作流配置测试: 通过
✓ 服务连接测试: 通过
✓ 所有测试通过！IP-Adapter 已准备好使用。
```

## 高级用法

### 多参考图像融合

IP-Adapter 支持综合多张参考图像的特征：

```python
# 可以依次使用不同的参考图像生成
reference_images = [
    "./storage/characters/char_001/full_body_front.jpg",
    "./storage/characters/char_001/half_body.jpg",
    "./storage/characters/char_001/face_closeup.jpg"
]

for ref_img in reference_images:
    image_path = service.generate_image(
        prompt="角色在公园散步",
        reference_image=ref_img,
        use_ipadapter=True
    )
    # 选择最满意的结果
```

### 调整一致性强度

根据不同需求调整权重：

- **弱一致性 (0.5-0.7)**: 仅保留基本特征，更多创意空间
- **平衡模式 (0.8)**: 面部、服装、体型的平衡 ⭐ 推荐
- **强一致性 (0.9-1.0)**: 严格保持所有特征，可能限制创意

### 禁用 IP-Adapter

如需临时禁用 IP-Adapter：

```python
image_path = service.generate_image(
    prompt="一个风景照",
    use_ipadapter=False  # 禁用 IP-Adapter
)
```

## 相关文档

- [ComfyUI IP-Adapter 插件文档](../ComfyUI/custom_nodes/ComfyUI_IPAdapter_plus/README.md)
- [角色一致性最佳实践](../docs/character-consistency.md)
- [ComfyUI 设置指南](../docs/comfyui-setup-guide.md)

## 技术支持

如遇到问题，请检查：
1. ComfyUI 服务是否正常运行
2. 模型文件是否存在且完整
3. 日志文件: `logs/app.log` 和 `logs/error.log`
