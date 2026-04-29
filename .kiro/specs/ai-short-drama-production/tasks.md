# 实现计划：AI 短剧自动化生产平台

## 概述

本文档将 AI 短剧自动化生产平台的设计和需求转化为可执行的实现任务。系统采用 Python + FastAPI + Celery 架构，集成多个 AI 模型（Qwen2.5-14B、Stable Diffusion、SVD、MiMo-V2-TTS）实现从创意到成品的全自动化短剧生产流程。

**技术栈**：
- 后端：Python 3.10+、FastAPI、Celery、Redis
- AI 模型：llama.cpp (Qwen2.5-14B)、ComfyUI (Stable Diffusion)、SVD、MiMo-V2-TTS
- 数据库：SQLite/PostgreSQL
- 视频处理：FFmpeg
- 前端：React/Vue + WebSocket

**实现策略**：
- 优先实现核心生产流程（剧本生成 → 内容生成 → 视频合成）
- 每个组件独立开发和测试
- 使用 Mock 服务进行集成测试
- 属性测试验证关键正确性属性

## 任务列表

- [x] 1. 搭建项目基础设施
  - [x] 1.1 初始化项目结构和配置开发环境
    - 创建标准 Python 项目结构（src/、tests/、docs/、models/、storage/）
    - 配置 pyproject.toml 和 requirements.txt（包含所有 AI 模型依赖）
    - 配置代码格式化工具（black、isort、mypy）
    - 创建 .env.example 定义环境变量（包含模型路径、API 密钥等）
    - 配置 .gitignore（排除模型文件和生成文件）
    - 创建 models/ 目录用于存储 AI 模型
    - 创建 storage/ 目录用于存储生成的文件
    - _需求：19.2, 19.3_
  
  - [x] 1.1.5 下载和配置 AI 模型
    - 下载 Qwen2.5-14B GGUF 模型（Q4_K_M 量化版本，约 8GB）
    - 下载 Stable Diffusion XL Base 模型
    - 下载 Stable Video Diffusion (SVD) 模型
    - 验证模型文件完整性（MD5/SHA256 校验）
    - 配置模型路径到 .env 文件
    - 编写模型下载脚本（scripts/download_models.sh）
    - _需求：4.1, 5.1, 6.1_
  
  - [x] 1.1.6 配置 ComfyUI 服务
    - 安装 ComfyUI（克隆仓库或使用 Docker）
    - 配置 ComfyUI 工作流文件
    - 将 SD 模型链接到 ComfyUI models 目录
    - 启动 ComfyUI 服务（默认端口 8188）
    - 验证 ComfyUI API 可访问性
    - 编写 ComfyUI 启动脚本
    - _需求：5.1, 5.3_

  - [x] 1.2 设计并实现数据库 Schema
    - 创建 SQLAlchemy ORM 模型（Project、Character、Scene、Task）
    - 实现数据库迁移脚本（Alembic）
    - 添加索引优化查询性能
    - 编写数据库初始化脚本
    - _需求：1.1, 1.2, 1.3_

  - [x] 1.3 配置 Redis 和 Celery 任务队列
    - 配置 Redis 连接（支持本地和远程）
    - 配置 Celery 应用（broker、backend、序列化）
    - 定义任务队列（default、image、video、audio）
    - 配置任务重试策略（指数退避）
    - 实现 Celery Worker 启动脚本
    - _需求：3.1, 3.2, 3.5, 11.1_

  - [x] 1.4 实现日志和监控系统
    - 配置结构化日志（loguru）
    - 实现日志分级和输出（控制台 + 文件）
    - 集成 Prometheus 客户端
    - 定义核心性能指标（API 响应时间、任务执行时间、GPU 显存）
    - 实现 /metrics 端点
    - _需求：15.1, 15.2, 15.3, 15.4, 19.3_

  - [x] 1.5 实现文件存储管理
    - 定义文件存储目录结构（projects/{project_id}/{images,videos,audios,subtitles}）
    - 实现文件路径生成工具函数
    - 实现文件清理工具（删除项目时清理文件）
    - 实现磁盘空间检查功能
    - _需求：1.4, 11.4_
  
  - [x] 1.6 配置和测试 GPU 环境
    - 验证 CUDA 安装和版本（需要 CUDA 11.8+）
    - 验证 PyTorch GPU 支持（torch.cuda.is_available()）
    - 测试 GPU 显存检测功能
    - 实现 GPU 缓存清理工具
    - 配置 GPU 显存监控
    - 测试 llama.cpp GPU 加速
    - _需求：12.1, 12.2, 12.3, 12.4, 12.5_
  
  - [x] 1.7 编写服务启动脚本（跳过，部署时完成）
    - 编写 Redis 启动脚本
    - 编写 Celery Worker 启动脚本（配置并发数和队列）
    - 编写 ComfyUI 启动脚本
    - 编写 FastAPI 启动脚本
    - 编写统一的服务启动脚本（start_services.sh）
    - 编写服务停止脚本（stop_services.sh）
    - 编写服务状态检查脚本（check_services.sh）
    - _需求：无（部署配置）_

