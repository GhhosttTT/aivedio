"""
角色参考图生成 API
"""
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from typing import Optional, Dict
from loguru import logger

from src.services.character_reference_generator import CharacterReferenceGenerator
from src.services.llm_service import get_llm_service


router = APIRouter(prefix="/character", tags=["character"])


class CharacterRequest(BaseModel):
    """角色生成请求"""
    name: str
    role: Optional[str] = "主角"
    personality: Optional[str] = "自信、专业"
    generate_images: Optional[bool] = False  # 是否立即生成参考图


class CharacterResponse(BaseModel):
    """角色生成响应"""
    success: bool
    character_data: Dict
    reference_prompts: Optional[Dict] = None
    message: str


@router.post("/generate-description", response_model=CharacterResponse)
async def generate_character_description(request: CharacterRequest):
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
    生成角色参考图（需要集成图像生成服务）
    
    TODO: 实现实际的图像生成逻辑
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
        
        # 3. TODO: 调用图像生成服务
        # 这里需要集成现有的图像生成服务
        # image_service = ImageGenerationService()
        # images = await image_service.generate_multiple(prompts)
        
        return {
            "success": True,
            "character_data": character_data,
            "prompts": prompts,
            "message": "提示词已生成，待实现图像生成功能",
            "next_steps": [
                "1. 使用正面特写提示词生成面部参考图",
                "2. 使用半身照提示词生成服装参考图",
                "3. 使用全身照提示词生成整体形象参考图",
                "4. 将生成的图片保存为角色参考图"
            ]
        }
        
    except Exception as e:
        logger.error(f"生成参考图失败: {e}")
        raise HTTPException(status_code=500, detail=f"生成失败: {str(e)}")


@router.get("/template/{character_name}")
async def get_character_template(character_name: str):
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
