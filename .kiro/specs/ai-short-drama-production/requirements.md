# 需求文档

## 简介

AI 短剧自动化生产平台是一个端到端的短剧制作解决方案，通过集成大语言模型（Qwen2.5-14B）、文生图（Stable Diffusion + ComfyUI）、图生视频（SVD）、AI 配音（MiMo-V2-TTS）和自动字幕生成技术，实现从创意想法到完整短剧视频的全自动化生产流程。

本文档定义了系统的功能需求和验收标准，基于设计文档中的9个核心组件和主要工作流程。所有需求遵循 EARS（Easy Approach to Requirements Syntax）规范，确保需求的清晰性、可测试性和可追溯性。

## 术语表

- **System**: AI 短剧自动化生产平台
- **ProjectManager**: 项目管理服务，负责管理短剧项目的生命周期
- **ScriptGenerator**: 剧本生成服务，负责调用 LLM 生成剧本和分镜
- **TaskOrchestrator**: 任务编排服务，负责协调各个 AI 服务的调用顺序
- **LLMService**: LLM 服务，封装 llama.cpp 调用逻辑
- **ComfyUIService**: ComfyUI 服务，负责调用 Stable Diffusion 生成图像
- **SVDService**: SVD 服务，负责将图像转换为视频
- **TTSService**: TTS 服务，负责调用 MiMo-V2-TTS API 生成配音
- **SubtitleGenerator**: 字幕生成服务，负责生成和烧录字幕
- **VideoComposer**: 视频合成服务，负责拼接视频片段并导出最终视频
- **Project**: 短剧项目，包含剧本、分镜、配置参数等信息
- **Scene**: 分镜，对应短剧中的一个镜头
- **Task**: 生产任务，如图像生成、视频生成、配音生成等
- **WebSocket**: 实时通信协议，用于推送任务进度更新
- **GPU**: 图形处理单元，用于运行 AI 模型
- **CPU_Offload**: 将部分 LLM 层从 GPU 转移到 CPU 执行，以节省显存

## 需求

### 需求 1：项目管理

**用户故事**：作为短剧创作者，我想要创建和管理短剧项目，以便组织我的创作内容和跟踪制作进度。

#### 验收标准

1. WHEN 用户提供项目名称和可选的主题或大纲 THEN THE ProjectManager SHALL 创建新项目并返回项目 ID
2. WHEN 用户请求获取项目详情 THEN THE ProjectManager SHALL 返回包含剧本、分镜、状态和配置的完整项目信息
3. WHEN 用户更新项目的剧本或分镜 THEN THE ProjectManager SHALL 保存更新并更新项目的 updated_at 时间戳
4. WHEN 用户请求删除项目 THEN THE ProjectManager SHALL 删除项目记录和所有关联的文件（图像、视频、音频）
5. WHEN 用户请求项目列表 THEN THE ProjectManager SHALL 返回按创建时间倒序排列的项目列表，支持状态过滤和分页

### 需求 2：剧本自动生成

**用户故事**：作为短剧创作者，我想要通过输入主题或故事大纲自动生成完整剧本和分镜，以便快速将创意转化为可执行的制作方案。

#### 验收标准

1. WHEN 用户提供主题关键词或故事大纲 THEN THE ScriptGenerator SHALL 调用 LLMService 生成包含对话、场景描述和角色动作的完整剧本
2. WHEN 剧本生成完成 THEN THE ScriptGenerator SHALL 自动解析剧本并生成结构化的分镜列表，每个分镜包含场景描述、角色、对话和图像提示词
3. WHEN 用户未提供主题和大纲 THEN THE ScriptGenerator SHALL 返回错误提示要求至少提供一个
4. WHEN 用户请求重新生成单个分镜 THEN THE ScriptGenerator SHALL 根据新的描述重新生成该分镜的所有字段
5. WHEN LLMService 不可用 THEN THE ScriptGenerator SHALL 返回服务不可用错误并记录日志

### 需求 3：任务编排与调度

**用户故事**：作为系统，我需要协调多个 AI 服务的调用顺序，以便高效地完成短剧生产流程。

#### 验收标准

