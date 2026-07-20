"""
数据库模型定义

定义所有数据库表的 ORM 模型
"""
from datetime import datetime
from enum import Enum
from typing import Optional

from sqlalchemy import (
    Column,
    Integer,
    String,
    Text,
    DateTime,
    ForeignKey,
    Enum as SQLEnum,
    Float,
)
from sqlalchemy.orm import relationship, declarative_base

Base = declarative_base()


class ProjectStatus(str, Enum):
    """项目状态枚举"""
    DRAFT = "draft"  # 草稿
    SCRIPT_GENERATED = "script_generated"  # 剧本已生成
    IN_PRODUCTION = "in_production"  # 生产中
    COMPLETED = "completed"  # 已完成
    FAILED = "failed"  # 失败


class TaskStatus(str, Enum):
    """任务状态枚举"""
    PENDING = "pending"  # 等待中
    RUNNING = "running"  # 运行中
    COMPLETED = "completed"  # 已完成
    FAILED = "failed"  # 失败
    CANCELLED = "cancelled"  # 已取消


class LocalizationJobStatus(str, Enum):
    """源片出海译制任务状态"""
    DRAFT = "draft"
    QUEUED = "queued"
    RUNNING = "running"
    NEEDS_REVIEW = "needs_review"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class LocalizationStage(str, Enum):
    """源片出海译制任务阶段"""
    UPLOADED = "uploaded"
    PREPROCESSING = "preprocessing"
    CLEANING = "cleaning"
    ASR = "asr"
    TRANSLATION = "translation"
    RENDERING = "rendering"
    MODERATION = "moderation"
    COMPLETED = "completed"


class User(Base):
    """用户模型"""
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String(50), unique=True, nullable=False, index=True)
    email = Column(String(100), unique=True, nullable=False, index=True)
    hashed_password = Column(String(255), nullable=False)
    is_active = Column(Integer, default=1)  # 1=激活, 0=禁用
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    # 关系
    projects = relationship("Project", back_populates="user", cascade="all, delete-orphan")


class Project(Base):
    """项目模型"""
    __tablename__ = "projects"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(200), nullable=False)
    description = Column(Text, nullable=True)
    theme = Column(Text, nullable=True)
    outline = Column(Text, nullable=True)
    script = Column(Text, nullable=True)
    final_video_path = Column(String(500), nullable=True)
    status = Column(SQLEnum(ProjectStatus), default=ProjectStatus.DRAFT, nullable=False, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    completed_at = Column(DateTime, nullable=True)

    # 关系
    user = relationship("User", back_populates="projects")
    characters = relationship("Character", back_populates="project", cascade="all, delete-orphan")
    scenes = relationship("Scene", back_populates="project", cascade="all, delete-orphan")
    tasks = relationship("Task", back_populates="project", cascade="all, delete-orphan")
    source_videos = relationship("SourceVideo", back_populates="project", cascade="all, delete-orphan")


class Character(Base):
    """角色模型"""
    __tablename__ = "characters"

    id = Column(Integer, primary_key=True, index=True)
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=False, index=True)
    name = Column(String(100), nullable=False)
    description = Column(Text, nullable=True)
    personality = Column(String(200), nullable=True)  # 角色性格
    appearance = Column(String(500), nullable=True)   # 角色外貌
    visual_description = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    # 关系
    project = relationship("Project", back_populates="characters")


class Scene(Base):
    """分镜模型"""
    __tablename__ = "scenes"

    id = Column(Integer, primary_key=True, index=True)
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=False, index=True)
    scene_number = Column(Integer, nullable=False)
    character_name = Column(String(100), nullable=True)  # 允许为空，某些分镜可能没有角色
    dialogue = Column(Text, nullable=True)  # 允许为空，某些分镜可能没有对话
    visual_description = Column(Text, nullable=False)
    image_prompt = Column(Text, nullable=True)
    image_path = Column(String(500), nullable=True)
    video_path = Column(String(500), nullable=True)
    audio_path = Column(String(500), nullable=True)
    audio_duration = Column(Float, nullable=True)
    subtitle_path = Column(String(500), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    # 关系
    project = relationship("Project", back_populates="scenes")


class Task(Base):
    """任务模型"""
    __tablename__ = "tasks"

    id = Column(Integer, primary_key=True, index=True)
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=False, index=True)
    celery_task_id = Column(String(100), unique=True, nullable=False, index=True)
    status = Column(SQLEnum(TaskStatus), default=TaskStatus.PENDING, nullable=False, index=True)
    progress = Column(Float, default=0.0, nullable=False)
    total_steps = Column(Integer, nullable=False)
    current_step = Column(Integer, default=0, nullable=False)
    error_message = Column(Text, nullable=True)
    retry_count = Column(Integer, default=0, nullable=False)
    result_path = Column(String(500), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    # 关系
    project = relationship("Project", back_populates="tasks")


class SourceVideo(Base):
    """用户上传的中文源片"""
    __tablename__ = "source_videos"

    id = Column(Integer, primary_key=True, index=True)
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=False, index=True)
    original_filename = Column(String(255), nullable=False)
    file_path = Column(String(500), nullable=False)
    clean_video_path = Column(String(500), nullable=True)
    duration = Column(Float, nullable=True)
    width = Column(Integer, nullable=True)
    height = Column(Integer, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)

    project = relationship("Project", back_populates="source_videos")
    localization_jobs = relationship("LocalizationJob", back_populates="source_video", cascade="all, delete-orphan")


class LocalizationJob(Base):
    """中文源片出海译制任务"""
    __tablename__ = "localization_jobs"

    id = Column(Integer, primary_key=True, index=True)
    source_video_id = Column(Integer, ForeignKey("source_videos.id"), nullable=False, index=True)
    celery_task_id = Column(String(100), nullable=True, index=True)
    target_languages = Column(Text, nullable=False)
    status = Column(SQLEnum(LocalizationJobStatus), default=LocalizationJobStatus.DRAFT, nullable=False, index=True)
    current_stage = Column(SQLEnum(LocalizationStage), default=LocalizationStage.UPLOADED, nullable=False)
    progress = Column(Float, default=0.0, nullable=False)
    transcript_path = Column(String(500), nullable=True)
    translated_subtitle_dir = Column(String(500), nullable=True)
    rendered_video_dir = Column(String(500), nullable=True)
    moderation_report_path = Column(String(500), nullable=True)
    error_message = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    source_video = relationship("SourceVideo", back_populates="localization_jobs")
