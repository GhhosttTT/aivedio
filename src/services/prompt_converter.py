"""
JSON 结构化提示词转换器
将 JSON 格式的角色描述转换为专业的 Stable Diffusion 提示词
"""
import json
from typing import Dict, Optional
from loguru import logger


class PromptConverter:
    """JSON 提示词转换器"""
    
    def __init__(self):
        self.quality_tags = {
            "masterpiece": "(masterpiece, best quality:1.3)",
            "photorealistic": "(photorealistic, realistic:1.4)",
            "cinematic": "(cinematic lighting, professional photography:1.3)",
            "detailed": "(ultra-detailed, highly detailed:1.2)",
            "8k": "(8k uhd, high resolution:1.2)"
        }
        
    def convert_json_to_prompt(self, json_data: Dict) -> str:
        """
        将 JSON 格式的角色描述转换为 SD 提示词
        
        Args:
            json_data: JSON 格式的角色描述
            
        Returns:
            优化后的提示词字符串
        """
        try:
            # 解析 JSON（如果输入是字符串）
            if isinstance(json_data, str):
                json_data = json.loads(json_data)
            
            prompt_parts = []
            
            # 1. 质量标签
            style = json_data.get("style", "photorealistic")
            if style in self.quality_tags:
                prompt_parts.append(self.quality_tags[style])
            else:
                prompt_parts.append(self.quality_tags["photorealistic"])
            
            # 2. 外貌描述
            appearance = json_data.get("appearance", "")
            if appearance:
                prompt_parts.append(f"({appearance}:1.2)")
            
            # 3. 表情和情绪
            expression = json_data.get("expression", "")
            if expression:
                prompt_parts.append(f"({expression}:1.1)")
            
            # 4. 姿势和动作
            pose = json_data.get("pose", "")
            if pose:
                prompt_parts.append(pose)
            
            # 5. 镜头角度
            camera = json_data.get("camera", "medium shot")
            prompt_parts.append(camera)
            
            # 6. 光线和环境
            lighting = json_data.get("lighting", "professional lighting")
            prompt_parts.append(lighting)
            
            # 7. 额外细节
            details = json_data.get("details", [])
            if isinstance(details, list):
                prompt_parts.extend(details)
            
            # 组合提示词
            prompt = ", ".join(prompt_parts)
            
            logger.info(f"JSON 提示词转换成功")
            logger.debug(f"原始 JSON: {json.dumps(json_data, ensure_ascii=False)[:200]}")
            logger.debug(f"生成提示词: {prompt[:200]}...")
            
            return prompt
            
        except Exception as e:
            logger.error(f"JSON 提示词转换失败: {e}")
            # 返回默认提示词
            return "(masterpiece, best quality, photorealistic:1.3), handsome man, professional photography, cinematic lighting"
    
    def convert_with_llm(self, json_data: Dict, llm_service=None) -> str:
        """
        使用 LLM 优化 JSON 提示词（更专业）
        
        Args:
            json_data: JSON 格式的角色描述
            llm_service: LLM 服务实例（可选）
            
        Returns:
            LLM 优化后的提示词
        """
        if not llm_service:
            # 如果没有 LLM，使用基础转换
            return self.convert_json_to_prompt(json_data)
        
        try:
            # 构建 LLM 提示
            system_prompt = """你是一个专业的 AI 绘画提示词工程师。请将 JSON 格式的角色描述转换为高质量的 Stable Diffusion 提示词。

要求：
1. 使用英文
2. 包含质量标签（masterpiece, best quality, photorealistic等）
3. 详细描述外貌、表情、姿势、光线、镜头
4. 使用权重语法 (tag:1.2) 强调重要特征
5. 控制在 150-200 个单词以内
6. 只输出提示词，不要其他内容

示例输入：
{
  "appearance": "25岁亚洲男性，黑色短发，白色衬衫",
  "expression": "严肃专注",
  "pose": "站立，双手插兜",
  "lighting": "柔和侧光",
  "style": "photorealistic",
  "camera": "medium shot"
}

示例输出：
(masterpiece, best quality, photorealistic:1.4), (25 year old asian male:1.2), short black hair, white shirt, (serious and focused expression:1.1), standing pose with hands in pockets, soft side lighting, medium shot, professional photography, cinematic lighting, ultra-detailed, 8k uhd"""
            
            user_prompt = f"请转换以下 JSON 为 SD 提示词：\n{json.dumps(json_data, ensure_ascii=False)}"
            
            # 调用 LLM
            response = llm_service.chat(
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                temperature=0.7,
                max_tokens=300
            )
            
            prompt = response.strip()
            logger.info(f"LLM 提示词优化成功")
            logger.debug(f"LLM 生成提示词: {prompt[:200]}...")
            
            return prompt
            
        except Exception as e:
            logger.warning(f"LLM 优化失败，使用基础转换: {e}")
            return self.convert_json_to_prompt(json_data)


# 测试
if __name__ == "__main__":
    converter = PromptConverter()
    
    # 测试数据
    test_json = {
        "appearance": "25岁亚洲男性，黑色短发，穿着白色衬衫和黑色西装",
        "expression": "严肃专注的表情，眼神坚定",
        "pose": "站立姿势，双手插在口袋里",
        "lighting": "柔和的侧光，背景虚化",
        "style": "photorealistic",
        "camera": "medium shot"
    }
    
    prompt = converter.convert_json_to_prompt(test_json)
    print(f"\n生成的提示词:\n{prompt}\n")