1. WHEN 用户提交生产任务 THEN THE TaskOrchestrator SHALL 为每个分镜创建图像生成、视频生成、配音生成和字幕生成的任务链
2. WHEN 任务链创建完成 THEN THE TaskOrchestrator SHALL 将任务提交到 Celery 队列并返回任务链 ID
3. WHEN 用户查询任务状态 THEN THE TaskOrchestrator SHALL 返回包含进度百分比、当前分镜和总分镜数的状态信息
4. WHEN 用户取消任务 THEN THE TaskOrchestrator SHALL 停止所有未完成的任务并更新任务状态为已取消
5. WHEN 任务失败且重试次数未达上限 THEN THE TaskOrchestrator SHALL 自动重试该任务，重试间隔使用指数退避策略
6. WHEN 所有分镜任务完成 THEN THE TaskOrchestrator SHALL 自动触发视频合成任务

### 需求 4：LLM 推理服务

**用户故事**：作为系统，我需要高效地运行大语言模型生成剧本，同时优化 GPU 显存使用。

#### 验收标准

1. WHEN LLMService 初始化 THEN THE LLMService SHALL 加载 GGUF 格式的 Qwen2.5-14B 模型，并将指定数量的层加载到 GPU，其余层 offload 到 CPU
2. WHEN LLMService 接收生成请求 THEN THE LLMService SHALL 在指定的 max_tokens、temperature 和 top_p 参数下生成文本
3. WHEN 生成请求包含停止词 THEN THE LLMService SHALL 在遇到停止词时立即停止生成
4. WHEN LLMService 卸载模型 THEN THE LLMService SHALL 释放所有 GPU 和 CPU 资源
5. WHEN GPU 显存不足 THEN THE LLMService SHALL 自动调整 offload 层数或返回显存不足错误

### 需求 5：图像生成服务

**用户故事**：作为系统，我需要根据分镜描述生成高质量图像，以便为视频生成提供输入。

#### 验收标准

1. WHEN ComfyUIService 接收图像生成请求 THEN THE ComfyUIService SHALL 调用 ComfyUI HTTP API 并传递提示词、分辨率和采样参数
2. WHEN 图像生成完成 THEN THE ComfyUIService SHALL 返回生成的图像文件路径
3. WHEN ComfyUI 服务不可用 THEN THE ComfyUIService SHALL 返回服务不可用错误
4. WHEN 图像生成失败 THEN THE ComfyUIService SHALL 自动重试最多 3 次，每次重试间隔递增
5. WHEN 批量生成图像 THEN THE ComfyUIService SHALL 支持一次生成多张图像以提高效率

### 需求 6：视频生成服务

**用户故事**：作为系统，我需要将生成的图像转换为视频片段，以便构建完整的短剧。

#### 验收标准

1. WHEN SVDService 接收视频生成请求 THEN THE SVDService SHALL 加载输入图像并使用 SVD 模型生成指定帧数和帧率的视频
2. WHEN 视频生成完成 THEN THE SVDService SHALL 保存视频文件并返回文件路径
3. WHEN GPU 显存不足 THEN THE SVDService SHALL 清理 GPU 缓存后重试
4. WHEN 视频生成失败 THEN THE SVDService SHALL 自动重试最多 3 次
5. WHEN 视频生成前 THEN THE SVDService SHALL 检查 GPU 显存使用情况并记录日志

### 需求 7：配音生成服务

**用户故事**：作为系统，我需要为剧本对话生成自然的配音，以便增强短剧的表现力。

#### 验收标准

1. WHEN TTSService 接收配音请求 THEN THE TTSService SHALL 调用 MiMo-V2-TTS API 并传递文本、说话人 ID、情感标签和语速参数
2. WHEN 配音生成完成 THEN THE TTSService SHALL 返回生成的音频文件路径
3. WHEN TTS API 返回配额不足错误 THEN THE TTSService SHALL 暂停所有配音任务并通知用户
4. WHEN TTS API 调用失败 THEN THE TTSService SHALL 自动重试最多 3 次
5. WHEN 用户查询可用说话人 THEN THE TTSService SHALL 返回所有可用的说话人 ID 和描述

### 需求 8：字幕生成与烧录

**用户故事**：作为系统，我需要自动生成字幕并嵌入视频，以便观众能够清晰看到对话内容。

#### 验收标准

