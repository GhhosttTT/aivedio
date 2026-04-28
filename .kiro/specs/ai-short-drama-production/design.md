# 设计文档：AI 短剧自动化生产平台

## 概述

AI 短剧自动化生产平台是一个端到端的短剧制作解决方案，通过集成大语言模型（Qwen2.5-14B）、文生图（Stable Diffusion + ComfyUI）、图生视频（SVD）、AI 配音（MiMo-V2-TTS）和自动字幕生成技术，实现从创意想法到完整短剧视频的全自动化生产流程。

该平台采用模块化设计，支持异步任务处理和实时进度更新，通过 Web 界面提供友好的用户交互体验。系统针对硬件资源进行了优化，LLM 使用 llama.cpp 支持 CPU offload，降低 GPU 显存占用，使得在单张 RTX 4090/3090 24GB 显卡上可以同时运行 Stable Diffusion 和 SVD。

**核心价值**：
- 将短剧制作时间从数天缩短至数小时
- 降低创作和技术双重门槛
- 实现从"有想法"到"有成品"的完全自动化
- 支持模块化扩展和性能优化


## 系统架构

### 整体架构图

```mermaid
graph TB
    subgraph "前端层"
        WebUI[Web 界面<br/>React/Vue + WebSocket]
    end
    
    subgraph "API 层"
        FastAPI[FastAPI 服务器<br/>RESTful API + WebSocket]
    end
    
    subgraph "业务逻辑层"
        ProjectMgr[项目管理服务]
        ScriptGen[剧本生成服务]
        TaskOrch[任务编排服务]
    end
    
    subgraph "任务队列层"
        Celery[Celery Worker Pool]
        Redis[(Redis<br/>消息队列 + 缓存)]
    end
    
    subgraph "AI 生成层"
        LLM[LLM 服务<br/>Qwen2.5-14B + llama.cpp]
        ComfyUI[ComfyUI 服务<br/>Stable Diffusion]
        SVD[SVD 服务<br/>图生视频]
        TTS[TTS 服务<br/>MiMo-V2-TTS API]
    end
    
    subgraph "后处理层"
        SubGen[字幕生成服务]
        VideoComp[视频合成服务<br/>FFmpeg]
    end
    
    subgraph "存储层"
        FileStore[(文件存储<br/>本地磁盘)]
        MetaDB[(元数据存储<br/>SQLite/PostgreSQL)]
    end
    
    WebUI --> FastAPI
    FastAPI --> ProjectMgr
    FastAPI --> ScriptGen
    FastAPI --> TaskOrch
    
    ProjectMgr --> MetaDB
    ScriptGen --> LLM
    TaskOrch --> Celery
    
    Celery --> Redis
    Celery --> ComfyUI
    Celery --> SVD
    Celery --> TTS
    Celery --> SubGen
    Celery --> VideoComp
    
    ComfyUI --> FileStore
    SVD --> FileStore
    TTS --> FileStore
    VideoComp --> FileStore
    
    LLM -.-> FileStore
    SubGen -.-> FileStore
```

### 架构说明

**分层设计**：
1. **前端层**：提供 Web 界面，支持剧本输入、参数配置、进度监控和结果预览
2. **API 层**：FastAPI 提供 RESTful API 和 WebSocket 接口，处理前端请求
3. **业务逻辑层**：核心业务服务，包括项目管理、剧本生成和任务编排
4. **任务队列层**：Celery + Redis 实现异步任务处理和分布式调度
5. **AI 生成层**：集成各类 AI 模型服务，负责内容生成
6. **后处理层**：字幕生成和视频合成服务
7. **存储层**：文件存储和元数据存储

**关键设计决策**：
- **异步任务处理**：使用 Celery 处理耗时的 AI 生成任务，避免阻塞 API 请求
- **模块化服务**：每个 AI 服务独立封装，支持独立升级和替换
- **显存优化**：LLM 使用 CPU offload，为 SD 和 SVD 预留足够显存
- **实时通信**：WebSocket 推送任务进度，提供流畅的用户体验


## 主要工作流程

### 端到端生产流程

```mermaid
sequenceDiagram
    participant User as 用户
    participant WebUI as Web 界面
    participant API as FastAPI
    participant ScriptGen as 剧本生成服务
    participant TaskOrch as 任务编排
    participant Celery as Celery Worker
    participant LLM as LLM 服务
    participant ComfyUI as ComfyUI
    participant SVD as SVD 服务
    participant TTS as TTS 服务
    participant SubGen as 字幕生成
    participant VideoComp as 视频合成
    
    User->>WebUI: 输入主题/大纲
    WebUI->>API: POST /api/projects/create
    API->>ScriptGen: 生成剧本请求
    ScriptGen->>LLM: 调用 LLM 生成剧本
    LLM-->>ScriptGen: 返回剧本和分镜
    ScriptGen-->>API: 返回剧本数据
    API-->>WebUI: 返回项目 ID
    
    User->>WebUI: 确认剧本并提交生产
    WebUI->>API: POST /api/projects/{id}/produce
    API->>TaskOrch: 创建生产任务链
    TaskOrch->>Celery: 提交任务到队列
    
    loop 每个分镜
        Celery->>ComfyUI: 生成图像
        ComfyUI-->>Celery: 返回图像路径
        Celery->>SVD: 图生视频
        SVD-->>Celery: 返回视频路径
        Celery->>TTS: 生成配音
        TTS-->>Celery: 返回音频路径
        Celery->>SubGen: 生成字幕
        SubGen-->>Celery: 返回字幕文件
        Celery-->>WebUI: WebSocket 推送进度
    end
    
    Celery->>VideoComp: 合成最终视频
    VideoComp-->>Celery: 返回视频路径
    Celery-->>WebUI: WebSocket 推送完成通知
    
    User->>WebUI: 下载最终视频
```

### 工作流程说明

**阶段 1：剧本生成**（1-2 分钟）
1. 用户输入主题或故事大纲
2. LLM 服务生成完整剧本（对话、场景描述、角色动作）
3. LLM 服务生成分镜描述（每个分镜对应一个镜头）
4. 用户预览、编辑或重新生成

**阶段 2：内容生成**（每个镜头 2-3 分钟，10 个镜头约 20-30 分钟）
1. 任务编排服务创建任务链并提交到 Celery 队列
2. 对每个分镜并行或串行执行：
   - ComfyUI 生成图像（20-30 秒）
   - SVD 将图像转换为视频（1-2 分钟）
   - TTS 生成配音（5 秒）
   - 字幕生成服务创建字幕文件（1 秒）
3. WebSocket 实时推送进度更新

**阶段 3：视频合成**（3-5 分钟）
1. 视频合成服务按顺序拼接所有视频片段
2. 同步配音音频和字幕
3. 烧录字幕到视频
4. 导出最终视频文件
5. 通知用户完成

**总耗时估算**：
- 单集短剧（10-20 个镜头）：约 1.5-2.5 小时
- 其中 AI 生成占 90% 时间，后处理占 10%


## 组件和接口

### 组件 1：项目管理服务（ProjectManager）

**职责**：
- 管理短剧项目的生命周期（创建、更新、删除、查询）
- 存储项目元数据（剧本、分镜、配置参数）
- 提供项目状态查询接口

**接口**：

```python
from typing import Optional, List
from pydantic import BaseModel
from datetime import datetime

class Project(BaseModel):
    """项目数据模型"""
    id: str
    name: str
    theme: Optional[str] = None
    outline: Optional[str] = None
    script: Optional[str] = None
    scenes: List[dict] = []
    status: str  # draft, generating, producing, completed, failed
    created_at: datetime
    updated_at: datetime
    config: dict = {}

class ProjectManager:
    """项目管理服务"""
    
    def create_project(self, name: str, theme: Optional[str] = None, 
                      outline: Optional[str] = None) -> Project:
        """
        创建新项目
        
        Args:
            name: 项目名称
            theme: 主题关键词（可选）
            outline: 故事大纲（可选）
            
        Returns:
            创建的项目对象
        """
        pass
    
    def get_project(self, project_id: str) -> Optional[Project]:
        """
        获取项目详情
        
        Args:
            project_id: 项目 ID
            
        Returns:
            项目对象，不存在则返回 None
        """
        pass
    
    def update_project(self, project_id: str, **kwargs) -> Project:
        """
        更新项目信息
        
        Args:
            project_id: 项目 ID
            **kwargs: 要更新的字段
            
        Returns:
            更新后的项目对象
        """
        pass
    
    def list_projects(self, status: Optional[str] = None, 
                     limit: int = 20, offset: int = 0) -> List[Project]:
        """
        列出项目列表
        
        Args:
            status: 过滤状态（可选）
            limit: 返回数量限制
            offset: 偏移量
            
        Returns:
            项目列表
        """
        pass
    
    def delete_project(self, project_id: str) -> bool:
        """
        删除项目
        
        Args:
            project_id: 项目 ID
            
        Returns:
            是否删除成功
        """
        pass
```

### 组件 2：剧本生成服务（ScriptGenerator）

**职责**：
- 调用 LLM 生成剧本和分镜
- 解析 LLM 输出并结构化存储
- 支持剧本重新生成和部分编辑

**接口**：

```python
from typing import List, Dict, Optional
from pydantic import BaseModel

class Scene(BaseModel):
    """分镜数据模型"""
    scene_id: int
    description: str  # 场景描述
    characters: List[str]  # 角色列表
    dialogue: Optional[str] = None  # 对话内容
    speaker: Optional[str] = None  # 说话人
    emotion: Optional[str] = None  # 情感（生气、温柔等）
    visual_prompt: str  # 图像生成提示词

class ScriptGenerator:
    """剧本生成服务"""
    
    def generate_script(self, theme: Optional[str] = None, 
                       outline: Optional[str] = None,
                       num_scenes: int = 10,
                       num_characters: int = 2,
                       style: str = "现代都市") -> Dict:
        """
        生成完整剧本和分镜
        
        Args:
            theme: 主题关键词
            outline: 故事大纲
            num_scenes: 分镜数量
            num_characters: 角色数量
            style: 风格偏好
            
        Returns:
            包含剧本和分镜列表的字典
            {
                "script": "完整剧本文本",
                "scenes": [Scene对象列表],
                "characters": ["角色1", "角色2"]
            }
        """
        pass
    
    def regenerate_scene(self, scene_id: int, description: str) -> Scene:
        """
        重新生成单个分镜
        
        Args:
            scene_id: 分镜 ID
            description: 新的场景描述
            
        Returns:
            重新生成的分镜对象
        """
        pass
    
    def parse_script(self, script_text: str) -> List[Scene]:
        """
        解析剧本文本为分镜列表
        
        Args:
            script_text: 剧本文本
            
        Returns:
            分镜对象列表
        """
        pass
```

### 组件 3：任务编排服务（TaskOrchestrator）

**职责**：
- 创建和管理生产任务链
- 协调各个 AI 服务的调用顺序
- 监控任务执行状态和进度
- 处理任务失败和重试逻辑

**接口**：

```python
from typing import List, Dict, Callable
from enum import Enum

class TaskStatus(Enum):
    """任务状态枚举"""
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    RETRYING = "retrying"

class TaskOrchestrator:
    """任务编排服务"""
    
    def create_production_task(self, project_id: str, scenes: List[Scene]) -> str:
        """
        创建生产任务链
        
        Args:
            project_id: 项目 ID
            scenes: 分镜列表
            
        Returns:
            任务链 ID
        """
        pass
    
    def get_task_status(self, task_id: str) -> Dict:
        """
        获取任务状态
        
        Args:
            task_id: 任务 ID
            
        Returns:
            任务状态信息
            {
                "task_id": "xxx",
                "status": "running",
                "progress": 0.45,
                "current_scene": 5,
                "total_scenes": 10,
                "error": None
            }
        """
        pass
    
    def cancel_task(self, task_id: str) -> bool:
        """
        取消任务
        
        Args:
            task_id: 任务 ID
            
        Returns:
            是否取消成功
        """
        pass
    
    def retry_failed_task(self, task_id: str, scene_id: Optional[int] = None) -> bool:
        """
        重试失败的任务
        
        Args:
            task_id: 任务 ID
            scene_id: 指定重试的分镜 ID（可选，不指定则重试所有失败的分镜）
            
        Returns:
            是否重试成功
        """
        pass
```

### 组件 4：LLM 服务（LLMService）

**职责**：
- 封装 llama.cpp 调用逻辑
- 管理 LLM 模型加载和卸载
- 优化 CPU offload 配置
- 提供剧本生成的 Prompt 模板

**接口**：

```python
from typing import Optional, Dict
from llama_cpp import Llama

class LLMService:
    """LLM 服务（Qwen2.5-14B + llama.cpp）"""
    
    def __init__(self, model_path: str, n_gpu_layers: int = 20, 
                 n_ctx: int = 4096, n_threads: int = 8):
        """
        初始化 LLM 服务
        
        Args:
            model_path: GGUF 模型文件路径
            n_gpu_layers: GPU 加载的层数（剩余层 offload 到 CPU）
            n_ctx: 上下文窗口大小
            n_threads: CPU 线程数
        """
        pass
    
    def generate(self, prompt: str, max_tokens: int = 2048, 
                temperature: float = 0.7, top_p: float = 0.9) -> str:
        """
        生成文本
        
        Args:
            prompt: 输入提示词
            max_tokens: 最大生成 token 数
            temperature: 温度参数
            top_p: Top-p 采样参数
            
        Returns:
            生成的文本
        """
        pass
    
    def generate_script_prompt(self, theme: Optional[str], outline: Optional[str],
                              num_scenes: int, num_characters: int, 
                              style: str) -> str:
        """
        构建剧本生成的 Prompt
        
        Args:
            theme: 主题关键词
            outline: 故事大纲
            num_scenes: 分镜数量
            num_characters: 角色数量
            style: 风格偏好
            
        Returns:
            完整的 Prompt 文本
        """
        pass
    
    def unload_model(self):
        """卸载模型释放资源"""
        pass
```

### 组件 5：ComfyUI 服务（ComfyUIService）

**职责**：
- 调用 ComfyUI HTTP API 生成图像
- 管理 Stable Diffusion 工作流配置
- 处理图像生成失败和重试

**接口**：

```python
from typing import Dict, Optional
import requests

class ComfyUIService:
    """ComfyUI 服务（Stable Diffusion）"""
    
    def __init__(self, base_url: str = "http://127.0.0.1:8188"):
        """
        初始化 ComfyUI 服务
        
        Args:
            base_url: ComfyUI 服务地址
        """
        pass
    
    def generate_image(self, prompt: str, negative_prompt: str = "",
                      width: int = 512, height: int = 512,
                      steps: int = 20, cfg_scale: float = 7.0) -> str:
        """
        生成图像
        
        Args:
            prompt: 正向提示词
            negative_prompt: 负向提示词
            width: 图像宽度
            height: 图像高度
            steps: 采样步数
            cfg_scale: CFG 强度
            
        Returns:
            生成的图像文件路径
        """
        pass
    
    def load_workflow(self, workflow_path: str) -> Dict:
        """
        加载工作流配置
        
        Args:
            workflow_path: 工作流 JSON 文件路径
            
        Returns:
            工作流配置字典
        """
        pass
    
    def check_status(self) -> bool:
        """
        检查 ComfyUI 服务是否可用
        
        Returns:
            服务是否可用
        """
        pass
```