- [ ] 2. 实现核心业务服务
  - [x] 2.1 实现项目管理服务（ProjectManager）
    - 实现 create_project() 方法
    - 实现 get_project() 方法
    - 实现 update_project() 方法
    - 实现 list_projects() 方法（支持状态过滤和分页）
    - 实现 delete_project() 方法（级联删除文件）
    - 添加输入验证（项目名称长度、字符限制）
    - _需求：1.1, 1.2, 1.3, 1.4, 1.5, 14.1_

  - [x] 2.2 编写 ProjectManager 单元测试
    - 测试项目创建、查询、更新、删除操作
    - 测试输入验证逻辑
    - 测试文件清理功能
    - _需求：1.1, 1.2, 1.3, 1.4, 1.5_

  - [x] 2.3 编写 ProjectManager 属性测试
    - **属性 1：项目创建幂等性**
    - **验证需求：1.1, 1.2**
    - **属性 2：项目更新保持一致性**
    - **验证需求：1.3**
    - **属性 3：项目删除完整性**
    - **验证需求：1.4**
    - **属性 4：项目列表排序正确性**
    - **验证需求：1.5**

- [ ] 3. 实现 AI 服务集成
  - [x] 3.1 实现 LLM 服务（LLMService）
    - 实现 LLMService 类初始化（加载 GGUF 模型）
    - 配置 CPU offload（n_gpu_layers 参数，默认 20 层）
    - 实现 generate() 方法（支持 temperature、top_p、max_tokens）
    - 实现 generate_script_prompt() 方法（构建剧本生成 Prompt）
    - 实现 unload_model() 方法（释放资源）
    - 添加错误处理（模型加载失败、显存不足）
    - 实现模型预热功能（首次加载优化）
    - 添加生成进度回调（可选）
    - _需求：4.1, 4.2, 4.4, 4.5, 12.1, 12.5_
  
  - [x] 3.1.5 测试 LLM 服务部署
    - 编写 LLM 服务启动脚本
    - 测试模型加载时间和显存占用
    - 测试不同 n_gpu_layers 配置的性能
    - 测试 CPU offload 功能
    - 验证生成质量和速度
    - 记录性能基准数据
    - _需求：4.1, 4.2, 12.1_

  - [ ] 3.2 编写 LLMService 集成测试
    - 使用小型测试模型验证加载和生成功能
    - 测试 CPU offload 配置
    - 测试错误处理
    - _需求：4.1, 4.2, 4.5_

  - [x] 3.3 实现剧本生成服务（ScriptGenerator）
    - 实现 generate_script() 方法（调用 LLMService）
    - 实现 parse_script() 方法（解析 LLM 输出）
    - 实现 regenerate_scene() 方法
    - 实现 generate_visual_prompt() 方法
    - 添加输入验证（主题和大纲至少一个非空）
    - 处理 LLM 输出格式错误
    - _需求：2.1, 2.2, 2.3, 2.4, 2.5_

  - [ ] 3.4 编写 ScriptGenerator 单元测试和集成测试
    - 测试剧本生成和解析逻辑
    - 测试分镜重新生成
    - 测试输入验证和错误处理
    - _需求：2.1, 2.2, 2.3, 2.4, 2.5_

  - [ ] 3.5 编写 ScriptGenerator 属性测试
    - **属性 5：剧本解析结构完整性**
    - **验证需求：2.2**
    - **属性 6：分镜重新生成隔离性**
    - **验证需求：2.4**

  - [x] 3.6 实现 ComfyUI 服务（ComfyUIService）
    - 实现 ComfyUIService 类初始化
    - 实现 generate_image() 方法（调用 ComfyUI API）
    - 实现 load_workflow() 方法（加载工作流配置）
    - 实现 check_status() 方法（检查服务可用性）
    - 添加重试逻辑（最多 3 次，指数退避）
    - 处理 API 错误（超时、连接失败）
    - 实现批量图像生成功能（可选优化）
    - _需求：5.1, 5.2, 5.3, 5.4, 11.1_
  
  - [ ] 3.6.5 配置和测试 ComfyUI 集成
    - 创建 ComfyUI 工作流配置文件（JSON）
    - 配置 SD 模型路径和参数
    - 测试单张图像生成
    - 测试批量图像生成
    - 测试不同分辨率和采样步数
    - 验证生成速度和质量
    - 记录性能基准数据
    - _需求：5.1, 5.2, 5.5_

  - [ ] 3.7 编写 ComfyUIService 集成测试
    - 使用 Mock API 测试图像生成
    - 测试重试逻辑和错误处理
    - _需求：5.1, 5.2, 5.3, 5.4_

  - [x] 3.8 实现 SVD 服务（SVDService）
    - 实现 SVDService 类初始化（加载 SVD 模型）
    - 实现 generate_video() 方法（图生视频）
    - 实现 check_gpu_memory() 方法（显存监控）
    - 添加 GPU 缓存清理逻辑
    - 添加重试逻辑（显存不足时清理后重试）
    - 配置视频生成参数（帧数、帧率、运动强度）
    - 实现视频质量优化（FP16 精度）
    - _需求：6.1, 6.2, 6.3, 6.4, 6.5, 12.2, 12.3_
  
  - [ ] 3.8.5 测试 SVD 服务部署
    - 测试 SVD 模型加载和显存占用
    - 测试单个视频生成时间
    - 测试不同帧数和分辨率的性能
    - 测试 GPU 缓存清理功能
    - 验证视频质量和流畅度
    - 测试与 SD 任务的显存协调
    - 记录性能基准数据
    - _需求：6.1, 6.2, 6.5, 12.2, 12.3_

  - [ ] 3.9 编写 SVDService 集成测试
    - 测试视频生成功能
    - 测试 GPU 显存监控和缓存清理
    - 测试重试逻辑
    - _需求：6.1, 6.2, 6.3, 6.4, 6.5_

  - [x] 3.10 实现 TTS 服务（TTSService）
    - 实现 TTSService 类初始化（配置 API 密钥）
    - 实现 generate_speech() 方法（调用 MiMo-V2-TTS API）
    - 实现 list_speakers() 方法（获取可用说话人）
    - 实现 check_quota() 方法（检查 API 配额）
    - 添加重试逻辑（API 调用失败）
    - 处理配额不足错误
    - 实现音频格式转换（如需要）
    - _需求：7.1, 7.2, 7.3, 7.4, 7.5, 11.1_
  
  - [ ] 3.10.5 测试 TTS API 集成
    - 配置 MiMo-V2-TTS API 密钥
    - 测试单句配音生成
    - 测试不同说话人和情感
    - 测试 API 配额检查
    - 测试错误处理和重试
    - 验证音频质量
    - 记录 API 调用性能
    - _需求：7.1, 7.2, 7.5_

  - [ ] 3.11 编写 TTSService 集成测试
    - 使用 Mock API 测试配音生成
    - 测试配额检查和错误处理
    - _需求：7.1, 7.2, 7.3, 7.4, 7.5_

