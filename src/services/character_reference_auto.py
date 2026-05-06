"""
角色参考图自动生成服务
自动生成高质量的正面角色头像，用于后续的角色一致性生成
"""
import json
import os
import time
from pathlib import Path
from typing import Dict, Optional
from loguru import logger

from src.services.character_reference_generator import CharacterReferenceGenerator
from src.services.comfyui_service import ComfyUIService
from src.services.llm_service import get_llm_service


class CharacterReferenceAutoGenerator:
    """角色参考图自动生成器"""
    
    def __init__(self, comfyui_service: Optional[ComfyUIService] = None):
        self.comfyui = comfyui_service or ComfyUIService()
        self.llm_service = get_llm_service()
        self.generator = CharacterReferenceGenerator(llm_service=self.llm_service)
        
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
            positive_prompt += ", front view, looking at camera, clear face, portrait photography, studio lighting, sharp focus on face"
            
            # 生成图像（使用纯文生图模式）
            result_path = self.comfyui.generate_image(
                prompt=positive_prompt,
                negative_prompt=negative_prompt,
                width=1024,
                height=1024,  # 正方形，适合头像
                steps=20,
                cfg_scale=7.0,
                seed=-1,
                reference_image=None,  # 不使用参考图
                use_ipadapter=False  # 关闭 IP-Adapter
            )
            
            logger.info(f"正面头像生成成功: {result_path}")
            
            # 步骤 4: 保存为角色参考图
            logger.info(f"步骤 4/4: 保存角色参考图...")
            
            # 创建角色目录
            character_dir = Path(save_dir) / character_name.replace(" ", "_")
            character_dir.mkdir(parents=True, exist_ok=True)
            
            # 复制文件
            from shutil import copy2
            timestamp = int(time.time())
            reference_path = character_dir / f"reference_{timestamp}.png"
            copy2(result_path, reference_path)
            
            logger.info(f"角色参考图已保存: {reference_path}")
            
            return {
                "success": True,
                "character_data": character_data,
                "reference_image_path": str(reference_path),
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
            
            # 创建角色目录
            character_dir = Path(save_dir) / character_name.replace(" ", "_")
            character_dir.mkdir(parents=True, exist_ok=True)
            
            generated_images = []
            
            # 生成多张图片（使用不同 seed）
            for i in range(count):
                logger.info(f"生成第 {i+1}/{count} 张参考图...")
                
                # 使用正面特写提示词
                prompt_data = reference_prompts["front_closeup"]
                positive_prompt = prompt_data["prompt"]
                negative_prompt = prompt_data["negative"]
                
                # 确保正面清晰
                positive_prompt += ", front view, looking at camera, clear face, portrait photography"
                
                # 使用不同 seed 生成变化
                seed = int(time.time() * 1000 + i * 1000) % (2**32)
                
                result_path = self.comfyui.generate_image(
                    prompt=positive_prompt,
                    negative_prompt=negative_prompt,
                    width=1024,
                    height=1024,
                    steps=20,
                    cfg_scale=7.0,
                    seed=seed,
                    reference_image=None,
                    use_ipadapter=False
                )
                
                # 保存
                timestamp = int(time.time())
                reference_path = character_dir / f"reference_{i+1}_{timestamp}.png"
                from shutil import copy2
                copy2(result_path, reference_path)
                
                generated_images.append(str(reference_path))
                logger.info(f"第 {i+1} 张参考图已保存: {reference_path}")
                
                # 等待一下避免太快
                time.sleep(2)
            
            return {
                "success": True,
                "character_data": character_data,
                "reference_images": generated_images,
                "reference_prompts": reference_prompts,
                "message": f"成功生成 {len(generated_images)} 张角色参考图"
            }
            
        except Exception as e:
            logger.error(f"生成多张参考图失败: {e}", exc_info=True)
            return {
                "success": False,
                "character_data": {},
                "reference_images": [],
                "message": f"生成失败: {str(e)}"
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