### 组件 6：SVD 服务（SVDService）

**职责**：
- 调用 SVD 模型将图像转换为视频
- 管理视频生成参数配置
- 处理视频生成失败和重试

**接口**：

```python
from typing import Optional

class SVDService:
    """SVD 服务（图生视频）"""
    
    def __init__(self, model_path: str, device: str = "cuda"):
        """
        初始化 SVD 服务
        
        Args:
            model_path: SVD 模型路径
            device: 运行设备（cuda 或 cpu）
        """
        pass
    
    def generate_video(self, image_path: str, output_path: str,
                      num_frames: int = 25, fps: int = 8,
                      motion_bucket_id: int = 127,
                      noise_aug_strength: float = 0.02) -> str:
        """
        生成视频
        
        Args:
            image_path: 输入图像路径
            output_path: 输出视频路径
            num_frames: 视频帧数
            fps: 帧率
            motion_bucket_id: 运动强度（0-255）
            noise_aug_strength: 噪声增强强度
            
        Returns:
            生成的视频文件路径
        """
        pass
    
    def check_gpu_memory(self) -> Dict:
        """
        检查 GPU 显存使用情况
        
        Returns:
            显存信息字典
            {
                "total": 24576,  # MB
                "used": 18432,
                "free": 6144
            }
        """
        pass
```

### 组件 7：TTS 服务（TTSService）

**职责**：
- 调用 MiMo-V2-TTS API 生成配音
- 管理角色声音配置
- 处理配音生成失败和重试

**接口**：

```python
from typing import Optional, Dict
import requests

class TTSService:
    """TTS 服务（MiMo-V2-TTS）"""
    
    def __init__(self, api_key: str, base_url: str = "https://mimo.xiaomi.com/api/v2/tts"):
        """
        初始化 TTS 服务
        
        Args:
            api_key: MiMo-V2-TTS API 密钥
            base_url: API 基础 URL
        """
        pass
    
    def generate_speech(self, text: str, speaker: str = "default",
                       emotion: Optional[str] = None,
                       speed: float = 1.0, pitch: float = 1.0) -> str:
        """
        生成语音
        
        Args:
            text: 要合成的文本
            speaker: 说话人 ID（男声、女声、角色声音等）
            emotion: 情感标签（生气、温柔、悄悄话等）
            speed: 语速（0.5-2.0）
            pitch: 音调（0.5-2.0）
            
        Returns:
            生成的音频文件路径
        """
        pass
    
    def list_speakers(self) -> Dict:
        """
        获取可用的说话人列表
        
        Returns:
            说话人信息字典
            {
                "male_1": "成熟男声",
                "female_1": "温柔女声",
                ...
            }
        """
        pass
    
    def check_quota(self) -> Dict:
        """
        检查 API 配额
        
        Returns:
            配额信息
            {
                "total": 10000,
                "used": 3456,
                "remaining": 6544
            }
        """
        pass
```

### 组件 8：字幕生成服务（SubtitleGenerator）

**职责**：
- 根据剧本对话生成 SRT 字幕文件
- 计算字幕时间轴（与配音音频对齐）
- 使用 FFmpeg 将字幕烧录到视频

**接口**：

```python
from typing import List, Dict
from pydantic import BaseModel

class SubtitleSegment(BaseModel):
    """字幕片段"""
    index: int
    start_time: float  # 秒
    end_time: float  # 秒
    text: str

class SubtitleGenerator:
    """字幕生成服务"""
    
    def generate_srt(self, dialogues: List[Dict], audio_paths: List[str],
                    output_path: str) -> str:
        """
        生成 SRT 字幕文件
        
        Args:
            dialogues: 对话列表 [{"text": "你好", "speaker": "角色1"}, ...]
            audio_paths: 对应的音频文件路径列表
            output_path: 输出 SRT 文件路径
            
        Returns:
            生成的 SRT 文件路径
        """
        pass
    
    def burn_subtitle(self, video_path: str, srt_path: str, 
                     output_path: str, font_size: int = 24,
                     font_color: str = "white", 
                     border_color: str = "black") -> str:
        """
        将字幕烧录到视频
        
        Args:
            video_path: 输入视频路径
            srt_path: SRT 字幕文件路径
            output_path: 输出视频路径
            font_size: 字体大小
            font_color: 字体颜色
            border_color: 描边颜色
            
        Returns:
            烧录后的视频文件路径
        """
        pass
    
    def calculate_timing(self, audio_path: str) -> float:
        """
        计算音频时长
        
        Args:
            audio_path: 音频文件路径
            
        Returns:
            音频时长（秒）
        """
        pass
```

### 组件 9：视频合成服务（VideoComposer）

**职责**：
- 拼接多个视频片段
- 同步配音音频和字幕
- 添加背景音乐（可选）
- 导出最终视频

**接口**：

```python
from typing import List, Optional

class VideoComposer:
    """视频合成服务"""
    
    def compose_video(self, video_paths: List[str], audio_paths: List[str],
                     subtitle_path: Optional[str], output_path: str,
                     bgm_path: Optional[str] = None,
                     bgm_volume: float = 0.2) -> str:
        """
        合成最终视频
        
        Args:
            video_paths: 视频片段路径列表（按顺序）
            audio_paths: 配音音频路径列表（按顺序）
            subtitle_path: 字幕文件路径（可选）
            output_path: 输出视频路径
            bgm_path: 背景音乐路径（可选）
            bgm_volume: 背景音乐音量（0.0-1.0）
            
        Returns:
            合成后的视频文件路径
        """
        pass
    
    def concat_videos(self, video_paths: List[str], output_path: str) -> str:
        """
        拼接视频片段
        
        Args:
            video_paths: 视频片段路径列表
            output_path: 输出视频路径
            
        Returns:
            拼接后的视频文件路径
        """
        pass
    
    def sync_audio_video(self, video_path: str, audio_path: str,
                        output_path: str) -> str:
        """
        同步音视频
        
        Args:
            video_path: 视频文件路径
            audio_path: 音频文件路径
            output_path: 输出视频路径
            
        Returns:
            同步后的视频文件路径
        """
        pass
    
    def add_bgm(self, video_path: str, bgm_path: str, output_path: str,
               bgm_volume: float = 0.2) -> str:
        """
        添加背景音乐
        
        Args:
            video_path: 视频文件路径
            bgm_path: 背景音乐路径
            output_path: 输出视频路径
            bgm_volume: 背景音乐音量
            
        Returns:
            添加背景音乐后的视频文件路径
        """
        pass
```


## 数据模型

### 项目数据模型

```python
from typing import List, Optional, Dict
from pydantic import BaseModel, Field
from datetime import datetime
from enum import Enum

class ProjectStatus(str, Enum):
    """项目状态"""
    DRAFT = "draft"  # 草稿
    GENERATING = "generating"  # 生成剧本中
    READY = "ready"  # 剧本已生成，待生产
    PRODUCING = "producing"  # 生产中
    COMPLETED = "completed"  # 已完成
    FAILED = "failed"  # 失败

class Character(BaseModel):
    """角色模型"""
    name: str
    voice_id: str  # TTS 说话人 ID
    description: Optional[str] = None

class Scene(BaseModel):
    """分镜模型"""
    scene_id: int
    description: str  # 场景描述
    characters: List[str]  # 出现的角色
    dialogue: Optional[str] = None  # 对话内容
    speaker: Optional[str] = None  # 说话人
    emotion: Optional[str] = None  # 情感
    visual_prompt: str  # 图像生成提示词
    image_path: Optional[str] = None  # 生成的图像路径
    video_path: Optional[str] = None  # 生成的视频路径
    audio_path: Optional[str] = None  # 配音音频路径
    status: str = "pending"  # pending, processing, completed, failed

class ProductionConfig(BaseModel):
    """生产配置"""
    image_width: int = 512
    image_height: int = 512
    video_fps: int = 8
    video_frames: int = 25
    enable_bgm: bool = False
    bgm_volume: float = 0.2

class Project(BaseModel):
    """项目模型"""
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    name: str
    theme: Optional[str] = None
    outline: Optional[str] = None
    script: Optional[str] = None  # 完整剧本文本
    characters: List[Character] = []
    scenes: List[Scene] = []
    status: ProjectStatus = ProjectStatus.DRAFT
    config: ProductionConfig = ProductionConfig()
    final_video_path: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)
    error_message: Optional[str] = None
```

### 任务数据模型

```python
from typing import List, Optional, Dict
from pydantic import BaseModel
from datetime import datetime
from enum import Enum

class TaskType(str, Enum):
    """任务类型"""
    GENERATE_IMAGE = "generate_image"
    GENERATE_VIDEO = "generate_video"
    GENERATE_AUDIO = "generate_audio"
    GENERATE_SUBTITLE = "generate_subtitle"
    COMPOSE_VIDEO = "compose_video"

class TaskStatus(str, Enum):
    """任务状态"""
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    RETRYING = "retrying"

class Task(BaseModel):
    """任务模型"""
    task_id: str
    project_id: str
    scene_id: Optional[int] = None
    task_type: TaskType
    status: TaskStatus = TaskStatus.PENDING
    progress: float = 0.0  # 0.0 - 1.0
    input_data: Dict = {}
    output_data: Dict = {}
    error_message: Optional[str] = None
    retry_count: int = 0
    max_retries: int = 3
    created_at: datetime = Field(default_factory=datetime.now)
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
```

### 数据库 Schema（SQLite/PostgreSQL）

```sql
-- 项目表
CREATE TABLE projects (
    id VARCHAR(36) PRIMARY KEY,
    name VARCHAR(255) NOT NULL,
    theme TEXT,
    outline TEXT,
    script TEXT,
    status VARCHAR(20) NOT NULL,
    config JSON,
    final_video_path TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    error_message TEXT
);

-- 角色表
CREATE TABLE characters (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id VARCHAR(36) NOT NULL,
    name VARCHAR(100) NOT NULL,
    voice_id VARCHAR(50) NOT NULL,
    description TEXT,
    FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE
);

-- 分镜表
CREATE TABLE scenes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id VARCHAR(36) NOT NULL,
    scene_id INTEGER NOT NULL,
    description TEXT NOT NULL,
    characters JSON,
    dialogue TEXT,
    speaker VARCHAR(100),
    emotion VARCHAR(50),
    visual_prompt TEXT NOT NULL,
    image_path TEXT,
    video_path TEXT,
    audio_path TEXT,
    status VARCHAR(20) DEFAULT 'pending',
    FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE
);

-- 任务表
CREATE TABLE tasks (
    task_id VARCHAR(36) PRIMARY KEY,
    project_id VARCHAR(36) NOT NULL,
    scene_id INTEGER,
    task_type VARCHAR(50) NOT NULL,
    status VARCHAR(20) DEFAULT 'pending',
    progress REAL DEFAULT 0.0,
    input_data JSON,
    output_data JSON,
    error_message TEXT,
    retry_count INTEGER DEFAULT 0,
    max_retries INTEGER DEFAULT 3,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    started_at TIMESTAMP,
    completed_at TIMESTAMP,
    FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE
);

-- 索引
CREATE INDEX idx_projects_status ON projects(status);
CREATE INDEX idx_scenes_project_id ON scenes(project_id);
CREATE INDEX idx_tasks_project_id ON tasks(project_id);
CREATE INDEX idx_tasks_status ON tasks(status);
```


## 核心算法与形式化规范

### 算法 1：剧本生成算法

```python
def generate_script_algorithm(theme: Optional[str], outline: Optional[str],
                              num_scenes: int, num_characters: int, 
                              style: str) -> Dict:
    """
    剧本生成算法
    
    前置条件：
    - theme 或 outline 至少有一个非空
    - num_scenes >= 1 且 num_scenes <= 50
    - num_characters >= 1 且 num_characters <= 10
    - LLM 服务已初始化且可用
    
    后置条件：
    - 返回包含完整剧本和分镜列表的字典
    - 分镜数量等于 num_scenes
    - 每个分镜包含有效的 visual_prompt
    - 如果有对话，则 speaker 和 dialogue 非空
    
    循环不变式：
    - 所有已生成的分镜都包含有效的 description 和 visual_prompt
    - 角色名称在整个剧本中保持一致
    """
    
    # 步骤 1：构建 Prompt
    prompt = build_script_prompt(theme, outline, num_scenes, num_characters, style)
    
    # 步骤 2：调用 LLM 生成剧本
    llm_output = llm_service.generate(prompt, max_tokens=2048, temperature=0.7)
    
    # 步骤 3：解析 LLM 输出
    script_data = parse_llm_output(llm_output)
    
    # 步骤 4：验证和补全分镜信息
    scenes = []
    for i, scene_raw in enumerate(script_data["scenes"]):
        # 确保每个分镜都有必需字段
        scene = Scene(
            scene_id=i + 1,
            description=scene_raw.get("description", ""),
            characters=scene_raw.get("characters", []),
            dialogue=scene_raw.get("dialogue"),
            speaker=scene_raw.get("speaker"),
            emotion=scene_raw.get("emotion"),
            visual_prompt=generate_visual_prompt(scene_raw)
        )
        scenes.append(scene)
    
    # 步骤 5：返回结果
    return {
        "script": script_data["script"],
        "scenes": scenes,
        "characters": script_data["characters"]
    }


def build_script_prompt(theme: Optional[str], outline: Optional[str],
                       num_scenes: int, num_characters: int, style: str) -> str:
    """
    构建剧本生成 Prompt
    
    前置条件：
    - theme 或 outline 至少有一个非空
    
    后置条件：
    - 返回格式化的 Prompt 字符串
    - Prompt 包含所有必要的生成指令
    """
    
    prompt_template = """你是一位专业的短剧编剧。请根据以下要求创作一个短剧剧本：

主题：{theme}
故事大纲：{outline}
分镜数量：{num_scenes}
角色数量：{num_characters}
风格：{style}

请按照以下格式输出：

【剧本】
（完整的剧本文本，包含对话、场景描述、角色动作）

【角色】
- 角色1：描述
- 角色2：描述

【分镜】
分镜1：
- 场景描述：xxx
- 出现角色：[角色1, 角色2]
- 对话：xxx
- 说话人：角色1
- 情感：温柔

分镜2：
...

要求：
1. 剧本要有完整的故事结构（开端、发展、高潮、结局）
2. 对话要自然流畅，符合角色性格
3. 场景描述要具体生动，便于图像生成
4. 每个分镜时长约 3-5 秒
5. 风格要符合"{style}"的特点
"""
    
    return prompt_template.format(
        theme=theme or "未指定",
        outline=outline or "未指定",
        num_scenes=num_scenes,
        num_characters=num_characters,
        style=style
    )


def generate_visual_prompt(scene_raw: Dict) -> str:
    """
    生成图像提示词
    
    前置条件：
    - scene_raw 包含 description 字段
    
    后置条件：
    - 返回适合 Stable Diffusion 的提示词
    - 提示词包含场景描述和风格标签
    """
    
    description = scene_raw.get("description", "")
    characters = scene_raw.get("characters", [])
    
    # 基础提示词
    prompt_parts = [description]
    
    # 添加角色信息
    if characters:
        prompt_parts.append(f"characters: {', '.join(characters)}")
    
    # 添加质量标签
    quality_tags = [
        "high quality",
        "detailed",
        "cinematic lighting",
        "professional photography"
    ]
    prompt_parts.extend(quality_tags)
    
    return ", ".join(prompt_parts)
```

