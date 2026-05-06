"""
角色参考图生成器
使用 LLM 生成详细的角色描述，然后创建高质量参考图
"""
import json
from typing import Dict, Optional, List
from loguru import logger


class CharacterReferenceGenerator:
    """角色参考图生成器"""
    
    def __init__(self, llm_service=None):
        self.llm_service = llm_service
        
    def generate_character_description(self, character_name: str, role: str = "", personality: str = "") -> Dict:
        """
        使用 LLM 生成详细的角色外貌描述
        
        Args:
            character_name: 角色名称
            role: 角色身份/职业
            personality: 性格特点
            
        Returns:
            JSON 格式的角色描述
        """
        if not self.llm_service:
            # 如果没有 LLM，返回默认模板
            return self._get_default_character_template(character_name)
        
        try:
            system_prompt = """你是一个专业的角色设计师和 AI 绘画提示词工程师。请为角色创建详细的外貌描述。

要求：
1. 描述要非常详细具体（年龄、脸型、五官、发型、身材、服装等）
2. 使用视觉化的语言，便于 AI 绘画理解
3. 包含正面、侧面、全身三个角度的描述
4. 输出 JSON 格式，包含以下字段：
   - name: 角色名
   - age: 年龄
   - gender: 性别
   - ethnicity: 种族/民族
   - face_shape: 脸型
   - eyes: 眼睛描述
   - nose: 鼻子描述
   - mouth: 嘴巴描述
   - hair: 发型和发色
   - body_type: 体型
   - height: 身高
   - clothing_style: 服装风格
   - outfit_details: 具体服装描述
   - skin_tone: 肤色
   - distinctive_features: 特征（痣、疤痕、纹身等）
   - expression_default: 默认表情
   - pose_front: 正面姿势描述
   - pose_side: 侧面姿势描述
   - pose_fullbody: 全身姿势描述
   - lighting_preference: 光线偏好
   - style_tags: 风格标签列表

示例输出：
{
  "name": "李明",
  "age": 28,
  "gender": "male",
  "ethnicity": "East Asian",
  "face_shape": "oval face with defined jawline",
  "eyes": "deep brown almond-shaped eyes, double eyelids, clear and bright",
  "nose": "straight nose bridge, moderate size",
  "mouth": "medium lips, natural pink color",
  "hair": "short black hair, slightly textured, side-parted, well-groomed",
  "body_type": "athletic build, toned muscles",
  "height": "180cm",
  "clothing_style": "modern business casual",
  "outfit_details": "white crisp button-down shirt, navy blue blazer, dark grey trousers",
  "skin_tone": "light tan Asian skin tone",
  "distinctive_features": "small mole on left cheek, clean-shaven",
  "expression_default": "confident and approachable smile",
  "pose_front": "standing straight, facing camera directly, hands relaxed at sides",
  "pose_side": "three-quarter view, looking slightly to the side",
  "pose_fullbody": "full body shot, standing confidently, one hand in pocket",
  "lighting_preference": "soft natural lighting from front-left",
  "style_tags": ["photorealistic", "professional", "cinematic", "high quality"]
}"""
            
            user_prompt = f"""请为以下角色创建详细的外貌描述：

角色名称：{character_name}
角色身份：{role if role else '主角'}
性格特点：{personality if personality else '自信、专业'}

请输出 JSON 格式的角色描述。"""
            
            response = self.llm_service.chat(
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                temperature=0.8,
                max_tokens=1500
            )
            
            # 解析 JSON
            try:
                # 提取 JSON 部分
                json_start = response.find('{')
                json_end = response.rfind('}') + 1
                if json_start != -1 and json_end != -1:
                    json_str = response[json_start:json_end]
                    character_data = json.loads(json_str)
                    logger.info(f"角色 '{character_name}' 描述生成成功")
                    return character_data
                else:
                    raise ValueError("未找到 JSON 内容")
            except Exception as e:
                logger.warning(f"JSON 解析失败，使用默认模板: {e}")
                return self._get_default_character_template(character_name)
                
        except Exception as e:
            logger.error(f"生成角色描述失败: {e}")
            return self._get_default_character_template(character_name)
    
    def generate_reference_prompts(self, character_data: Dict) -> Dict[str, str]:
        """
        基于角色数据生成多个角度的参考图提示词
        
        Args:
            character_data: 角色描述 JSON
            
        Returns:
            包含不同角度提示词的字典
        """
        # 高质量基础标签 - 电影级人像摄影风格
        base_quality = "masterpiece, best quality, ultra-detailed, 8k uhd, RAW photo, photorealistic, realistic, cinematic, professional photography"
        
        # 精致面部关键词
        face_details = "beautiful detailed face, delicate facial features, flawless skin, soft natural makeup, expressive eyes with catchlights, perfect symmetry, natural skin texture"
        
        # 专业摄影参数
        camera_specs = "shot on professional DSLR, 85mm f/1.4 lens, shallow depth of field, sharp focus on face, bokeh background"
        
        # 电影级光线
        lighting = "cinematic lighting, soft diffused light, warm golden tones, volumetric lighting, rim light, lens flare, professional color grading"
        
        # 构建基础描述
        appearance = f"{character_data.get('age', 25)} year old {character_data.get('ethnicity', 'Asian')} {character_data.get('gender', 'male')}"
        face = f"{character_data.get('face_shape', 'oval face')}, {character_data.get('eyes', 'brown eyes')}, {character_data.get('nose', 'straight nose')}, {character_data.get('mouth', 'natural lips')}"
        hair = f"{character_data.get('hair', 'black hair')}, detailed hair strands, realistic hair texture"
        body = f"{character_data.get('body_type', 'athletic build')}, {character_data.get('height', 'average height')}"
        outfit = f"{character_data.get('outfit_details', 'elegant clothing')}, highly detailed clothing, intricate patterns, rich textures"
        skin = character_data.get('skin_tone', 'natural skin tone')
        
        # 强力负面提示词
        negative_prompt = "(worst quality, low quality:1.8), (ugly, deformed, distorted:1.6), disfigured, bad anatomy, bad hands, missing limbs, extra limbs, fused fingers, too many fingers, long neck, mutation, mutated, blurry, out of focus, jpeg artifacts, text, watermark, signature, logo, (cartoon:1.8), (anime:1.8), (illustration:1.8), (painting:1.8), (drawing:1.8), (sketch:1.8), (artwork:1.8), (digital art:1.8), (3d render:1.6), (cgi:1.6), plastic skin, doll-like, nsfw, nude, gross proportions, malformed limbs, bad proportions, extra arms, extra legs, poorly drawn face, flat color, vector art, comic book, manga, chibi, simple shading, low detail"
        
        # 生成三个角度的提示词
        prompts = {
            "front_closeup": {
                "prompt": f"{base_quality}, ({appearance}:1.2), ({face}:1.3), {face_details}, ({hair}:1.1), ({skin}:1.1), close-up portrait, facing camera directly, {character_data.get('expression_default', 'gentle smile')}, {camera_specs}, {lighting}, highly detailed, elegant, graceful",
                "negative": negative_prompt,
                "description": "正面特写（用于面部识别）- 电影级精致人像"
            },
            "half_body": {
                "prompt": f"{base_quality}, ({appearance}:1.2), ({hair}:1.1), ({outfit}:1.3), half-body shot, waist up, {character_data.get('pose_front', 'elegant standing pose')}, confident posture, {face_details}, {camera_specs}, {lighting}, highly detailed clothing, rich textures, elegant, graceful",
                "negative": negative_prompt,
                "description": "半身照（用于服装和姿态）- 华丽服饰细节"
            },
            "full_body": {
                "prompt": f"{base_quality}, ({appearance}:1.2), ({body}:1.1), ({hair}:1.1), ({outfit}:1.3), full body shot, {character_data.get('pose_fullbody', 'elegant standing pose')}, complete outfit visible, proportional body, {face_details}, {camera_specs}, {lighting}, highly detailed, elegant draping, sophisticated",
                "negative": negative_prompt,
                "description": "全身照（用于整体形象）- 完整造型展示"
            }
        }
        
        logger.info(f"生成了 {len(prompts)} 个高质量参考图提示词（电影级人像风格）")
        return prompts
    
    def _get_default_character_template(self, name: str) -> Dict:
        """获取默认角色模板"""
        return {
            "name": name,
            "age": 25,
            "gender": "male",
            "ethnicity": "East Asian",
            "face_shape": "oval face with defined jawline",
            "eyes": "deep brown almond-shaped eyes, double eyelids",
            "nose": "straight nose bridge",
            "mouth": "medium lips, natural color",
            "hair": "short black hair, slightly textured, side-parted",
            "body_type": "athletic build",
            "height": "175-180cm",
            "clothing_style": "modern casual",
            "outfit_details": "white shirt, dark jacket, jeans",
            "skin_tone": "light tan Asian skin",
            "distinctive_features": "clean-shaven, neat appearance",
            "expression_default": "confident slight smile",
            "pose_front": "facing camera, relaxed posture",
            "pose_side": "three-quarter view",
            "pose_fullbody": "standing naturally, hands at sides",
            "lighting_preference": "soft natural lighting",
            "style_tags": ["photorealistic", "professional", "high quality"]
        }


# 测试
if __name__ == "__main__":
    generator = CharacterReferenceGenerator()
    
    # 测试生成角色描述
    character = generator.generate_character_description(
        character_name="张伟",
        role="年轻企业家",
        personality="自信、果断、有魅力"
    )
    
    print("\n角色描述:")
    print(json.dumps(character, ensure_ascii=False, indent=2))
    
    # 生成参考图提示词
    prompts = generator.generate_reference_prompts(character)
    
    print("\n\n参考图提示词:")
    for angle, data in prompts.items():
        print(f"\n[{angle}] {data['description']}")
        print(f"Prompt: {data['prompt'][:150]}...")
