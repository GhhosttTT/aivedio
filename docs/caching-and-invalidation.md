# 进程内缓存与失效语义

这个项目为了降低轮询、复审和合成阶段的开销，在进程内做了几层缓存。它们都只存在于当前 Python 进程：API 重启或 Celery Worker 重启后自动清空，不同进程之间不共享。

## 1. 文件摘要缓存

**位置**：`src/services/generation_review.py` · `file_hash()`

**键**：绝对路径 + `mtime_ns` + 文件大小

**作用**：同一文件在未变化时复用 SHA-256，避免轮询和证据校验反复读取整个视频。

**失效**：文件被替换（mtime 或大小变化）后自动重算。LRU 上限 512 条。

**限制**：如果原地重写后大小不变、且 mtime 被精确还原，会命中旧摘要。正常生成流程不会出现这种情况。

## 2. 视频技术指标缓存

**位置**：`src/services/video_quality_metrics.py` · `video_candidate_metrics()`

**键**：绝对路径 + `mtime_ns` + 大小 + `max_samples`

**作用**：provider 输出校验和候选排名经常对同一个新生成的片段重复评分；命中时直接深拷贝结果，调用方仍可自由添加字段。

**失效**：文件签名变化自动重算。`status != "available"` 的结果**不会缓存**，避免一次临时解码失败被固定下来。LRU 上限 32 条。

## 3. 合成阶段 ffprobe 缓存

**位置**：`src/services/video_composer.py`

**键**：绝对路径 + `mtime_ns` + 大小

**缓存项**：

- `_cached_probe_duration`：时长
- `_cached_probe_has_audio`：是否带音轨
- `_cached_probe_pixel_format`：像素格式（位深与色度检查共用）

**失效**：文件签名变化自动重算。无法 `stat` 的路径不缓存，仍走原来的直接探测路径。每个缓存 LRU 上限 256 条。

## 4. 字幕烧录像素格式缓存

**位置**：`src/services/subtitle_generator.py` · `_cached_pixel_format()`

**键**：绝对路径 + `mtime_ns` + 大小

**作用**：位深判断和色度格式判断共用一次 `ffprobe`。LRU 上限 128 条；无法 `stat` 的路径不缓存。

## 5. 生产就绪报告缓存

**位置**：`src/services/production_readiness.py` · `get_cached_production_readiness()`

**键**：项目 ID + `project.updated_at` + 引擎/模型/模式/分辨率/格式/时长覆盖参数

**TTL**：10 秒，最多 64 条。

**只缓存 `status == "ready"` 的报告**：

- `blocked` / `needs_review` 每次都重新计算，修完问题立刻可见；
- 任务创建路径直接调用 `ProductionReadinessService.build_report()`，不经过该缓存，因此**生成授权不依赖缓存副本**；
- 返回深拷贝，路由附加的 `delivery_evidence` 不会污染缓存。

## 6. 复审审计复用

**位置**：`src/api/routes/projects.py` · `_build_generation_review()`

**键**：`audit_input_hash`，由以下内容计算：

- 当前质量阈值（`_current_quality_gates`）
- 角色资产证据（参考图 hash 等）
- 图像生成合同
- 生产控制资产
- 每个分镜的文本字段、音频时长、图像/视频签名

**复用条件**：磁盘报告存在、`input_hash` 相同、`evidence_schema_version == 1`。

**覆盖范围**：连续性、节奏、场次风格、角色一致性、对白交付、上下文、运动、首帧，以及故事房质量。

**写入**：本轮已经持久化的审计不会在后续循环里重复写；首次计算也不会写两次。

## 7. 熔断与边界

- 所有这些缓存都是**进程内**的，多 worker 部署时各自独立，不会互相失效。
- 缓存不替代质量门禁：复审、就绪检查和任务创建仍会在关键路径重新校验必要证据。
- 若需要强制刷新，重启对应进程即可；测试中可通过各模块的 `clear_*_cache()` 函数清理。

## 8. 新增缓存时的建议

1. 优先用「路径 + mtime_ns + 大小」作为键，不要只用路径。
2. 返回可变对象时做深拷贝，避免调用方修改污染缓存。
3. 不要把失败结果缓存成永久状态；临时错误应允许下次重试。
4. 明确 TTL 或失效条件，并写一个能证明失效行为的测试。
5. 授权/计费路径不要依赖展示层缓存。