### 算法 2：生产任务编排算法

```python
def orchestrate_production_algorithm(project_id: str, scenes: List[Scene]) -> str:
    """
    生产任务编排算法
    
    前置条件：
    - project_id 对应的项目存在
    - scenes 列表非空
    - 所有 AI 服务（ComfyUI、SVD、TTS）可用
    
    后置条件：
    - 创建并提交所有必要的任务到 Celery 队列
    - 返回任务链 ID
    - 任务按正确的依赖顺序执行
    
    循环不变式：
    - 每个分镜的任务链保持正确的执行顺序：图像 -> 视频 -> 配音 -> 字幕
    - 所有任务都关联到正确的 project_id 和 scene_id
    """
    
    # 步骤 1：创建任务链 ID
    task_chain_id = generate_task_chain_id()
    
    # 步骤 2：为每个分镜创建任务链
    scene_tasks = []
    for scene in scenes:
        # 2.1 创建图像生成任务
        image_task = create_task(
            project_id=project_id,
            scene_id=scene.scene_id,
            task_type=TaskType.GENERATE_IMAGE,
            input_data={
                "prompt": scene.visual_prompt,
                "width": 512,
                "height": 512
            }
        )
        
        # 2.2 创建视频生成任务（依赖图像任务）
        video_task = create_task(
            project_id=project_id,
            scene_id=scene.scene_id,
            task_type=TaskType.GENERATE_VIDEO,
            input_data={
                "image_task_id": image_task.task_id
            }
        )
        
        # 2.3 创建配音任务（可与视频任务并行）
        audio_task = None
        if scene.dialogue:
            audio_task = create_task(
                project_id=project_id,
                scene_id=scene.scene_id,
                task_type=TaskType.GENERATE_AUDIO,
                input_data={
                    "text": scene.dialogue,
                    "speaker": scene.speaker,
                    "emotion": scene.emotion
                }
            )
        
        # 2.4 创建字幕任务（依赖配音任务）
        subtitle_task = None
        if audio_task:
            subtitle_task = create_task(
                project_id=project_id,
                scene_id=scene.scene_id,
                task_type=TaskType.GENERATE_SUBTITLE,
                input_data={
                    "audio_task_id": audio_task.task_id,
                    "dialogue": scene.dialogue
                }
            )
        
        # 2.5 构建任务链
        scene_task_chain = build_task_chain([
            image_task,
            video_task,
            audio_task,
            subtitle_task
        ])
        scene_tasks.append(scene_task_chain)
    
    # 步骤 3：创建视频合成任务（依赖所有分镜任务完成）
    compose_task = create_task(
        project_id=project_id,
        scene_id=None,
        task_type=TaskType.COMPOSE_VIDEO,
        input_data={
            "scene_task_ids": [t.task_id for t in scene_tasks]
        }
    )
    
    # 步骤 4：提交任务链到 Celery
    celery_chain = chain(scene_tasks + [compose_task])
    celery_chain.apply_async(task_id=task_chain_id)
    
    # 步骤 5：返回任务链 ID
    return task_chain_id


def build_task_chain(tasks: List[Task]) -> CeleryChain:
    """
    构建 Celery 任务链
    
    前置条件：
    - tasks 列表非空
    - 任务按执行顺序排列
    
    后置条件：
    - 返回 Celery 任务链对象
    - 任务按顺序执行，前一个任务的输出作为后一个任务的输入
    """
    
    # 过滤掉 None 任务
    valid_tasks = [t for t in tasks if t is not None]
    
    # 构建 Celery 任务链
    celery_tasks = []
    for task in valid_tasks:
        celery_task = get_celery_task_by_type(task.task_type)
        celery_tasks.append(celery_task.s(task.input_data))
    
    return chain(*celery_tasks)
```

### 算法 3：视频合成算法

```python
def compose_video_algorithm(project_id: str, scene_videos: List[str],
                           scene_audios: List[str], subtitle_path: Optional[str],
                           bgm_path: Optional[str]) -> str:
    """
    视频合成算法
    
    前置条件：
    - scene_videos 和 scene_audios 长度相同且非空
    - 所有视频和音频文件存在且可读
    - FFmpeg 已安装且可用
    
    后置条件：
    - 返回合成后的视频文件路径
    - 视频包含所有分镜片段，按顺序拼接
    - 配音与视频精确同步
    - 字幕已烧录到视频（如果提供）
    - 背景音乐已添加（如果提供）
    
    循环不变式：
    - 所有已处理的视频片段都已正确同步音频
    - 视频分辨率保持一致
    """
    
    # 步骤 1：为每个分镜同步音视频
    synced_videos = []
    for i, (video_path, audio_path) in enumerate(zip(scene_videos, scene_audios)):
        synced_video = sync_audio_video(video_path, audio_path, 
                                       f"temp_synced_{i}.mp4")
        synced_videos.append(synced_video)
    
    # 步骤 2：拼接所有视频片段
    concat_video = concat_videos(synced_videos, "temp_concat.mp4")
    
    # 步骤 3：烧录字幕（如果提供）
    if subtitle_path:
        subtitled_video = burn_subtitle(concat_video, subtitle_path, 
                                       "temp_subtitled.mp4")
    else:
        subtitled_video = concat_video
    
    # 步骤 4：添加背景音乐（如果提供）
    if bgm_path:
        final_video = add_bgm(subtitled_video, bgm_path, 
                             f"final_{project_id}.mp4", bgm_volume=0.2)
    else:
        final_video = subtitled_video
    
    # 步骤 5：清理临时文件
    cleanup_temp_files([*synced_videos, concat_video, subtitled_video])
    
    # 步骤 6：返回最终视频路径
    return final_video


def sync_audio_video(video_path: str, audio_path: str, output_path: str) -> str:
    """
    同步音视频
    
    前置条件：
    - video_path 和 audio_path 文件存在
    - FFmpeg 可用
    
    后置条件：
    - 返回同步后的视频文件路径
    - 音频与视频时长一致
    - 如果音频较短，视频会被裁剪
    - 如果音频较长，视频会循环或静止
    """
    
    # 获取音频时长
    audio_duration = get_audio_duration(audio_path)
    
    # 获取视频时长
    video_duration = get_video_duration(video_path)
    
    # 构建 FFmpeg 命令
    if audio_duration <= video_duration:
        # 音频较短，裁剪视频
        cmd = [
            "ffmpeg", "-i", video_path, "-i", audio_path,
            "-t", str(audio_duration),
            "-c:v", "copy", "-c:a", "aac",
            "-y", output_path
        ]
    else:
        # 音频较长，循环视频或静止最后一帧
        cmd = [
            "ffmpeg", "-stream_loop", "-1", "-i", video_path,
            "-i", audio_path,
            "-t", str(audio_duration),
            "-c:v", "libx264", "-c:a", "aac",
            "-y", output_path
        ]
    
    # 执行 FFmpeg 命令
    subprocess.run(cmd, check=True)
    
    return output_path


def concat_videos(video_paths: List[str], output_path: str) -> str:
    """
    拼接视频片段
    
    前置条件：
    - video_paths 非空
    - 所有视频文件存在
    - 所有视频分辨率和编码格式一致
    
    后置条件：
    - 返回拼接后的视频文件路径
    - 视频按 video_paths 顺序拼接
    - 无缝衔接，无黑屏或跳帧
    """
    
    # 创建 concat 文件列表
    concat_file = "temp_concat_list.txt"
    with open(concat_file, "w") as f:
        for video_path in video_paths:
            f.write(f"file '{video_path}'\n")
    
    # 构建 FFmpeg 命令
    cmd = [
        "ffmpeg", "-f", "concat", "-safe", "0",
        "-i", concat_file,
        "-c", "copy",
        "-y", output_path
    ]
    
    # 执行 FFmpeg 命令
    subprocess.run(cmd, check=True)
    
    # 清理临时文件
    os.remove(concat_file)
    
    return output_path


def burn_subtitle(video_path: str, srt_path: str, output_path: str,
                 font_size: int = 24, font_color: str = "white",
                 border_color: str = "black") -> str:
    """
    烧录字幕到视频
    
    前置条件：
    - video_path 和 srt_path 文件存在
    - SRT 文件格式正确
    - FFmpeg 支持 subtitles 滤镜
    
    后置条件：
    - 返回烧录字幕后的视频文件路径
    - 字幕位置：底部居中，距离底部 10% 高度
    - 字幕样式：白色字体 + 黑色描边
    """
    
    # 构建字幕滤镜参数
    subtitle_filter = (
        f"subtitles={srt_path}:"
        f"force_style='FontSize={font_size},"
        f"PrimaryColour=&H{color_to_hex(font_color)},"
        f"OutlineColour=&H{color_to_hex(border_color)},"
        f"Outline=2,"
        f"Alignment=2,"  # 底部居中
        f"MarginV=50'"  # 距离底部 50 像素
    )
    
    # 构建 FFmpeg 命令
    cmd = [
        "ffmpeg", "-i", video_path,
        "-vf", subtitle_filter,
        "-c:a", "copy",
        "-y", output_path
    ]
    
    # 执行 FFmpeg 命令
    subprocess.run(cmd, check=True)
    
    return output_path
```

### 算法 4：显存优化算法

```python
def optimize_gpu_memory_algorithm() -> Dict:
    """
    显存优化算法
    
    目标：
    - 在单张 RTX 4090/3090 24GB 显卡上同时运行 SD + SVD
    - LLM 使用 CPU offload，释放 GPU 显存
    
    策略：
    - LLM：仅加载 20 层到 GPU（约 4-6GB），其余层 offload 到 CPU
    - SD：占用约 8-10GB 显存
    - SVD：占用约 8-10GB 显存
    - 总计：约 20-26GB（需要动态调度）
    
    前置条件：
    - GPU 显存 >= 24GB
    - CPU 核心数 >= 8
    - RAM >= 32GB（推荐 64GB）
    
    后置条件：
    - LLM、SD、SVD 可以在同一 GPU 上运行
    - 显存使用率 < 95%
    - 不发生 OOM 错误
    """
    
    # 步骤 1：检测 GPU 显存
    total_vram = get_gpu_total_memory()  # MB
    
    # 步骤 2：计算 LLM offload 层数
    # 目标：LLM 占用 4-6GB 显存
    target_llm_vram = 5 * 1024  # 5GB
    llm_layers_on_gpu = calculate_llm_layers(target_llm_vram)
    
    # 步骤 3：配置 LLM
    llm_config = {
        "model_path": "models/qwen2.5-14b-instruct-q4_k_m.gguf",
        "n_gpu_layers": llm_layers_on_gpu,  # 约 20 层
        "n_ctx": 4096,
        "n_threads": 8,  # CPU 线程数
        "n_batch": 512
    }
    
    # 步骤 4：配置 SD 和 SVD
    # SD 和 SVD 不同时运行，通过任务调度错开
    sd_config = {
        "model": "stable-diffusion-xl-base-1.0",
        "vram_usage": "high"  # 约 8-10GB
    }
    
    svd_config = {
        "model": "stable-video-diffusion-img2vid-xt",
        "vram_usage": "high"  # 约 8-10GB
    }
    
    # 步骤 5：任务调度策略
    # - LLM 任务优先执行（剧本生成）
    # - SD 和 SVD 任务串行执行，避免同时占用显存
    # - 可选：SD 和 SVD 任务之间插入显存清理
    
    scheduling_strategy = {
        "llm_priority": "high",  # LLM 任务优先
        "sd_svd_serial": True,  # SD 和 SVD 串行执行
        "clear_cache_between_tasks": True  # 任务间清理缓存
    }
    
    return {
        "llm_config": llm_config,
        "sd_config": sd_config,
        "svd_config": svd_config,
        "scheduling_strategy": scheduling_strategy
    }


def calculate_llm_layers(target_vram_mb: int) -> int:
    """
    计算 LLM 应加载到 GPU 的层数
    
    前置条件：
    - target_vram_mb > 0
    - Qwen2.5-14B 模型总层数为 40
    
    后置条件：
    - 返回应加载到 GPU 的层数
    - 返回值在 [0, 40] 范围内
    
    估算：
    - Qwen2.5-14B Q4_K_M 量化模型约 8GB
    - 每层约 200MB
    - target_vram_mb / 200 = 层数
    """
    
    total_layers = 40  # Qwen2.5-14B 总层数
    vram_per_layer_mb = 200  # 每层约 200MB
    
    layers_on_gpu = int(target_vram_mb / vram_per_layer_mb)
    
    # 限制在 [0, total_layers] 范围内
    layers_on_gpu = max(0, min(layers_on_gpu, total_layers))
    
    return layers_on_gpu


def clear_gpu_cache():
    """
    清理 GPU 缓存
    
    用途：
    - 在 SD 和 SVD 任务之间释放显存
    - 避免显存碎片化
    """
    
    import torch
    import gc
    
    # 清理 PyTorch 缓存
    torch.cuda.empty_cache()
    
    # 强制垃圾回收
    gc.collect()
```


## API 设计

### RESTful API 端点

#### 1. 项目管理 API

