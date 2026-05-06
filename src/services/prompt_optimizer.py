"""
提示词优化引擎（PromptOptimizer）

自动优化提示词，增强真实感和质量
"""

from typing import Optional, List, Dict, Any
from enum import Enum
from dataclasses import dataclass

from src.utils.logger import logger


class OptimizationMode(str, Enum):
    """优化模式枚举"""
    QUALITY = "quality"  # 质量优先模式
    REALISM = "realism"  # 真实感优先模式
    ARTISTIC = "artistic"  # 艺术风格模式
    BALANCED = "balanced"  # 平衡模式


@dataclass
class OptimizedPrompt:
    """优化后的提示词"""
    positive_prompt: str  # 正面提示词
    negative_prompt: str  # 负面提示词
    original_prompt: str  # 原始提示词
    added_keywords: List[str]  # 添加的关键词
    optimization_mode: OptimizationMode  # 优化模式
    word_count: int  # 单词数量


class PromptOptimizer:
    """提示词优化引擎"""
    
    # 质量标签
    QUALITY_TAGS = [
        "masterpiece",
        "best quality",
        "ultra-detailed",
        "high resolution",
        "professional",
        "8k uhd",
        "sharp focus"
    ]
    
    # 真实感关键词
    REALISM_KEYWORDS = [
        "raw photo",
        "candid shot",
        "natural lighting",
        "film grain",
        "photorealistic",
        "realistic skin texture",
        "natural colors",
        "authentic",
        "unposed",
        "documentary style"
    ]
    
    # 艺术风格关键词
    ARTISTIC_KEYWORDS = [
        "cinematic",
        "dramatic lighting",
        "depth of field",
        "bokeh",
        "artistic composition",
        "color grading",
        "aesthetic",
        "stylized"
    ]
    
    # 光影和摄影术语
    LIGHTING_TERMS = [
        "soft lighting",
        "natural light",
        "golden hour",
        "rim lighting",
        "ambient light",
        "diffused light",
        "studio lighting",
        "volumetric lighting"
    ]
    
    # 摄影术语
    PHOTOGRAPHY_TERMS = [
        "shallow depth of field",
        "wide aperture",
        "35mm lens",
        "50mm lens",
        "portrait lens",
        "professional photography",
        "DSLR",
        "full frame"
    ]
    
    # 负面提示词（通用）
    NEGATIVE_COMMON = [
        "low quality",
        "worst quality",
        "blurry",
        "out of focus",
        "distorted",
        "deformed",
        "ugly",
        "bad anatomy",
        "extra limbs",
        "missing limbs",
        "watermark",
        "text",
        "signature"
    ]
    
    # 负面提示词（真实感）
    NEGATIVE_REALISM = [
        "CGI",
        "3D render",
        "plastic skin",
        "airbrushed",
        "artificial",
        "synthetic",
        "cartoon",
        "anime",
        "illustration",
        "painting",
        "drawing",
        "oversaturated",
        "overexposed",
        "HDR effect"
    ]
    
    # 负面提示词（艺术风格）
    NEGATIVE_ARTISTIC = [
        "amateur",
        "snapshot",
        "phone camera",
        "low resolution",
        "pixelated",
        "jpeg artifacts"
    ]
    
    def __init__(self):
        """初始化提示词优化器"""
        logger.info("提示词优化器初始化完成")
    
    def optimize(
        self,
        prompt: str,
        mode: OptimizationMode = OptimizationMode.BALANCED,
        target_word_count: int = 100,
        add_quality_tags: bool = True,
        add_lighting_terms: bool = True,
        add_photography_terms: bool = True,
        custom_keywords: Optional[List[str]] = None,
        custom_negative: Optional[List[str]] = None
    ) -> OptimizedPrompt:
        """
        优化提示词
        
        Args:
            prompt: 原始提示词
            mode: 优化模式
            target_word_count: 目标单词数量（80-120）
            add_quality_tags: 是否添加质量标签
            add_lighting_terms: 是否添加光影术语
            add_photography_terms: 是否添加摄影术语
            custom_keywords: 自定义关键词
            custom_negative: 自定义负面提示词
            
        Returns:
            优化后的提示词对象
        """
        # 验证参数
        if not prompt or not prompt.strip():
            raise ValueError("提示词不能为空")
        
        if target_word_count < 50 or target_word_count > 200:
            logger.warning(f"目标单词数量 {target_word_count} 超出推荐范围 (50-200)，将使用默认值 100")
            target_word_count = 100
        
        # 清理原始提示词
        cleaned_prompt = self._clean_prompt(prompt)
        
        # 收集要添加的关键词
        added_keywords = []
        
        # 1. 添加质量标签
        if add_quality_tags:
            quality_tags = self._select_quality_tags(mode)
            added_keywords.extend(quality_tags)
        
        # 2. 根据模式添加特定关键词
        mode_keywords = self._select_mode_keywords(mode)
        added_keywords.extend(mode_keywords)
        
        # 3. 添加光影术语
        if add_lighting_terms:
            lighting_terms = self._select_lighting_terms(mode)
            added_keywords.extend(lighting_terms)
        
        # 4. 添加摄影术语
        if add_photography_terms:
            photography_terms = self._select_photography_terms(mode)
            added_keywords.extend(photography_terms)
        
        # 5. 添加自定义关键词
        if custom_keywords:
            added_keywords.extend(custom_keywords)
        
        # 6. 构建正面提示词
        positive_prompt = self._build_positive_prompt(
            cleaned_prompt,
            added_keywords,
            target_word_count
        )
        
        # 7. 构建负面提示词
        negative_prompt = self._build_negative_prompt(mode, custom_negative)
        
        # 8. 计算单词数量
        word_count = len(positive_prompt.split())
        
        # 创建优化结果
        result = OptimizedPrompt(
            positive_prompt=positive_prompt,
            negative_prompt=negative_prompt,
            original_prompt=prompt,
            added_keywords=added_keywords,
            optimization_mode=mode,
            word_count=word_count
        )
        
        # 记录优化结果
        self._log_optimization(result)
        
        return result
    
    def _clean_prompt(self, prompt: str) -> str:
        """
        清理提示词
        
        Args:
            prompt: 原始提示词
            
        Returns:
            清理后的提示词
        """
        # 移除多余的空格
        cleaned = " ".join(prompt.split())
        
        # 移除开头和结尾的逗号
        cleaned = cleaned.strip(", ")
        
        return cleaned
    
    def _select_quality_tags(self, mode: OptimizationMode) -> List[str]:
        """
        选择质量标签
        
        Args:
            mode: 优化模式
            
        Returns:
            质量标签列表
        """
        if mode == OptimizationMode.QUALITY:
            # 质量模式：使用所有质量标签
            return self.QUALITY_TAGS[:5]
        elif mode == OptimizationMode.REALISM:
            # 真实感模式：使用部分质量标签
            return ["best quality", "high resolution", "sharp focus"]
        elif mode == OptimizationMode.ARTISTIC:
            # 艺术模式：使用艺术相关的质量标签
            return ["masterpiece", "best quality", "professional"]
        else:
            # 平衡模式：使用核心质量标签
            return ["best quality", "high resolution", "professional"]
    
    def _select_mode_keywords(self, mode: OptimizationMode) -> List[str]:
        """
        根据模式选择关键词
        
        Args:
            mode: 优化模式
            
        Returns:
            关键词列表
        """
        if mode == OptimizationMode.QUALITY:
            # 质量模式：强调细节和清晰度
            return ["ultra-detailed", "sharp focus", "8k uhd"]
        elif mode == OptimizationMode.REALISM:
            # 真实感模式：强调真实感
            return self.REALISM_KEYWORDS[:6]
        elif mode == OptimizationMode.ARTISTIC:
            # 艺术模式：强调艺术风格
            return self.ARTISTIC_KEYWORDS[:5]
        else:
            # 平衡模式：混合使用
            return [
                "photorealistic",
                "natural lighting",
                "cinematic",
                "sharp focus"
            ]
    
    def _select_lighting_terms(self, mode: OptimizationMode) -> List[str]:
        """
        选择光影术语
        
        Args:
            mode: 优化模式
            
        Returns:
            光影术语列表
        """
        if mode == OptimizationMode.REALISM:
            # 真实感模式：自然光影
            return ["natural light", "soft lighting", "ambient light"]
        elif mode == OptimizationMode.ARTISTIC:
            # 艺术模式：戏剧性光影
            return ["dramatic lighting", "rim lighting", "volumetric lighting"]
        else:
            # 其他模式：平衡光影
            return ["natural lighting", "soft lighting"]
    
    def _select_photography_terms(self, mode: OptimizationMode) -> List[str]:
        """
        选择摄影术语
        
        Args:
            mode: 优化模式
            
        Returns:
            摄影术语列表
        """
        if mode == OptimizationMode.REALISM:
            # 真实感模式：专业摄影术语
            return ["professional photography", "DSLR", "35mm lens"]
        elif mode == OptimizationMode.ARTISTIC:
            # 艺术模式：艺术摄影术语
            return ["shallow depth of field", "bokeh", "cinematic composition"]
        else:
            # 其他模式：基础摄影术语
            return ["professional photography", "sharp focus"]
    
    def _build_positive_prompt(
        self,
        base_prompt: str,
        keywords: List[str],
        target_word_count: int
    ) -> str:
        """
        构建正面提示词
        
        Args:
            base_prompt: 基础提示词
            keywords: 要添加的关键词
            target_word_count: 目标单词数量
            
        Returns:
            构建后的正面提示词
        """
        # 计算基础提示词的单词数
        base_word_count = len(base_prompt.split())
        
        # 计算可以添加的关键词数量
        available_words = target_word_count - base_word_count
        
        # 选择要添加的关键词
        selected_keywords = []
        current_word_count = 0
        
        for keyword in keywords:
            keyword_word_count = len(keyword.split())
            if current_word_count + keyword_word_count <= available_words:
                selected_keywords.append(keyword)
                current_word_count += keyword_word_count
            else:
                break
        
        # 构建最终提示词
        if selected_keywords:
            # 将关键词添加到基础提示词前面
            prompt_parts = selected_keywords + [base_prompt]
            final_prompt = ", ".join(prompt_parts)
        else:
            final_prompt = base_prompt
        
        return final_prompt
    
    def _build_negative_prompt(
        self,
        mode: OptimizationMode,
        custom_negative: Optional[List[str]] = None
    ) -> str:
        """
        构建负面提示词
        
        Args:
            mode: 优化模式
            custom_negative: 自定义负面提示词
            
        Returns:
            构建后的负面提示词
        """
        # 收集负面提示词
        negative_keywords = []
        
        # 1. 添加通用负面提示词
        negative_keywords.extend(self.NEGATIVE_COMMON)
        
        # 2. 根据模式添加特定负面提示词
        if mode == OptimizationMode.REALISM:
            negative_keywords.extend(self.NEGATIVE_REALISM)
        elif mode == OptimizationMode.ARTISTIC:
            negative_keywords.extend(self.NEGATIVE_ARTISTIC)
        elif mode == OptimizationMode.QUALITY:
            negative_keywords.extend(self.NEGATIVE_REALISM[:5])
        else:
            # 平衡模式：混合使用
            negative_keywords.extend(self.NEGATIVE_REALISM[:8])
        
        # 3. 添加自定义负面提示词
        if custom_negative:
            negative_keywords.extend(custom_negative)
        
        # 4. 去重并构建负面提示词
        unique_negative = list(dict.fromkeys(negative_keywords))
        negative_prompt = ", ".join(unique_negative)
        
        return negative_prompt
    
    def _log_optimization(self, result: OptimizedPrompt):
        """
        记录优化结果
        
        Args:
            result: 优化结果
        """
        logger.info(
            f"提示词优化完成 - 模式: {result.optimization_mode}, "
            f"单词数: {result.word_count}, "
            f"添加关键词数: {len(result.added_keywords)}"
        )
        logger.debug(f"原始提示词: {result.original_prompt}")
        logger.debug(f"优化后提示词: {result.positive_prompt}")
        logger.debug(f"负面提示词: {result.negative_prompt}")
        logger.debug(f"添加的关键词: {', '.join(result.added_keywords)}")
    
    def optimize_for_scene(
        self,
        prompt: str,
        scene_type: str,
        enable_realism: bool = False
    ) -> OptimizedPrompt:
        """
        根据场景类型优化提示词
        
        Args:
            prompt: 原始提示词
            scene_type: 场景类型（portrait, landscape, action等）
            enable_realism: 是否启用真实感模式
            
        Returns:
            优化后的提示词对象
        """
        # 根据场景类型选择优化模式
        if enable_realism:
            mode = OptimizationMode.REALISM
        elif scene_type in ["portrait", "close_up", "full_body"]:
            # 人物场景：平衡模式
            mode = OptimizationMode.BALANCED
        elif scene_type in ["landscape", "wide_shot"]:
            # 风景场景：艺术模式
            mode = OptimizationMode.ARTISTIC
        else:
            # 其他场景：质量模式
            mode = OptimizationMode.QUALITY
        
        # 根据场景类型添加特定关键词
        custom_keywords = []
        if scene_type == "portrait":
            custom_keywords = ["portrait photography", "face focus", "detailed face"]
        elif scene_type == "landscape":
            custom_keywords = ["landscape photography", "wide angle", "scenic view"]
        elif scene_type == "action":
            custom_keywords = ["action shot", "dynamic pose", "motion blur"]
        
        return self.optimize(
            prompt=prompt,
            mode=mode,
            custom_keywords=custom_keywords
        )


# 全局提示词优化器实例（单例模式）
_prompt_optimizer_instance: Optional[PromptOptimizer] = None


def get_prompt_optimizer() -> PromptOptimizer:
    """
    获取全局提示词优化器实例（单例模式）
    
    Returns:
        提示词优化器实例
    """
    global _prompt_optimizer_instance
    
    if _prompt_optimizer_instance is None:
        _prompt_optimizer_instance = PromptOptimizer()
        logger.info("全局提示词优化器实例创建成功")
    
    return _prompt_optimizer_instance


def cleanup_prompt_optimizer():
    """
    清理全局提示词优化器实例
    
    用于应用关闭时释放资源
    """
    global _prompt_optimizer_instance
    
    if _prompt_optimizer_instance is not None:
        _prompt_optimizer_instance = None
        logger.info("全局提示词优化器实例已清理")