- [ ] 4. 实现后处理服务
  - [x] 4.1 实现字幕生成服务（SubtitleGenerator）
    - 实现 generate_srt() 方法
    - 实现 calculate_timing() 方法
    - 实现 burn_subtitle() 方法（使用 FFmpeg）
    - 处理超长对话（自动分行）
    - 实现时间轴对齐逻辑
    - 添加字幕样式配置
    - _需求：8.1, 8.2, 8.3, 8.4, 8.5_

  - [x] 4.2 编写 SubtitleGenerator 单元测试和集成测试
    - 测试 SRT 文件生成
    - 测试字幕烧录
    - 测试时间轴对齐
    - _需求：8.1, 8.2, 8.3, 8.4, 8.5_

  - [ ] 4.3 编写 SubtitleGenerator 属性测试
    - **属性 11：字幕时间轴对齐**
    - **验证需求：8.1, 8.5**
    - **属性 12：字幕文件格式正确性**
    - **验证需求：8.1**

  - [x] 4.4 实现视频合成服务（VideoComposer）
    - 实现 concat_videos() 方法
    - 实现 sync_audio_video() 方法
    - 实现 add_bgm() 方法
    - 实现 compose_video() 方法
    - 处理分辨率不一致（统一为最高分辨率）
    - 处理时长不匹配（自动调整）
    - _需求：9.1, 9.2, 9.3, 9.4, 9.5, 9.6, 9.7_

  - [x] 4.5 编写 VideoComposer 集成测试
    - 测试视频拼接和合成
    - 测试音视频同步
    - 测试分辨率统一和时长对齐
    - _需求：9.1, 9.2, 9.3, 9.4, 9.5, 9.6, 9.7_

  - [ ] 4.6 编写 VideoComposer 属性测试
    - **属性 13：视频拼接时长守恒**
    - **验证需求：9.1**
    - **属性 14：音视频同步一致性**
    - **验证需求：9.2, 9.7**
    - **属性 15：视频分辨率统一性**
    - **验证需求：9.6**