```python
from fastapi import APIRouter, HTTPException, status
from typing import List, Optional
from pydantic import BaseModel

router = APIRouter(prefix="/api/projects", tags=["projects"])

# 请求/响应模型
class CreateProjectRequest(BaseModel):
    """创建项目请求"""
    name: str
    theme: Optional[str] = None
    outline: Optional[str] = None
    num_scenes: int = 10
    num_characters: int = 2
    style: str = "现代都市"

class ProjectResponse(BaseModel):
    """项目响应"""
    id: str
    name: str
    theme: Optional[str]
    outline: Optional[str]
    script: Optional[str]
    characters: List[dict]
    scenes: List[dict]
    status: str
    config: dict
    final_video_path: Optional[str]
    created_at: str
    updated_at: str

@router.post("/", response_model=ProjectResponse, status_code=status.HTTP_201_CREATED)
async def create_project(request: CreateProjectRequest):
    """
    创建新项目
    
    功能：
    - 创建项目记录
    - 如果提供 theme 或 outline，自动调用 LLM 生成剧本
    
    返回：
    - 201: 项目创建成功
    - 400: 请求参数错误
    - 500: 服务器内部错误
    """
    pass

@router.get("/{project_id}", response_model=ProjectResponse)
async def get_project(project_id: str):
    """
    获取项目详情
    
    返回：
    - 200: 成功返回项目信息
    - 404: 项目不存在
    """
    pass

@router.get("/", response_model=List[ProjectResponse])
async def list_projects(status: Optional[str] = None, limit: int = 20, offset: int = 0):
    """
    列出项目列表
    
    参数：
    - status: 过滤状态（可选）
    - limit: 返回数量限制
    - offset: 偏移量
    
    返回：
    - 200: 成功返回项目列表
    """
    pass

@router.put("/{project_id}", response_model=ProjectResponse)
async def update_project(project_id: str, script: Optional[str] = None, 
                        scenes: Optional[List[dict]] = None):
    """
    更新项目信息
    
    功能：
    - 更新剧本或分镜
    - 支持部分更新
    
    返回：
    - 200: 更新成功
    - 404: 项目不存在
    - 400: 请求参数错误
    """
    pass

@router.delete("/{project_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_project(project_id: str):
    """
    删除项目
    
    功能：
    - 删除项目记录
    - 删除关联的文件（图像、视频、音频）
    
    返回：
    - 204: 删除成功
    - 404: 项目不存在
    """
    pass
```

#### 2. 剧本生成 API

```python
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional, List

router = APIRouter(prefix="/api/scripts", tags=["scripts"])

class GenerateScriptRequest(BaseModel):
    """生成剧本请求"""
    theme: Optional[str] = None
    outline: Optional[str] = None
    num_scenes: int = 10
    num_characters: int = 2
    style: str = "现代都市"

class GenerateScriptResponse(BaseModel):
    """生成剧本响应"""
    script: str
    characters: List[dict]
    scenes: List[dict]

@router.post("/generate", response_model=GenerateScriptResponse)
async def generate_script(request: GenerateScriptRequest):
    """
    生成剧本
    
    功能：
    - 调用 LLM 生成完整剧本和分镜
    - 解析并结构化输出
    
    返回：
    - 200: 生成成功
    - 400: 请求参数错误（theme 和 outline 都为空）
    - 500: LLM 服务错误
    - 503: LLM 服务不可用
    """
    pass

@router.post("/regenerate-scene", response_model=dict)
async def regenerate_scene(scene_id: int, description: str):
    """
    重新生成单个分镜
    
    功能：
    - 根据新的描述重新生成分镜
    
    返回：
    - 200: 重新生成成功
    - 400: 请求参数错误
    - 500: LLM 服务错误
    """
    pass
```

#### 3. 生产任务 API

```python
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional

router = APIRouter(prefix="/api/production", tags=["production"])

class StartProductionRequest(BaseModel):
    """开始生产请求"""
    project_id: str

class ProductionStatusResponse(BaseModel):
    """生产状态响应"""
    task_id: str
    project_id: str
    status: str
    progress: float
    current_scene: int
    total_scenes: int
    error: Optional[str]

@router.post("/start", response_model=dict)
async def start_production(request: StartProductionRequest):
    """
    开始生产任务
    
    功能：
    - 创建生产任务链
    - 提交到 Celery 队列
    
    返回：
    - 200: 任务创建成功，返回 task_id
    - 404: 项目不存在
    - 400: 项目状态不允许生产（如剧本未生成）
    """
    pass

@router.get("/status/{task_id}", response_model=ProductionStatusResponse)
async def get_production_status(task_id: str):
    """
    获取生产任务状态
    
    返回：
    - 200: 成功返回任务状态
    - 404: 任务不存在
    """
    pass

@router.post("/cancel/{task_id}", response_model=dict)
async def cancel_production(task_id: str):
    """
    取消生产任务
    
    返回：
    - 200: 取消成功
    - 404: 任务不存在
    - 400: 任务状态不允许取消（如已完成）
    """
    pass

@router.post("/retry/{task_id}", response_model=dict)
async def retry_production(task_id: str, scene_id: Optional[int] = None):
    """
    重试失败的任务
    
    参数：
    - scene_id: 指定重试的分镜 ID（可选）
    
    返回：
    - 200: 重试成功
    - 404: 任务不存在
    - 400: 任务状态不允许重试（如正在运行）
    """
    pass
```

#### 4. 文件下载 API

```python
from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

router = APIRouter(prefix="/api/files", tags=["files"])

@router.get("/video/{project_id}")
async def download_video(project_id: str):
    """
    下载最终视频
    
    返回：
    - 200: 成功返回视频文件
    - 404: 项目不存在或视频未生成
    """
    pass

@router.get("/scene-image/{project_id}/{scene_id}")
async def download_scene_image(project_id: str, scene_id: int):
    """
    下载分镜图像
    
    返回：
    - 200: 成功返回图像文件
    - 404: 分镜不存在或图像未生成
    """
    pass

@router.get("/scene-video/{project_id}/{scene_id}")
async def download_scene_video(project_id: str, scene_id: int):
    """
    下载分镜视频
    
    返回：
    - 200: 成功返回视频文件
    - 404: 分镜不存在或视频未生成
    """
    pass
```

### WebSocket API

```python
from fastapi import WebSocket, WebSocketDisconnect
from typing import Dict, Set

class ConnectionManager:
    """WebSocket 连接管理器"""
    
    def __init__(self):
        # 存储活跃连接：{project_id: Set[WebSocket]}
        self.active_connections: Dict[str, Set[WebSocket]] = {}
    
    async def connect(self, websocket: WebSocket, project_id: str):
        """
        接受 WebSocket 连接
        
        Args:
            websocket: WebSocket 连接对象
            project_id: 项目 ID
        """
        await websocket.accept()
        if project_id not in self.active_connections:
            self.active_connections[project_id] = set()
        self.active_connections[project_id].add(websocket)
    
    def disconnect(self, websocket: WebSocket, project_id: str):
        """
        断开 WebSocket 连接
        
        Args:
            websocket: WebSocket 连接对象
            project_id: 项目 ID
        """
        if project_id in self.active_connections:
            self.active_connections[project_id].discard(websocket)
            if not self.active_connections[project_id]:
                del self.active_connections[project_id]
    
    async def broadcast(self, project_id: str, message: dict):
        """
        向指定项目的所有连接广播消息
        
        Args:
            project_id: 项目 ID
            message: 消息内容
        """
        if project_id in self.active_connections:
            for connection in self.active_connections[project_id]:
                await connection.send_json(message)

manager = ConnectionManager()

@app.websocket("/ws/progress/{project_id}")
async def websocket_progress(websocket: WebSocket, project_id: str):
    """
    WebSocket 进度推送端点
    
    功能：
    - 实时推送任务进度更新
    - 推送任务状态变化
    - 推送错误信息
    
    消息格式：
    {
        "type": "progress",  # progress, status, error, complete
        "project_id": "xxx",
        "scene_id": 1,
        "status": "running",
        "progress": 0.45,
        "message": "正在生成第 5/10 个镜头..."
    }
    """
    await manager.connect(websocket, project_id)
    try:
        while True:
            # 保持连接，等待客户端消息（心跳）
            data = await websocket.receive_text()
            # 可以处理客户端发送的心跳或控制消息
    except WebSocketDisconnect:
        manager.disconnect(websocket, project_id)
```

### API 错误响应格式

```python
from pydantic import BaseModel
from typing import Optional

class ErrorResponse(BaseModel):
    """统一错误响应格式"""
    error_code: str  # 错误代码（如 PROJECT_NOT_FOUND）
    message: str  # 错误消息
    details: Optional[dict] = None  # 详细信息（可选）

# 错误代码定义
class ErrorCode:
    # 项目相关
    PROJECT_NOT_FOUND = "PROJECT_NOT_FOUND"
    PROJECT_INVALID_STATUS = "PROJECT_INVALID_STATUS"
    
    # 剧本生成相关
    SCRIPT_GENERATION_FAILED = "SCRIPT_GENERATION_FAILED"
    LLM_SERVICE_UNAVAILABLE = "LLM_SERVICE_UNAVAILABLE"
    
    # 生产任务相关
    TASK_NOT_FOUND = "TASK_NOT_FOUND"
    TASK_CREATION_FAILED = "TASK_CREATION_FAILED"
    
    # AI 服务相关
    COMFYUI_UNAVAILABLE = "COMFYUI_UNAVAILABLE"
    SVD_UNAVAILABLE = "SVD_UNAVAILABLE"
    TTS_API_ERROR = "TTS_API_ERROR"
    
    # 文件相关
    FILE_NOT_FOUND = "FILE_NOT_FOUND"
    FILE_GENERATION_FAILED = "FILE_GENERATION_FAILED"
    
    # 通用错误
    INVALID_REQUEST = "INVALID_REQUEST"
    INTERNAL_ERROR = "INTERNAL_ERROR"

# 示例错误响应
"""
{
    "error_code": "PROJECT_NOT_FOUND",
    "message": "项目不存在",
    "details": {
        "project_id": "abc123"
    }
}
"""
```


## 错误处理

### 错误场景 1：LLM 服务不可用

**条件**：llama.cpp 服务未启动或模型加载失败

**响应**：
- 返回 503 Service Unavailable
- 错误代码：LLM_SERVICE_UNAVAILABLE
- 错误消息："LLM 服务不可用，请检查模型是否正确加载"

**恢复**：
- 提示用户检查 llama.cpp 服务状态
- 提供重试选项
- 记录错误日志供排查

### 错误场景 2：ComfyUI 图像生成失败

**条件**：ComfyUI API 调用失败或生成超时

**响应**：
- 自动重试最多 3 次
- 如果仍失败，标记该分镜为失败状态
- 通过 WebSocket 推送错误通知
- 错误代码：COMFYUI_GENERATION_FAILED

**恢复**：
- 用户可以手动重试该分镜
- 用户可以调整提示词后重新生成
- 系统继续处理其他分镜

### 错误场景 3：SVD 视频生成失败

**条件**：SVD 模型推理失败或 GPU 显存不足

**响应**：
- 检查 GPU 显存使用情况
- 如果显存不足，清理缓存后重试
- 自动重试最多 3 次
- 如果仍失败，标记该分镜为失败状态

**恢复**：
- 用户可以手动重试该分镜
- 系统提供显存优化建议
- 可选：降低视频质量参数后重试

### 错误场景 4：TTS API 配额不足

**条件**：MiMo-V2-TTS API 返回配额不足错误

**响应**：
- 暂停所有配音任务
- 通过 WebSocket 推送配额不足通知
- 错误代码：TTS_QUOTA_EXCEEDED

**恢复**：
- 提示用户充值或等待配额恢复
- 已生成的配音保留，未生成的配音暂停
- 用户可以在配额恢复后继续生产

### 错误场景 5：视频合成失败

**条件**：FFmpeg 执行失败或文件损坏

**响应**：
- 检查所有输入文件的完整性
- 记录详细的 FFmpeg 错误日志
- 错误代码：VIDEO_COMPOSITION_FAILED

**恢复**：
- 重新生成损坏的视频片段
- 用户可以手动调整合成参数后重试
- 提供详细的错误日志供排查

### 错误场景 6：磁盘空间不足

**条件**：生成文件时磁盘空间不足

**响应**：
- 暂停所有生成任务
- 通过 WebSocket 推送磁盘空间不足通知
- 错误代码：DISK_SPACE_INSUFFICIENT

**恢复**：
- 提示用户清理磁盘空间
- 提供自动清理临时文件的选项
- 用户可以在清理后继续生产

### 错误处理策略

```python
from typing import Optional, Callable
import logging
from functools import wraps

logger = logging.getLogger(__name__)

class RetryConfig:
    """重试配置"""
    max_retries: int = 3
    retry_delay: float = 5.0  # 秒
    exponential_backoff: bool = True

def retry_on_failure(config: RetryConfig = RetryConfig()):
    """
    失败重试装饰器
    
    功能：
    - 自动重试失败的操作
    - 支持指数退避
    - 记录重试日志
    """
    def decorator(func: Callable):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            last_exception = None
            for attempt in range(config.max_retries):
                try:
                    return await func(*args, **kwargs)
                except Exception as e:
                    last_exception = e
                    logger.warning(
                        f"函数 {func.__name__} 第 {attempt + 1} 次尝试失败: {str(e)}"
                    )
                    
                    if attempt < config.max_retries - 1:
                        # 计算延迟时间
                        if config.exponential_backoff:
                            delay = config.retry_delay * (2 ** attempt)
                        else:
                            delay = config.retry_delay
                        
                        logger.info(f"等待 {delay} 秒后重试...")
                        await asyncio.sleep(delay)
            
            # 所有重试都失败
            logger.error(f"函数 {func.__name__} 在 {config.max_retries} 次重试后仍然失败")
            raise last_exception
        
        return wrapper
    return decorator


class ErrorHandler:
    """统一错误处理器"""
    
    @staticmethod
    async def handle_llm_error(error: Exception, project_id: str):
        """
        处理 LLM 服务错误
        
        Args:
            error: 异常对象
            project_id: 项目 ID
        """
        logger.error(f"LLM 服务错误 (项目 {project_id}): {str(error)}")
        
        # 更新项目状态
        await update_project_status(project_id, "failed", 
                                   error_message="LLM 服务不可用")
        
        # 推送错误通知
        await manager.broadcast(project_id, {
            "type": "error",
            "error_code": "LLM_SERVICE_UNAVAILABLE",
            "message": "LLM 服务不可用，请检查服务状态"
        })
    
    @staticmethod
    async def handle_comfyui_error(error: Exception, project_id: str, scene_id: int):
        """
        处理 ComfyUI 错误
        
        Args:
            error: 异常对象
            project_id: 项目 ID
            scene_id: 分镜 ID
        """
        logger.error(f"ComfyUI 错误 (项目 {project_id}, 分镜 {scene_id}): {str(error)}")
        
        # 更新分镜状态
        await update_scene_status(project_id, scene_id, "failed")
        
        # 推送错误通知
        await manager.broadcast(project_id, {
            "type": "error",
            "scene_id": scene_id,
            "error_code": "COMFYUI_GENERATION_FAILED",
            "message": f"分镜 {scene_id} 图像生成失败"
        })
    
    @staticmethod
    async def handle_gpu_oom_error(error: Exception, project_id: str):
        """
        处理 GPU 显存不足错误
        
        Args:
            error: 异常对象
            project_id: 项目 ID
        """
        logger.error(f"GPU 显存不足 (项目 {project_id}): {str(error)}")
        
        # 清理 GPU 缓存
        clear_gpu_cache()
        
        # 推送错误通知
        await manager.broadcast(project_id, {
            "type": "error",
            "error_code": "GPU_OOM",
            "message": "GPU 显存不足，已清理缓存，请重试"
        })
```


