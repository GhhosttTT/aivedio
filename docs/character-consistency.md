# 角色面部一致性功能使用指南

## 概述

本系统已集成 IP-Adapter 技术，可以确保短剧中每个角色的面部在不同场景中保持高度一致。

**最重要的一点：完全自动化！**
- ✅ 无需手动创建角色
- ✅ 无需手动上传参考图
- ✅ 系统自动识别、自动学习、自动保持一致

## 自动安装完成的内容

✅ **ComfyUI_IPAdapter_plus 插件** - 已安装到 `ComfyUI/custom_nodes/ComfyUI_IPAdapter_plus`  
✅ **IP-Adapter FaceID 模型** - 已下载到 `ComfyUI/models/ipadapter/`  
✅ **CLIP Vision 模型** - 已下载到 `ComfyUI/models/clip_vision/`  
✅ **角色管理 API** - 支持上传和管理角色参考图像  
✅ **工作流配置** - 包含 IP-Adapter 节点的完整工作流  

## 使用步骤

### 🎯 全自动流程（推荐）

**你只需要做两件事：**
1. 生成剧本时包含角色名称（例如：“张三走进房间”）
2. 点击“开始制作”按钮

**系统自动完成所有工作：**
- 🔍 检测场景中的角色名称
- 💾 首次出现时创建角色记录
- 🎨 生成图像并保存为参考图
- ✨ 再次出现时自动使用参考图保持一致性

### 📝 手动管理（可选）

如果你想手动管理角色或上传更高质量的参考图，可以使用以下 API：

### 1. 创建角色（可选，系统会自动创建）

通过 API 或前端界面为项目创建角色：

```bash
POST /api/projects/{project_id}/characters
{
  "name": "张三",
  "description": "男主角，25岁，阳光帅气",
  "personality": "开朗、勇敢",
  "appearance": "黑色短发，身材高大"
}
```

### 2. 上传角色参考图像（可选，系统会自动保存）

为每个角色上传 5-10 张清晰的正面照片：

```bash
POST /api/projects/{project_id}/characters/{character_id}/reference
Content-Type: multipart/form-data

file: [图片文件]
description: "正面照，微笑"
```

**参考图像要求：**
- ✅ 清晰的面部特写
- ✅ 不同角度和表情（建议）
- ✅ 光线充足
- ❌ 避免遮挡面部
- ❌ 避免模糊或低分辨率

**注意：** 如果不手动上传，系统会在首次生成时自动保存生成的图像作为参考图。

### 3. 生成剧本和分镜

正常生成剧本，系统会自动识别场景中的角色名称。

### 4. 启动生产

点击“开始制作”，系统将：
1. 自动检测每个场景中的角色
2. 首次出现的角色 → 创建记录并生成图像，然后保存为参考图
3. 再次出现的角色 → 使用之前的参考图，启用 IP-Adapter 保持一致性
4. 所有图像自动生成并保存

## 技术原理

### IP-Adapter FaceID

IP-Adapter (Image Prompt Adapter) 是一种先进的图像提示技术，可以让 AI 模型：

1. **提取面部特征** - 从参考图像中提取角色的面部特征向量
2. **保持身份一致性** - 在生成新图像时保持这些特征
3. **适应不同场景** - 根据提示词改变姿势、服装、背景，但保持面部不变

### 工作流程

```
角色参考图 → IP-Adapter → 面部特征编码
                              ↓
提示词 + 面部特征 → Stable Diffusion → 角色一致的图像
```

## API 端点

### 角色管理

| 方法 | 路径 | 描述 |
|------|------|------|
| POST | `/api/projects/{id}/characters` | 创建角色 |
| GET | `/api/projects/{id}/characters` | 获取角色列表 |
| GET | `/api/projects/{id}/characters/{cid}` | 获取角色详情 |
| DELETE | `/api/projects/{id}/characters/{cid}` | 删除角色 |