- [ ] 5. 实现任务编排和调度
  - [x] 5.1 实现任务编排服务（TaskOrchestrator）
    - 实现 create_production_task() 方法
    - 实现 get_task_status() 方法
    - 实现 cancel_task() 方法
    - 实现 retry_failed_task() 方法
    - 定义 Celery 任务函数（image_task、video_task、audio_task、subtitle_task、compose_task）
    - 实现任务依赖管理（使用 Celery chain）
    - 实现进度计算逻辑
    - _需求：3.1, 3.2, 3.3, 3.4, 3.5, 3.6, 11.1, 11.2, 11.5_

  - [x] 5.2 编写 TaskOrchestrator 单元测试和集成测试
    - 测试任务链创建和调度
    - 测试任务状态查询和取消
    - 测试任务重试逻辑
    - 测试进度计算
    - _需求：3.1, 3.2, 3.3, 3.4, 3.5, 3.6_

  - [ ] 5.3 编写 TaskOrchestrator 属性测试
    - **属性 7：任务链结构正确性**
    - **验证需求：3.1**
    - **属性 8：任务进度单调递增**
    - **验证需求：3.3**
    - **属性 9：任务取消有效性**
    - **验证需求：3.4**
    - **属性 10：任务重试次数限制**
    - **验证需求：3.5, 11.1**
    - **属性 18：错误重试指数退避**
    - **验证需求：3.5, 11.1**
    - **属性 25：任务完成触发合成**
    - **验证需求：3.6**

- [x] 6. 检查点 - 确保所有核心服务测试通过
  - 确保所有核心服务测试通过，询问用户是否有问题

