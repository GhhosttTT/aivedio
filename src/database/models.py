"""
数据库 ORM 模型定义
定义了 AI 短剧自动化生产平台的所有数据库表结构
"""

from datetime import datetime
from enum import Enum as PyEnum
from typing import Optional, List
from sqlalchemy import (
    Column, Integer, String, Text, DateTime, ForeignKey,
    Enum, Boolean, Float, JSON, Index
)
from sqlalchemy.orm import relationship, declarative_base
from sqlalchemy.sql import func

Base = declarative_base()


class ProjectStatus(PyEnum):
    """项目状态枚举"""
    DRAFT = "draft"  # 草稿
    SCRIPT_GENERATED = "script_generated"  # 剧本已生成
    IN_PRODUCTION = "in_production"  # 生产中
    COMPLETED = "completed"  # 已完成
    FAILED = "failed"  # 失败
    CANCELLED = "cancelled"  # 已取消


class TaskStatus(PyEnum):
    """任务状态枚举"""
    PENDING = "pending"  # 等待中
    RUNNING = "running"  # 运行中
    COMPLETED = "completed"  # 已完成
    FAILED = "failed"  # 失败
    CANCELLED = "cancelled"  # 已取消


class TaskType(PyEnum):
    """任务类型枚举"""
    IMAGE_GENERATION = "image_generation"  # 图像生成
    VIDEO_GENERATION = "video_generation"  # 视频生成
    AUDIO_GENERATION = "audio_generation"  # 音频生成
    SUBTITLE_GENERATION = "subtitle_generation"  # 字幕生成
    VIDEO_COMPOSITION = "video_composition"  # 视频合成


class Project(Base):
    """
    项目表
    存储短剧项目的基本信息
    """
    __tablename__ = "projects"

    # 主键
    id = Column(Integer, primary_key=True, index=True, comment="项目ID")
    
    # 基本信息
    name = Column(String(255), nullable=False, comment="项目名称")
    description = Column(Text, nullable=True, comment="项目描述")
    theme = Column(String(500), nullable=True, comment="剧本主题")
    outline = Column(Text, nullable=True, comment="剧本大纲")
    
    # 状态信息
    status = Column(
        Enum(ProjectStatus),
        nullable=False,
        default=ProjectStatus.DRAFT,
        comment="项目状态"
    )
    
    # 剧本信息
    script = Column(JSON, nullable=True, comment="生成的剧本（JSON格式）")
    total_scenes = Column(Integer, default=0, comment="总分镜数")
    
    # 文件路径
    storage_path = Column(String(500), nullable=True, comment="文件存储路径")
    final_video_path = Column(String(500), nullable=True, comment="最终视频路径")
    
    # 时间戳
    created_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
        comment="创建时间"
    )
    updated_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
        comment="更新时间"
    )
    completed_at = Column(
        DateTime(timezone=True),
        nullable=True,
        comment="完成时间"
    )
    
    # 关系
    characters = relationship(
        "Character",
        back_populates="project",
        cascade="all, delete-orphan"
    )
    scenes = relationship(
        "Scene",
        back_populates="project",
        cascade="all, delete-orphan",
        order_by="Scene.scene_number"
    )
    tasks = relationship(
        "Task",
        back_populates="project",
        cascade="all, delete-orphan"
    )
    
    # 索引
    __table_args__ = (
        Index("idx_project_status", "status"),
        Index("idx_project_created_at", "created_at"),
        Index("idx_project_name", "name"),
    )
    
    def __repr__(self):
        return f"<Project(id={self.id}, name='{self.name}', status='{self.status.value}')>"


class Character(Base):
    """
    角色表
    存储短剧中的角色信息
    """
    __tablename__ = "characters"
    
    # 主键
    id = Column(Integer, primary_key=True, index=True, comment="角色ID")
    
    # 外键
    project_id = Column(
        Integer,
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
        comment="所属项目ID"
    )
    
    # 角色信息
    name = Column(String(100), nullable=False, comment="角色名称")
    description = Column(Text, nullable=True, comment="角色描述")
    appearance = Column(Text, nullable=True, comment="外貌特征")
    personality = Column(Text, nullable=True, comment="性格特点")
    
    # 配音设置
    voice_speaker = Column(String(100), nullable=True, comment="配音说话人")
    voice_emotion = Column(String(50), nullable=True, comment="配音情感")
    
    # 时间戳
    created_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
        comment="创建时间"
    )
    updated_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
        comment="更新时间"
    )
    
    # 关系
    project = relationship("Project", back_populates="characters")
    
    # 索引
    __table_args__ = (
        Index("idx_character_project_id", "project_id"),
        Index("idx_character_name", "name"),
    )
    
    def __repr__(self):
        return f"<Character(id={self.id}, name='{self.name}', project_id={self.project_id})>"


