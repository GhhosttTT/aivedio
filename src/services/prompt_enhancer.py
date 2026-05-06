"""
Prompt 增强服务

使用 LLM 将简短的视觉描述扩展为详细的 Stable Diffusion 图像提示词
"""

from dotenv import load_dotenv
from src.services.llm_service import get_llm_service
from src.utils.logger import get_logger

# 加载环境变量
load_dotenv()

logger = get_logger(__name__)


class PromptEnhancer:
    """Prompt 增强器"""
    
    def __init__(self):
        """初始化 Prompt 增强器"""
        self.llm_service = None
    
    def _get_llm_service(self):
        """获取 LLM 服务（懒加载）"""
        if self.llm_service is None:
            try:
                self.llm_service = get_llm_service()
            except Exception as e:
                logger.warning(f"LLM 服务不可用，将使用原始描述: {e}")
                return None
        return self.llm_service
    
    def enhance_prompt(
        self,
        visual_description: str,
        character_name: str = None,
        scene_context: str = None
    ) -> str:
        """
        增强图像提示词
        
        将简短的视觉描述转换为详细的 Stable Diffusion 提示词
        
        Args:
            visual_description: 原始视觉描述
            character_name: 角色名称（可选）
            scene_context: 场景上下文（可选）
        
        Returns:
            增强后的图像提示词
        """
        llm = self._get_llm_service()
        
        # 如果 LLM 不可用，返回原始描述
        if llm is None:
            logger.warning("LLM 服务不可用，返回原始描述")
            return visual_description
        
        try:
            # 构建增强提示词的 prompt
            system_prompt = """你是一个专业的 Stable Diffusion 图像提示词工程师。你的任务是将简短的场景描述转换为详细、专业的图像生成提示词。

要求：
1. 使用英文输出（Stable Diffusion 对英文理解更好）
2. **必须包含以下要素**：
   - **主体描述（人物必须明确出现在画面中）**：如果提到角色，必须用 "1girl/1boy/1man/1woman [角色名]" 开头
   - 环境/背景描述
   - 光线和氛围
   - 艺术风格（写实、电影感）
   - 构图和视角
3. **强制规则**：
   - 如果场景中有角色，必须在提示词开头明确标注人物存在（例如："1woman Su Wan, ..."）
   - 添加质量保证词：(masterpiece, best quality, ultra-detailed)
   - 确保人物不会被忽略：在描述中加入人物的具体动作、表情、位置
4. 保持简洁但详细，50-100 个单词
5. 负面提示词单独返回（不要包含在主提示词中）
6. 使用逗号分隔不同的描述元素

示例输入："白月光车祸现场"
示例输出："cinematic shot of a car accident scene at night, broken glass scattered on wet asphalt road, emergency lights flashing red and blue, dramatic lighting with rain falling, smoke rising from damaged vehicle, realistic photography style, high detail, 8k, professional cinematography, moody atmosphere, shallow depth of field"

示例输入："苏晚拿着匿名信站在花园里"
示例输出："(masterpiece, best quality), 1woman Su Wan, standing in garden holding anonymous letter, calm expression, elegant dress, Lin Family estate background, soft natural lighting, cinematic composition, detailed facial features, realistic photography, 8k, ultra-detailed"

请严格按照上述要求生成提示词。**确保人物一定会出现在画面中**。"""

            user_prompt = f"""请将以下场景描述转换为详细的 Stable Diffusion 图像提示词：

场景描述：{visual_description}
{f'主要角色：{character_name}' if character_name else ''}
{f'场景上下文：{scene_context}' if scene_context else ''}

生成的提示词（英文）："""

            # 调用 LLM 生成提示词
            enhanced = llm.generate(
                prompt=f"{system_prompt}\n\n{user_prompt}",
                max_tokens=150,
                temperature=0.7,
                top_p=0.9
            )
            
            # 清理结果
            enhanced = enhanced.strip()
            
            # 移除可能的引号
            if enhanced.startswith('"') and enhanced.endswith('"'):
                enhanced = enhanced[1:-1]
            
            logger.info(f"提示词增强完成: '{visual_description[:30]}...' -> '{enhanced[:50]}...'")
            
            return enhanced
        
        except Exception as e:
            logger.error(f"提示词增强失败: {e}，返回原始描述")
            return visual_description
    
    def batch_enhance_prompts(
        self,
        scenes: list
    ) -> dict:
        """
        批量增强多个分镜的提示词
        
        Args:
            scenes: 分镜列表，每个分镜包含：
                - scene_number: 分镜编号
                - visual_description: 视觉描述
                - character_name: 角色名称（可选）
        
        Returns:
            字典，key 为 scene_number，value 为增强后的提示词
        """
        results = {}
        
        for i, scene in enumerate(scenes):
            logger.info(f"增强分镜 {i+1}/{len(scenes)} 的提示词...")
            
            enhanced_prompt = self.enhance_prompt(
                visual_description=scene.get('visual_description', ''),
                character_name=scene.get('character_name'),
                scene_context=scene.get('context')
            )
            
            results[scene['scene_number']] = enhanced_prompt
        
        return results


# 全局单例
_enhancer_instance = None


def get_prompt_enhancer() -> PromptEnhancer:
    """获取 Prompt 增强器单例"""
    global _enhancer_instance
    if _enhancer_instance is None:
        _enhancer_instance = PromptEnhancer()
    return _enhancer_instance
