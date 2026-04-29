"""
API 请求和响应模型

使用 Pydantic 定义 API 的请求和响应数据结构
"""

from typing import Optional, List
from datetime import datetime
from pydantic import BaseModel, Field, field_validator


# ==================== 项目相关模型 ====================

class ProjectCreate(BaseModel):
    """
    创建项目请求模型
    """
    name: str = Field(..., min_length=1, max_length=100, description="项目名称")
    description: Optional[str] = Field(None, max_length=500, description="项目描述")
    theme: Optional[str] = Field(None, max_length=200, description="剧本主题")
    outline: Optional[str] = Field(None, max_length=1000, description="剧本大纲")
    
    @field_validator("name")
    @classmethod
    def validate_name(cls, v: str) -> str:
        """
        验证项目名称
        
        不允许包含特殊字符
        """
        if not v.strip():
            raise ValueError("项目名称不能为空")
        
        # 检查是否包含非法字符
        invalid_chars = ['/', '\\', ':', '*', '?', '"', '<', '>', '|']
        for char in invalid_chars:
            if char in v:
                raise ValueError(f"项目名称不能包含字符: {char}")
        
        return v.strip()


class ProjectUpdate(BaseModel):
    """
    更新项目请求模型
    """
    name: Optional[str] = Field(None, min_length=1, max_length=100, description="项目名称")
    description: Optional[str] = Field(None, max_length=500, description="项目描述")
    theme: Optional[str] = Field(None, max_length=200, description="剧本主题")
    outline: Optional[str] = Field(None, max_length=1000, description="剧本大纲")
    status: Optional[str] = Field(None, description="项目状态")
    
    @field_validator("name")
    @classmethod
    def validate_name(cls, v: Optional[str]) -> Optional[str]:
        """
        验证项目名称
        """
        if v is None:
            return None
        
        if not v.strip():
            raise ValueError("项目名称不能为空")
        
        # 检查是否包含非法字符
        invalid_chars = ['/', '\\', ':', '*', '?', '"', '<', '>', '|']
        for char in invalid_chars:
            if char in v:
                raise ValueError(f"项目名称不能包含字符: {char}")
        
        return v.strip()


class CharacterResponse(BaseModel):
    """
    角色响应模型
    """
    model_config = {"from_attributes": True}
    
    id: int
    name: str
    description: Optional[str] = None


class SceneResponse(BaseModel):
    """
    分镜响应模型
    """
    model_config = {"from_attributes": True}
    
    id: int
    scene_number: int
    location: str
    time_period: str
    characters: str
    dialogue: str
    visual_description: str
    duration: Optional[float] = None
    image_path: Optional[str] = None
    video_path: Optional[str] = None
    audio_path: Optional[str] = None


class ProjectResponse(BaseModel):
    """
    项目响应模型
    """
    model_config = {"from_attributes": True}
    
    id: int
    name: str
    description: Optional[str] = None
    theme: Optional[str] = None
    outline: Optional[str] = None
    status: str
    created_at: datetime
    updated_at: datetime
    characters: List[CharacterResponse] = []
    scenes: List[SceneResponse] = []


class ProjectListResponse(BaseModel):
    """
    项目列表响应模型
    """
    total: int
    page: int
    page_size: int
    projects: List[ProjectResponse]


# ==================== 剧本生成相关模型 ====================

class GenerateScriptRequest(BaseModel):
    """
    生成剧本请求模型
    """
    theme: Optional[str] = Field(None, max_length=200, description="剧本主题")
    outline: Optional[str] = Field(None, max_length=1000, description="剧本大纲")
    
    @field_validator("theme", "outline")
    @classmethod
    def validate_not_both_empty(cls, v: Optional[str], info) -> Optional[str]:
        """
        验证主题和大纲至少有一个非空
        """
        # 这个验证会在 model_validator 中处理
        return v
    
    @classmethod
    def model_validate(cls, obj):
        """
        模型级别验证
        """
        instance = super().model_validate(obj)
        
        # 检查主题和大纲至少有一个非空
        theme = instance.theme
        outline = instance.outline
        
        if (not theme or not theme.strip()) and (not outline or not outline.strip()):
            raise ValueError("主题和大纲至少需要提供一个")
        
        return instance


class RegenerateSceneRequest(BaseModel):
    """
    重新生成分镜请求模型
    """
    scene_number: int = Field(..., ge=1, description="分镜编号")


# ==================== 任务相关模型 ====================

class ProductionTaskResponse(BaseModel):
    """
    生产任务响应模型
    """
    task_id: str
    project_id: int
    status: str
    progress: float
    current_step: str
    total_steps: int
    created_at: datetime
    updated_at: datetime
    error_message: Optional[str] = None


class TaskStatusResponse(BaseModel):
    """
    任务状态响应模型
    """
    task_id: str
    status: str
    progress: float
    current_step: str
    result: Optional[dict] = None
    error: Optional[str] = None


# ==================== 通用响应模型 ====================

class MessageResponse(BaseModel):
    """
    通用消息响应模型
    """
    message: str
    detail: Optional[str] = None


class ErrorResponse(BaseModel):
    """
    错误响应模型
    """
    error: str
    detail: str
    path: str
