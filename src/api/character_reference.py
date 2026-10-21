"""
角色参考图生成 API
"""
import asyncio
import os
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from typing import Optional, Dict
from loguru import logger

from src.services.character_reference_generator import CharacterReferenceGenerator
from src.services.character_reference_auto import CharacterReferenceAutoGenerator
from src.services.llm_service import get_llm_service
from src.api.dependencies import get_current_user
from src.config import settings


router = APIRouter(
    prefix="/character",
    tags=["character"],
    dependencies=[Depends(get_current_user)],
)


def _safe_reference_dir(requested: str | None) -> str:
    """Resolve a reference output directory without allowing path traversal."""
    storage_root = Path(
        os.getenv("STORAGE_PATH")
        or getattr(settings, "STORAGE_PATH", "./storage")
        or "./storage"
    ).resolve()
    reference_root = (storage_root / "characters").resolve()
    candidate = Path(requested or str(reference_root)).resolve()
    if not candidate.is_relative_to(reference_root):
        raise HTTPException(
            status_code=400,
            detail="save_dir must be inside the configured character storage directory",
        )
    candidate.mkdir(parents=True, exist_ok=True)
    return str(candidate)


class CharacterRequest(BaseModel):
    """角色生成请求"""
    name: str
    role: Optional[str] = "主角"
    personality: Optional[str] = "自信、专业"
    generate_images: Optional[bool] = False  # 是否立即生成参考图
    count: Optional[int] = 3  # 生成候选参考图数量
    save_dir: Optional[str] = None


class CharacterResponse(BaseModel):
    """角色生成响应"""
    success: bool
    character_data: Dict
    reference_prompts: Optional[Dict] = None
    message: str


@router.post("/generate-description", response_model=CharacterResponse)
def generate_character_description(request: CharacterRequest):
    """
    使用 LLM 生成详细的角色描述
    
    Args:
        request: 角色请求数据
        
    Returns:
        角色描述 JSON 和参考图提示词
    """
    try:
        logger.info(f"开始生成角色描述: {request.name}")
        
        # 获取 LLM 服务
        llm_service = get_llm_service()
        
        # 创建生成器
        generator = CharacterReferenceGenerator(llm_service=llm_service)
        
        # 生成角色描述
        character_data = generator.generate_character_description(
            character_name=request.name,
            role=request.role,
            personality=request.personality
        )
        
        # 生成参考图提示词
        reference_prompts = generator.generate_reference_prompts(character_data)
        
        logger.info(f"角色 '{request.name}' 描述生成成功")
        
        return CharacterResponse(
            success=True,
            character_data=character_data,
            reference_prompts=reference_prompts,
            message=f"角色 '{request.name}' 描述生成成功，包含 {len(reference_prompts)} 个角度的参考图提示词"
        )
        
    except Exception as e:
        logger.error(f"生成角色描述失败: {e}")
        raise HTTPException(status_code=500, detail=f"生成失败: {str(e)}")


@router.post("/generate-reference-images", response_model=Dict)
async def generate_reference_images(request: CharacterRequest):
    """
    生成角色参考图提示词，或调用生产级服务生成并筛选参考图。

    ``generate_images=false`` 保持旧行为，只生成提示词；开启后复用
    CharacterReferenceAutoGenerator 的候选图、质量评分和最佳图选择流程。
    """
    try:
        logger.info(f"开始生成角色参考图: {request.name}")
        
        # 1. 生成角色描述
        llm_service = get_llm_service()
        generator = CharacterReferenceGenerator(llm_service=llm_service)
        
        character_data = generator.generate_character_description(
            character_name=request.name,
            role=request.role,
            personality=request.personality
        )
        
        # 2. 生成提示词
        prompts = generator.generate_reference_prompts(character_data)
        
        if not request.generate_images:
            return {
                "success": True,
                "character_data": character_data,
                "prompts": prompts,
                "message": "角色描述和参考图提示词生成成功",
                "reference_images": [],
            }

        count = max(1, min(int(request.count or 3), 8))
        safe_save_dir = _safe_reference_dir(request.save_dir)
        generator = CharacterReferenceAutoGenerator(generator=generator)
        result = await asyncio.to_thread(
            generator.generate_multiple_references,
            character_name=request.name,
            role=request.role or "主角",
            personality=request.personality or "自信、专业",
            count=count,
            save_dir=safe_save_dir,
        )

        return {
            **result,
            "prompts": result.get("reference_prompts", prompts),
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"生成参考图失败: {e}")
        raise HTTPException(status_code=500, detail=f"生成失败: {str(e)}")


@router.get("/template/{character_name}")
def get_character_template(character_name: str):
    """
    获取角色模板（不使用 LLM）
    
    Args:
        character_name: 角色名称
        
    Returns:
        默认角色模板
    """
    try:
        generator = CharacterReferenceGenerator()
        template = generator._get_default_character_template(character_name)
        prompts = generator.generate_reference_prompts(template)
        
        return {
            "success": True,
            "character_data": template,
            "reference_prompts": prompts
        }
        
    except Exception as e:
        logger.error(f"获取模板失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))