### 参考图像管理

| 方法 | 路径 | 描述 |
|------|------|------|
| POST | `/api/projects/{id}/characters/{cid}/reference` | 上传参考图像 |
| GET | `/api/projects/{id}/characters/{cid}/references` | 获取参考图像列表 |

## 配置选项

### IP-Adapter 参数

在 `configs/comfyui_workflow_ipadapter.json` 中可以调整：

```json
{
  "ipadapter_config": {
    "weight": 0.8,           // 角色一致性强度 (0.5-1.0)
    "lora_strength": 0.6,    // LoRA 强度 (0.3-1.0)
    "face_detection": true   // 是否启用人脸检测
  }
}
```

**参数说明：**
- **weight**: 值越高，角色一致性越强，但可能影响图像质量
- **lora_strength**: 控制面部特征的保留程度

## 故障排除

### 问题：角色面部不一致

**解决方案：**
1. 检查是否上传了足够的参考图像（至少 3-5 张）
2. 确保参考图像质量高、清晰
3. 增加 IP-Adapter weight 值（如从 0.8 提高到 0.9）

### 问题：图像质量下降

**解决方案：**
1. 降低 IP-Adapter weight 值
2. 减少参考图像数量，只保留最好的几张
3. 提高采样步数（steps）

### 问题：IP-Adapter 未生效

**检查清单：**
- [ ] ComfyUI 服务正在运行
- [ ] IP-Adapter 插件已正确安装
- [ ] 模型文件已下载
- [ ] 角色有参考图像
- [ ] 日志中显示"启用 IP-Adapter"

查看日志：
```bash
grep "IP-Adapter" logs/*.log
```

## 性能优化

### 推荐配置

对于 RTX 3060 (12GB VRAM)：

- 图像尺寸: 768x768 或 1024x1024
- 采样步数: 20-25
- CFG Scale: 7.0-8.0
- IP-Adapter Weight: 0.8

### 批量生成

系统会自动并行处理多个分镜的图像生成，无需手动操作。

## 示例代码

### Python 客户端

```python
import requests

# 1. 创建角色
response = requests.post(
    "http://localhost:8000/api/projects/1/characters",
    json={
        "name": "李四",
        "description": "女主角",
        "personality": "温柔、聪明",
        "appearance": "长发，大眼睛"
    }
)
character_id = response.json()["id"]

# 2. 上传参考图像
with open("photo1.jpg", "rb") as f:
    requests.post(
        f"http://localhost:8000/api/projects/1/characters/{character_id}/reference",
        files={"file": f},
        data={"description": "正面照"}
    )

# 3. 启动生产
requests.post(f"http://localhost:8000/api/projects/1/produce")
```

## 常见问题

### Q: 我需要手动上传参考图像吗？

A: **不需要！** 系统会自动处理：
- 首次生成时，自动保存生成的图像作为参考图
- 再次生成时，自动使用之前的参考图保持一致性
- 如果你想获得更好的效果，可以手动上传更高质量的参考图（可选）

### Q: 需要多少张参考图像？

A: 
- **自动模式**：系统会自动保存首次生成的图像（1张）
- **手动优化**：可以上传 5-10 张高质量照片以获得更好效果

### Q: 可以使用动漫风格的角色吗？

A: 可以！IP-Adapter 支持真实照片和动漫风格。

### Q: 能否在生成过程中更换参考图像？

A: 可以，随时上传新的参考图像，下次生成时会使用最新的。

### Q: 为什么有时角色看起来还是不太一样？

A: 可能的原因：
- 提示词差异太大
- IP-Adapter weight 太低
- 参考图像质量不佳
- 场景角度太极端

尝试调整参数或添加更多角度的参考图像。

## 技术支持

如有问题，请查看：
1. 后端日志：`logs/backend.log`
2. Celery worker 日志：`logs/celery.log`
3. ComfyUI 控制台输出

或联系开发团队获取帮助。