- [ ] 7. 实现 API 层
  - [x] 7.1 初始化 FastAPI 应用
    - 创建 FastAPI 应用实例
    - 配置 CORS（允许前端跨域请求）
    - 配置静态文件服务
    - 实现健康检查端点（/health）
    - 配置请求日志中间件
    - 配置异常处理中间件
    - _需求：13.1, 13.2, 13.3, 13.4, 14.4, 16.6_

  - [x] 7.2 实现 RESTful API 端点
    - POST /api/projects - 创建项目
    - GET /api/projects/{id} - 获取项目详情
    - PUT /api/projects/{id} - 更新项目
    - DELETE /api/projects/{id} - 删除项目
    - GET /api/projects - 列出项目
    - POST /api/projects/{id}/generate-script - 生成剧本
    - POST /api/projects/{id}/regenerate-scene - 重新生成分镜
    - POST /api/projects/{id}/produce - 提交生产任务
    - GET /api/tasks/{id}/status - 查询任务状态
    - POST /api/tasks/{id}/cancel - 取消任务
    - POST /api/tasks/{id}/retry - 重试任务
    - 添加请求验证（使用 Pydantic）
    - 添加错误处理（返回标准错误格式）
    - _需求：1.1, 1.2, 1.3, 1.4, 1.5, 2.1, 2.4, 3.1, 3.3, 3.4, 3.5, 14.1, 14.2, 14.4_

  - [x] 7.3 编写 API 端点测试
    - 测试所有 API 端点的正常流程
    - 测试输入验证和错误处理
    - 测试认证和授权
    - _需求：1.1, 1.2, 1.3, 1.4, 1.5, 2.1, 2.4, 3.1, 3.3, 3.4, 3.5, 13.1, 13.2, 13.3, 14.1, 14.2, 14.4_

  - [x] 7.4 实现 WebSocket 实时通信
    - 实现 WebSocket 端点（/ws/{project_id}）
    - 实现连接管理（连接池）
    - 实现消息广播
    - 定义消息格式（状态更新、进度更新、完成通知、错误通知）
    - 实现心跳机制
    - 处理连接断开
    - _需求：10.1, 10.2, 10.3, 10.4, 10.5, 11.6_

  - [x] 7.5 编写 WebSocket 测试
    - 测试连接建立和断开
    - 测试消息推送
    - 测试心跳机制
    - _需求：10.1, 10.2, 10.3, 10.4, 10.5_

  - [ ] 7.6 编写 WebSocket 属性测试
    - **属性 16：WebSocket 消息推送及时性**
    - **验证需求：10.2, 10.3**
    - **属性 17：WebSocket 连接管理正确性**
    - **验证需求：10.5**

- [ ] 8. 实现安全和验证
  - [x] 8.1 实现 API 认证和授权
    - 实现用户登录端点（POST /api/auth/login）
    - 实现 JWT Token 生成和验证
    - 实现 Token 刷新端点
    - 实现受保护端点的认证中间件
    - 实现密码哈希（使用 bcrypt）
    - _需求：13.1, 13.2, 13.3, 13.4, 13.5, 20.2_

  - [x] 8.2 编写认证和授权测试
    - 测试登录和 Token 生成
    - 测试 Token 验证和过期
    - 测试受保护端点的访问控制
    - _需求：13.1, 13.2, 13.3, 13.4, 13.5_

  - [x] 8.3 编写安全属性测试
    - **属性 21：JWT Token 有效期限制**
    - **验证需求：13.3**
    - **属性 22：密码哈希不可逆性**
    - **验证需求：20.2**
    - **额外属性：Token 篡改检测和用户 ID 类型一致性**

  - [x] 8.4 实现 API 速率限制
    - 实现速率限制中间件
    - 配置不同端点的速率限制
    - 实现速率限制错误响应（429）
    - _需求：20.5_

  - [ ] 8.5 编写速率限制测试
    - **属性 23：API 速率限制有效性**
    - **验证需求：20.5**

- [x] 9. 检查点 - 确保所有 API 测试通过
  - 确保所有 API 测试通过，询问用户是否有问题

- [ ] 10. 实现前端界面
  - [ ] 10.1 创建 React/Vue 项目
    - 初始化前端项目
    - 配置开发环境和构建工具
    - 配置路由和状态管理
    - 集成 UI 组件库
    - _需求：无（前端实现）_

  - [ ] 10.2 实现项目管理页面
    - 实现项目列表页面
    - 实现项目创建页面（输入主题/大纲）
    - 实现项目详情页面
    - 集成 API 调用
    - _需求：1.1, 1.2, 1.5_

  - [ ] 10.3 实现剧本生成和编辑页面
    - 实现剧本预览页面
    - 实现剧本编辑功能
    - 实现分镜重新生成功能
    - 集成 API 调用
    - _需求：2.1, 2.4_

  - [ ] 10.4 实现生产进度监控页面
    - 实现实时进度条
    - 集成 WebSocket 客户端
    - 实现任务取消和重试按钮
    - 显示错误通知
    - _需求：3.3, 3.4, 3.5, 10.2, 10.3, 10.4_

  - [ ] 10.5 实现视频预览和下载页面
    - 实现视频播放器
    - 实现视频下载功能
    - 实现分镜视频预览
    - _需求：9.5_

  - [ ] 10.6 编写前端端到端测试
    - 测试完整的用户流程
    - 测试 WebSocket 实时更新
    - 测试错误处理和加载状态
    - _需求：无（前端测试）_