1. WHEN SubtitleGenerator 接收字幕生成请求 THEN THE SubtitleGenerator SHALL 根据对话内容和音频时长生成 SRT 格式的字幕文件
2. WHEN 字幕文件生成完成 THEN THE SubtitleGenerator SHALL 使用 FFmpeg 将字幕烧录到视频中，字幕样式为白色字体加黑色描边
3. WHEN 字幕烧录完成 THEN THE SubtitleGenerator SHALL 返回烧录后的视频文件路径
4. WHEN 对话过长导致字幕显示不全 THEN THE SubtitleGenerator SHALL 自动分行或缩短显示时间
5. WHEN 字幕时间轴与配音不匹配 THEN THE SubtitleGenerator SHALL 自动调整字幕时间戳以对齐配音

### 需求 9：视频合成与导出

**用户故事**：作为短剧创作者，我想要系统自动将所有视频片段、配音和字幕合成为完整的短剧成品，以便直接发布。

#### 验收标准

1. WHEN VideoComposer 接收合成请求 THEN THE VideoComposer SHALL 按分镜顺序拼接所有视频片段
2. WHEN 视频片段拼接完成 THEN THE VideoComposer SHALL 同步配音音频到视频
3. WHEN 提供字幕文件 THEN THE VideoComposer SHALL 将字幕烧录到视频中
4. WHEN 提供背景音乐 THEN THE VideoComposer SHALL 添加背景音乐并调整音量
5. WHEN 视频合成完成 THEN THE VideoComposer SHALL 导出最终视频文件并返回文件路径
6. WHEN 视频片段分辨率不一致 THEN THE VideoComposer SHALL 自动统一为最高分辨率
7. WHEN 配音音频与视频时长不匹配 THEN THE VideoComposer SHALL 自动调整音频或视频播放速度以对齐

### 需求 10：实时进度推送

**用户故事**：作为短剧创作者，我想要实时看到生产进度更新，以便了解任务执行状态。

#### 验收标准

1. WHEN 用户连接到 WebSocket 端点 THEN THE System SHALL 接受连接并将其加入到对应项目的连接池
2. WHEN 任务状态发生变化 THEN THE System SHALL 通过 WebSocket 向所有连接的客户端推送状态更新消息
3. WHEN 任务进度更新 THEN THE System SHALL 推送包含进度百分比、当前分镜和状态描述的消息
4. WHEN 任务完成或失败 THEN THE System SHALL 推送完成或错误通知消息
5. WHEN 客户端断开连接 THEN THE System SHALL 从连接池中移除该连接

### 需求 11：错误处理与重试

**用户故事**：作为系统，我需要优雅地处理各种错误情况，以便提高系统的可靠性和用户体验。

#### 验收标准

1. WHEN AI 服务调用失败 THEN THE System SHALL 自动重试最多 3 次，使用指数退避策略
2. WHEN 重试仍然失败 THEN THE System SHALL 标记任务为失败状态并记录详细错误日志
3. WHEN GPU 显存不足 THEN THE System SHALL 清理 GPU 缓存并重试操作
4. WHEN 磁盘空间不足 THEN THE System SHALL 暂停所有生成任务并通知用户清理空间
5. WHEN 用户请求重试失败的任务 THEN THE System SHALL 重新提交该任务到队列
6. IF 任务失败 THEN THE System SHALL 通过 WebSocket 推送错误通知，包含错误代码和描述

### 需求 12：显存优化

**用户故事**：作为系统，我需要优化 GPU 显存使用，以便在单张 24GB 显卡上同时运行多个 AI 模型。

#### 验收标准

1. WHEN LLMService 初始化 THEN THE System SHALL 仅加载指定数量的层到 GPU（默认 20 层），其余层 offload 到 CPU
2. WHEN SD 和 SVD 任务执行 THEN THE System SHALL 串行执行这两类任务，避免同时占用显存
3. WHEN 任务切换时 THEN THE System SHALL 清理 GPU 缓存以释放显存
4. WHEN GPU 显存使用率超过 95% THEN THE System SHALL 记录警告日志并尝试清理缓存
5. WHEN 系统启动时 THEN THE System SHALL 检测 GPU 显存大小并自动调整 LLM offload 层数

### 需求 13：API 认证与授权

**用户故事**：作为系统管理员，我想要保护 API 端点免受未授权访问，以便确保系统安全。

#### 验收标准

