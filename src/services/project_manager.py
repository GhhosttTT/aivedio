"""
项目管理服务

负责管理短剧项目的生命周期（创建、更新、删除、查询）
"""

import os
import shutil
import json
from typing import Optional, List, Dict
from datetime import datetime
from sqlalchemy.orm import Session
from sqlalchemy import desc

from src.database.models import Project, Character, Scene, ProjectStatus
from src.utils.storage import get_project_storage_path, cleanup_project_files
from src.utils.logger import logger


class ProjectManager:
    """项目管理服务"""
    
    def __init__(self, db_session: Session):
        """
        初始化项目管理服务
        
        Args:
            db_session: 数据库会话
        """
        self.db = db_session
    
    def create_project(
        self,
        name: str,
        user_id: int,
        description: Optional[str] = None,
        theme: Optional[str] = None,
        outline: Optional[str] = None
    ) -> Project:
        """
        创建新项目
        
        Args:
            name: 项目名称（1-100字符）
            user_id: 用户 ID
            description: 项目描述（可选）
            theme: 剧本主题（可选）
            outline: 剧本大纲（可选）
            
        Returns:
            创建的项目对象
            
        Raises:
            ValueError: 如果输入验证失败
        """
        # 输入验证
        if not name or len(name.strip()) == 0:
            raise ValueError("项目名称不能为空")
        
        if len(name) > 100:
            raise ValueError("项目名称不能超过100个字符")
        
        # 验证名称只包含合法字符（中文、英文、数字、下划线、连字符、空格）
        import re
        if not re.match(r'^[\u4e00-\u9fa5a-zA-Z0-9_\-\s]+$', name):
            raise ValueError("项目名称只能包含中文、英文、数字、下划线、连字符和空格")
        
        try:
            # 创建项目对象
            # 对于可选文本字段，strip 后如果为空字符串则设为 None
            stripped_description = description.strip() if description else None
            stripped_theme = theme.strip() if theme else None
            stripped_outline = outline.strip() if outline else None
            
            project = Project(
                name=name.strip(),
                user_id=user_id,
                description=stripped_description if stripped_description else None,
                theme=stripped_theme if stripped_theme else None,
                outline=stripped_outline if stripped_outline else None,
                status=ProjectStatus.DRAFT
            )
            
            # 保存到数据库
            self.db.add(project)
            self.db.commit()
            self.db.refresh(project)
            
            # 创建项目存储目录
            storage_path = get_project_storage_path(project.id)
            os.makedirs(storage_path, exist_ok=True)
            
            logger.info(f"创建项目成功: id={project.id}, name='{project.name}', user_id={user_id}")
            
            return project
            
        except Exception as e:
            self.db.rollback()
            logger.error(f"创建项目失败: {e}")
            raise
    
    def get_project(self, project_id: int) -> Optional[Project]:
        """
        获取项目详情
        
        Args:
            project_id: 项目ID
            
        Returns:
            项目对象，不存在则返回None
        """
        try:
            from sqlalchemy.orm import joinedload
            
            # 使用 joinedload 预加载关联数据
            project = self.db.query(Project).options(
                joinedload(Project.characters),
                joinedload(Project.scenes)
            ).filter(Project.id == project_id).first()
            
            if project:
                logger.debug(f"获取项目: id={project_id}, name='{project.name}', scenes={len(project.scenes)}, characters={len(project.characters)}")
            else:
                logger.warning(f"项目不存在: id={project_id}")
            
            return project
            
        except Exception as e:
            logger.error(f"获取项目失败: project_id={project_id}, error={e}")
            raise
    
    def update_project(
        self,
        project_id: int,
        **kwargs
    ) -> Project:
        """
        更新项目信息
        
        Args:
            project_id: 项目ID
            **kwargs: 要更新的字段（name, description, theme, outline, script, status等）
            
        Returns:
            更新后的项目对象
            
        Raises:
            ValueError: 如果项目不存在或输入验证失败
        """
        project = self.get_project(project_id)
        
        if not project:
            raise ValueError(f"项目不存在: id={project_id}")
        
        try:
            # 更新允许的字段
            allowed_fields = [
                'name', 'description', 'theme', 'outline',
                'script', 'status', 'total_scenes', 'final_video_path'
            ]
            
            updated_fields = []
            
            for field, value in kwargs.items():
                if field in allowed_fields:
                    # 特殊验证
                    if field == 'name':
                        if not value or len(value.strip()) == 0:
                            raise ValueError("项目名称不能为空")
                        if len(value) > 100:
                            raise ValueError("项目名称不能超过100个字符")
                        value = value.strip()
                    
                    # 对可选文本字段进行 strip，空字符串转为 None
                    if field in ['description', 'theme', 'outline'] and value:
                        value = value.strip()
                        if not value:  # strip 后为空字符串
                            value = None
                    
                    if field == 'status' and isinstance(value, str):
                        # 转换字符串为枚举
                        value = ProjectStatus(value)
                    if field == 'script' and value is not None and not isinstance(value, str):
                        value = json.dumps(value, ensure_ascii=False)
                    
                    setattr(project, field, value)
                    updated_fields.append(field)
            
            # 更新时间戳
            project.updated_at = datetime.now()
            
            # 如果状态变为完成，设置完成时间
            if 'status' in kwargs and kwargs['status'] == ProjectStatus.COMPLETED:
                project.completed_at = datetime.now()
            
            self.db.commit()
            self.db.refresh(project)
            
            logger.info(
                f"更新项目成功: id={project_id}, "
                f"updated_fields={updated_fields}"
            )
            
            return project
            
        except Exception as e:
            self.db.rollback()
            logger.error(f"更新项目失败: project_id={project_id}, error={e}")
            raise
    
    def delete_project(self, project_id: int) -> bool:
        """
        删除项目
        
        Args:
            project_id: 项目ID
            
        Returns:
            是否删除成功
            
        Raises:
            ValueError: 如果项目不存在
        """
        project = self.get_project(project_id)
        
        if not project:
            raise ValueError(f"项目不存在: id={project_id}")
        
        try:
            # 删除项目文件
            storage_path = get_project_storage_path(project_id)
            if os.path.exists(storage_path):
                cleanup_project_files(storage_path)
                logger.info(f"删除项目文件: path={storage_path}")
            
            # 删除数据库记录（级联删除关联的角色、分镜、任务）
            self.db.delete(project)
            self.db.commit()
            
            logger.info(f"删除项目成功: id={project_id}, name='{project.name}'")
            
            return True
            
        except Exception as e:
            self.db.rollback()
            logger.error(f"删除项目失败: project_id={project_id}, error={e}")
            raise
    
    def list_projects(
        self,
        status: Optional[ProjectStatus] = None,
        limit: int = 20,
        offset: int = 0,
        order_by: str = "created_at",
        order_desc: bool = True
    ) -> List[Project]:
        """
        列出项目列表
        
        Args:
            status: 过滤状态（可选）
            limit: 返回数量限制（默认20）
            offset: 偏移量（默认0）
            order_by: 排序字段（默认created_at）
            order_desc: 是否降序（默认True）
            
        Returns:
            项目列表
        """
        try:
            query = self.db.query(Project)
            
            # 状态过滤
            if status:
                if isinstance(status, str):
                    status = ProjectStatus(status)
                query = query.filter(Project.status == status)
            
            # 排序
            order_field = getattr(Project, order_by, Project.created_at)
            if order_desc:
                query = query.order_by(desc(order_field))
            else:
                query = query.order_by(order_field)
            
            # 分页
            query = query.limit(limit).offset(offset)
            
            projects = query.all()
            
            logger.debug(
                f"列出项目: status={status}, "
                f"limit={limit}, offset={offset}, count={len(projects)}"
            )
            
            return projects
            
        except Exception as e:
            logger.error(f"列出项目失败: error={e}")
            raise
    
    def count_projects(self, status: Optional[ProjectStatus] = None) -> int:
        """
        统计项目数量
        
        Args:
            status: 过滤状态（可选）
            
        Returns:
            项目数量
        """
        try:
            query = self.db.query(Project)
            
            if status:
                if isinstance(status, str):
                    status = ProjectStatus(status)
                query = query.filter(Project.status == status)
            
            count = query.count()
            
            logger.debug(f"统计项目数量: status={status}, count={count}")
            
            return count
            
        except Exception as e:
            logger.error(f"统计项目数量失败: error={e}")
            raise
    
    def add_character(
        self,
        project_id: int,
        name: str,
        description: Optional[str] = None,
        visual_description: Optional[str] = None
    ) -> Character:
        """
        添加角色到项目
        
        Args:
            project_id: 项目ID
            name: 角色名称
            description: 角色描述
            visual_description: 视觉描述（外貌特征）
            
        Returns:
            创建的角色对象
            
        Raises:
            ValueError: 如果项目不存在或输入验证失败
        """
        project = self.get_project(project_id)
        
        if not project:
            raise ValueError(f"项目不存在: id={project_id}")
        
        if not name or len(name.strip()) == 0:
            raise ValueError("角色名称不能为空")
        
        try:
            character = Character(
                project_id=project_id,
                name=name.strip(),
                description=description,
                visual_description=visual_description
            )
            
            self.db.add(character)
            self.db.commit()
            self.db.refresh(character)
            
            logger.info(
                f"添加角色成功: project_id={project_id}, "
                f"character_name='{character.name}'"
            )
            
            return character
            
        except Exception as e:
            self.db.rollback()
            logger.error(f"添加角色失败: project_id={project_id}, error={e}")
            raise
    
    def add_scene(
        self,
        project_id: int,
        scene_number: int,
        visual_description: str,
        dialogue: Optional[str] = None,
        character_name: Optional[str] = None,
        image_prompt: Optional[str] = None
    ) -> Scene:
        """
        添加分镜到项目
        
        Args:
            project_id: 项目ID
            scene_number: 分镜序号
            visual_description: 视觉描述（场景描述）
            dialogue: 对话内容
            character_name: 说话角色
            image_prompt: 图像生成提示词
            
        Returns:
            创建的分镜对象
            
        Raises:
            ValueError: 如果项目不存在或输入验证失败
        """
        project = self.get_project(project_id)
        
        if not project:
            raise ValueError(f"项目不存在: id={project_id}")
        
        if not visual_description or len(visual_description.strip()) == 0:
            raise ValueError("场景描述不能为空")
        
        try:
            scene = Scene(
                project_id=project_id,
                scene_number=scene_number,
                visual_description=visual_description.strip(),
                dialogue=dialogue or "",
                character_name=character_name or "",
                image_prompt=image_prompt or visual_description.strip()
            )
            
            self.db.add(scene)
            self.db.commit()
            self.db.refresh(scene)
            
            logger.info(
                f"添加分镜成功: project_id={project_id}, "
                f"scene_number={scene_number}"
            )
            
            return scene
            
        except Exception as e:
            self.db.rollback()
            logger.error(f"添加分镜失败: project_id={project_id}, error={e}")
            raise
    
    def get_project_scenes(self, project_id: int) -> List[Scene]:
        """
        获取项目的所有分镜
        
        Args:
            project_id: 项目ID
            
        Returns:
            分镜列表（按scene_number排序）
        """
        try:
            scenes = (
                self.db.query(Scene)
                .filter(Scene.project_id == project_id)
                .order_by(Scene.scene_number)
                .all()
            )
            
            logger.debug(f"获取项目分镜: project_id={project_id}, count={len(scenes)}")
            
            return scenes
            
        except Exception as e:
            logger.error(f"获取项目分镜失败: project_id={project_id}, error={e}")
            raise
    
    def get_project_characters(self, project_id: int) -> List[Character]:
        """
        获取项目的所有角色
        
        Args:
            project_id: 项目ID
            
        Returns:
            角色列表
        """
        try:
            characters = (
                self.db.query(Character)
                .filter(Character.project_id == project_id)
                .all()
            )
            
            logger.debug(
                f"获取项目角色: project_id={project_id}, count={len(characters)}"
            )
            
            return characters
            
        except Exception as e:
            logger.error(f"获取项目角色失败: project_id={project_id}, error={e}")
            raise


# ==================== 单例模式 ====================

_project_manager_instance: Optional[ProjectManager] = None


def get_project_manager() -> ProjectManager:
    """
    获取 ProjectManager 单例实例
    
    Returns:
        ProjectManager 实例
    """
    global _project_manager_instance
    
    if _project_manager_instance is None:
        from src.database.session import get_db_session
        db_session = next(get_db_session())
        _project_manager_instance = ProjectManager(db_session)
        logger.info("ProjectManager 实例已创建")
    
    return _project_manager_instance


def cleanup_project_manager():
    """
    清理 ProjectManager 单例实例
    """
    global _project_manager_instance
    
    if _project_manager_instance is not None:
        _project_manager_instance = None
        logger.info("ProjectManager 实例已清理")

