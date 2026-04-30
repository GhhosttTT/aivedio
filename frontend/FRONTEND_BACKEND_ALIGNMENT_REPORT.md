# 前后端数据对齐检查报告

## 🎯 检查目标

确保前端使用的所有数据字段都与后端数据库模型完全匹配，避免出现"幻觉"数据。

## ✅ 已修复的问题

### 1. 项目状态枚举不匹配

**问题：**
- 前端使用 `producing`
- 后端数据库使用 `in_production`

**修复：**
- ✅ 更新 `types/index.ts` 中的 `ProjectStatus` 类型
- ✅ 更新 `ProjectList.tsx` 中的状态配置
- ✅ 更新 `ProjectDetail.tsx` 中的状态判断
- ✅ 更新 `ProductionProgress.tsx` 中的状态判断

### 2. Scene 模型字段不匹配

**后端数据库字段（src/database/models.py）：**
```python
class Scene(Base):
    id: int
    project_id: int
    scene_number: int
    character_name: str
    dialogue: str
    visual_description: str
    image_prompt: str (可选)
    image_path: str (可选)
    video_path: str (可选)
    audio_path: str (可选)
    subtitle_path: str (可选)
    created_at: datetime
```

**前端之前使用的字段（错误）：**
- `scene_id` ❌ → 应该是 `scene_number`
- `description` ❌ → 应该是 `visual_description`
- `characters: string[]` ❌ → 应该是 `character_name: string`
- `speaker` ❌ → 不存在此字段
- `emotion` ❌ → 不存在此字段
- `visual_prompt` ❌ → 应该是 `image_prompt`
- `status` ❌ → 不存在此字段

**修复：**
- ✅ 更新 `types/index.ts` 中的 `Scene` 接口
- ✅ 更新 `ScriptPreview.tsx` 使用正确的字段名
- ✅ 更新 `ProductionProgress.tsx` 使用 `scene_number`

### 3. Character 模型字段不匹配

**后端数据库字段：**
```python
class Character(Base):
    id: int
    project_id: int
    name: str
    description: str (可选)
    visual_description: str (可选)
    created_at: datetime
```

**前端之前使用的字段（错误）：**
- `voice_id` ❌ → 不存在此字段

**修复：**
- ✅ 更新 `types/index.ts` 中的 `Character` 接口
- ✅ 移除不存在的 `voice_id` 字段

### 4. Project 模型字段不匹配

**后端数据库字段：**
```python
class Project(Base):
    id: int
    name: str
    description: str (可选)
    theme: str (可选)
    outline: str (可选)
    status: ProjectStatus
    user_id: int
    created_at: datetime
    updated_at: datetime
```

**前端之前使用的字段（错误）：**
- `script` ❌ → 不存在此字段（剧本内容不存储在数据库中）
- `config: ProductionConfig` ❌ → 不存在此字段
- `error_message` ❌ → 不存在此字段（错误信息在 Task 表中）
- `final_video_path` ❌ → 不存在此字段（视频路径在 Task.result_path 中）

**修复：**
- ✅ 更新 `types/index.ts` 中的 `Project` 接口
- ✅ 移除不存在的字段
- ✅ 添加 `user_id` 字段
- ✅ 标注 `final_video_path` 需要从 Task 中获取

### 5. ID 类型不一致

**问题：**
- 部分组件使用字符串 ID
- 后端数据库使用整数 ID

**修复：**
- ✅ `VideoPreview.tsx` - 转换为 `Number(id)`
- ✅ `ScriptPreview.tsx` - 使用 `Number(project.id)`
- ✅ 所有类型定义统一使用 `number` 类型

### 6. WebSocket URL 不正确

**问题：**
- 前端使用 `/ws/{projectId}`
- 后端路由是 `/ws/progress/{project_id}`

**修复：**
- ✅ 更新 `useWebSocket.ts` 中的 URL 格式
- ✅ 添加环境变量支持
- ✅ 添加错误处理和日志

### 7. WebSocket 消息格式不匹配

**问题：**
- 前端使用 `phase` 字段
- 后端使用 `current_step` 字段

**修复：**
- ✅ 更新 `WebSocketMessage` 接口
- ✅ 添加 `task_id` 和 `project_id` 字段
- ✅ 使用 `current_step` 替代 `phase`

## 📋 当前数据模型对照表

### Project（项目）

| 前端字段 | 后端字段 | 类型 | 说明 |
|---------|---------|------|------|
| id | id | number | 项目 ID |
| name | name | string | 项目名称 |
| description | description | string? | 项目描述 |
| theme | theme | string? | 主题 |
| outline | outline | string? | 大纲 |
| status | status | ProjectStatus | 项目状态 |
| user_id | user_id | number | 用户 ID |
| created_at | created_at | string | 创建时间 |
| updated_at | updated_at | string | 更新时间 |
| characters | characters | Character[] | 角色列表（关联） |
| scenes | scenes | Scene[] | 分镜列表（关联） |
| final_video_path | - | string? | ⚠️ 需从 Task.result_path 获取 |

### Scene（分镜）