class Scene(Base):
    """
    分镜表
    存储短剧的分镜信息
    """
    __tablename__ = "scenes"
    
    # 主键
    id = Column(Integer, primary_key=True, index=True, comment="分镜ID")
    
    # 外键
    project_id = Column(
        Integer,
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
        comment="所属项目ID"
    )
    
    # 分镜信息
    scene_number = Column(Integer, nullable=False, comment="分镜序号")
    title = Column(String(255), nullable=True, comment="分镜标题")
    description = Column(Text, nullable=False, comment="场景描述")
    dialogue = Column(Text, nullable=True, comment="对话内容")
    character_name = Column(String(100), nullable=True, comment="说话角色")
    
    # 视觉提示词
    visual_prompt = Column(Text, nullable=True, comment="图像生成提示词")
    negative_prompt = Column(Text, nullable=True, comment="负面提示词")
    
    # 生成的文件路径
    image_path = Column(String(500), nullable=True, comment="生成的图像路径")
    video_path = Column(String(500), nullable=True, comment="生成的视频路径")
    audio_path = Column(String(500), nullable=True, comment="生成的音频路径")
    subtitle_path = Column(String(500), nullable=True, comment="字幕文件路径")
    
    # 时长信息（秒）
    duration = Column(Float, nullable=True, comment="分镜时长（秒）")
    audio_duration = Column(Float, nullable=True, comment="音频时长（秒）")
    
    # 生成状态
    image_generated = Column(Boolean, default=False, comment="图像是否已生成")
    video_generated = Column(Boolean, default=False, comment="视频是否已生成")
    audio_generated = Column(Boolean, default=False, comment="音频是否已生成")
    subtitle_generated = Column(Boolean, default=False, comment="字幕是否已生成")
    
    # 时间戳
    created_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
        comment="创建时间"
    )
    updated_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
        comment="更新时间"
    )
    
    # 关系
    project = relationship("Project", back_populates="scenes")
    
    # 索引
    __table_args__ = (
        Index("idx_scene_project_id", "project_id"),
        Index("idx_scene_number", "project_id", "scene_number"),
        Index("idx_scene_generated", "image_generated", "video_generated", "audio_generated"),
    )
    
    def __repr__(self):
        return f"<Scene(id={self.id}, scene_number={self.scene_number}, project_id={self.project_id})>"


class Task(Base):
    """
    任务表
    存储异步任务的执行信息
    """
    __tablename__ = "tasks"
    
    # 主键
    id = Column(Integer, primary_key=True, index=True, comment="任务ID")
    
    # 外键
    project_id = Column(
        Integer,
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
        comment="所属项目ID"
    )
    
    # 任务信息
    task_type = Column(
        Enum(TaskType),
        nullable=False,
        comment="任务类型"
    )
    status = Column(
        Enum(TaskStatus),
        nullable=False,
        default=TaskStatus.PENDING,
        comment="任务状态"
    )
    
    # Celery 任务信息
    celery_task_id = Column(String(255), nullable=True, unique=True, comment="Celery任务ID")
    
    # 任务参数和结果
    parameters = Column(JSON, nullable=True, comment="任务参数（JSON格式）")
    result = Column(JSON, nullable=True, comment="任务结果（JSON格式）")
    error_message = Column(Text, nullable=True, comment="错误信息")
    
    # 进度信息
    progress = Column(Float, default=0.0, comment="任务进度（0-100）")
    current_step = Column(String(255), nullable=True, comment="当前步骤")
    total_steps = Column(Integer, nullable=True, comment="总步骤数")
    
    # 重试信息
    retry_count = Column(Integer, default=0, comment="重试次数")
    max_retries = Column(Integer, default=3, comment="最大重试次数")
    
    # 时间戳
    created_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
        comment="创建时间"
    )
    started_at = Column(
        DateTime(timezone=True),
        nullable=True,
        comment="开始时间"
    )
    completed_at = Column(
        DateTime(timezone=True),
        nullable=True,
        comment="完成时间"
    )
    updated_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
        comment="更新时间"
    )
    
    # 关系
    project = relationship("Project", back_populates="tasks")
    
    # 索引
    __table_args__ = (
        Index("idx_task_project_id", "project_id"),
        Index("idx_task_status", "status"),
        Index("idx_task_type", "task_type"),
        Index("idx_task_celery_id", "celery_task_id"),
        Index("idx_task_created_at", "created_at"),
    )
    
    def __repr__(self):
        return f"<Task(id={self.id}, type='{self.task_type.value}', status='{self.status.value}')>"