## 测试策略

### 单元测试

**测试范围**：
- 所有服务类的核心方法
- 数据模型的验证逻辑
- 工具函数和辅助函数

**测试框架**：pytest

**示例测试用例**：

```python
import pytest
from unittest.mock import Mock, patch
from services.script_generator import ScriptGenerator
from services.llm_service import LLMService

class TestScriptGenerator:
    """剧本生成服务测试"""
    
    @pytest.fixture
    def llm_service_mock(self):
        """LLM 服务 Mock"""
        mock = Mock(spec=LLMService)
        mock.generate.return_value = """
        【剧本】
        这是一个测试剧本...
        
        【角色】
        - 角色1：主角
        - 角色2：配角
        
        【分镜】
        分镜1：
        - 场景描述：测试场景
        - 出现角色：[角色1]
        - 对话：你好
        - 说话人：角色1
        - 情感：温柔
        """
        return mock
    
    @pytest.fixture
    def script_generator(self, llm_service_mock):
        """剧本生成服务实例"""
        return ScriptGenerator(llm_service=llm_service_mock)
    
    def test_generate_script_with_theme(self, script_generator):
        """测试：使用主题生成剧本"""
        result = script_generator.generate_script(
            theme="爱情",
            num_scenes=5,
            num_characters=2,
            style="现代都市"
        )
        
        assert result is not None
        assert "script" in result
        assert "scenes" in result
        assert "characters" in result
        assert len(result["scenes"]) > 0
    
    def test_generate_script_without_theme_and_outline(self, script_generator):
        """测试：缺少主题和大纲时抛出异常"""
        with pytest.raises(ValueError, match="主题或大纲至少提供一个"):
            script_generator.generate_script(
                theme=None,
                outline=None,
                num_scenes=5
            )
    
    def test_parse_script(self, script_generator):
        """测试：解析剧本文本"""
        script_text = """
        【分镜】
        分镜1：
        - 场景描述：测试场景
        - 出现角色：[角色1]
        - 对话：你好
        - 说话人：角色1
        """
        
        scenes = script_generator.parse_script(script_text)
        
        assert len(scenes) == 1
        assert scenes[0].description == "测试场景"
        assert scenes[0].dialogue == "你好"
        assert scenes[0].speaker == "角色1"


class TestVideoComposer:
    """视频合成服务测试"""
    
    @pytest.fixture
    def video_composer(self):
        """视频合成服务实例"""
        return VideoComposer()
    
    @patch('subprocess.run')
    def test_concat_videos(self, mock_subprocess, video_composer, tmp_path):
        """测试：拼接视频片段"""
        # 创建临时视频文件
        video1 = tmp_path / "video1.mp4"
        video2 = tmp_path / "video2.mp4"
        video1.touch()
        video2.touch()
        
        output = tmp_path / "output.mp4"
        
        # 执行拼接
        result = video_composer.concat_videos(
            [str(video1), str(video2)],
            str(output)
        )
        
        # 验证 FFmpeg 命令被调用
        mock_subprocess.assert_called_once()
        assert result == str(output)
    
    def test_calculate_timing(self, video_composer, tmp_path):
        """测试：计算音频时长"""
        # 创建临时音频文件（需要实际的音频文件或 Mock）
        audio_path = tmp_path / "audio.mp3"
        audio_path.touch()
        
        # 这里需要 Mock ffprobe 的输出
        with patch('subprocess.run') as mock_run:
            mock_run.return_value.stdout = "5.5"  # 5.5 秒
            
            duration = video_composer.calculate_timing(str(audio_path))
            
            assert duration == 5.5
```

### 集成测试

**测试范围**：
- API 端点的完整流程
- 服务之间的交互
- 数据库操作

**测试框架**：pytest + httpx

**示例测试用例**：

```python
import pytest
from httpx import AsyncClient
from main import app

@pytest.mark.asyncio
class TestProjectAPI:
    """项目 API 集成测试"""
    
    async def test_create_project_flow(self):
        """测试：完整的项目创建流程"""
        async with AsyncClient(app=app, base_url="http://test") as client:
            # 1. 创建项目
            response = await client.post("/api/projects/", json={
                "name": "测试项目",
                "theme": "爱情",
                "num_scenes": 5,
                "num_characters": 2,
                "style": "现代都市"
            })
            
            assert response.status_code == 201
            project = response.json()
            assert project["name"] == "测试项目"
            assert project["status"] == "generating"
            
            project_id = project["id"]
            
            # 2. 等待剧本生成完成（这里需要 Mock LLM 服务）
            # ...
            
            # 3. 获取项目详情
            response = await client.get(f"/api/projects/{project_id}")
            assert response.status_code == 200
            project = response.json()
            assert project["script"] is not None
            assert len(project["scenes"]) == 5
            
            # 4. 开始生产
            response = await client.post("/api/production/start", json={
                "project_id": project_id
            })
            assert response.status_code == 200
            task_data = response.json()
            assert "task_id" in task_data
            
            # 5. 查询生产状态
            task_id = task_data["task_id"]
            response = await client.get(f"/api/production/status/{task_id}")
            assert response.status_code == 200
            status = response.json()
            assert status["status"] in ["pending", "running", "completed"]
    
    async def test_create_project_without_theme(self):
        """测试：缺少主题时返回错误"""
        async with AsyncClient(app=app, base_url="http://test") as client:
            response = await client.post("/api/projects/", json={
                "name": "测试项目",
                "num_scenes": 5
            })
            
            assert response.status_code == 400
            error = response.json()
            assert error["error_code"] == "INVALID_REQUEST"
```

### 端到端测试

**测试范围**：
- 完整的短剧生产流程
- 从创建项目到导出视频

**测试策略**：
- 使用真实的 AI 服务（或 Mock）
- 验证生成的文件存在且有效
- 验证 WebSocket 进度推送

**示例测试用例**：

```python
import pytest
import asyncio
from httpx import AsyncClient
from websockets import connect

@pytest.mark.asyncio
@pytest.mark.slow
class TestEndToEnd:
    """端到端测试"""
    
    async def test_full_production_flow(self):
        """测试：完整的短剧生产流程"""
        async with AsyncClient(app=app, base_url="http://test") as client:
            # 1. 创建项目并生成剧本
            response = await client.post("/api/projects/", json={
                "name": "端到端测试项目",
                "theme": "科幻",
                "num_scenes": 3,  # 使用较少的分镜以加快测试
                "num_characters": 2,
                "style": "未来科技"
            })
            
            assert response.status_code == 201
            project = response.json()
            project_id = project["id"]
            
            # 2. 等待剧本生成完成
            for _ in range(30):  # 最多等待 30 秒
                response = await client.get(f"/api/projects/{project_id}")
                project = response.json()
                if project["status"] == "ready":
                    break
                await asyncio.sleep(1)
            
            assert project["status"] == "ready"
            assert len(project["scenes"]) == 3
            
            # 3. 开始生产并监听进度
            response = await client.post("/api/production/start", json={
                "project_id": project_id
            })
            task_data = response.json()
            task_id = task_data["task_id"]
            
            # 4. 通过 WebSocket 监听进度
            progress_updates = []
            async with connect(f"ws://test/ws/progress/{project_id}") as websocket:
                # 启动一个任务来接收进度更新
                async def receive_progress():
                    while True:
                        try:
                            message = await websocket.recv()
                            progress_updates.append(message)
                            if message["type"] == "complete":
                                break
                        except:
                            break
                
                # 等待生产完成（最多 10 分钟）
                await asyncio.wait_for(receive_progress(), timeout=600)
            
            # 5. 验证进度更新
            assert len(progress_updates) > 0
            assert any(msg["type"] == "complete" for msg in progress_updates)
            
            # 6. 验证最终视频文件
            response = await client.get(f"/api/projects/{project_id}")
            project = response.json()
            assert project["status"] == "completed"
            assert project["final_video_path"] is not None
            
            # 7. 下载并验证视频文件
            response = await client.get(f"/api/files/video/{project_id}")
            assert response.status_code == 200
            assert len(response.content) > 0
```

### 性能测试

**测试目标**：
- 验证单集短剧生产时间 < 3 小时
- 验证 API 响应时间 < 500ms
- 验证并发处理能力

**测试工具**：locust

**示例性能测试**：

```python
from locust import HttpUser, task, between

class ShortDramaUser(HttpUser):
    """短剧平台用户模拟"""
    wait_time = between(1, 3)
    
    def on_start(self):
        """初始化：创建项目"""
        response = self.client.post("/api/projects/", json={
            "name": f"性能测试项目_{self.user_id}",
            "theme": "爱情",
            "num_scenes": 10,
            "num_characters": 2
        })
        self.project_id = response.json()["id"]
    
    @task(3)
    def get_project(self):
        """任务：获取项目详情"""
        self.client.get(f"/api/projects/{self.project_id}")
    
    @task(1)
    def list_projects(self):
        """任务：列出项目列表"""
        self.client.get("/api/projects/")
    
    @task(2)
    def get_production_status(self):
        """任务：查询生产状态"""
        # 假设已有 task_id
        if hasattr(self, 'task_id'):
            self.client.get(f"/api/production/status/{self.task_id}")
```


## 性能考虑

### 性能目标

| 指标 | 目标值 | 测量方法 |
|------|--------|----------|
| 剧本生成时间 | < 1 分钟 | 从 API 调用到返回结果的时间 |
| 单张图像生成时间 | < 30 秒 | ComfyUI 生成时间 |
| 单个视频生成时间 | < 2 分钟 | SVD 生成时间 |
| 单句配音生成时间 | < 5 秒 | TTS API 调用时间 |
| 完整短剧生产时间（10 镜头） | < 2.5 小时 | 从开始生产到视频合成完成 |
| API 响应时间 | < 500ms | 非生成类 API 的响应时间 |
| WebSocket 延迟 | < 100ms | 进度更新推送延迟 |

### 性能优化策略

#### 1. LLM 推理优化

**策略**：
- 使用 GGUF 量化模型（Q4_K_M 或 Q5_K_M）减少模型大小
- CPU offload：将部分层 offload 到 CPU，释放 GPU 显存
- 批处理：如果需要生成多个剧本，使用批处理提高吞吐量
- 缓存：缓存常用的 Prompt 模板

**实现**：

```python
class LLMService:
    """LLM 服务优化版本"""
    
    def __init__(self, model_path: str, n_gpu_layers: int = 20):
        """
        初始化 LLM 服务
        
        优化配置：
        - n_gpu_layers=20: 仅加载 20 层到 GPU（约 4-6GB 显存）
        - n_threads=8: 使用 8 个 CPU 线程处理 offload 层
        - n_batch=512: 批处理大小
        """
        self.llm = Llama(
            model_path=model_path,
            n_gpu_layers=n_gpu_layers,  # GPU 层数
            n_ctx=4096,  # 上下文窗口
            n_threads=8,  # CPU 线程数
            n_batch=512,  # 批处理大小
            use_mlock=True,  # 锁定内存，避免交换
            verbose=False
        )
    
    def generate(self, prompt: str, max_tokens: int = 2048) -> str:
        """
        生成文本（优化版本）
        
        优化：
        - 使用流式生成减少首 token 延迟
        - 设置合理的 temperature 和 top_p
        """
        output = self.llm(
            prompt,
            max_tokens=max_tokens,
            temperature=0.7,
            top_p=0.9,
            stop=["【结束】"],  # 停止词
            stream=False  # 非流式生成（如需流式可改为 True）
        )
        return output["choices"][0]["text"]
```

#### 2. 图像生成优化

**策略**：
- 使用 SDXL Turbo 或 LCM 模型减少采样步数
- 降低分辨率（512x512 或 768x768）
- 批量生成：一次生成多张图像
- 使用 xFormers 或 Flash Attention 加速

**实现**：

```python
class ComfyUIService:
    """ComfyUI 服务优化版本"""
    
    def generate_image_batch(self, prompts: List[str], batch_size: int = 4) -> List[str]:
        """
        批量生成图像
        
        优化：
        - 一次生成多张图像，减少模型加载开销
        - 使用 batch_size 控制并发数量
        
        Args:
            prompts: 提示词列表
            batch_size: 批处理大小
            
        Returns:
            生成的图像路径列表
        """
        image_paths = []
        
        for i in range(0, len(prompts), batch_size):
            batch_prompts = prompts[i:i+batch_size]
            
            # 构建 ComfyUI 工作流（批量模式）
            workflow = self.build_batch_workflow(batch_prompts)
            
            # 调用 ComfyUI API
            response = requests.post(
                f"{self.base_url}/prompt",
                json={"prompt": workflow}
            )
            
            # 等待生成完成并获取结果
            batch_images = self.wait_for_completion(response.json()["prompt_id"])
            image_paths.extend(batch_images)
        
        return image_paths
```

#### 3. 视频生成优化

**策略**：
- 降低视频帧数（25 帧 -> 16 帧）
- 降低分辨率（512x512）
- 使用 FP16 精度
- 清理 GPU 缓存避免 OOM

**实现**：

```python
class SVDService:
    """SVD 服务优化版本"""
    
    def generate_video(self, image_path: str, output_path: str,
                      num_frames: int = 16, fps: int = 8) -> str:
        """
        生成视频（优化版本）
        
        优化：
        - 使用较少的帧数（16 帧）减少生成时间
        - 使用 FP16 精度减少显存占用
        - 生成前清理 GPU 缓存
        
        Args:
            image_path: 输入图像路径
            output_path: 输出视频路径
            num_frames: 视频帧数（默认 16）
            fps: 帧率（默认 8）
            
        Returns:
            生成的视频文件路径
        """
        # 清理 GPU 缓存
        clear_gpu_cache()
        
        # 加载图像
        image = Image.open(image_path)
        
        # 调用 SVD 模型（使用 FP16）
        with torch.cuda.amp.autocast(dtype=torch.float16):
            video_frames = self.model.generate(
                image=image,
                num_frames=num_frames,
                fps=fps,
                motion_bucket_id=127,
                noise_aug_strength=0.02
            )
        
        # 保存视频
        save_video(video_frames, output_path, fps=fps)
        
        return output_path
```

#### 4. 任务调度优化

**策略**：
- 并行处理：多个分镜的图像生成可以并行
- 流水线：图像生成完成后立即开始视频生成，无需等待所有图像
- 优先级队列：重要任务优先处理
- 资源池：限制并发任务数量，避免资源竞争

**实现**：