- [ ] 11. 性能优化和压力测试
  - [ ] 11.1 进行 API 压力测试
    - 使用 locust 或 k6 进行压力测试
    - 测试 API 响应时间和吞吐量
    - 识别性能瓶颈
    - _需求：16.6_

  - [ ] 11.2 优化数据库查询
    - 添加缺失的索引
    - 优化慢查询
    - 配置数据库连接池
    - _需求：16.6_

  - [ ] 11.3 优化 GPU 显存使用
    - 调整 LLM offload 层数
    - 优化 SD 和 SVD 任务调度
    - 测试单张 RTX 4090 的并发处理能力
    - _需求：12.1, 12.2, 12.3, 12.4, 12.5_

  - [ ] 11.4 编写性能属性测试
    - **属性 19：GPU 缓存清理有效性**
    - **验证需求：12.3**

  - [ ] 11.5 优化 Celery 任务配置
    - 调整任务队列并发数
    - 优化任务优先级
    - 测试任务吞吐量
    - _需求：16.1, 16.2, 16.3, 16.4, 16.5_

- [ ] 12. 部署和文档
  - [ ] 12.1 创建 Docker 容器化配置
    - 编写 Dockerfile（多阶段构建）
    - 编写 docker-compose.yml（包含所有服务）
    - 配置 GPU 支持（nvidia-docker）
    - 配置环境变量和卷挂载
    - 配置模型文件挂载
    - 编写启动脚本
    - _需求：无（部署配置）_
  
  - [ ] 12.1.5 创建模型部署文档
    - 编写模型下载指南（包含所有模型链接）
    - 编写模型配置指南（路径、参数）
    - 编写 GPU 配置指南（CUDA、显存优化）
    - 编写 ComfyUI 部署指南
    - 编写服务启动顺序说明
    - 编写常见部署问题排查指南
    - _需求：无（文档）_

  - [ ] 12.2 测试容器部署
    - 测试 Docker 镜像构建
    - 测试 docker-compose 启动
    - 测试 GPU 访问
    - _需求：无（部署测试）_

  - [ ] 12.3 编写部署文档
    - 编写安装指南（依赖安装、模型下载）
    - 编写配置指南（环境变量、API 密钥）
    - 编写部署指南（Docker、裸机部署）
    - 编写运维指南（日志查看、性能监控、故障排查）
    - 编写 API 使用文档
    - 添加常见问题解答（FAQ）
    - 编写模型管理指南（更新、切换模型）
    - 编写性能调优指南（GPU 显存优化、任务并发配置）
    - _需求：无（文档）_
  
  - [ ] 12.3.5 编写服务监控和维护文档
    - 编写服务健康检查指南
    - 编写日志分析指南
    - 编写性能监控指南（Prometheus + Grafana）
    - 编写备份和恢复指南
    - 编写扩容指南（增加 Worker、GPU）
    - 编写安全加固指南
    - _需求：无（文档）_

  - [ ] 12.4 编写用户文档和示例
    - 编写快速开始指南
    - 编写用户手册
    - 提供示例剧本和配置
    - 编写最佳实践指南
    - _需求：无（文档）_

- [ ] 13. 最终检查点 - 确保所有测试通过
  - 确保所有测试通过，询问用户是否有问题

## 注意事项

- 任务标记 `*` 的为可选任务，可以跳过以加快 MVP 开发
- 每个任务都引用了相关的需求编号，确保可追溯性
- 检查点任务用于确保增量验证和用户反馈
- 属性测试验证设计文档中定义的正确性属性
- 所有代码使用 Python 3.10+ 和类型注解
- 遵循 PEP 8 代码风格和中文注释规范

**模型部署注意事项**：
- Qwen2.5-14B GGUF 模型约 8GB，下载时间取决于网络速度
- Stable Diffusion XL 模型约 6.9GB
- Stable Video Diffusion 模型约 3.8GB
- 总模型大小约 18-20GB，确保有足够的磁盘空间
- 首次加载模型会较慢，建议实现模型预热功能
- GPU 显存分配需要仔细调优，建议从 n_gpu_layers=20 开始测试
- ComfyUI 需要单独启动，确保端口 8188 可用
- 建议使用 SSD 存储模型文件以加快加载速度