1. WHEN 用户登录 THEN THE System SHALL 验证用户名和密码，成功后返回 JWT Token
2. WHEN 用户访问受保护的 API 端点 THEN THE System SHALL 验证 JWT Token 的有效性
3. WHEN JWT Token 无效或过期 THEN THE System SHALL 返回 401 未授权错误
4. WHEN JWT Token 有效 THEN THE System SHALL 允许访问并从 Token 中提取用户信息
5. WHEN 用户注销 THEN THE System SHALL 使 JWT Token 失效（通过黑名单或过期时间）

### 需求 14：输入验证

**用户故事**：作为系统，我需要验证所有用户输入，以便防止注入攻击和数据损坏。

#### 验收标准

1. WHEN 用户提交项目创建请求 THEN THE System SHALL 验证项目名称长度在 1-100 字符之间且只包含合法字符
2. WHEN 用户提交剧本生成请求 THEN THE System SHALL 验证分镜数量在 1-50 之间，角色数量在 1-10 之间
3. WHEN 用户输入包含特殊字符 THEN THE System SHALL 转义或移除潜在的 XSS 攻击代码
4. WHEN 输入验证失败 THEN THE System SHALL 返回 400 错误并提供详细的验证错误信息
5. WHEN 用户上传文件 THEN THE System SHALL 验证文件类型和大小是否符合限制

### 需求 15：性能监控

**用户故事**：作为系统管理员，我想要监控系统性能指标，以便及时发现和解决性能问题。

#### 验收标准

1. WHEN API 请求完成 THEN THE System SHALL 记录请求耗时并更新 Prometheus 指标
2. WHEN 任务执行完成 THEN THE System SHALL 记录任务执行时间并按任务类型分类
3. WHEN GPU 显存使用量变化 THEN THE System SHALL 定期更新 GPU 显存使用量指标
4. WHEN 用户访问监控端点 THEN THE System SHALL 返回所有收集的性能指标
5. WHEN 性能指标超过阈值 THEN THE System SHALL 记录警告日志

## 非功能需求

### 需求 16：性能要求

**用户故事**：作为短剧创作者，我期望系统能够在合理的时间内完成短剧生产。

#### 验收标准

1. THE System SHALL 在 1 分钟内完成单个剧本的生成（10-20 个分镜）
2. THE System SHALL 在 30 秒内完成单张图像的生成（基于 RTX 3090 或更高性能 GPU）
3. THE System SHALL 在 2 分钟内完成单个视频片段的生成（3-5 秒视频）
4. THE System SHALL 在 5 秒内完成单句对话的配音生成
5. THE System SHALL 在 2.5 小时内完成包含 10 个镜头的完整短剧生产
6. THE System SHALL 在 500 毫秒内响应非生成类 API 请求（如获取项目详情）
7. THE System SHALL 在 100 毫秒内通过 WebSocket 推送进度更新

### 需求 17：可靠性要求

**用户故事**：作为短剧创作者，我期望系统能够稳定运行，不会因为偶发错误而导致整个生产流程失败。

#### 验收标准

1. WHEN 单个分镜生成失败 THEN THE System SHALL 继续处理其他分镜，不影响整体流程
2. WHEN AI 服务暂时不可用 THEN THE System SHALL 自动重试并在服务恢复后继续执行
3. WHEN 系统重启 THEN THE System SHALL 能够恢复未完成的任务并继续执行
4. THE System SHALL 保证 99% 的 API 请求成功率（排除用户输入错误）
5. THE System SHALL 在发生错误时提供详细的错误信息和恢复建议

### 需求 18：可扩展性要求

**用户故事**：作为系统架构师，我期望系统能够方便地扩展和升级各个组件。

#### 验收标准

1. THE System SHALL 采用模块化设计，每个 AI 服务独立封装
2. WHEN 需要升级 LLM 模型 THEN THE System SHALL 支持通过配置文件切换模型而无需修改代码
3. WHEN 需要添加新的 AI 服务 THEN THE System SHALL 支持通过实现标准接口来集成新服务
4. THE System SHALL 支持水平扩展 Celery Worker 以提高并发处理能力
5. THE System SHALL 支持通过配置文件调整任务队列优先级和并发数

### 需求 19：可维护性要求

**用户故事**：作为开发人员，我期望系统代码清晰易懂，便于维护和调试。

#### 验收标准