```python
from celery import group, chain, chord

def orchestrate_production_optimized(project_id: str, scenes: List[Scene]) -> str:
    """
    优化的生产任务编排
    
    优化：
    - 使用 Celery group 并行处理多个分镜的图像生成
    - 使用 chain 串联每个分镜的任务流
    - 使用 chord 在所有分镜完成后执行视频合成
    """
    
    # 为每个分镜创建任务链
    scene_chains = []
    for scene in scenes:
        # 每个分镜的任务链：图像 -> 视频 -> 配音 -> 字幕
        scene_chain = chain(
            generate_image_task.s(scene.visual_prompt),
            generate_video_task.s(),
            generate_audio_task.s(scene.dialogue, scene.speaker),
            generate_subtitle_task.s()
        )
        scene_chains.append(scene_chain)
    
    # 使用 chord 并行处理所有分镜，完成后执行视频合成
    production_workflow = chord(scene_chains)(
        compose_video_task.s(project_id)
    )
    
    return production_workflow.id
```

#### 5. 缓存策略

**策略**：
- Redis 缓存：缓存项目元数据、任务状态
- 文件缓存：缓存生成的图像、视频、音频
- LLM 输出缓存：相同 Prompt 的输出可以复用

**实现**：

```python
import redis
import hashlib
import json

class CacheService:
    """缓存服务"""
    
    def __init__(self, redis_url: str = "redis://localhost:6379"):
        self.redis = redis.from_url(redis_url)
    
    def cache_llm_output(self, prompt: str, output: str, ttl: int = 3600):
        """
        缓存 LLM 输出
        
        Args:
            prompt: 输入提示词
            output: LLM 输出
            ttl: 缓存过期时间（秒）
        """
        # 使用 Prompt 的哈希值作为 key
        key = f"llm:{hashlib.md5(prompt.encode()).hexdigest()}"
        self.redis.setex(key, ttl, output)
    
    def get_cached_llm_output(self, prompt: str) -> Optional[str]:
        """
        获取缓存的 LLM 输出
        
        Args:
            prompt: 输入提示词
            
        Returns:
            缓存的输出，不存在则返回 None
        """
        key = f"llm:{hashlib.md5(prompt.encode()).hexdigest()}"
        cached = self.redis.get(key)
        return cached.decode() if cached else None
    
    def cache_project(self, project: Project, ttl: int = 300):
        """
        缓存项目数据
        
        Args:
            project: 项目对象
            ttl: 缓存过期时间（秒）
        """
        key = f"project:{project.id}"
        self.redis.setex(key, ttl, project.json())
    
    def get_cached_project(self, project_id: str) -> Optional[Project]:
        """
        获取缓存的项目数据
        
        Args:
            project_id: 项目 ID
            
        Returns:
            项目对象，不存在则返回 None
        """
        key = f"project:{project_id}"
        cached = self.redis.get(key)
        if cached:
            return Project.parse_raw(cached)
        return None
```

### 性能监控

**监控指标**：
- API 响应时间（P50, P95, P99）
- 任务执行时间
- GPU 显存使用率
- CPU 使用率
- 磁盘 I/O
- 网络带宽

**监控工具**：
- Prometheus + Grafana：指标收集和可视化
- Celery Flower：Celery 任务监控
- nvidia-smi：GPU 监控

**实现**：

```python
from prometheus_client import Counter, Histogram, Gauge
import time

# 定义监控指标
api_request_duration = Histogram(
    'api_request_duration_seconds',
    'API 请求耗时',
    ['method', 'endpoint']
)

task_execution_duration = Histogram(
    'task_execution_duration_seconds',
    '任务执行耗时',
    ['task_type']
)

gpu_memory_usage = Gauge(
    'gpu_memory_usage_bytes',
    'GPU 显存使用量'
)

# 使用装饰器记录 API 耗时
def monitor_api_duration(endpoint: str):
    def decorator(func):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            start_time = time.time()
            try:
                return await func(*args, **kwargs)
            finally:
                duration = time.time() - start_time
                api_request_duration.labels(
                    method=func.__name__,
                    endpoint=endpoint
                ).observe(duration)
        return wrapper
    return decorator

# 使用装饰器记录任务耗时
def monitor_task_duration(task_type: str):
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            start_time = time.time()
            try:
                return func(*args, **kwargs)
            finally:
                duration = time.time() - start_time
                task_execution_duration.labels(
                    task_type=task_type
                ).observe(duration)
        return wrapper
    return decorator

# 定期更新 GPU 显存使用量
def update_gpu_metrics():
    """更新 GPU 监控指标"""
    import pynvml
    
    pynvml.nvmlInit()
    handle = pynvml.nvmlDeviceGetHandleByIndex(0)
    info = pynvml.nvmlDeviceGetMemoryInfo(handle)
    
    gpu_memory_usage.set(info.used)
    pynvml.nvmlShutdown()
```


## 安全考虑

### 数据隐私

**策略**：
- 所有剧本、分镜、生成的图像和视频均存储在本地
- 不上传到云端（除 LLM API 和 TTS API 调用外）
- 用户数据不与第三方共享

**实现**：

```python
class DataPrivacyManager:
    """数据隐私管理器"""
    
    @staticmethod
    def sanitize_llm_prompt(prompt: str) -> str:
        """
        清理 LLM Prompt 中的敏感信息
        
        Args:
            prompt: 原始 Prompt
            
        Returns:
            清理后的 Prompt
        """
        # 移除可能的个人信息（姓名、地址、电话等）
        # 这里可以使用正则表达式或 NLP 模型
        sanitized = prompt
        
        # 示例：移除电话号码
        import re
        sanitized = re.sub(r'\d{11}', '[电话]', sanitized)
        
        return sanitized
    
    @staticmethod
    def encrypt_api_key(api_key: str) -> str:
        """
        加密 API 密钥
        
        Args:
            api_key: 原始 API 密钥
            
        Returns:
            加密后的 API 密钥
        """
        from cryptography.fernet import Fernet
        
        # 使用环境变量中的加密密钥
        encryption_key = os.getenv("ENCRYPTION_KEY")
        fernet = Fernet(encryption_key)
        
        encrypted = fernet.encrypt(api_key.encode())
        return encrypted.decode()
    
    @staticmethod
    def decrypt_api_key(encrypted_key: str) -> str:
        """
        解密 API 密钥
        
        Args:
            encrypted_key: 加密的 API 密钥
            
        Returns:
            原始 API 密钥
        """
        from cryptography.fernet import Fernet
        
        encryption_key = os.getenv("ENCRYPTION_KEY")
        fernet = Fernet(encryption_key)
        
        decrypted = fernet.decrypt(encrypted_key.encode())
        return decrypted.decode()
```

### API 密钥管理

**策略**：
- API 密钥通过环境变量或配置文件管理
- 不硬编码在代码中
- 使用加密存储

**实现**：

```python
from pydantic import BaseSettings

class Settings(BaseSettings):
    """应用配置"""
    
    # LLM 配置
    llm_model_path: str
    llm_n_gpu_layers: int = 20
    
    # TTS API 配置
    tts_api_key: str
    tts_base_url: str = "https://mimo.xiaomi.com/api/v2/tts"
    
    # ComfyUI 配置
    comfyui_base_url: str = "http://127.0.0.1:8188"
    
    # SVD 配置
    svd_model_path: str
    
    # 数据库配置
    database_url: str = "sqlite:///./short_drama.db"
    
    # Redis 配置
    redis_url: str = "redis://localhost:6379"
    
    # 文件存储配置
    storage_path: str = "./storage"
    
    # 安全配置
    encryption_key: str
    jwt_secret_key: str
    
    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"

# 加载配置
settings = Settings()
```

**.env 文件示例**：

```bash
# LLM 配置
LLM_MODEL_PATH=./models/qwen2.5-14b-instruct-q4_k_m.gguf
LLM_N_GPU_LAYERS=20

# TTS API 配置
TTS_API_KEY=your_mimo_api_key_here
TTS_BASE_URL=https://mimo.xiaomi.com/api/v2/tts

# ComfyUI 配置
COMFYUI_BASE_URL=http://127.0.0.1:8188

# SVD 配置
SVD_MODEL_PATH=./models/stable-video-diffusion-img2vid-xt

# 数据库配置
DATABASE_URL=sqlite:///./short_drama.db

# Redis 配置
REDIS_URL=redis://localhost:6379

# 文件存储配置
STORAGE_PATH=./storage

# 安全配置
ENCRYPTION_KEY=your_encryption_key_here
JWT_SECRET_KEY=your_jwt_secret_key_here
```

### 访问控制

**策略**：
- Web 界面支持基本的用户认证（用户名 + 密码）
- 使用 JWT Token 进行 API 认证
- 防止未授权访问

**实现**：

```python
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from jose import JWTError, jwt
from datetime import datetime, timedelta
from passlib.context import CryptContext

# 密码加密
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# JWT 配置
security = HTTPBearer()

class AuthService:
    """认证服务"""
    
    @staticmethod
    def hash_password(password: str) -> str:
        """
        哈希密码
        
        Args:
            password: 原始密码
            
        Returns:
            哈希后的密码
        """
        return pwd_context.hash(password)
    
    @staticmethod
    def verify_password(plain_password: str, hashed_password: str) -> bool:
        """
        验证密码
        
        Args:
            plain_password: 原始密码
            hashed_password: 哈希后的密码
            
        Returns:
            密码是否匹配
        """
        return pwd_context.verify(plain_password, hashed_password)
    
    @staticmethod
    def create_access_token(data: dict, expires_delta: timedelta = timedelta(hours=24)) -> str:
        """
        创建访问令牌
        
        Args:
            data: 要编码的数据
            expires_delta: 过期时间
            
        Returns:
            JWT Token
        """
        to_encode = data.copy()
        expire = datetime.utcnow() + expires_delta
        to_encode.update({"exp": expire})
        
        encoded_jwt = jwt.encode(
            to_encode,
            settings.jwt_secret_key,
            algorithm="HS256"
        )
        return encoded_jwt
    
    @staticmethod
    def verify_token(token: str) -> dict:
        """
        验证访问令牌
        
        Args:
            token: JWT Token
            
        Returns:
            解码后的数据
            
        Raises:
            HTTPException: Token 无效或过期
        """
        try:
            payload = jwt.decode(
                token,
                settings.jwt_secret_key,
                algorithms=["HS256"]
            )
            return payload
        except JWTError:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="无效的认证凭证",
                headers={"WWW-Authenticate": "Bearer"}
            )

# 依赖注入：验证用户身份
async def get_current_user(credentials: HTTPAuthorizationCredentials = Depends(security)):
    """
    获取当前用户
    
    Args:
        credentials: HTTP 认证凭证
        
    Returns:
        用户信息
        
    Raises:
        HTTPException: 认证失败
    """
    token = credentials.credentials
    payload = AuthService.verify_token(token)
    return payload

# 使用示例
@router.get("/api/projects/", dependencies=[Depends(get_current_user)])
async def list_projects():
    """列出项目（需要认证）"""
    pass
```

### 输入验证

**策略**：
- 验证所有用户输入
- 防止 SQL 注入、XSS 攻击
- 限制文件上传大小和类型

**实现**：

```python
from pydantic import BaseModel, validator, Field
from typing import Optional

class CreateProjectRequest(BaseModel):
    """创建项目请求（带验证）"""
    
    name: str = Field(..., min_length=1, max_length=100)
    theme: Optional[str] = Field(None, max_length=500)
    outline: Optional[str] = Field(None, max_length=2000)
    num_scenes: int = Field(10, ge=1, le=50)
    num_characters: int = Field(2, ge=1, le=10)
    style: str = Field("现代都市", max_length=50)
    
    @validator('name')
    def validate_name(cls, v):
        """验证项目名称"""
        # 移除特殊字符
        import re
        if not re.match(r'^[\w\s\u4e00-\u9fa5-]+$', v):
            raise ValueError('项目名称只能包含字母、数字、中文和空格')
        return v
    
    @validator('theme', 'outline')
    def validate_text_input(cls, v):
        """验证文本输入"""
        if v:
            # 移除潜在的 XSS 攻击代码
            import html
            v = html.escape(v)
        return v
```

### 速率限制

**策略**：
- 限制 API 调用频率
- 防止滥用和 DDoS 攻击

**实现**：

```python
from fastapi import Request, HTTPException
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded

# 创建限流器
limiter = Limiter(key_func=get_remote_address)

# 注册到 FastAPI 应用
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# 使用限流装饰器
@router.post("/api/projects/")
@limiter.limit("10/minute")  # 每分钟最多 10 次请求
async def create_project(request: Request, data: CreateProjectRequest):
    """创建项目（带速率限制）"""
    pass

@router.post("/api/scripts/generate")
@limiter.limit("5/minute")  # 每分钟最多 5 次请求
async def generate_script(request: Request, data: GenerateScriptRequest):
    """生成剧本（带速率限制）"""
    pass
```


## 依赖管理

### Python 依赖

**requirements.txt**：

```txt
# Web 框架
fastapi==0.104.1
uvicorn[standard]==0.24.0
pydantic==2.5.0
pydantic-settings==2.1.0

# 任务队列
celery==5.3.4
redis==5.0.1
flower==2.0.1

# 数据库
sqlalchemy==2.0.23
alembic==1.12.1
psycopg2-binary==2.9.9  # PostgreSQL（可选）

# LLM 推理
llama-cpp-python==0.2.20

# 图像处理
Pillow==10.1.0
opencv-python==4.8.1.78

# 视频处理
ffmpeg-python==0.2.0

# AI 模型
torch==2.1.1
torchvision==0.16.1
diffusers==0.24.0
transformers==4.35.2
accelerate==0.25.0
xformers==0.0.23

# HTTP 客户端
httpx==0.25.2
requests==2.31.0

# WebSocket
websockets==12.0

# 认证和安全
python-jose[cryptography]==3.3.0
passlib[bcrypt]==1.7.4
python-multipart==0.0.6
cryptography==41.0.7

# 监控
prometheus-client==0.19.0

# 工具
python-dotenv==1.0.0
pyyaml==6.0.1
```

### 系统依赖

**Ubuntu/Debian**：

```bash
# 基础工具
sudo apt-get update
sudo apt-get install -y \
    build-essential \
    cmake \
    git \
    wget \
    curl

# Python 开发环境
sudo apt-get install -y \
    python3.10 \
    python3.10-dev \
    python3-pip

# FFmpeg
sudo apt-get install -y ffmpeg

# CUDA（如果使用 NVIDIA GPU）
# 参考：https://developer.nvidia.com/cuda-downloads

# Redis
sudo apt-get install -y redis-server
```

**Windows**：

```powershell
# 使用 Chocolatey 安装
choco install python310 -y
choco install ffmpeg -y
choco install redis-64 -y

# CUDA
# 从 NVIDIA 官网下载安装：https://developer.nvidia.com/cuda-downloads
```

### 模型下载

**Qwen2.5-14B GGUF**：

