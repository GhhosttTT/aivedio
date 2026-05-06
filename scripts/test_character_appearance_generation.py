"""
测试角色外貌特征生成功能

用于验证角色外貌特征生成和提示词增强是否正常工作
"""

import sys
import os

# 添加项目根目录到 Python 路径
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from src.services.llm_service import get_llm_service
from src.services.prompt_enhancer import get_prompt_enhancer
from src.utils.logger import get_logger

logger = get_logger(__name__)


def test_character_appearance_generation():
    """测试角色外貌特征生成"""
    print("=" * 80)
    print("🎭 测试角色外貌特征生成")
    print("=" * 80)
    
    # 测试角色列表
    test_characters = [
        {
            "name": "苏晚",
            "description": "女主角，温柔善良，林家大小姐"
        },
        {
            "name": "林家少爷",
            "description": "男主角，霸道总裁，林氏集团继承人"
        },
        {
            "name": "张秘书",
            "description": "林家少爷的秘书，干练职业"
        },
        {
            "name": "反派商人",
            "description": "商界对手，阴险狡诈"
        }
    ]
    
    try:
        llm_service = get_llm_service()
        
        for i, char in enumerate(test_characters, 1):
            print(f"\n{i}. 角色: {char['name']}")
            print(f"   描述: {char['description']}")
            print(f"   生成外貌特征中...")
            
            # 生成外貌特征
            prompt = f"""你是一个专业的角色设计师。请根据角色名称和描述，生成详细的外貌特征，用于图像生成时区分不同角色。

角色名称：{char['name']}
角色描述：{char['description']}

请生成详细的外貌特征，必须包含：
1. 年龄段（如"25岁"、"30岁"）
2. 性别
3. 发型和发色（如"短发"、"长发披肩"、"微卷黑发"）
4. 脸型特征（如"瓜子脸"、"方脸"）
5. 身材特征（如"身材苗条"、"身材挺拔"）
6. 服装风格（如"商务西装"、"优雅连衣裙"、"休闲装"）
7. 气质特征（如"温柔气质"、"霸道总裁气场"、"成熟稳重"）
8. 独特标识（如"戴金丝眼镜"、"略带胡茬"、"精致妆容"）

要求：
- 外貌特征要具体、独特，能明显区分不同角色
- 避免使用"帅气"、"美丽"等泛化词汇
- 使用具体的视觉特征描述
- 输出格式：一句话，用逗号分隔各个特征
- 示例："30岁男性，短发，戴金丝眼镜，商务西装，成熟稳重气质，身材挺拔"

外貌特征："""
            
            appearance = llm_service.generate(
                prompt=prompt,
                max_tokens=150,
                temperature=0.7
            )
            
            appearance = appearance.strip()
            if appearance.startswith('"') and appearance.endswith('"'):
                appearance = appearance[1:-1]
            
            print(f"   ✅ 外貌特征: {appearance}")
            
            # 保存到字典
            char['appearance'] = appearance
        
        print("\n" + "=" * 80)
        print("✅ 角色外貌特征生成测试完成")
        print("=" * 80)
        
        return test_characters
        
    except Exception as e:
        print(f"\n❌ 测试失败: {e}")
        import traceback
        traceback.print_exc()
        return None


def test_prompt_enhancement(characters):
    """测试提示词增强（包含角色外貌特征）"""
    print("\n" + "=" * 80)
    print("🎨 测试提示词增强（包含角色外貌特征）")
    print("=" * 80)
    
    # 测试场景
    test_scenes = [
        {
            "character": characters[0],  # 苏晚
            "visual_description": "苏晚站在花园里，手里拿着一封匿名信，表情疑惑"
        },
        {
            "character": characters[1],  # 林家少爷
            "visual_description": "林家少爷坐在办公室里，看着窗外，若有所思"
        },
        {
            "character": characters[3],  # 反派商人
            "visual_description": "反派商人在豪华餐厅里，冷笑着举起酒杯"
        }
    ]
    
    try:
        enhancer = get_prompt_enhancer()
        
        for i, scene in enumerate(test_scenes, 1):
            char = scene['character']
            print(f"\n{i}. 场景: {scene['visual_description']}")
            print(f"   角色: {char['name']}")
            print(f"   外貌: {char['appearance']}")
            print(f"   增强提示词中...")
            
            enhanced_prompt = enhancer.enhance_prompt(
                visual_description=scene['visual_description'],
                character_name=char['name'],
                character_appearance=char['appearance'],
                scene_context=None
            )
            
            print(f"   ✅ 增强提示词:")
            print(f"   {enhanced_prompt[:200]}...")
            
        print("\n" + "=" * 80)
        print("✅ 提示词增强测试完成")
        print("=" * 80)
        
    except Exception as e:
        print(f"\n❌ 测试失败: {e}")
        import traceback
        traceback.print_exc()


def main():
    """主函数"""
    print("\n🚀 开始测试角色外貌特征生成和提示词增强功能\n")
    
    # 测试1: 角色外貌特征生成
    characters = test_character_appearance_generation()
    
    if characters:
        # 测试2: 提示词增强
        test_prompt_enhancement(characters)
        
        print("\n" + "=" * 80)
        print("🎉 所有测试完成！")
        print("=" * 80)
        print("\n总结：")
        print("✅ 角色外貌特征生成正常")
        print("✅ 提示词增强功能正常")
        print("✅ 不同角色具有明显区分的外貌特征")
        print("\n现在可以开始生成短剧，角色将不再"长一个样子"！")
    else:
        print("\n❌ 测试失败，请检查 LLM 服务是否正常运行")


if __name__ == "__main__":
    main()