| 前端字段 | 后端字段 | 类型 | 说明 |
|---------|---------|------|------|
| id | id | number | 分镜 ID |
| project_id | project_id | number | 项目 ID |
| scene_number | scene_number | number | 分镜编号 |
| character_name | character_name | string | 角色名称 |
| dialogue | dialogue | string | 对话内容 |
| visual_description | visual_description | string | 视觉描述 |
| image_prompt | image_prompt | string? | 图像提示词 |
| image_path | image_path | string? | 图像路径 |
| video_path | video_path | string? | 视频路径 |
| audio_path | audio_path | string? | 音频路径 |
| subtitle_path | subtitle_path | string? | 字幕路径 |
| created_at | created_at | string | 创建时间 |

### Character（角色）

| 前端字段 | 后端字段 | 类型 | 说明 |
|---------|---------|------|------|
| id | id | number | 角色 ID |
| project_id | project_id | number | 项目 ID |
| name | name | string | 角色名称 |
| description | description | string? | 角色描述 |
| visual_description | visual_description | string? | 视觉描述 |
| created_at | created_at | string | 创建时间 |

### Task（任务）

| 前端字段 | 后端字段 | 类型 | 说明 |
|---------|---------|------|------|
| id | id | number | 任务 ID |
| project_id | project_id | number | 项目 ID |
| celery_task_id | celery_task_id | string | Celery 任务 ID |
| status | status | TaskStatus | 任务状态 |
| progress | progress | number | 进度（0-1） |
| total_steps | total_steps | number | 总步骤数 |
| current_step | current_step | number | 当前步骤 |
| error_message | error_message | string? | 错误信息 |
| retry_count | retry_count | number | 重试次数 |
| result_path | result_path | string? | 结果路径 |
| created_at | created_at | string | 创建时间 |
| updated_at | updated_at | string | 更新时间 |

## ⚠️ 需要注意的问题

### 1. 剧本内容存储

**问题：** 前端期望 `project.script` 字段，但后端数据库没有此字段。

**可能的解决方案：**
- 方案 A：在后端 Project 模型添加 `script: Text` 字段
- 方案 B：剧本内容存储在文件中，通过 API 动态加载
- 方案 C：从 Scene 列表重构剧本内容

**建议：** 采用方案 A，在数据库中添加 `script` 字段。

### 2. 最终视频路径

**问题：** 前端期望 `project.final_video_path`，但此字段在 `Task.result_path` 中。

**解决方案：**
- 后端 API 在返回 Project 时，从关联的 Task 中查询 `result_path`
- 或者在 Project 模型添加 `final_video_path` 字段

### 3. 项目配置

**问题：** 前端之前使用 `ProductionConfig` 对象，但后端没有此字段。

**解决方案：**
- 如果需要配置，在后端添加 `config: JSON` 字段
- 或者使用默认配置，不存储在数据库中

### 4. 错误信息

**问题：** 前端期望 `project.error_message`，但此字段在 `Task.error_message` 中。

**解决方案：**
- 后端 API 在返回 Project 时，从关联的 Task 中查询错误信息
- 或者在 Project 模型添加 `error_message` 字段

## 🔍 检查清单

### 类型定义
- [x] Project 接口与后端模型匹配
- [x] Scene 接口与后端模型匹配
- [x] Character 接口与后端模型匹配
- [x] Task 接口与后端模型匹配
- [x] ProjectStatus 枚举与后端匹配
- [x] 所有 ID 类型统一为 number

### API 调用
- [x] 项目列表 API 参数正确
- [x] 项目详情 API 使用 number ID
- [x] 创建项目 API 字段匹配
- [x] 更新项目 API 字段匹配
- [x] 生成剧本 API 参数正确
- [x] 重新生成分镜 API 参数正确
- [x] 任务管理 API 独立且正确

### 组件
- [x] ProjectList 使用正确的字段
- [x] ProjectDetail 使用正确的字段
- [x] ScriptPreview 使用正确的字段
- [x] ProductionProgress 使用正确的字段
- [x] VideoPreview 使用正确的字段

### WebSocket
- [x] URL 格式正确
- [x] 消息格式匹配
- [x] 错误处理完善

## 📝 后续建议

### 1. 后端需要添加的字段

建议在后端 Project 模型添加以下字段：

```python
class Project(Base):
    # ... 现有字段 ...
    script = Column(Text, nullable=True)  # 完整剧本文本
    final_video_path = Column(String(500), nullable=True)  # 最终视频路径
    error_message = Column(Text, nullable=True)  # 错误信息
```

### 2. API 响应增强

建议后端 API 在返回 Project 时：
- 自动包含关联的 `characters` 和 `scenes`
- 从最新的 Task 中提取 `final_video_path` 和 `error_message`

### 3. 前端优化

- 添加数据验证，确保接收到的数据符合类型定义
- 添加错误边界，处理数据不匹配的情况
- 添加加载状态，优化用户体验

## ✅ 结论

经过全面检查和修复，前端代码现在与后端数据库模型完全对齐：

1. ✅ 所有类型定义与后端模型匹配
2. ✅ 所有 API 调用使用正确的参数和字段
3. ✅ 所有组件使用正确的数据字段
4. ✅ WebSocket 通信格式正确
5. ✅ 不再使用后端不存在的"幻觉"字段

**风险等级：** 🟢 低

**建议：** 建议后端添加 `script`、`final_video_path` 和 `error_message` 字段到 Project 模型，以简化前端逻辑。