1. THE System SHALL 为所有公共函数和方法提供文档字符串，说明功能、参数和返回值
2. THE System SHALL 使用统一的代码风格（4 空格缩进，驼峰命名）
3. THE System SHALL 为所有关键操作记录详细的日志，包括时间戳、操作类型和结果
4. THE System SHALL 提供单元测试覆盖率不低于 80% 的核心业务逻辑
5. THE System SHALL 使用类型注解（Type Hints）提高代码可读性

### 需求 20：安全性要求

**用户故事**：作为系统管理员，我期望系统能够保护用户数据和 API 密钥的安全。

#### 验收标准

1. THE System SHALL 将所有 API 密钥存储在环境变量或加密配置文件中，不硬编码在代码中
2. THE System SHALL 使用 bcrypt 算法哈希存储用户密码
3. THE System SHALL 使用 HTTPS 协议保护 API 通信（生产环境）
4. THE System SHALL 对所有用户输入进行验证和清理，防止注入攻击
5. THE System SHALL 实施 API 速率限制，防止滥用和 DDoS 攻击
6. THE System SHALL 将用户生成的所有文件存储在本地，不上传到云端（除 API 调用外）


## 验收标准可测试性分析

### 需求 1：项目管理

1.1 WHEN 用户提供项目名称和可选的主题或大纲 THEN THE ProjectManager SHALL 创建新项目并返回项目 ID
  思考：这是测试项目创建功能，可以生成随机的项目名称、主题和大纲，验证返回的项目 ID 是否有效且唯一
  分类：PROPERTY
  测试策略：生成随机项目数据，验证创建成功且返回有效 ID

1.2 WHEN 用户请求获取项目详情 THEN THE ProjectManager SHALL 返回包含剧本、分镜、状态和配置的完整项目信息
  思考：这是测试项目检索功能，可以创建随机项目后立即检索，验证返回的数据完整性
  分类：PROPERTY
  测试策略：创建项目后检索，验证所有字段都存在且正确

1.3 WHEN 用户更新项目的剧本或分镜 THEN THE ProjectManager SHALL 保存更新并更新项目的 updated_at 时间戳
  思考：这是测试更新功能，可以生成随机更新数据，验证更新后的值和时间戳
  分类：PROPERTY
  测试策略：更新项目，验证字段值改变且 updated_at 增加

1.4 WHEN 用户请求删除项目 THEN THE ProjectManager SHALL 删除项目记录和所有关联的文件
  思考：这是测试删除功能，可以创建项目和文件后删除，验证项目和文件都不存在
  分类：PROPERTY
  测试策略：创建项目和文件，删除后验证都不存在

1.5 WHEN 用户请求项目列表 THEN THE ProjectManager SHALL 返回按创建时间倒序排列的项目列表
  思考：这是测试列表排序功能，可以创建多个项目，验证返回的列表顺序正确
  分类：PROPERTY
  测试策略：创建多个项目，验证列表按时间倒序排列

### 需求 2：剧本自动生成

2.1 WHEN 用户提供主题关键词或故事大纲 THEN THE ScriptGenerator SHALL 调用 LLMService 生成完整剧本
  思考：这是测试 LLM 集成，但 LLM 输出不确定。我们可以验证输出格式和必需字段的存在
  分类：INTEGRATION
  测试策略：使用 mock LLM 服务，验证调用参数正确且输出格式有效

2.2 WHEN 剧本生成完成 THEN THE ScriptGenerator SHALL 自动解析剧本并生成结构化的分镜列表
  思考：这是测试解析功能，可以提供各种格式的剧本文本，验证解析结果的结构正确性
  分类：PROPERTY
  测试策略：生成随机剧本文本，验证解析后的分镜列表结构完整

2.3 WHEN 用户未提供主题和大纲 THEN THE ScriptGenerator SHALL 返回错误提示
  思考：这是边界条件测试，验证输入验证逻辑
  分类：EXAMPLE
  测试策略：提供空输入，验证返回特定错误

2.4 WHEN 用户请求重新生成单个分镜 THEN THE ScriptGenerator SHALL 根据新的描述重新生成该分镜
  思考：这是测试部分重新生成功能，可以生成随机分镜描述，验证只有指定分镜被更新
  分类：PROPERTY
  测试策略：重新生成单个分镜，验证只有该分镜改变

2.5 WHEN LLMService 不可用 THEN THE ScriptGenerator SHALL 返回服务不可用错误
  思考：这是错误处理测试，模拟服务不可用情况
  分类：EXAMPLE
  测试策略：Mock LLM 服务抛出异常，验证错误处理

