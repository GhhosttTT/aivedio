"""
角色参考图自动生成服务
自动生成高质量的正面角色头像，用于后续的角色一致性生成
"""
import json
from pathlib import Path
from typing import Dict, Optional
from loguru import logger

from src.config import settings
from src.services.character_reference_generator import CharacterReferenceGenerator
from src.services.comfyui_service import ComfyUIService
from src.services.image_quality_service import ImageQualitySelector
from src.services.llm_service import get_llm_service


class CharacterReferenceAutoGenerator:
    """角色参考图自动生成器"""
    
    def __init__(self, comfyui_service: Optional[ComfyUIService] = None, generator: Optional[CharacterReferenceGenerator] = None):
        self.comfyui = comfyui_service or ComfyUIService()
        self.llm_service = None if generator else get_llm_service()
        self.generator = generator or CharacterReferenceGenerator(llm_service=self.llm_service)
        
    def generate_character_reference(
        self,
        character_name: str,
        role: str = "主角",
        personality: str = "自信、专业",
        save_dir: str = "./storage/characters"
    ) -> Dict:
        """
        自动生成角色参考图
        
        流程：
        1. LLM 生成详细角色描述
        2. 生成正面特写提示词
        3. 使用 ComfyUI 生成高质量正面头像
        4. 保存为角色参考图
        
        Args:
            character_name: 角色名称
            role: 角色身份
            personality: 性格特点
            save_dir: 保存目录
            
        Returns:
            {
                "success": bool,
                "character_data": Dict,  # LLM 生成的角色描述
                "reference_image_path": str,  # 生成的参考图路径
                "message": str
            }
        """
        try:
            logger.info(f"开始为角色 '{character_name}' 生成参考图")
            
            # 步骤 1: 使用 LLM 生成详细的角色描述
            logger.info(f"步骤 1/4: LLM 生成角色描述...")
            character_data = self.generator.generate_character_description(
                character_name=character_name,
                role=role,
                personality=personality
            )
            logger.info(f"角色描述生成成功: {json.dumps(character_data, ensure_ascii=False)[:200]}")
            
            # 步骤 2: 生成正面特写的提示词
            logger.info(f"步骤 2/4: 生成正面特写提示词...")
            reference_prompts = self.generator.generate_reference_prompts(character_data)
            front_prompt = reference_prompts["front_closeup"]
            
            logger.info(f"正面特写提示词: {front_prompt['prompt'][:150]}...")
            
            # 步骤 3: 使用 ComfyUI 生成正面头像（不使用 IP-Adapter）
            logger.info(f"步骤 3/4: 使用 ComfyUI 生成正面头像...")
            
            # 构建高质量的正面头像提示词
            positive_prompt = front_prompt["prompt"]
            negative_prompt = front_prompt["negative"]
            
            # 确保是正面清晰人像
            positive_prompt += (
                ", front view, looking at camera, clear face, consistent facial identity reference, "
                "portrait photography, commercial lighting, natural skin texture, sharp focus on face"
            )
            
            result = self._generate_and_select_reference(
                character_name=character_name,
                character_data=character_data,
                prompt=positive_prompt,
                negative_prompt=negative_prompt,
                count=max(1, settings.GENERATION_IMAGE_CANDIDATES),
                save_dir=save_dir,
            )
            reference_path = result["reference_image_path"]
            
            return {
                "success": True,
                "character_data": character_data,
                "reference_image_path": str(reference_path),
                "candidate_images": result["candidate_images"],
                "quality_report": result["quality_report"],
                "reference_prompts": reference_prompts,
                "message": f"角色 '{character_name}' 参考图生成成功"
            }
            
        except Exception as e:
            logger.error(f"生成角色参考图失败: {e}", exc_info=True)
            return {
                "success": False,
                "character_data": {},
                "reference_image_path": None,
                "message": f"生成失败: {str(e)}"
            }
    
    def generate_multiple_references(
        self,
        character_name: str,
        role: str = "主角",
        personality: str = "自信、专业",
        count: int = 3,
        save_dir: str = "./storage/characters"
    ) -> Dict:
        """
        生成多个不同角度的角色参考图
        
        Args:
            character_name: 角色名称
            role: 角色身份
            personality: 性格特点
            count: 生成数量
            save_dir: 保存目录
            
        Returns:
            生成的参考图列表
        """
        try:
            logger.info(f"开始为角色 '{character_name}' 生成 {count} 张参考图")
            
            # 生成角色描述
            character_data = self.generator.generate_character_description(
                character_name=character_name,
                role=role,
                personality=personality
            )
            
            # 生成提示词
            reference_prompts = self.generator.generate_reference_prompts(character_data)
            
            prompt_data = reference_prompts["front_closeup"]
            positive_prompt = (
                prompt_data["prompt"]
                + ", front view, looking at camera, clear face, consistent facial identity reference, "
                "portrait photography, commercial lighting, natural skin texture"
            )
            negative_prompt = prompt_data["negative"]
            selected = self._generate_and_select_reference(
                character_name=character_name,
                character_data=character_data,
                prompt=positive_prompt,
                negative_prompt=negative_prompt,
                count=count,
                save_dir=save_dir,
            )
            
            return {
                "success": True,
                "character_data": character_data,
                "reference_images": selected["candidate_images"],
                "reference_image_path": selected["reference_image_path"],
                "quality_report": selected["quality_report"],
                "reference_prompts": reference_prompts,
                "message": f"成功生成 {len(selected['candidate_images'])} 张候选参考图，并选择最佳定妆图"
            }
            
        except Exception as e:
            logger.error(f"生成多张参考图失败: {e}", exc_info=True)
            return {
                "success": False,
                "character_data": {},
                "reference_images": [],
                "message": f"生成失败: {str(e)}"
            }

    def _generate_and_select_reference(
        self,
        character_name: str,
        character_data: Dict,
        prompt: str,
        negative_prompt: str,
        count: int,
        save_dir: str,
    ) -> Dict:
        character_dir = Path(save_dir) / character_name.replace(" ", "_")
        character_dir.mkdir(parents=True, exist_ok=True)
        final_path = character_dir / "reference_selected.png"
        selector = ImageQualitySelector()
        candidates = []
        count = max(1, min(count, 8))
        import hashlib
        for index in range(count):
            output_path = character_dir / f"reference_candidate_{index + 1:02d}.png"
            seed = int(hashlib.sha256(f"{character_name}:{index}:{json.dumps(character_data, ensure_ascii=False, sort_keys=True)}".encode()).hexdigest()[:8], 16)
            result_path = self.comfyui.generate_image(
                prompt=prompt,
                negative_prompt=negative_prompt,
                width=1024,
                height=1024,
                steps=min(max(settings.GENERATION_STEPS, 28) + index * 4, 48),
                cfg_scale=settings.GENERATION_CFG,
                seed=seed,
                output_path=str(output_path),
                reference_image=None,
                use_ipadapter=False,
            )
            report = selector.review_candidate(
                index + 1,
                result_path,
                _reference_review_payload(character_name, character_data),
                prompt,
                None,
            )
            report["path"] = result_path
            report["request"] = {"seed": seed, "steps": min(max(settings.GENERATION_STEPS, 28) + index * 4, 48), "cfg_scale": settings.GENERATION_CFG}
            candidates.append(report)
        selection = selector.select_best(
            candidates,
            final_path,
            character_dir / "reference_quality.json",
            min_average=settings.GENERATION_IMAGE_MIN_SCORE,
            require_vlm=settings.GENERATION_REQUIRE_IMAGE_REVIEW,
        )
        return {
            "reference_image_path": str(final_path),
            "candidate_images": [candidate["path"] for candidate in candidates],
            "quality_report": selection,
        }


