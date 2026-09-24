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
from src.services.generation_review import ReviewError, write_report
from src.services.image_quality_service import ImageQualitySelector
from src.services.llm_service import get_llm_service
from src.services.turnaround_quality import attach_turnaround_quality_gate, turnaround_expected_features


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

    def generate_turnaround_album(
        self,
        character_name: str,
        role: str = "主角",
        personality: str = "自信、专业",
        count_per_view: int = 3,
        save_dir: str = "./storage/characters",
    ) -> Dict:
        """
        Generate front/side/back candidates and select the best image per view.

        The selected views are meant to be frozen by CharacterTurnaroundAlbumService
        before final production.
        """
        try:
            logger.info(f"开始为角色 '{character_name}' 生成三视图立体画册")
            character_data = self.generator.generate_character_description(
                character_name=character_name,
                role=role,
                personality=personality,
            )
            reference_prompts = self.generator.generate_reference_prompts(character_data)
            view_prompts = self._turnaround_view_prompts(reference_prompts, character_data)
            selected_views = {}
            quality_reports = {}
            candidate_images = {}
            for view, prompt_data in view_prompts.items():
                selected = self._generate_and_select_reference(
                    character_name=character_name,
                    character_data=character_data,
                    prompt=prompt_data["prompt"],
                    negative_prompt=prompt_data["negative"],
                    count=count_per_view,
                    save_dir=save_dir,
                    final_name=f"turnaround_{view}_selected.png",
                    candidate_prefix=f"turnaround_{view}_candidate",
                    report_name=f"turnaround_{view}_quality.json",
                    review_payload=_turnaround_review_payload(character_name, character_data, view),
                    turnaround_view=view,
                    generation_context={"turnaround_contract": prompt_data["turnaround_contract"]},
                )
                selected_views[view] = selected["reference_image_path"]
                quality_reports[view] = selected["quality_report"]
                candidate_images[view] = selected["candidate_images"]
            return {
                "success": True,
                "character_data": character_data,
                "selected_views": selected_views,
                "candidate_images": candidate_images,
                "quality_reports": quality_reports,
                "reference_prompts": reference_prompts,
                "message": f"角色 '{character_name}' 三视图立体画册生成成功",
            }
        except Exception as e:
            logger.error(f"生成三视图立体画册失败: {e}", exc_info=True)
            return {
                "success": False,
                "character_data": {},
                "selected_views": {},
                "candidate_images": {},
                "quality_reports": {},
                "message": f"生成失败: {str(e)}",
            }

    def _generate_and_select_reference(
        self,
        character_name: str,
        character_data: Dict,
        prompt: str,
        negative_prompt: str,
        count: int,
        save_dir: str,
        final_name: str = "reference_selected.png",
        candidate_prefix: str = "reference_candidate",
        report_name: str = "reference_quality.json",
        review_payload: Optional[Dict] = None,
        turnaround_view: Optional[str] = None,
        generation_context: Optional[Dict] = None,
    ) -> Dict:
        character_dir = Path(save_dir) / character_name.replace(" ", "_")
        character_dir.mkdir(parents=True, exist_ok=True)
        final_path = character_dir / final_name
        selector = ImageQualitySelector()
        candidates = []
        count = max(1, min(count, 8))
        import hashlib
        for index in range(count):
            output_path = character_dir / f"{candidate_prefix}_{index + 1:02d}.png"
            seed = int(hashlib.sha256(
                f"{character_name}:{candidate_prefix}:{index}:{json.dumps(character_data, ensure_ascii=False, sort_keys=True)}".encode()
            ).hexdigest()[:8], 16)
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
                review_payload or _reference_review_payload(character_name, character_data),
                prompt,
                None,
            )
            if turnaround_view:
                attach_turnaround_quality_gate(
                    report,
                    turnaround_view,
                    character_data,
                    settings.GENERATION_TURNAROUND_FEATURE_MIN_SCORE,
                )
            report["path"] = result_path
            report["request"] = {
                "seed": seed,
                "steps": min(max(settings.GENERATION_STEPS, 28) + index * 4, 48),
                "cfg_scale": settings.GENERATION_CFG,
            }
            if turnaround_view:
                report["request"]["turnaround_view"] = turnaround_view
            if generation_context:
                report["request"].update(generation_context)
            candidates.append(report)
        report_path = character_dir / report_name
        selection = selector.select_best(
            candidates,
            final_path,
            report_path,
            min_average=settings.GENERATION_IMAGE_MIN_SCORE,
            require_vlm=settings.GENERATION_REQUIRE_IMAGE_REVIEW,
        )
        if turnaround_view:
            selected = next(
                (candidate for candidate in selection.get("candidates", []) if candidate.get("index") == selection.get("best_index")),
                {},
            )
            selection["turnaround_view"] = turnaround_view
            selection["turnaround_gate"] = selected.get("turnaround_gate", {})
            selection["turnaround_contract"] = selected.get("request", {}).get("turnaround_contract", {})
            write_report(report_path, selection)
            if selection["turnaround_gate"].get("status") != "passed":
                raise ReviewError(
                    f"Turnaround {turnaround_view} feature gate failed: "
                    + ", ".join(selection["turnaround_gate"].get("missing") or selection["turnaround_gate"].get("low", {}).keys())
                )
        return {
            "reference_image_path": str(final_path),
            "candidate_images": [candidate["path"] for candidate in candidates],
            "quality_report": selection,
        }

    def _turnaround_view_prompts(self, reference_prompts: Dict, character_data: Dict) -> Dict[str, Dict[str, str]]:
        negative = next(
            (item.get("negative") for item in reference_prompts.values() if isinstance(item, dict) and item.get("negative")),
            "blurry, deformed, bad anatomy, text, watermark, extra limbs, changed outfit",
        )
        appearance = (
            f"{character_data.get('age', 25)} year old {character_data.get('ethnicity', 'East Asian')} "
            f"{character_data.get('gender', 'person')}, {character_data.get('face_shape', 'oval face')}, "
            f"{character_data.get('hair', 'neat hair')}, {character_data.get('body_type', 'average build')}, "
            f"{character_data.get('outfit_details', 'consistent outfit')}"
        )
        identity = _reference_identity_anchor(str(character_data.get("name") or ""), character_data)
        base = (
            "production character turnaround sheet, photorealistic short-drama character reference, "
            "plain neutral background, full outfit visible, consistent hairstyle and wardrobe, "
            f"{appearance}, identity anchor: {identity}"
        )
        front_prompt = reference_prompts.get("front_closeup", {}).get("prompt")
        side_prompt = reference_prompts.get("side_profile", {}).get("prompt")
        back_prompt = reference_prompts.get("back_view", {}).get("prompt")
        prompts = {}
        for view, prompt_data in {
            "front": {
                "prompt": (
                    front_prompt
                    or f"{base}, front view, facing camera, readable face, shoulders square, arms relaxed"
                ) + _turnaround_prompt_suffix("front"),
                "negative": negative,
            },
            "side": {
                "prompt": (
                    side_prompt
                    or f"{base}, strict side profile view, nose silhouette, hair outline, outfit side seam visible"
                ) + _turnaround_prompt_suffix("side"),
                "negative": negative,
            },
            "back": {
                "prompt": (
                    back_prompt
                    or f"{base}, back view, hairstyle back shape, outfit back silhouette, shoulders and full body visible"
                ) + _turnaround_prompt_suffix("back"),
                "negative": negative,
            },
        }.items():
            contract = _turnaround_sheet_contract(view, character_data)
            prompt_data["turnaround_contract"] = contract
            prompts[view] = prompt_data
        return prompts


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