### 需求 3：任务编排与调度

3.1 WHEN 用户提交生产任务 THEN THE TaskOrchestrator SHALL 为每个分镜创建任务链
  思考：这是测试任务创建逻辑，可以生成随机数量的分镜，验证任务链结构正确
  分类：PROPERTY
  测试策略：提交不同数量的分镜，验证任务链数量和结构

3.2 WHEN 任务链创建完成 THEN THE TaskOrchestrator SHALL 将任务提交到 Celery 队列
  思考：这是测试 Celery 集成，可以验证任务是否被正确提交
  分类：INTEGRATION
  测试策略：Mock Celery，验证任务提交调用

3.3 WHEN 用户查询任务状态 THEN THE TaskOrchestrator SHALL 返回包含进度信息的状态
  思考：这是测试状态查询功能，可以在不同阶段查询，验证状态信息正确
  分类：PROPERTY
  测试策略：在不同进度查询，验证返回的进度百分比正确

3.4 WHEN 用户取消任务 THEN THE TaskOrchestrator SHALL 停止所有未完成的任务
  思考：这是测试取消功能，可以在任务执行中取消，验证状态变化
  分类：PROPERTY
  测试策略：启动任务后立即取消，验证状态为已取消

3.5 WHEN 任务失败且重试次数未达上限 THEN THE TaskOrchestrator SHALL 自动重试
  思考：这是测试重试逻辑，可以模拟失败情况，验证重试次数和间隔
  分类：PROPERTY
  测试策略：模拟任务失败，验证重试次数和指数退避

3.6 WHEN 所有分镜任务完成 THEN THE TaskOrchestrator SHALL 自动触发视频合成任务
  思考：这是测试任务链完成逻辑，可以模拟所有任务完成，验证合成任务被触发
  分类：PROPERTY
  测试策略：完成所有分镜任务，验证合成任务启动

### 需求 4-7：AI 服务（LLM、ComfyUI、SVD、TTS）

这些需求主要涉及外部 AI 服务的集成，行为不随输入显著变化，适合使用集成测试而非属性测试。

4.1-4.5, 5.1-5.5, 6.1-6.5, 7.1-7.5
  思考：这些是测试外部 AI 服务的集成，服务行为由外部系统决定，不适合属性测试
  分类：INTEGRATION
  测试策略：使用 Mock 服务，验证调用参数正确和错误处理

### 需求 8：字幕生成与烧录

8.1 WHEN SubtitleGenerator 接收字幕生成请求 THEN SHALL 生成 SRT 格式的字幕文件
  思考：这是测试字幕生成功能，可以生成随机对话和音频时长，验证 SRT 格式正确
  分类：PROPERTY
  测试策略：生成随机对话，验证 SRT 文件格式和时间轴正确

8.2 WHEN 字幕文件生成完成 THEN SHALL 使用 FFmpeg 将字幕烧录到视频中
  思考：这是测试 FFmpeg 集成，可以验证烧录后的视频包含字幕
  分类：INTEGRATION
  测试策略：烧录字幕，验证输出视频存在且大小合理

8.3 WHEN 字幕烧录完成 THEN SHALL 返回烧录后的视频文件路径
  思考：这是测试返回值，可以验证路径有效且文件存在
  分类：PROPERTY
  测试策略：烧录字幕，验证返回路径指向有效文件

8.4 WHEN 对话过长 THEN SHALL 自动分行或缩短显示时间
  思考：这是测试边界处理，可以生成超长对话，验证分行逻辑
  分类：EDGE_CASE
  测试策略：生成超长对话，验证字幕被正确分行

8.5 WHEN 字幕时间轴与配音不匹配 THEN SHALL 自动调整字幕时间戳
  思考：这是测试时间对齐功能，可以提供不匹配的时间轴，验证调整逻辑
  分类：PROPERTY
  测试策略：提供不匹配的时间轴，验证调整后对齐

### 需求 9：视频合成与导出

9.1 WHEN VideoComposer 接收合成请求 THEN SHALL 按分镜顺序拼接所有视频片段
  思考：这是测试视频拼接功能，可以生成随机数量的视频片段，验证拼接顺序正确
  分类：PROPERTY
  测试策略：拼接多个视频，验证输出视频时长等于所有片段之和