```bash
# 创建模型目录
mkdir -p models

# 下载 Q4_K_M 量化模型（推荐，约 8GB）
wget https://huggingface.co/Qwen/Qwen2.5-14B-Instruct-GGUF/resolve/main/qwen2.5-14b-instruct-q4_k_m.gguf \
    -O models/qwen2.5-14b-instruct-q4_k_m.gguf

# 或下载 Q5_K_M 量化模型（更高质量，约 10GB）
# wget https://huggingface.co/Qwen/Qwen2.5-14B-Instruct-GGUF/resolve/main/qwen2.5-14b-instruct-q5_k_m.gguf \
#     -O models/qwen2.5-14b-instruct-q5_k_m.gguf
```

**Stable Diffusion XL**：

```bash
# 使用 Hugging Face CLI 下载
pip install huggingface-hub

# 下载 SDXL Base 模型
huggingface-cli download stabilityai/stable-diffusion-xl-base-1.0 \
    --local-dir models/stable-diffusion-xl-base-1.0

# 或使用 ComfyUI 的模型管理器下载
```

**Stable Video Diffusion**：

```bash
# 下载 SVD 模型
huggingface-cli download stabilityai/stable-video-diffusion-img2vid-xt \
    --local-dir models/stable-video-diffusion-img2vid-xt
```

### 项目结构

```
ai-short-drama-production/
├── .env                          # 环境变量配置
├── .gitignore
├── README.md
├── requirements.txt              # Python 依赖
├── docker-compose.yml            # Docker 编排（可选）
├── alembic.ini                   # 数据库迁移配置
│
├── models/                       # AI 模型存储
│   ├── qwen2.5-14b-instruct-q4_k_m.gguf
│   ├── stable-diffusion-xl-base-1.0/
│   └── stable-video-diffusion-img2vid-xt/
│
├── storage/                      # 文件存储
│   ├── projects/                 # 项目文件
│   ├── images/                   # 生成的图像
│   ├── videos/                   # 生成的视频
│   └── audios/                   # 生成的音频
│
├── src/                          # 源代码
│   ├── __init__.py
│   ├── main.py                   # FastAPI 应用入口
│   ├── config.py                 # 配置管理
│   │
│   ├── api/                      # API 路由
│   │   ├── __init__.py
│   │   ├── projects.py           # 项目管理 API
│   │   ├── scripts.py            # 剧本生成 API
│   │   ├── production.py         # 生产任务 API
│   │   └── files.py              # 文件下载 API
│   │
│   ├── services/                 # 业务服务
│   │   ├── __init__.py
│   │   ├── project_manager.py    # 项目管理服务
│   │   ├── script_generator.py   # 剧本生成服务
│   │   ├── task_orchestrator.py  # 任务编排服务
│   │   ├── llm_service.py        # LLM 服务
│   │   ├── comfyui_service.py    # ComfyUI 服务
│   │   ├── svd_service.py        # SVD 服务
│   │   ├── tts_service.py        # TTS 服务
│   │   ├── subtitle_generator.py # 字幕生成服务
│   │   └── video_composer.py     # 视频合成服务
│   │
│   ├── tasks/                    # Celery 任务
│   │   ├── __init__.py
│   │   ├── celery_app.py         # Celery 应用配置
│   │   ├── image_tasks.py        # 图像生成任务
│   │   ├── video_tasks.py        # 视频生成任务
│   │   ├── audio_tasks.py        # 配音任务
│   │   └── composition_tasks.py  # 视频合成任务
│   │
│   ├── models/                   # 数据模型
│   │   ├── __init__.py
│   │   ├── project.py            # 项目模型
│   │   ├── scene.py              # 分镜模型
│   │   └── task.py               # 任务模型
│   │
│   ├── database/                 # 数据库
│   │   ├── __init__.py
│   │   ├── base.py               # 数据库基类
│   │   └── session.py            # 数据库会话
│   │
│   ├── utils/                    # 工具函数
│   │   ├── __init__.py
│   │   ├── file_utils.py         # 文件操作工具
│   │   ├── video_utils.py        # 视频处理工具
│   │   └── gpu_utils.py          # GPU 工具
│   │
│   └── websocket/                # WebSocket
│       ├── __init__.py
│       └── connection_manager.py # 连接管理器
│
├── frontend/                     # 前端代码
│   ├── package.json
│   ├── src/
│   │   ├── App.vue
│   │   ├── main.js
│   │   ├── components/           # Vue 组件
│   │   ├── views/                # 页面视图
│   │   └── api/                  # API 调用
│   └── public/
│
├── tests/                        # 测试代码
│   ├── __init__.py
│   ├── test_api/                 # API 测试
│   ├── test_services/            # 服务测试
│   └── test_tasks/               # 任务测试
│
├── scripts/                      # 脚本
│   ├── setup.sh                  # 环境设置脚本
│   ├── download_models.sh        # 模型下载脚本
│   └── start_services.sh         # 启动服务脚本
│
└── docs/                         # 文档
    ├── api.md                    # API 文档
    ├── deployment.md             # 部署文档
    └── user_guide.md             # 用户指南
```

### 部署脚本

**setup.sh**（环境设置）：

```bash
#!/bin/bash

echo "开始设置 AI 短剧自动化生产平台..."

# 1. 检查 Python 版本
python_version=$(python3 --version | cut -d' ' -f2 | cut -d'.' -f1,2)
if [ "$python_version" != "3.10" ]; then
    echo "错误：需要 Python 3.10，当前版本：$python_version"
    exit 1
fi

# 2. 创建虚拟环境
echo "创建虚拟环境..."
python3 -m venv venv
source venv/bin/activate

# 3. 安装 Python 依赖
echo "安装 Python 依赖..."
pip install --upgrade pip
pip install -r requirements.txt

# 4. 创建必要的目录
echo "创建目录结构..."
mkdir -p models storage/projects storage/images storage/videos storage/audios

# 5. 初始化数据库
echo "初始化数据库..."
alembic upgrade head

# 6. 生成加密密钥
echo "生成加密密钥..."
python -c "from cryptography.fernet import Fernet; print(f'ENCRYPTION_KEY={Fernet.generate_key().decode()}')" >> .env
python -c "import secrets; print(f'JWT_SECRET_KEY={secrets.token_urlsafe(32)}')" >> .env

echo "设置完成！"
echo "请编辑 .env 文件，填写 TTS API 密钥等配置。"
```

**start_services.sh**（启动服务）：

```bash
#!/bin/bash

echo "启动 AI 短剧自动化生产平台..."

# 1. 启动 Redis
echo "启动 Redis..."
redis-server --daemonize yes

# 2. 启动 Celery Worker
echo "启动 Celery Worker..."
celery -A src.tasks.celery_app worker --loglevel=info --concurrency=2 &

# 3. 启动 Celery Flower（监控）
echo "启动 Celery Flower..."
celery -A src.tasks.celery_app flower --port=5555 &

# 4. 启动 FastAPI 服务
echo "启动 FastAPI 服务..."
uvicorn src.main:app --host 0.0.0.0 --port 8000 --reload

echo "所有服务已启动！"
echo "FastAPI: http://localhost:8000"
echo "Celery Flower: http://localhost:5555"
```


## 部署指南

### 硬件要求

**最低配置**：
- GPU：NVIDIA RTX 3090 24GB
- CPU：8 核心（Intel i7 或 AMD Ryzen 7）
- RAM：32GB
- 存储：500GB SSD
- 操作系统：Windows 10/11 或 Ubuntu 20.04+

**推荐配置**：
- GPU：NVIDIA RTX 4090 24GB
- CPU：16 核心（Intel i9 或 AMD Ryzen 9）
- RAM：64GB
- 存储：1TB NVMe SSD
- 操作系统：Ubuntu 22.04 LTS

### 软件要求

- Python 3.10+
- CUDA 11.8+
- FFmpeg 4.4+
- Redis 6.0+
- Node.js 18+ (前端)

### 部署步骤

#### 1. 克隆仓库

```bash
git clone https://github.com/your-org/ai-short-drama-production.git
cd ai-short-drama-production
```

#### 2. 安装系统依赖

**Ubuntu**：

```bash
# 更新包列表
sudo apt-get update

# 安装基础工具
sudo apt-get install -y build-essential cmake git wget curl

# 安装 Python 3.10
sudo apt-get install -y python3.10 python3.10-dev python3-pip

# 安装 FFmpeg
sudo apt-get install -y ffmpeg

# 安装 Redis
sudo apt-get install -y redis-server
sudo systemctl enable redis-server
sudo systemctl start redis-server

# 安装 CUDA（如果尚未安装）
# 参考：https://developer.nvidia.com/cuda-downloads
```

**Windows**：

```powershell
# 使用 Chocolatey 安装
choco install python310 -y
choco install ffmpeg -y
choco install redis-64 -y

# 安装 CUDA
# 从 NVIDIA 官网下载安装：https://developer.nvidia.com/cuda-downloads
```

#### 3. 设置 Python 环境

```bash
# 创建虚拟环境
python3 -m venv venv

# 激活虚拟环境
# Linux/Mac:
source venv/bin/activate
# Windows:
# venv\Scripts\activate

# 升级 pip
pip install --upgrade pip

# 安装依赖
pip install -r requirements.txt
```

#### 4. 下载 AI 模型

```bash
# 运行模型下载脚本
bash scripts/download_models.sh

# 或手动下载：

# Qwen2.5-14B GGUF
mkdir -p models
wget https://huggingface.co/Qwen/Qwen2.5-14B-Instruct-GGUF/resolve/main/qwen2.5-14b-instruct-q4_k_m.gguf \
    -O models/qwen2.5-14b-instruct-q4_k_m.gguf

# Stable Diffusion XL
pip install huggingface-hub
huggingface-cli download stabilityai/stable-diffusion-xl-base-1.0 \
    --local-dir models/stable-diffusion-xl-base-1.0

# Stable Video Diffusion
huggingface-cli download stabilityai/stable-video-diffusion-img2vid-xt \
    --local-dir models/stable-video-diffusion-img2vid-xt
```

#### 5. 配置环境变量

```bash
# 复制环境变量模板
cp .env.example .env

# 编辑 .env 文件
nano .env
```

**.env 配置示例**：

```bash
# LLM 配置
LLM_MODEL_PATH=./models/qwen2.5-14b-instruct-q4_k_m.gguf
LLM_N_GPU_LAYERS=20

# TTS API 配置
TTS_API_KEY=your_mimo_api_key_here
TTS_BASE_URL=https://mimo.xiaomi.com/api/v2/tts

# ComfyUI 配置
COMFYUI_BASE_URL=http://127.0.0.1:8188

# SVD 配置
SVD_MODEL_PATH=./models/stable-video-diffusion-img2vid-xt

# 数据库配置
DATABASE_URL=sqlite:///./short_drama.db

# Redis 配置
REDIS_URL=redis://localhost:6379

# 文件存储配置
STORAGE_PATH=./storage

# 安全配置（自动生成）
ENCRYPTION_KEY=
JWT_SECRET_KEY=
```

#### 6. 初始化数据库

```bash
# 运行数据库迁移
alembic upgrade head
```

#### 7. 安装和配置 ComfyUI

```bash
# 克隆 ComfyUI
git clone https://github.com/comfyanonymous/ComfyUI.git
cd ComfyUI

# 安装依赖
pip install -r requirements.txt

# 启动 ComfyUI
python main.py --listen 127.0.0.1 --port 8188

# 在浏览器中访问 http://127.0.0.1:8188 验证安装
```

#### 8. 启动服务

```bash
# 方式 1：使用启动脚本
bash scripts/start_services.sh

# 方式 2：手动启动各个服务

# 启动 Redis（如果未自动启动）
redis-server --daemonize yes

# 启动 Celery Worker
celery -A src.tasks.celery_app worker --loglevel=info --concurrency=2 &

# 启动 Celery Flower（可选，用于监控）
celery -A src.tasks.celery_app flower --port=5555 &

# 启动 FastAPI 服务
uvicorn src.main:app --host 0.0.0.0 --port 8000 --reload
```

#### 9. 启动前端（可选）

```bash
cd frontend

# 安装依赖
npm install

# 启动开发服务器
npm run dev

# 或构建生产版本
npm run build
```

#### 10. 验证部署

```bash
# 检查 FastAPI 服务
curl http://localhost:8000/health

# 检查 Celery Worker
celery -A src.tasks.celery_app inspect active

# 检查 Redis
redis-cli ping

# 检查 ComfyUI
curl http://127.0.0.1:8188/system_stats
```

### Docker 部署（可选）

**docker-compose.yml**：

```yaml
version: '3.8'

services:
  redis:
    image: redis:7-alpine
    ports:
      - "6379:6379"
    volumes:
      - redis_data:/data
    command: redis-server --appendonly yes

  postgres:
    image: postgres:15-alpine
    environment:
      POSTGRES_USER: shortdrama
      POSTGRES_PASSWORD: shortdrama
      POSTGRES_DB: shortdrama
    ports:
      - "5432:5432"
    volumes:
      - postgres_data:/var/lib/postgresql/data

  backend:
    build:
      context: .
      dockerfile: Dockerfile
    ports:
      - "8000:8000"
    environment:
      - DATABASE_URL=postgresql://shortdrama:shortdrama@postgres:5432/shortdrama
      - REDIS_URL=redis://redis:6379
    volumes:
      - ./storage:/app/storage
      - ./models:/app/models
    depends_on:
      - redis
      - postgres
    command: uvicorn src.main:app --host 0.0.0.0 --port 8000

  celery_worker:
    build:
      context: .
      dockerfile: Dockerfile
    environment:
      - DATABASE_URL=postgresql://shortdrama:shortdrama@postgres:5432/shortdrama
      - REDIS_URL=redis://redis:6379
    volumes:
      - ./storage:/app/storage
      - ./models:/app/models
    depends_on:
      - redis
      - postgres
    command: celery -A src.tasks.celery_app worker --loglevel=info --concurrency=2
    deploy:
      resources:
        reservations:
          devices:
            - driver: nvidia
              count: 1
              capabilities: [gpu]

  flower:
    build:
      context: .
      dockerfile: Dockerfile
    ports:
      - "5555:5555"
    environment:
      - REDIS_URL=redis://redis:6379
    depends_on:
      - redis
    command: celery -A src.tasks.celery_app flower --port=5555

volumes:
  redis_data:
  postgres_data:
```

**Dockerfile**：

```dockerfile
FROM nvidia/cuda:11.8.0-cudnn8-runtime-ubuntu22.04

# 设置工作目录
WORKDIR /app

# 安装系统依赖
RUN apt-get update && apt-get install -y \
    python3.10 \
    python3-pip \
    ffmpeg \
    git \
    && rm -rf /var/lib/apt/lists/*

# 复制依赖文件
COPY requirements.txt .

# 安装 Python 依赖
RUN pip3 install --no-cache-dir -r requirements.txt

# 复制应用代码
COPY . .

# 暴露端口
EXPOSE 8000

# 默认命令
CMD ["uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

**启动 Docker 服务**：

```bash
# 构建镜像
docker-compose build