def _turnaround_sheet_contract(view: str, character_data: Dict) -> Dict:
    view_camera = {
        "front": "strict orthographic front camera, shoulders square to camera",
        "side": "strict 90 degree side profile camera, no three-quarter rotation",
        "back": "strict orthographic rear camera, no face visible",
    }
    return {
        "view": view,
        "layout": "single full-body character on a neutral production sheet, head-to-toe visible, centered on the same scale",
        "camera": view_camera[view],
        "pose": "neutral A-pose or relaxed straight pose, feet visible, no dramatic action",
        "background": "plain light gray studio background, no props, no text, no watermark",
        "scale": "match height, lens distance, and body proportions across front side back views",
        "expected_features": turnaround_expected_features(view, character_data),
    }


def _turnaround_prompt_suffix(view: str) -> str:
    suffix = {
        "front": "strict front turnaround view, no dramatic pose, no camera tilt",
        "side": "90 degree side view, full body, neutral pose, no three-quarter angle",
        "back": "strict rear turnaround view, no face visible, neutral pose",
    }[view]
    return (
        f", {suffix}, production model sheet, full body head-to-toe visible, "
        "same scale as other views, centered neutral standing pose, plain light gray background, "
        "no props, no text, no watermark"
    )


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


def _turnaround_review_payload(character_name: str, character_data: Dict, view: str) -> Dict:
    payload = _reference_review_payload(character_name, character_data)
    requirements = {
        "front": [
            "strict front view",
            "face and outfit front readable",
            "neutral pose suitable for identity reference",
        ],
        "side": [
            "strict side profile, not three-quarter",
            "nose silhouette and hair outline readable",
            "body proportion and outfit side seam visible",
        ],
        "back": [
            "strict back view",
            "hairstyle back shape and outfit back silhouette readable",
            "no face or accidental front-facing pose",
        ],
    }
    payload["visual_description"] = f"{view} character turnaround reference"
    payload["turnaround_view"] = view
    payload["turnaround_contract"] = _turnaround_sheet_contract(view, character_data)
    payload["reference_requirements"] = payload["reference_requirements"] + requirements[view]
    return payload


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