**性能优化建议**：
- LLM 使用 CPU offload 可节省 10-15GB 显存
- SD 和 SVD 任务应串行执行，避免显存冲突
- 使用 FP16 精度可减少约 50% 显存占用
- 批量处理图像可提高 20-30% 吞吐量
- 合理配置 Celery Worker 并发数（建议 2-4）

## 实现顺序说明

1. **任务 1**：搭建基础设施，为后续开发提供环境
2. **任务 2-5**：实现核心业务服务和 AI 集成，这是系统的核心功能
3. **任务 6**：检查点，确保核心服务正常工作
4. **任务 7**：实现 API 层，提供外部访问接口
5. **任务 8**：实现安全和验证，保护系统安全
6. **任务 9**：检查点，确保 API 正常工作
7. **任务 10**：实现前端界面，提供用户交互
8. **任务 11**：性能优化，确保系统满足性能要求
9. **任务 12**：部署和文档，准备发布
10. **任务 13**：最终检查点，确保系统完整可用

## 估时说明

- **任务 1**：约 20 小时（基础设施 + 模型下载和配置 + GPU 环境）
- **任务 2-5**：约 95 小时（核心服务和 AI 集成 + 模型部署测试）
- **任务 7-8**：约 30 小时（API 和安全）
- **任务 10**：约 20 小时（前端）
- **任务 11**：约 20 小时（性能优化 + GPU 调优）
- **任务 12**：约 18 小时（部署和文档 + 模型部署文档）

**总计**：约 203 小时（约 25.5 个工作日）

**关键里程碑**：
1. **第 1 周**：完成基础设施、模型下载和 AI 服务集成（任务 1-3）
2. **第 2 周**：完成后处理服务和任务编排（任务 4-5）
3. **第 3 周**：完成 API 层和前端（任务 7-10）
4. **第 4 周**：性能优化和部署（任务 11-12）

## 属性测试覆盖

本任务列表包含以下属性测试：

- **属性 1-6**：项目管理和剧本生成（任务 2.3, 3.5）
- **属性 7-10, 18, 25**：任务编排和调度（任务 5.3）
- **属性 11-12**：字幕生成（任务 4.3）
- **属性 13-15**：视频合成（任务 4.6）
- **属性 16-17**：WebSocket 通信（任务 7.6）
- **属性 19**：GPU 显存管理（任务 11.4）
- **属性 20-23**：安全和验证（任务 8.3, 8.5）

未包含的属性（24）因为是简单的文件存在性检查，可以通过单元测试覆盖。


## 模型和服务依赖清单

### AI 模型