# 启动服务
docker-compose up -d

# 查看日志
docker-compose logs -f

# 停止服务
docker-compose down
```

### 生产环境优化

#### 1. 使用 Gunicorn + Uvicorn

```bash
# 安装 Gunicorn
pip install gunicorn

# 启动服务（4 个 worker）
gunicorn src.main:app \
    --workers 4 \
    --worker-class uvicorn.workers.UvicornWorker \
    --bind 0.0.0.0:8000 \
    --timeout 300
```

#### 2. 配置 Nginx 反向代理

**/etc/nginx/sites-available/shortdrama**：

```nginx
upstream backend {
    server 127.0.0.1:8000;
}

server {
    listen 80;
    server_name your-domain.com;

    client_max_body_size 100M;

    location / {
        proxy_pass http://backend;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }

    location /ws/ {
        proxy_pass http://backend;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }

    location /static/ {
        alias /path/to/frontend/dist/;
    }
}
```

#### 3. 配置 Systemd 服务

**/etc/systemd/system/shortdrama-backend.service**：

```ini
[Unit]
Description=Short Drama Production Backend
After=network.target

[Service]
Type=notify
User=www-data
Group=www-data
WorkingDirectory=/path/to/ai-short-drama-production
Environment="PATH=/path/to/venv/bin"
ExecStart=/path/to/venv/bin/gunicorn src.main:app \
    --workers 4 \
    --worker-class uvicorn.workers.UvicornWorker \
    --bind 0.0.0.0:8000 \
    --timeout 300
Restart=always

[Install]
WantedBy=multi-user.target
```

**/etc/systemd/system/shortdrama-celery.service**：

```ini
[Unit]
Description=Short Drama Production Celery Worker
After=network.target redis.service

[Service]
Type=forking
User=www-data
Group=www-data
WorkingDirectory=/path/to/ai-short-drama-production
Environment="PATH=/path/to/venv/bin"
ExecStart=/path/to/venv/bin/celery -A src.tasks.celery_app worker \
    --loglevel=info \
    --concurrency=2 \
    --detach
Restart=always

[Install]
WantedBy=multi-user.target
```

**启动服务**：

```bash
# 重新加载 systemd
sudo systemctl daemon-reload

# 启动服务
sudo systemctl start shortdrama-backend
sudo systemctl start shortdrama-celery

# 设置开机自启
sudo systemctl enable shortdrama-backend
sudo systemctl enable shortdrama-celery

# 查看状态
sudo systemctl status shortdrama-backend
sudo systemctl status shortdrama-celery
```

### 监控和日志

#### 1. 配置日志

**logging_config.py**：

```python
import logging
from logging.handlers import RotatingFileHandler
import os

def setup_logging():
    """配置日志"""
    
    # 创建日志目录
    os.makedirs("logs", exist_ok=True)
    
    # 配置根日志记录器
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=[
            # 控制台输出
            logging.StreamHandler(),
            # 文件输出（自动轮转）
            RotatingFileHandler(
                "logs/app.log",
                maxBytes=10*1024*1024,  # 10MB
                backupCount=5
            )
        ]
    )
    
    # 配置特定模块的日志级别
    logging.getLogger("uvicorn").setLevel(logging.INFO)
    logging.getLogger("celery").setLevel(logging.INFO)
    logging.getLogger("sqlalchemy").setLevel(logging.WARNING)
```

#### 2. 配置 Prometheus 监控

```python
from prometheus_client import make_asgi_app

# 在 FastAPI 应用中挂载 Prometheus 端点
metrics_app = make_asgi_app()
app.mount("/metrics", metrics_app)
```

#### 3. 配置 Grafana 仪表板

- 导入 Prometheus 数据源
- 创建仪表板监控关键指标：
  - API 请求量和响应时间
  - Celery 任务执行情况
  - GPU 显存使用率
  - 系统资源使用情况

### 故障排查

#### 常见问题

**1. LLM 服务启动失败**

```bash
# 检查模型文件是否存在
ls -lh models/qwen2.5-14b-instruct-q4_k_m.gguf

# 检查 GPU 显存
nvidia-smi

# 检查日志
tail -f logs/app.log
```

**2. ComfyUI 连接失败**

```bash
# 检查 ComfyUI 是否运行
curl http://127.0.0.1:8188/system_stats

# 重启 ComfyUI
cd ComfyUI
python main.py --listen 127.0.0.1 --port 8188
```

**3. Celery 任务不执行**

```bash
# 检查 Redis 连接
redis-cli ping

# 检查 Celery Worker 状态
celery -A src.tasks.celery_app inspect active

# 重启 Celery Worker
celery -A src.tasks.celery_app worker --loglevel=info --concurrency=2
```

**4. GPU 显存不足**

```bash
# 清理 GPU 缓存
python -c "import torch; torch.cuda.empty_cache()"

# 降低 LLM GPU 层数
# 编辑 .env 文件：LLM_N_GPU_LAYERS=10

# 重启服务
```


## 总结

### 设计亮点

1. **端到端自动化**：从创意想法到完整短剧视频的全流程自动化，大幅降低制作门槛和时间成本

2. **模块化架构**：各个 AI 服务独立封装，支持独立升级和替换，便于后续扩展和优化

3. **显存优化**：LLM 使用 CPU offload 技术，在单张 RTX 4090/3090 24GB 显卡上可同时运行 SD + SVD，降低硬件成本

4. **异步任务处理**：使用 Celery + Redis 实现异步任务队列，支持并行处理和任务重试，提高系统吞吐量

5. **实时进度更新**：通过 WebSocket 推送任务进度，提供流畅的用户体验

6. **完善的错误处理**：自动重试、错误通知、详细日志，确保系统稳定性

7. **性能优化**：批量生成、缓存策略、资源池管理，确保高效的生产流程

8. **安全设计**：数据隐私保护、API 密钥加密、访问控制、速率限制，保障系统安全

### 技术选型理由

| 技术 | 选型理由 |
|------|----------|
| **Qwen2.5-14B + llama.cpp** | 开源免费，支持 CPU offload，降低显存占用，适合本地部署 |
| **Stable Diffusion XL** | 开源免费，图像质量高，社区活跃，模型丰富 |
| **Stable Video Diffusion** | 开源免费，图生视频效果好，与 SD 生态兼容 |
| **MiMo-V2-TTS** | 支持多情感、多风格配音，API 调用简单，质量高 |
| **FastAPI** | 高性能异步框架，自动生成 API 文档，开发效率高 |
| **Celery + Redis** | 成熟的异步任务队列方案，支持分布式部署，可靠性高 |
| **FFmpeg** | 功能强大的视频处理工具，支持各种格式和操作 |
| **SQLite/PostgreSQL** | SQLite 适合单机部署，PostgreSQL 适合生产环境 |

### 未来扩展方向

1. **角色一致性优化**：
   - 使用 LoRA 或 DreamBooth 训练角色模型
   - 确保同一角色在不同镜头中保持视觉一致性

2. **多语言支持**：
   - 支持英文、日文等多语言剧本生成
   - 支持多语言配音和字幕

3. **高级视频编辑**：
   - 支持转场动画、特效、色彩调整
   - 提供可视化的视频编辑器

4. **云端部署**：
   - 提供 SaaS 服务
   - 支持多用户协作

5. **批量生产**：
   - 支持一次提交多个短剧项目
   - 自动调度和资源分配

6. **质量评估**：
   - AI 自动评估剧本质量
   - 提供改进建议

7. **模型升级**：
   - 升级到 Qwen2.5-72B 提高剧本质量
   - 使用 SDXL Turbo 或 LCM 加速图像生成
   - 探索更先进的视频生成模型

### 风险与挑战

| 风险 | 影响 | 缓解措施 |
|------|------|----------|
| **LLM 生成质量不稳定** | 高 | 优化 Prompt 工程；提供重新生成选项；支持手动编辑 |
| **GPU 显存不足** | 中 | 优化 offload 配置；降低生成参数；提供硬件升级建议 |
| **AI 服务生成失败** | 高 | 自动重试机制；详细错误日志；支持手动重试 |
| **TTS API 配额限制** | 中 | 提前申请足够配额；实现降级方案；缓存已生成音频 |
| **视频合成同步问题** | 中 | 使用 FFmpeg 精确对齐；提供手动调整选项 |
| **用户学习成本** | 低 | 提供详细文档和教程；设计直观的 UI 界面 |

### 性能基准

基于推荐硬件配置（RTX 4090 24GB + 16 核 CPU + 64GB RAM）的预期性能：

| 任务 | 预期时间 |
|------|----------|
| 剧本生成（10 镜头） | 30-60 秒 |
| 单张图像生成 | 20-30 秒 |
| 单个视频生成（16 帧） | 1-2 分钟 |
| 单句配音生成 | 3-5 秒 |
| 字幕生成 | 5-10 秒 |
| 视频合成（10 镜头） | 3-5 分钟 |
| **完整短剧生产（10 镜头）** | **1.5-2.5 小时** |

### 成本估算

**硬件成本**（一次性）：
- RTX 4090 24GB：约 ¥12,000-15,000
- 16 核 CPU + 64GB RAM + 1TB SSD：约 ¥8,000-10,000
- **总计：约 ¥20,000-25,000**

**运营成本**（每月）：
- 电费（24/7 运行）：约 ¥500-800
- MiMo-V2-TTS API 费用：根据使用量，约 ¥100-500
- **总计：约 ¥600-1,300/月**

**单集短剧成本**（10 镜头）：
- 电费：约 ¥2-3
- TTS API 费用：约 ¥5-10
- **总计：约 ¥7-13/集**

相比传统制作方式（人工成本 ¥1,000-5,000/集），成本降低 **99%** 以上。

## 附录

### 术语表

| 术语 | 定义 |
|------|------|
| **LLM** | Large Language Model，大语言模型 |
| **GGUF** | GPT-Generated Unified Format，一种量化模型格式 |
| **Offload** | 将部分计算任务从 GPU 转移到 CPU |
| **SD** | Stable Diffusion，文生图模型 |
| **SDXL** | Stable Diffusion XL，SD 的升级版本 |
| **SVD** | Stable Video Diffusion，图生视频模型 |
| **TTS** | Text-to-Speech，文本转语音 |
| **ComfyUI** | 一个用于构建和运行 SD 工作流的开源工具 |
| **Celery** | Python 分布式任务队列框架 |
| **Redis** | 内存数据库，常用于缓存和消息队列 |
| **FFmpeg** | 开源的音视频处理工具 |
| **WebSocket** | 全双工通信协议，用于实时数据推送 |
| **JWT** | JSON Web Token，用于身份认证 |
| **OOM** | Out of Memory，内存不足错误 |

### 参考资料

**AI 模型**：
- Qwen2.5-14B：https://huggingface.co/Qwen/Qwen2.5-14B-Instruct-GGUF
- llama.cpp：https://github.com/ggerganov/llama.cpp
- llama-cpp-python：https://github.com/abetlen/llama-cpp-python
- Stable Diffusion XL：https://huggingface.co/stabilityai/stable-diffusion-xl-base-1.0
- Stable Video Diffusion：https://huggingface.co/stabilityai/stable-video-diffusion-img2vid-xt
- ComfyUI：https://github.com/comfyanonymous/ComfyUI
- MiMo-V2-TTS：https://mimo.xiaomi.com/mimo-v2-tts

**框架和工具**：
- FastAPI：https://fastapi.tiangolo.com/
- Celery：https://docs.celeryq.dev/
- Redis：https://redis.io/documentation
- FFmpeg：https://ffmpeg.org/documentation.html
- PyTorch：https://pytorch.org/docs/
- Diffusers：https://huggingface.co/docs/diffusers/

**部署和运维**：
- Docker：https://docs.docker.com/
- Nginx：https://nginx.org/en/docs/
- Systemd：https://www.freedesktop.org/software/systemd/man/
- Prometheus：https://prometheus.io/docs/
- Grafana：https://grafana.com/docs/

### 常见问题 (FAQ)

**Q1: 为什么选择 Qwen2.5-14B 而不是 GPT-4？**

A: Qwen2.5-14B 是开源模型，可以本地部署，无需支付 API 费用，数据隐私更有保障。虽然质量略低于 GPT-4，但对于短剧剧本生成已经足够，且支持 CPU offload，降低硬件成本。

**Q2: 单张 RTX 4090 24GB 显卡够用吗？**

A: 够用。通过 LLM CPU offload（仅加载 20 层到 GPU，约 4-6GB），为 SD 和 SVD 预留约 18-20GB 显存。SD 和 SVD 不同时运行，通过任务调度错开，可以在单卡上流畅运行。

**Q3: 生产一集短剧需要多长时间？**

A: 基于推荐硬件配置，10 个镜头的短剧约需 1.5-2.5 小时。其中剧本生成 1 分钟，每个镜头生成 2-3 分钟（图像 + 视频 + 配音），视频合成 3-5 分钟。

**Q4: 可以使用其他 LLM 模型吗？**

A: 可以。只需修改 LLMService 的实现，支持其他模型（如 Llama 3、Mistral、ChatGLM 等）。如果使用 API 服务（如 GPT-4、Claude），需要修改调用逻辑。

**Q5: 可以使用其他 TTS 服务吗？**

A: 可以。只需修改 TTSService 的实现，支持其他 TTS 服务（如 Azure TTS、Google TTS、本地 TTS 模型等）。

**Q6: 如何提高剧本生成质量？**

A: 
1. 优化 Prompt 工程，提供更详细的指令和示例
2. 升级到更大的模型（如 Qwen2.5-72B）
3. 使用 Few-shot Learning，提供优质剧本示例
4. 支持用户手动编辑和调整

**Q7: 如何保证角色在不同镜头中的一致性？**

A: 当前版本通过提示词控制角色描述的一致性。未来版本可以使用 LoRA 或 DreamBooth 训练角色模型，确保视觉一致性。

**Q8: 可以批量生产多个短剧吗？**

A: 当前版本支持串行生产。未来版本将支持批量提交和并行处理，通过任务队列自动调度。

**Q9: 如何监控系统运行状态？**

A: 
1. 使用 Celery Flower 监控任务队列：http://localhost:5555
2. 使用 Prometheus + Grafana 监控系统指标
3. 查看日志文件：logs/app.log

**Q10: 遇到问题如何排查？**

A: 
1. 查看日志文件：logs/app.log
2. 检查各个服务状态（Redis、ComfyUI、Celery）
3. 使用 nvidia-smi 检查 GPU 状态
4. 参考"故障排查"章节的常见问题解决方案

---

**文档版本**：1.0  
**最后更新**：2024-01-15  
**作者**：AI 短剧自动化生产平台开发团队

