# 用户手册

本手册详细介绍 AI 短剧自动化生产平台的所有功能和使用方法。

## 目录

- [系统概述](#系统概述)
- [用户管理](#用户管理)
- [项目管理](#项目管理)
- [剧本生成](#剧本生成)
- [生产任务](#生产任务)
- [文件管理](#文件管理)
- [高级功能](#高级功能)

## 系统概述

AI 短剧自动化生产平台是一个基于多个 AI 模型的自动化短剧生产系统，可以从创意到成品视频的全流程自动化生产。

### 核心功能

1. **剧本生成**：使用 Qwen2.5-14B 大语言模型自动生成剧本和分镜
2. **图像生成**：使用 Stable Diffusion XL 生成分镜图像
3. **视频生成**：使用 Stable Video Diffusion 将图像转换为视频
4. **配音生成**：使用 MiMo-V2-TTS 生成角色配音
5. **字幕生成**：自动生成 SRT 字幕并烧录到视频
6. **视频合成**：自动拼接所有分镜视频并添加背景音乐

### 工作流程

```
创意输入 → 剧本生成 → 分镜生成 → 图像生成 → 视频生成 → 配音生成 → 字幕生成 → 视频合成 → 成品输出
```

## 用户管理

### 注册账号

**API 端点**: `POST /api/auth/register`

**请求参数**:
```json
{
    "username": "your_username",
    "email": "your_email@example.com",
    "password": "your_password"
}
```

**密码要求**:
- 最少 8 个字符
- 建议包含大小写字母、数字和特殊字符

**示例**:
```bash
curl -X POST "http://localhost:8000/api/auth/register" \
  -H "Content-Type: application/json" \
  -d '{
    "username": "alice",
    "email": "alice@example.com",
    "password": "SecurePass123!"
  }'
```

### 登录

**API 端点**: `POST /api/auth/login`

**请求参数**:
```json
{
    "username": "your_username",
    "password": "your_password"
}
```

**响应**:
```json
{
    "access_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
    "refresh_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
    "token_type": "bearer",
    "expires_in": 86400
}
```

**使用 Token**:

在后续所有 API 请求中，需要在 Header 中添加：

```
Authorization: Bearer YOUR_ACCESS_TOKEN
```

### 刷新 Token

**API 端点**: `POST /api/auth/refresh`

**请求参数**:
```json
{
    "refresh_token": "YOUR_REFRESH_TOKEN"
}
```

**Token 有效期**:
- Access Token: 24 小时
- Refresh Token: 7 天

### 获取当前用户信息

**API 端点**: `GET /api/auth/me`

**响应**:
```json
{
    "id": 1,
    "username": "alice",
    "email": "alice@example.com",
    "is_active": true,
    "created_at": "2024-01-01T00:00:00Z"
}
```

## 项目管理

### 创建项目

**API 端点**: `POST /api/projects`

**请求参数**:
```json
{
    "name": "项目名称",
    "description": "项目描述（可选）",
    "theme": "主题（可选）",
    "outline": "大纲（可选）"
}
```

**字段说明**:
- `name`: 项目名称（必填，1-100 字符）
- `description`: 项目描述（可选，最多 500 字符）
- `theme`: 剧本主题（可选，用于剧本生成）
- `outline`: 剧本大纲（可选，用于剧本生成）

**注意**: `theme` 和 `outline` 至少需要提供一个，用于后续的剧本生成。

**示例**:
```bash
curl -X POST "http://localhost:8000/api/projects" \
  -H "Authorization: Bearer YOUR_ACCESS_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "友情的力量",
    "description": "一个关于友情和成长的温馨故事",
    "theme": "友情、成长、温馨、励志",
    "outline": "讲述两个好朋友小明和小红在面对困难时互相帮助，最终克服困难的故事。故事分为三个部分：相遇、困难、克服。"
  }'
```

**响应**:
```json
{
    "id": 1,
    "name": "友情的力量",
    "description": "一个关于友情和成长的温馨故事",
    "theme": "友情、成长、温馨、励志",
    "outline": "讲述两个好朋友小明和小红...",
    "status": "draft",
    "created_at": "2024-01-01T00:00:00Z",
    "updated_at": "2024-01-01T00:00:00Z"
}
```

### 获取项目列表

**API 端点**: `GET /api/projects`

**查询参数**:
- `status`: 项目状态过滤（可选）
  - `draft`: 草稿
  - `script_generated`: 剧本已生成
  - `in_production`: 生产中
  - `completed`: 已完成
  - `failed`: 失败
- `skip`: 跳过的记录数（分页，默认 0）
- `limit`: 返回的记录数（分页，默认 10，最大 100）

**示例**:
```bash
# 获取所有项目
curl -X GET "http://localhost:8000/api/projects" \
  -H "Authorization: Bearer YOUR_ACCESS_TOKEN"

# 获取已完成的项目
curl -X GET "http://localhost:8000/api/projects?status=completed" \
  -H "Authorization: Bearer YOUR_ACCESS_TOKEN"

# 分页获取（第 2 页，每页 20 条）
curl -X GET "http://localhost:8000/api/projects?skip=20&limit=20" \
  -H "Authorization: Bearer YOUR_ACCESS_TOKEN"
```

### 获取项目详情

**API 端点**: `GET /api/projects/{project_id}`

**响应**:
```json
{
    "id": 1,
    "name": "友情的力量",
    "description": "一个关于友情和成长的温馨故事",
    "theme": "友情、成长、温馨、励志",
    "outline": "讲述两个好朋友小明和小红...",
    "status": "completed",
    "created_at": "2024-01-01T00:00:00Z",
    "updated_at": "2024-01-01T10:00:00Z",
    "characters": [
        {
            "id": 1,
            "name": "小明",
            "description": "一个乐观开朗的男孩",
            "personality": "乐观、勇敢、善良"
        },
        {
            "id": 2,
            "name": "小红",
            "description": "一个聪明伶俐的女孩",
            "personality": "聪明、细心、温柔"
        }
    ],
    "scenes": [
        {
            "id": 1,
            "scene_number": 1,
            "title": "相遇",
            "description": "小明和小红在公园相遇",
            "dialogue": "小明：你好，我叫小明。\n小红：你好，我叫小红。",
            "visual_prompt": "A sunny park with children playing...",
            "duration": 10
        }
    ]
}
```

### 更新项目

**API 端点**: `PUT /api/projects/{project_id}`

**请求参数**:
```json
{
    "name": "新的项目名称（可选）",
    "description": "新的项目描述（可选）",
    "theme": "新的主题（可选）",
    "outline": "新的大纲（可选）"
}
```

**注意**: 只能更新状态为 `draft` 的项目。

### 删除项目

**API 端点**: `DELETE /api/projects/{project_id}`

**注意**: 删除项目会同时删除所有相关的文件（图像、视频、音频、字幕）。

## 剧本生成

### 生成剧本

**API 端点**: `POST /api/projects/{project_id}/generate-script`

**请求参数**:
```json
{
    "theme": "主题（可选，如果项目已有则使用项目的）",
    "outline": "大纲（可选，如果项目已有则使用项目的）"
}
```

**生成过程**:
1. 系统使用 Qwen2.5-14B 模型分析主题和大纲
2. 生成角色列表（包含姓名、描述、性格）
3. 生成分镜列表（包含标题、描述、对话、视觉提示、时长）
4. 保存到数据库并更新项目状态为 `script_generated`

**生成时间**: 约 30-60 秒（取决于 GPU 性能和剧本复杂度）

**示例**:
```bash
curl -X POST "http://localhost:8000/api/projects/1/generate-script" \
  -H "Authorization: Bearer YOUR_ACCESS_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "theme": "友情、成长、温馨、励志",
    "outline": "讲述两个好朋友小明和小红在面对困难时互相帮助，最终克服困难的故事。"
  }'
```

**响应**:
```json
{
    "message": "剧本生成成功",
    "characters_count": 2,
    "scenes_count": 5
}
```

### 重新生成分镜

**API 端点**: `POST /api/projects/{project_id}/regenerate-scene`

**请求参数**:
```json
{
    "scene_number": 1,
    "instruction": "重新生成指令（可选）"
}
```

**使用场景**:
- 对某个分镜不满意，想重新生成
- 想调整分镜的内容或风格

**示例**:
```bash
curl -X POST "http://localhost:8000/api/projects/1/regenerate-scene" \
  -H "Authorization: Bearer YOUR_ACCESS_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "scene_number": 1,
    "instruction": "让这个场景更加温馨，增加更多细节描述"
  }'
```

## 生产任务

### 提交生产任务

**API 端点**: `POST /api/projects/{project_id}/produce`

**前提条件**:
- 项目状态必须是 `script_generated`（剧本已生成）
- 项目必须有至少一个分镜

**生产流程**:
1. **图像生成**：为每个分镜生成图像（使用 Stable Diffusion XL）
2. **视频生成**：将图像转换为视频（使用 Stable Video Diffusion）
3. **配音生成**：为每个分镜生成配音（使用 MiMo-V2-TTS）
4. **字幕生成**：生成 SRT 字幕文件
5. **视频合成**：拼接所有分镜视频，添加字幕和背景音乐

**生产时间**: 约 5-15 分钟/分镜（取决于 GPU 性能和分镜数量）

**示例**:
```bash
curl -X POST "http://localhost:8000/api/projects/1/produce" \
  -H "Authorization: Bearer YOUR_ACCESS_TOKEN"
```

**响应**:
```json
{
    "task_id": "abc123def456",
    "message": "生产任务已提交",
    "estimated_time": 600
}
```

### 查询任务状态

**API 端点**: `GET /api/tasks/{task_id}/status`

**响应**:
```json
{
    "task_id": "abc123def456",
    "project_id": 1,
    "status": "in_progress",
    "progress": 45,
    "current_step": "video_generation",
    "total_steps": 5,
    "completed_steps": 2,
    "created_at": "2024-01-01T10:00:00Z",
    "updated_at": "2024-01-01T10:05:00Z",
    "error_message": null
}
```

**状态说明**:
- `pending`: 等待中
- `in_progress`: 进行中
- `completed`: 已完成
- `failed`: 失败
- `cancelled`: 已取消

**当前步骤说明**:
- `image_generation`: 图像生成中
- `video_generation`: 视频生成中
- `audio_generation`: 配音生成中
- `subtitle_generation`: 字幕生成中
- `video_composition`: 视频合成中

### 取消任务

**API 端点**: `POST /api/tasks/{task_id}/cancel`

**注意**: 只能取消状态为 `pending` 或 `in_progress` 的任务。

**示例**:
```bash
curl -X POST "http://localhost:8000/api/tasks/abc123def456/cancel" \
  -H "Authorization: Bearer YOUR_ACCESS_TOKEN"
```

### 重试失败的任务

**API 端点**: `POST /api/tasks/{task_id}/retry`

**注意**: 只能重试状态为 `failed` 的任务，且重试次数不超过 3 次。

**示例**:
```bash
curl -X POST "http://localhost:8000/api/tasks/abc123def456/retry" \
  -H "Authorization: Bearer YOUR_ACCESS_TOKEN"
```

## 文件管理

### 文件存储结构

生成的文件保存在 `storage/projects/{project_id}/` 目录下：

```
storage/
└── projects/
    └── {project_id}/
        ├── images/
        │   ├── scene_1.png
        │   ├── scene_2.png
        │   └── ...
        ├── videos/
        │   ├── scene_1.mp4
        │   ├── scene_2.mp4
        │   └── ...
        ├── audios/
        │   ├── scene_1.mp3
        │   ├── scene_2.mp3
        │   └── ...
        ├── subtitles/
        │   ├── scene_1.srt
        │   ├── scene_2.srt
        │   └── ...
        └── final_video.mp4
```

### 访问文件

文件可以通过静态文件服务访问：

```
http://localhost:8000/static/projects/{project_id}/final_video.mp4
```

### 下载文件

可以使用浏览器直接下载，或使用 curl：

```bash
curl -O "http://localhost:8000/static/projects/1/final_video.mp4"
```

## 高级功能

### WebSocket 实时通知

系统支持 WebSocket 实时推送任务状态更新。

**连接地址**: `ws://localhost:8000/ws/{project_id}`

**消息格式**:

1. **连接成功**:
```json
{
    "type": "connected",
    "project_id": 1,
    "message": "WebSocket 连接成功"
}
```

2. **状态更新**:
```json
{
    "type": "status_update",
    "project_id": 1,
    "status": "in_production",
    "timestamp": "2024-01-01T10:00:00Z"
}
```

3. **进度更新**:
```json
{
    "type": "progress_update",
    "project_id": 1,
    "task_id": "abc123def456",
    "progress": 45,
    "current_step": "video_generation",
    "timestamp": "2024-01-01T10:05:00Z"
}
```

4. **完成通知**:
```json
{
    "type": "completion",
    "project_id": 1,
    "task_id": "abc123def456",
    "message": "生产任务已完成",
    "final_video_url": "/static/projects/1/final_video.mp4",
    "timestamp": "2024-01-01T10:15:00Z"
}
```

5. **错误通知**:
```json
{
    "type": "error",
    "project_id": 1,
    "task_id": "abc123def456",
    "error": "GPU 显存不足",
    "timestamp": "2024-01-01T10:10:00Z"
}
```

6. **心跳**:
```json
{
    "type": "heartbeat",
    "timestamp": "2024-01-01T10:00:00Z"
}
```

**JavaScript 示例**:
```javascript
const ws = new WebSocket('ws://localhost:8000/ws/1');

ws.onopen = () => {
    console.log('WebSocket 连接成功');
};

ws.onmessage = (event) => {
    const data = JSON.parse(event.data);
    console.log('收到消息:', data);
    
    if (data.type === 'progress_update') {
        console.log(`进度: ${data.progress}%`);
    } else if (data.type === 'completion') {
        console.log('任务完成！');
        console.log('视频地址:', data.final_video_url);
    } else if (data.type === 'error') {
        console.error('任务失败:', data.error);
    }
};

ws.onerror = (error) => {
    console.error('WebSocket 错误:', error);
};

ws.onclose = () => {
    console.log('WebSocket 连接关闭');
};
```

### API 速率限制

为了保护系统资源，API 实施了速率限制：

- **默认限制**: 60 次/分钟
- **登录端点**: 5 次/分钟
- **注册端点**: 3 次/分钟
- **项目列表**: 30 次/分钟

**响应头**:
- `X-RateLimit-Limit`: 速率限制（请求数）
- `X-RateLimit-Period`: 时间窗口（秒）
- `Retry-After`: 重试等待时间（秒，仅在 429 响应中）

**超出限制时的响应**:
```json
{
    "detail": "速率限制超出，请在 30 秒后重试",
    "retry_after": 30
}
```

HTTP 状态码: `429 Too Many Requests`

### 批量操作

#### 批量创建项目

可以使用脚本批量创建项目：

```python
import requests

BASE_URL = "http://localhost:8000"
TOKEN = "YOUR_ACCESS_TOKEN"
headers = {"Authorization": f"Bearer {TOKEN}"}

projects = [
    {
        "name": "项目 1",
        "theme": "主题 1",
        "outline": "大纲 1"
    },
    {
        "name": "项目 2",
        "theme": "主题 2",
        "outline": "大纲 2"
    },
    # ... 更多项目
]

for project in projects:
    response = requests.post(
        f"{BASE_URL}/api/projects",
        headers=headers,
        json=project
    )
    print(f"创建项目: {project['name']}, 状态: {response.status_code}")
```

#### 批量查询任务状态

```python
import requests

BASE_URL = "http://localhost:8000"
TOKEN = "YOUR_ACCESS_TOKEN"
headers = {"Authorization": f"Bearer {TOKEN}"}

task_ids = ["task1", "task2", "task3"]

for task_id in task_ids:
    response = requests.get(
        f"{BASE_URL}/api/tasks/{task_id}/status",
        headers=headers
    )
    status = response.json()
    print(f"任务 {task_id}: {status['status']}, 进度: {status['progress']}%")
```

## 最佳实践

### 1. 剧本生成

- **提供详细的主题和大纲**：越详细的输入，生成的剧本质量越高
- **使用关键词**：在主题中使用关键词（如"温馨"、"励志"、"悬疑"）
- **控制分镜数量**：建议 3-10 个分镜，太多会增加生产时间

### 2. 生产任务

- **避免并发生产**：同时生产多个项目会导致 GPU 显存不足
- **监控任务状态**：使用 WebSocket 实时监控，及时发现问题
- **保存重要项目**：定期备份生成的视频文件

### 3. 性能优化

- **调整 GPU 层数**：根据显存大小调整 `LLM_N_GPU_LAYERS`
- **降低分辨率**：如果显存不足，可以降低图像/视频分辨率
- **使用 Redis**：启用 Redis 可以提高任务调度性能

### 4. 错误处理

- **重试失败的任务**：大部分失败是临时性的，重试通常能成功
- **查看日志**：遇到问题时查看日志文件获取详细信息
- **清理 GPU 缓存**：定期重启服务清理 GPU 缓存

## 故障排查

### 常见错误

#### 1. 401 Unauthorized

**原因**: Token 无效或过期

**解决方案**:
- 重新登录获取新的 Token
- 使用 Refresh Token 刷新 Access Token

#### 2. 429 Too Many Requests

**原因**: 超出 API 速率限制

**解决方案**:
- 等待 `Retry-After` 秒后重试
- 减少 API 调用频率

#### 3. 500 Internal Server Error

**原因**: 服务器内部错误

**解决方案**:
- 查看服务器日志
- 检查服务是否正常运行
- 联系管理员

#### 4. 任务失败

**原因**: GPU 显存不足、模型加载失败、API 调用失败等

**解决方案**:
- 查看任务错误信息
- 重试任务
- 调整配置参数

## 附录

### API 端点总览

| 端点 | 方法 | 描述 |
|------|------|------|
| `/api/auth/register` | POST | 注册用户 |
| `/api/auth/login` | POST | 用户登录 |
| `/api/auth/refresh` | POST | 刷新 Token |
| `/api/auth/me` | GET | 获取当前用户信息 |
| `/api/projects` | GET | 获取项目列表 |
| `/api/projects` | POST | 创建项目 |
| `/api/projects/{id}` | GET | 获取项目详情 |
| `/api/projects/{id}` | PUT | 更新项目 |
| `/api/projects/{id}` | DELETE | 删除项目 |
| `/api/projects/{id}/generate-script` | POST | 生成剧本 |
| `/api/projects/{id}/regenerate-scene` | POST | 重新生成分镜 |
| `/api/projects/{id}/produce` | POST | 提交生产任务 |
| `/api/tasks/{id}/status` | GET | 查询任务状态 |
| `/api/tasks/{id}/cancel` | POST | 取消任务 |
| `/api/tasks/{id}/retry` | POST | 重试任务 |
| `/health` | GET | 健康检查 |
| `/ws/{project_id}` | WebSocket | 实时通知 |

### 状态码说明

| 状态码 | 说明 |
|--------|------|
| 200 | 请求成功 |
| 201 | 创建成功 |
| 400 | 请求参数错误 |
| 401 | 未授权（Token 无效或过期） |
| 403 | 禁止访问 |
| 404 | 资源不存在 |
| 429 | 速率限制超出 |
| 500 | 服务器内部错误 |

### 项目状态说明

| 状态 | 说明 |
|------|------|
| `draft` | 草稿（刚创建） |
| `script_generated` | 剧本已生成 |
| `in_production` | 生产中 |
| `completed` | 已完成 |
| `failed` | 失败 |

### 任务状态说明

| 状态 | 说明 |
|------|------|
| `pending` | 等待中 |
| `in_progress` | 进行中 |
| `completed` | 已完成 |
| `failed` | 失败 |
| `cancelled` | 已取消 |

## 获取帮助

如果您在使用过程中遇到问题，可以：

1. 查看 [快速开始指南](quick-start.md)
2. 查看 [常见问题解答（FAQ）](faq.md)
3. 查看 [API 文档](http://localhost:8000/docs)
4. 提交 [GitHub Issue](https://github.com/your-org/ai-short-drama-production/issues)
5. 加入社区讨论

祝您使用愉快！🎬