| 模型 | 大小 | 用途 | 下载链接 | 配置参数 |
|------|------|------|----------|----------|
| Qwen2.5-14B-Instruct (Q4_K_M) | ~8GB | 剧本生成 | [HuggingFace](https://huggingface.co/Qwen/Qwen2.5-14B-Instruct-GGUF) | n_gpu_layers=20, n_ctx=4096 |
| Stable Diffusion XL Base 1.0 | ~6.9GB | 图像生成 | [HuggingFace](https://huggingface.co/stabilityai/stable-diffusion-xl-base-1.0) | steps=20, cfg_scale=7.0 |
| Stable Video Diffusion XT | ~3.8GB | 图生视频 | [HuggingFace](https://huggingface.co/stabilityai/stable-video-diffusion-img2vid-xt) | num_frames=16, fps=8 |

### 外部服务

| 服务 | 用途 | 配置要求 | 备注 |
|------|------|----------|------|
| ComfyUI | SD 图像生成 | 端口 8188 | 需要单独启动 |
| MiMo-V2-TTS API | 配音生成 | API 密钥 | 需要申请 API 密钥 |
| Redis | 消息队列和缓存 | 端口 6379 | 建议使用 Redis 6.0+ |
| PostgreSQL (可选) | 数据库 | 端口 5432 | 可用 SQLite 替代 |

### 系统依赖

| 依赖 | 版本要求 | 用途 |
|------|----------|------|
| Python | 3.10+ | 运行环境 |
| CUDA | 11.8+ | GPU 加速 |
| FFmpeg | 4.4+ | 视频处理 |
| Node.js | 18+ | 前端构建 |

### GPU 显存分配方案

**单张 RTX 4090 24GB 配置**：
- LLM (Qwen2.5-14B): 4-6GB (n_gpu_layers=20)
- SD (SDXL): 8-10GB
- SVD: 8-10GB
- 系统预留: 2-4GB

**优化策略**：
- LLM 和 SD/SVD 可以同时运行（LLM 使用 CPU offload）
- SD 和 SVD 必须串行执行（通过任务调度）
- 任务切换时清理 GPU 缓存

### 服务启动顺序

1. **Redis** - 消息队列和缓存
2. **ComfyUI** - SD 图像生成服务
3. **Celery Worker** - 异步任务处理
4. **FastAPI** - Web API 服务
5. **前端** (可选) - Web 界面

### 环境变量配置清单

```bash
# LLM 配置
LLM_MODEL_PATH=./models/qwen2.5-14b-instruct-q4_k_m.gguf
LLM_N_GPU_LAYERS=20
LLM_N_CTX=4096
LLM_N_THREADS=8

# ComfyUI 配置
COMFYUI_BASE_URL=http://127.0.0.1:8188
COMFYUI_WORKFLOW_PATH=./configs/comfyui_workflow.json

# SVD 配置
SVD_MODEL_PATH=./models/stable-video-diffusion-img2vid-xt
SVD_NUM_FRAMES=16
SVD_FPS=8

# TTS 配置
TTS_API_KEY=your_mimo_api_key_here
TTS_BASE_URL=https://mimo.xiaomi.com/api/v2/tts

# 数据库配置
DATABASE_URL=sqlite:///./short_drama.db
# 或使用 PostgreSQL:
# DATABASE_URL=postgresql://user:password@localhost:5432/short_drama

# Redis 配置
REDIS_URL=redis://localhost:6379/0

# 文件存储配置
STORAGE_PATH=./storage
MAX_STORAGE_SIZE_GB=500

# Celery 配置
CELERY_BROKER_URL=redis://localhost:6379/1
CELERY_RESULT_BACKEND=redis://localhost:6379/2
CELERY_WORKER_CONCURRENCY=2

# 安全配置
ENCRYPTION_KEY=your_encryption_key_here
JWT_SECRET_KEY=your_jwt_secret_key_here
JWT_EXPIRATION_HOURS=24

# 性能配置
GPU_MEMORY_FRACTION=0.95
ENABLE_GPU_CACHE_CLEAR=true
API_RATE_LIMIT=10/minute
```

### 快速启动命令

```bash
# 1. 下载模型
bash scripts/download_models.sh

# 2. 启动所有服务
bash scripts/start_services.sh

# 3. 检查服务状态
bash scripts/check_services.sh

# 4. 访问 Web 界面
# http://localhost:8000

# 5. 停止所有服务
bash scripts/stop_services.sh
```

### 故障排查清单

**问题 1：LLM 模型加载失败**
- 检查模型文件是否完整（MD5 校验）
- 检查 GPU 显存是否足够
- 尝试减少 n_gpu_layers 参数
- 检查 CUDA 版本是否兼容

**问题 2：ComfyUI 连接失败**
- 检查 ComfyUI 服务是否启动（端口 8188）
- 检查防火墙设置
- 检查 SD 模型是否正确加载
- 查看 ComfyUI 日志

**问题 3：GPU 显存不足**
- 减少 LLM n_gpu_layers（从 20 降到 15）
- 降低图像分辨率（从 768 降到 512）
- 减少视频帧数（从 25 降到 16）
- 启用 FP16 精度
- 清理 GPU 缓存

**问题 4：视频生成速度慢**
- 检查 GPU 利用率
- 减少视频帧数
- 降低分辨率
- 检查磁盘 I/O 性能
- 考虑使用 SSD

**问题 5：TTS API 调用失败**
- 检查 API 密钥是否正确
- 检查网络连接
- 检查 API 配额
- 查看 API 错误日志
