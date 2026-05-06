"""
角色参考图自动生成 API
"""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional, Dict, List
from loguru import logger

from src.services.character_reference_auto import CharacterReferenceAutoGenerator


router = APIRouter(prefix="/character-auto", tags=["character-auto"])


class AutoGenerateRequest(BaseModel):
    """自动生成请求"""
    name: str
    role: Optional[str] = "主角"
    personality: Optional[str] = "自信、专业"
    count: Optional[int] = 1  # 生成数量，默认1张


class AutoGenerateResponse(BaseModel):
    """自动生成响应"""
    success: bool
    character_data: Optional[Dict] = None
    reference_images: Optional[List[str]] = None
    reference_image_path: Optional[str] = None
    message: str


@router.post("/generate", response_model=AutoGenerateResponse)
async def auto_generate_character_reference(request: AutoGenerateRequest):
    """
    自动生成角色参考图
    
    流程：
    1. LLM 生成详细角色描述
    2. 生成正面特写提示词
    3. 使用 ComfyUI 生成高质量正面头像
    4. 保存为角色参考图
    
    Args:
        request: 生成请求
        
    Returns:
        生成的参考图信息
    """
    try:
        logger.info(f"接收到自动生成请求: {request.name}")
        
        generator = CharacterReferenceAutoGenerator()
        
        if request.count > 1:
            # 生成多张
            result = generator.generate_multiple_references(
                character_name=request.name,
                role=request.role,
                personality=request.personality,
                count=request.count
            )
            
            return AutoGenerateResponse(
                success=result["success"],
                character_data=result.get("character_data"),
                reference_images=result.get("reference_images", []),
                message=result["message"]
            )
        else:
            # 生成单张
            result = generator.generate_character_reference(
                character_name=request.name,
                role=request.role,
                personality=request.personality
            )
            
            return AutoGenerateResponse(
                success=result["success"],
                character_data=result.get("character_data"),
                reference_image_path=result.get("reference_image_path"),
                message=result["message"]
            )
            
    except Exception as e:
        logger.error(f"自动生成失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"生成失败: {str(e)}")


@router.post("/generate-batch", response_model=AutoGenerateResponse)
async def batch_generate_character_reference(request: AutoGenerateRequest):
    """
    批量生成角色参考图（多张不同角度）
    
    生成 3-5 张不同 seed 的正面头像，选择最佳的一张作为参考图
    
    Args:
        request: 生成请求
        
    Returns:
        生成的参考图信息
    """
    try:
        logger.info(f"接收到批量生成请求: {request.name}, count={request.count}")
        
        generator = CharacterReferenceAutoGenerator()
        
        result = generator.generate_multiple_references(
            character_name=request.name,
            role=request.role,
            personality=request.personality,
            count=request.count or 3  # 默认3张
        )
        
        return AutoGenerateResponse(
            success=result["success"],
            character_data=result.get("character_data"),
            reference_images=result.get("reference_images", []),
            message=result["message"]
        )
        
    except Exception as e:
        logger.error(f"批量生成失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"生成失败: {str(e)}")
