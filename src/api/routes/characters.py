"""
角色管理 API 路由

提供角色的 CRUD 操作和参考图像管理功能
"""

from fastapi import APIRouter, HTTPException, status, Depends, UploadFile, File
from typing import List, Optional
from sqlalchemy.orm import Session
import os
from pathlib import Path

from src.api.schemas import (
    CharacterCreate,
    CharacterResponse,
    CharacterReferenceResponse,
    MessageResponse
)
from src.database.session import get_db_session
from src.database.models import Character, Project
from src.services.character_service import get_character_manager
from src.utils.logger import get_logger

logger = get_logger(__name__)

router = APIRouter(prefix="/api/projects/{project_id}/characters", tags=["角色管理"])


@router.post("", response_model=CharacterResponse, status_code=status.HTTP_201_CREATED)
async def create_character(
    project_id: int,
    character: CharacterCreate,
    db_session: Session = Depends(get_db_session)
):
    """
    创建新角色
    
    Args:
        project_id: 项目ID
        character: 角色创建请求
        db_session: 数据库会话
    
    Returns:
        创建的角色信息
    """
    try:
        logger.info(f"创建角色: project_id={project_id}, name={character.name}")
        
        # 检查项目是否存在
        project = db_session.query(Project).filter(Project.id == project_id).first()
        if not project:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"项目不存在: {project_id}"
            )
        
        # 创建角色
        db_character = Character(
            project_id=project_id,
            name=character.name,
            description=character.description,
            personality=character.personality,
            appearance=character.appearance
        )
        
        db_session.add(db_character)
        db_session.commit()
        db_session.refresh(db_character)
        
        logger.info(f"角色创建成功: id={db_character.id}")
        return db_character
    
    except HTTPException:
        raise
    except Exception as e:
        db_session.rollback()
        logger.error(f"创建角色失败: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="创建角色时发生错误"
        )


@router.get("", response_model=List[CharacterResponse])
async def list_characters(
    project_id: int,
    db_session: Session = Depends(get_db_session)
):
    """
    获取项目的所有角色
    
    Args:
        project_id: 项目ID
        db_session: 数据库会话
    
    Returns:
        角色列表
    """
    try:
        logger.info(f"获取角色列表: project_id={project_id}")
        
        characters = db_session.query(Character).filter(
            Character.project_id == project_id
        ).all()
        
        return characters
    
    except Exception as e:
        logger.error(f"获取角色列表失败: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="获取角色列表时发生错误"
        )


@router.get("/{character_id}", response_model=CharacterResponse)
async def get_character(
    project_id: int,
    character_id: int,
    db_session: Session = Depends(get_db_session)
):
    """
    获取角色详情
    
    Args:
        project_id: 项目ID
        character_id: 角色ID
        db_session: 数据库会话
    
    Returns:
        角色详细信息
    """
    try:
        logger.info(f"获取角色详情: character_id={character_id}")
        
        character = db_session.query(Character).filter(
            Character.id == character_id,
            Character.project_id == project_id
        ).first()
        
        if not character:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"角色不存在: {character_id}"
            )
        
        return character
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"获取角色详情失败: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="获取角色详情时发生错误"
        )


@router.post("/{character_id}/reference", response_model=CharacterReferenceResponse)
async def upload_reference_image(
    project_id: int,
    character_id: int,
    file: UploadFile = File(...),
    description: Optional[str] = None,
    db_session: Session = Depends(get_db_session)
):
    """
    上传角色参考图像
    
    Args:
        project_id: 项目ID
        character_id: 角色ID
        file: 参考图像文件
        description: 图像描述
        db_session: 数据库会话
    
    Returns:
        参考图像信息
    """
    try:
        logger.info(f"上传角色参考图像: character_id={character_id}, file={file.filename}")
        
        # 检查角色是否存在
        character = db_session.query(Character).filter(
            Character.id == character_id,
            Character.project_id == project_id
        ).first()
        
        if not character:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"角色不存在: {character_id}"
            )
        
        # 保存上传的文件
        from src.services.character_service import get_character_manager
        character_manager = get_character_manager()
        
        # 创建临时目录保存上传文件
        temp_dir = Path("./storage/temp")
        temp_dir.mkdir(parents=True, exist_ok=True)
        temp_path = temp_dir / f"{file.filename}"
        
        with open(temp_path, "wb") as buffer:
            content = await file.read()
            buffer.write(content)
        
        # 保存到角色参考目录
        reference_path = character_manager.save_character_reference(
            character_id=character_id,
            project_id=project_id,
            image_path=str(temp_path),
            description=description or ""
        )
        
        # 删除临时文件
        os.remove(temp_path)
        
        logger.info(f"参考图像保存成功: {reference_path}")
        
        return CharacterReferenceResponse(
            id=len(character_manager.get_character_references(character_id, project_id)),
            character_id=character_id,
            image_path=reference_path,
            description=description or ""
        )
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"上传参考图像失败: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="上传参考图像时发生错误"
        )


@router.get("/{character_id}/references", response_model=List[CharacterReferenceResponse])
async def list_reference_images(
    project_id: int,
    character_id: int,
    db_session: Session = Depends(get_db_session)
):
    """
    获取角色的所有参考图像
    
    Args:
        project_id: 项目ID
        character_id: 角色ID
        db_session: 数据库会话
    
    Returns:
        参考图像列表
    """
    try:
        logger.info(f"获取角色参考图像: character_id={character_id}")
        
        # 检查角色是否存在
        character = db_session.query(Character).filter(
            Character.id == character_id,
            Character.project_id == project_id
        ).first()
        
        if not character:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"角色不存在: {character_id}"
            )
        
        # 获取参考图像
        from src.services.character_service import get_character_manager
        character_manager = get_character_manager()
        references = character_manager.get_character_references(character_id, project_id)
        
        return [
            CharacterReferenceResponse(
                id=i + 1,
                character_id=character_id,
                image_path=ref_path,
                description=""
            )
            for i, ref_path in enumerate(references)
        ]
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"获取参考图像失败: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="获取参考图像时发生错误"
        )


@router.delete("/{character_id}", response_model=MessageResponse)
async def delete_character(
    project_id: int,
    character_id: int,
    db_session: Session = Depends(get_db_session)
):
    """
    删除角色
    
    Args:
        project_id: 项目ID
        character_id: 角色ID
        db_session: 数据库会话
    
    Returns:
        删除成功消息
    """
    try:
        logger.info(f"删除角色: character_id={character_id}")
        
        character = db_session.query(Character).filter(
            Character.id == character_id,
            Character.project_id == project_id
        ).first()
        
        if not character:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"角色不存在: {character_id}"
            )
        
        db_session.delete(character)
        db_session.commit()
        
        logger.info(f"角色删除成功: character_id={character_id}")
        
        return MessageResponse(message=f"角色 {character.name} 已删除")
    
    except HTTPException:
        raise
    except Exception as e:
        db_session.rollback()
        logger.error(f"删除角色失败: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="删除角色时发生错误"
        )
