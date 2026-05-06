# 视频生产流程修复总结

## 修复日期
2026-05-06

## 问题诊断

### 1. 任务链参数传递问题
**问题**: 在 `task_orchestrator.py` 中,任务使用了 `.s()` (signature) 方法,但任务函数定义中包含 `previous_result` 参数。这导致 Celery 任务链在传递参数时出现不匹配。

**影响**: 
- 视频生成任务无法正确接收参数
- 音频生成任务无法正确接收参数
- 字幕生成任务无法正确接收参数
- 整个任务链可能在第一步之后就失败

### 2. 任务签名不一致
**问题**: 
- `video_tasks.py` 中的 `generate_video_task` 有 `previous_result` 参数
- `audio_tasks.py` 中的 `generate_audio_task` 有 `previous_result` 参数
- `subtitle_tasks.py` 中的 `generate_subtitle_task` 有 `previous_result` 参数

但在任务编排器中使用 `.s()` 方法时,这些参数会导致签名不匹配。

### 3. 前端缺少独立控制
**问题**: 前端只有"开始制作"按钮,无法单独触发:
- 图像生成
- 视频生成
- 配音生成
- 字幕生成
- 视频合成

## 修复内容

### 后端修复

#### 1. 修复任务编排器 (`src/services/task_orchestrator.py`)
**修改**: 将所有任务从 `.s()` 改为 `.si()` (immutable signature)

```python
# 修改前
generate_video_task.s(scene.id, project_id, task_id)

# 修改后
generate_video_task.si(scene.id, project_id, task_id)
```

**原因**: `.si()` 方法创建不可变签名,忽略前一个任务的返回值,直接使用指定的参数。

#### 2. 修复视频生成任务 (`src/tasks/video_tasks.py`)
**修改**: 移除 `previous_result` 参数

```python
# 修改前
def generate_video_task(self, previous_result, scene_id: int, project_id: int, task_id: int, **kwargs):

# 修改后
def generate_video_task(self, scene_id: int, project_id: int, task_id: int, **kwargs):
```

#### 3. 修复音频生成任务 (`src/tasks/audio_tasks.py`)
**修改**: 移除 `previous_result` 参数

```python
# 修改前
def generate_audio_task(self, previous_result, scene_id: int, text: str, speaker: str, project_id: int, task_id: int, **kwargs):

# 修改后
def generate_audio_task(self, scene_id: int, text: str, speaker: str, project_id: int, task_id: int, **kwargs):
```

#### 4. 修复字幕生成任务 (`src/tasks/subtitle_tasks.py`)
**修改**: 移除 `previous_result` 参数

```python
# 修改前
def generate_subtitle_task(self, previous_result, scene_id: int, project_id: int, task_id: int, **kwargs):

# 修改后
def generate_subtitle_task(self, scene_id: int, project_id: int, task_id: int, **kwargs):
```

### 任务链执行流程

修复后的任务链执行顺序:

```
1. 图像生成 (并行)
   ├─ 分镜1: 生成图像
   ├─ 分镜2: 生成图像
   └─ 分镜N: 生成图像
   
2. 视频生成 (并行,依赖图像)
   ├─ 分镜1: 图生视频 (SVD)
   ├─ 分镜2: 图生视频 (SVD)
   └─ 分镜N: 图生视频 (SVD)
   
3. 音频生成 (并行)
   ├─ 分镜1: TTS 配音
   ├─ 分镜2: TTS 配音
   └─ 分镜N: TTS 配音
   
4. 字幕生成 (并行,依赖音频)
   ├─ 分镜1: 生成 SRT 字幕
   ├─ 分镜2: 生成 SRT 字幕
   └─ 分镜N: 生成 SRT 字幕
   
5. 视频合成 (串行)
   ├─ 拼接所有视频片段
   ├─ 同步音频
   ├─ 添加背景音乐 (可选)
   └─ 烧录字幕
```

## 前端改进建议

### 当前状态
- ✅ 有"开始制作"按钮 (触发完整流程)
- ✅ 有"重新制作"按钮 (清除图像并重新开始)
- ✅ 显示4个任务状态 (图像、视频、音频、字幕)
- ❌ 缺少独立步骤控制按钮

### 建议添加的功能

#### 1. 独立步骤控制按钮
在 `ProjectDetail.tsx` 中添加:

```typescript
// 仅生成视频 (图生视频)
<button onClick={handleGenerateVideos}>
  <Video size={20} />
  <span>生成视频</span>
</button>

// 仅生成配音
<button onClick={handleGenerateAudios}>
  <Mic size={20} />
  <span>生成配音</span>
</button>

// 仅生成字幕
<button onClick={handleGenerateSubtitles}>
  <FileText size={20} />
  <span>生成字幕</span>
</button>

// 仅合成视频
<button onClick={handleComposeVideo}>
  <Film size={20} />
  <span>合成视频</span>
</button>
```

#### 2. 后端 API 端点 (需要添加)
在 `src/api/routes/projects.py` 中添加:

```python
@router.post("/{project_id}/generate-videos")
async def generate_videos_only(project_id: int):
    """仅生成视频 (图生视频)"""
    # 调用任务编排器,只执行视频生成步骤
    pass

@router.post("/{project_id}/generate-audios")
async def generate_audios_only(project_id: int):
    """仅生成配音"""
    # 调用任务编排器,只执行音频生成步骤
    pass

@router.post("/{project_id}/generate-subtitles")
async def generate_subtitles_only(project_id: int):
    """仅生成字幕"""
    # 调用任务编排器,只执行字幕生成步骤
    pass

@router.post("/{project_id}/compose-video")
async def compose_video_only(project_id: int):
    """仅合成最终视频"""
    # 调用任务编排器,只执行合成步骤
    pass
```

#### 3. 任务编排器方法 (需要添加)
在 `src/services/task_orchestrator.py` 中添加:

```python
def create_video_generation_task(self, project_id: int) -> str:
    """创建仅视频生成任务"""
    return self.create_production_task(
        project_id=project_id,
        generate_images=False,  # 跳过图像
        generate_videos=True,   # 只生成视频
        generate_audios=False,  # 跳过音频
        generate_subtitles=False,  # 跳过字幕
    )

def create_audio_generation_task(self, project_id: int) -> str:
    """创建仅音频生成任务"""
    return self.create_production_task(
        project_id=project_id,
        generate_images=False,
        generate_videos=False,
        generate_audios=True,   # 只生成音频
        generate_subtitles=False,
    )

def create_subtitle_generation_task(self, project_id: int) -> str:
    """创建仅字幕生成任务"""
    return self.create_production_task(
        project_id=project_id,
        generate_images=False,
        generate_videos=False,
        generate_audios=False,
        generate_subtitles=True,  # 只生成字幕
    )

def create_composition_task(self, project_id: int) -> str:
    """创建仅合成任务"""
    # 直接调用合成任务
    from src.tasks.composition_tasks import compose_final_video_task
    result = compose_final_video_task.apply_async(
        args=[project_id, 0, False, None]
    )
    return result.id
```

## 测试建议

### 1. 单元测试
- 测试任务链构建是否正确
- 测试每个任务是否能独立执行
- 测试参数传递是否正确

### 2. 集成测试
- 创建项目 → 生成剧本 → 开始制作 → 验证完整流程
- 测试"重新制作"功能
- 测试任务取消功能
- 测试任务重试功能

### 3. 端到端测试
- 使用真实的 ComfyUI、SVD、TTS 服务
- 验证生成的图像、视频、音频、字幕质量
- 验证最终合成视频的质量

## 验证步骤

1. **重启 Celery Worker**
   ```bash
   # 停止现有 worker
   pkill -f celery
   
   # 启动新 worker
   celery -A src.tasks.celery_app worker --loglevel=info
   ```

2. **测试完整流程**
   - 创建新项目
   - 生成剧本
   - 点击"开始制作"
   - 观察日志输出
   - 检查是否生成了图像、视频、音频、字幕
   - 检查最终视频是否合成成功

3. **检查日志**
   ```bash
   # 查看 Celery 日志
   tail -f celery.log
   
   # 查看 API 日志
   tail -f api.log
   ```

## 已知限制

1. **任务链不支持部分重试**: 如果某个步骤失败,需要重新执行整个流程
2. **并行任务数量限制**: 取决于 Celery worker 的并发配置
3. **资源占用**: 图像和视频生成需要大量 GPU 资源

## 后续优化建议

1. **添加任务队列优先级**: 让重要任务优先执行
2. **添加任务进度细粒度追踪**: 每个步骤的详细进度
3. **添加任务失败自动重试**: 自动重试失败的任务
4. **添加资源监控**: 监控 GPU、内存使用情况
5. **添加任务调度策略**: 根据资源情况动态调整任务执行

## 相关文件

### 后端
- `src/services/task_orchestrator.py` - 任务编排器
- `src/tasks/image_tasks.py` - 图像生成任务
- `src/tasks/video_tasks.py` - 视频生成任务 ✅ 已修复
- `src/tasks/audio_tasks.py` - 音频生成任务 ✅ 已修复
- `src/tasks/subtitle_tasks.py` - 字幕生成任务 ✅ 已修复
- `src/tasks/composition_tasks.py` - 视频合成任务
- `src/api/routes/projects.py` - 项目 API 路由

### 前端
- `frontend/src/pages/ProjectDetail.tsx` - 项目详情页
- `frontend/src/components/ProductionProgress.tsx` - 生产进度组件

## 总结

本次修复解决了任务链参数传递的核心问题,确保了图像→视频→音频→字幕→合成的完整流程能够正确执行。

**关键修改**:
1. 使用 `.si()` 代替 `.s()` 创建不可变任务签名
2. 移除所有任务函数中的 `previous_result` 参数
3. 保持任务链的顺序执行逻辑

**验证状态**: ⏳ 待测试

**下一步**: 
1. 重启 Celery Worker
2. 运行完整流程测试
3. 根据测试结果进行进一步优化
