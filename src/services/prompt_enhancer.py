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
        character_appearance: str = None,
        scene_context: str = None
    ) -> str:
        """
        增强图像提示词
        
        将简短的视觉描述转换为详细的 Stable Diffusion 提示词
        
        Args:
            visual_description: 原始视觉描述
            character_name: 角色名称（可选）
            character_appearance: 角色外貌特征（可选，用于区分不同角色）
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
            system_prompt = """你是一个专业的真实感图像提示词工程师。你的任务是生成接近真实照片的提示词,避免 AI 感。

核心原则:
1. **真实感优先** - 像真实照片,不是完美的 CG
2. **自然光影** - 使用 natural lighting, ambient light, 不用 perfect lighting
3. **适度瑕疵** - 添加 film grain, subtle noise, slight imperfections
4. **纪实风格** - 使用 candid shot, documentary style, raw photo
5. **避免过度修饰** - 不用 ultra-detailed, flawless, perfect 等词
6. **角色特征明确** - 如果提供了角色外貌特征，必须详细描述以区分不同角色

必须包含的真实感元素:
- raw photo / candid shot (纪实风格)
- natural lighting / ambient light (自然光)
- film grain / subtle noise (胶片颗粒)
- realistic skin texture (真实皮肤)
- slight imperfections (轻微瑕疵)
- natural colors (自然色彩)
- unposed / authentic (自然姿态)

角色外貌描述规范（重要！用于区分不同角色）:
- 必须包含：年龄段、发型、发色、脸型、身材特征
- 服装风格：根据角色身份描述（如"商务西装"、"休闲装"、"传统服饰"）
- 气质特征：如"温柔气质"、"霸道总裁气场"、"邻家女孩感"
- 独特标识：如"戴眼镜"、"有胡须"、"长发披肩"等

禁止使用的词汇:
- ❌ (masterpiece:1.2), (best quality:1.2) - 太完美
- ❌ ultra-detailed, hyper-realistic - 过度渲染
- ❌ perfect, flawless - 不真实
- ❌ professional photography - 太专业
- ❌ 8k, high resolution - 过度强调质量
- ❌ handsome, beautiful（太泛化，必须用具体特征替代）

推荐使用的词汇:
- ✅ raw photo, candid shot - 纪实感
- ✅ natural lighting, soft light - 自然光
- ✅ film grain, subtle noise - 胶片感
- ✅ realistic, authentic - 真实感
- ✅ documentary style - 纪录片风格

示例输入："苏晚拿着匿名信站在花园里"
角色外貌："25岁女性，长发披肩，温柔气质，穿着优雅连衣裙"
示例输出："raw photo, candid shot, 1woman age 25 with long flowing hair, gentle temperament, elegant dress, standing in garden holding anonymous letter, natural expression with slight concern, realistic facial features, natural skin texture, Lin Family estate garden background with real flowers, natural daylight, soft ambient lighting, film grain, subtle color grading, documentary photography style, authentic moment, unposed, 35mm film aesthetic, natural colors, slight imperfections, real life scene"

示例输入："林家少爷在书房看文件"
角色外貌："30岁男性，短发，戴金丝眼镜，商务西装，成熟稳重气质"
示例输出："raw photo, candid shot, 1man age 30 with short hair, wearing gold-rimmed glasses, business suit, mature and composed demeanor, sitting in study room reviewing documents, natural expression, realistic facial features, natural skin texture, luxury study room background with bookshelves, natural window light, ambient shadows, film grain, documentary photography style, authentic moment, unposed, 35mm film aesthetic, natural colors, slight imperfections, real life scene"

请严格遵循真实感原则和角色特征明确性,生成自然、真实且能区分不同角色的提示词。"""

            user_prompt = f"""请将以下场景描述转换为详细的 Stable Diffusion 图像提示词：

场景描述：{visual_description}
{f'主要角色：{character_name}' if character_name else ''}
{f'角色外貌特征：{character_appearance}（必须在提示词中详细体现这些特征以区分角色）' if character_appearance else ''}
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
                - character_appearance: 角色外貌特征（可选）
        
        Returns:
            字典，key 为 scene_number，value 为增强后的提示词
        """
        results = {}
        
        for i, scene in enumerate(scenes):
            logger.info(f"增强分镜 {i+1}/{len(scenes)} 的提示词...")
            
            enhanced_prompt = self.enhance_prompt(
                visual_description=scene.get('visual_description', ''),
                character_name=scene.get('character_name'),
                character_appearance=scene.get('character_appearance'),
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