9.2 WHEN 视频片段拼接完成 THEN SHALL 同步配音音频到视频
  思考：这是测试音视频同步功能，可以验证同步后的时长一致
  分类：PROPERTY
  测试策略：同步音视频，验证输出视频时长与音频一致

9.3-9.5 字幕烧录、背景音乐、导出
  思考：这些是测试视频处理功能，可以验证输出文件的存在和格式
  分类：PROPERTY
  测试策略：执行操作，验证输出文件有效

9.6 WHEN 视频片段分辨率不一致 THEN SHALL 自动统一为最高分辨率
  思考：这是测试分辨率统一功能，可以提供不同分辨率的视频，验证统一逻辑
  分类：PROPERTY
  测试策略：提供不同分辨率视频，验证输出为最高分辨率

9.7 WHEN 配音音频与视频时长不匹配 THEN SHALL 自动调整以对齐
  思考：这是测试时长对齐功能，可以提供不匹配的音视频，验证调整逻辑
  分类：PROPERTY
  测试策略：提供不匹配的音视频，验证调整后时长一致

### 需求 10：实时进度推送

10.1 WHEN 用户连接到 WebSocket 端点 THEN SHALL 接受连接
  思考：这是测试 WebSocket 连接功能，可以验证连接建立成功
  分类：EXAMPLE
  测试策略：建立连接，验证连接状态

10.2 WHEN 任务状态发生变化 THEN SHALL 通过 WebSocket 推送状态更新消息
  思考：这是测试消息推送功能，可以模拟状态变化，验证消息被推送
  分类：PROPERTY
  测试策略：改变任务状态，验证 WebSocket 收到消息

10.3-10.5 进度更新、完成通知、断开连接
  思考：这些是测试 WebSocket 通信功能，可以验证消息格式和连接管理
  分类：PROPERTY
  测试策略：执行操作，验证 WebSocket 行为正确

### 需求 11：错误处理与重试

11.1 WHEN AI 服务调用失败 THEN SHALL 自动重试最多 3 次
  思考：这是测试重试逻辑，可以模拟失败情况，验证重试次数
  分类：PROPERTY
  测试策略：模拟服务失败，验证重试次数为 3

11.2-11.6 各种错误处理场景
  思考：这些是测试错误处理逻辑，可以模拟各种错误，验证处理行为
  分类：PROPERTY
  测试策略：模拟错误，验证错误处理和恢复逻辑

### 需求 12：显存优化

12.1 WHEN LLMService 初始化 THEN SHALL 仅加载指定数量的层到 GPU
  思考：这是测试 GPU 配置功能，可以验证加载的层数正确
  分类：EXAMPLE
  测试策略：初始化服务，验证 GPU 层数配置

12.2-12.5 显存管理和优化
  思考：这些是测试显存管理功能，可以监控显存使用情况
  分类：INTEGRATION
  测试策略：执行任务，监控显存使用率

### 需求 13-14：安全性（认证、输入验证）

13.1-13.5, 14.1-14.5
  思考：这些是测试安全功能，可以提供各种输入，验证验证和认证逻辑
  分类：PROPERTY
  测试策略：提供有效和无效输入，验证验证逻辑

### 需求 15：性能监控

15.1-15.5
  思考：这些是测试监控功能，可以执行操作，验证指标被记录
  分类：INTEGRATION
  测试策略：执行操作，验证 Prometheus 指标更新

### 非功能需求 16-20

这些是性能、可靠性、可扩展性、可维护性和安全性要求，不适合属性测试，需要通过性能测试、代码审查和安全审计来验证。

## 正确性属性

*属性是系统在所有有效执行中应该保持的特征或行为——本质上是关于系统应该做什么的形式化陈述。属性是人类可读规范和机器可验证正确性保证之间的桥梁。*

### 属性 1：项目创建幂等性

*对于任何*有效的项目名称、主题和大纲，创建项目应该返回唯一的项目 ID，且该项目可以通过 ID 检索到完整信息

**验证需求：1.1, 1.2**

### 属性 2：项目更新保持一致性

*对于任何*已存在的项目，更新剧本或分镜后，检索项目应该返回更新后的值，且 updated_at 时间戳应该大于更新前的值

**验证需求：1.3**

### 属性 3：项目删除完整性