def _reference_identity_anchor(character_name: str, character_data: Dict) -> str:
    fields = [
        character_data.get("face_shape"),
        character_data.get("eyes"),
        character_data.get("nose"),
        character_data.get("mouth"),
        character_data.get("hair"),
        character_data.get("skin_tone"),
        character_data.get("distinctive_features"),
        character_data.get("outfit_details"),
    ]
    details = ", ".join(str(field).strip() for field in fields if str(field or "").strip())
    return f"{character_name}: {details}" if details else character_name


def _reference_review_payload(character_name: str, character_data: Dict) -> Dict:
    anchor = _reference_identity_anchor(character_name, character_data)
    return {
        "scene_number": 1,
        "visual_description": "front-facing character reference portrait",
        "character_name": character_name,
        "identity": character_data,
        "visible_characters": [{"name": character_name, "appearance": anchor}],
        "reference_requirements": [
            "front-facing readable face",
            "distinctive facial traits visible",
            "stable hairstyle and wardrobe anchor",
            "mobile short-drama commercial portrait quality",
        ],
    }


# 测试
if __name__ == "__main__":
    generator = CharacterReferenceAutoGenerator()
    
    # 测试生成单个角色参考图
    result = generator.generate_character_reference(
        character_name="李明",
        role="年轻企业家",
        personality="自信、果断、有魅力"
    )
    
    print("\n生成结果:")
    print(json.dumps(result, ensure_ascii=False, indent=2))