*对于任何*已存在的项目，删除项目后，该项目不应该能被检索到，且所有关联的文件应该被删除

**验证需求：1.4**

### 属性 4：项目列表排序正确性

*对于任何*项目集合，列表查询应该返回按 created_at 时间戳倒序排列的项目列表

**验证需求：1.5**

### 属性 5：剧本解析结构完整性

*对于任何*符合格式的剧本文本，解析后的分镜列表中每个分镜都应该包含 scene_id、description 和 visual_prompt 字段

**验证需求：2.2**

### 属性 6：分镜重新生成隔离性

*对于任何*包含多个分镜的项目，重新生成单个分镜后，只有该分镜的内容应该改变，其他分镜保持不变

**验证需求：2.4**

### 属性 7：任务链结构正确性

*对于任何*包含 N 个分镜的项目，创建生产任务应该生成 N 个分镜任务链，每个任务链包含图像、视频、配音和字幕任务

**验证需求：3.1**

### 属性 8：任务进度单调递增

*对于任何*正在执行的任务，查询任务状态返回的进度百分比应该单调递增（不会减少）

**验证需求：3.3**

### 属性 9：任务取消有效性

*对于任何*正在执行的任务，取消任务后，任务状态应该变为已取消，且不应该继续执行

**验证需求：3.4**

### 属性 10：任务重试次数限制

*对于任何*失败的任务，自动重试次数不应该超过配置的最大重试次数（默认 3 次）

**验证需求：3.5, 11.1**

### 属性 11：字幕时间轴对齐

*对于任何*对话和配音音频，生成的字幕时间轴应该与音频时长对齐，误差不超过 100 毫秒

**验证需求：8.1, 8.5**

### 属性 12：字幕文件格式正确性

*对于任何*对话列表，生成的 SRT 文件应该符合 SRT 格式规范，包含序号、时间戳和文本

**验证需求：8.1**

### 属性 13：视频拼接时长守恒

*对于任何*视频片段列表，拼接后的视频总时长应该等于所有片段时长之和（误差不超过 1 秒）

**验证需求：9.1**

### 属性 14：音视频同步一致性

*对于任何*视频和音频，同步后的输出视频时长应该与音频时长一致

**验证需求：9.2, 9.7**

### 属性 15：视频分辨率统一性

*对于任何*包含不同分辨率的视频片段列表，合成后的视频分辨率应该等于所有片段中的最高分辨率

**验证需求：9.6**

### 属性 16：WebSocket 消息推送及时性

*对于任何*任务状态变化，所有连接到该项目的 WebSocket 客户端应该在 100 毫秒内收到状态更新消息

**验证需求：10.2, 10.3**

### 属性 17：WebSocket 连接管理正确性

*对于任何*WebSocket 连接，断开连接后，该连接不应该再收到任何消息

**验证需求：10.5**

### 属性 18：错误重试指数退避

*对于任何*失败的任务，重试间隔应该按指数增长（第 N 次重试间隔 = 基础间隔 × 2^(N-1)）

**验证需求：3.5, 11.1**

### 属性 19：GPU 缓存清理有效性

*对于任何*GPU 缓存清理操作，清理后的 GPU 显存使用量应该小于清理前的使用量

**验证需求：12.3**

### 属性 20：输入验证拒绝无效输入

*对于任何*不符合验证规则的输入（如项目名称过长、分镜数量超限），系统应该返回 400 错误并提供详细的验证错误信息

**验证需求：14.1, 14.2, 14.4**

### 属性 21：JWT Token 有效期限制

*对于任何*JWT Token，在过期时间之后访问受保护的 API 端点应该返回 401 未授权错误

**验证需求：13.3**

### 属性 22：密码哈希不可逆性

*对于任何*用户密码，哈希后的密码不应该能够反向推导出原始密码

**验证需求：20.2**

### 属性 23：API 速率限制有效性

*对于任何*API 端点，在限制时间窗口内的请求次数超过限制时，应该返回 429 错误

**验证需求：20.5**

### 属性 24：文件路径返回有效性

*对于任何*文件生成操作（图像、视频、音频），返回的文件路径应该指向一个存在且可读的文件

**验证需求：5.2, 6.2, 7.2, 8.3, 9.5**

### 属性 25：任务完成触发合成

*对于任何*项目，当所有分镜任务都完成时，视频合成任务应该自动启动

**验证需求：3.6**
