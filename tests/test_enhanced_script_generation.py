"""
测试增强版剧本生成功能
"""

import sys
import os

# 添加项目根目录到 Python 路径
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from src.services.enhanced_script_prompt import generate_enhanced_script_prompt


def test_enhanced_prompt_generation():
    """测试增强版 Prompt 生成"""
    print("=" * 80)
    print("测试增强版剧本生成 Prompt")
    print("=" * 80)
    
    # 生成增强版 Prompt
    prompt = generate_enhanced_script_prompt(
        theme="都市爱情",
        outline="一个工作狂高管在深夜加班时，遇到了一个温暖的设计师，两人从陌生到相识，最终走到一起",
        num_scenes=12,
        num_characters=2,
        style="现代都市",
        num_chapters=3
    )
    
    print(f"\n生成的 Prompt 长度: {len(prompt)} 字符")
    print(f"\n前 500 字符预览:")
    print("-" * 80)
    print(prompt[:500])
    print("-" * 80)
    
    # 验证 Prompt 包含关键元素
    assert "【故事大纲】" in prompt, "Prompt 应包含故事大纲部分"
    assert "【角色】" in prompt, "Prompt 应包含角色部分"
    assert "【第一章" in prompt, "Prompt 应包含第一章"
    assert "章节概述" in prompt, "Prompt 应包含章节概述"
    assert "故事节点" in prompt, "Prompt 应包含故事节点"
    assert "环境描述" in prompt, "Prompt 应包含环境描述"
    assert "至少50字" in prompt, "Prompt 应包含字数要求"
    
    print("\n✅ 所有验证通过！")
    print("\n增强版 Prompt 包含以下关键元素：")
    print("  - 故事大纲（200-300字）")
    print("  - 角色详细设定（每个角色100+字）")
    print("  - 章节结构（3章）")
    print("  - 详细分镜描述（每个分镜200+字）")
    print("  - 多维度描述要求（环境、人物、镜头、光线、氛围）")


def test_prompt_structure():
    """测试 Prompt 结构完整性"""
    print("\n" + "=" * 80)
    print("测试 Prompt 结构完整性")
    print("=" * 80)
    
    prompt = generate_enhanced_script_prompt(
        theme="科幻冒险",
        outline="未来世界，人类与AI共存，主角发现了一个惊天秘密",
        num_scenes=15,
        num_characters=3,
        style="科幻未来",
        num_chapters=5
    )
    
    # 检查章节数量
    chapter_count = prompt.count("【第")
    print(f"\n检测到章节数量: {chapter_count}")
    
    # 检查关键字段
    required_fields = [
        "故事节点",
        "环境描述",
        "人物描述",
        "镜头描述",
        "光线描述",
        "氛围描述",
        "出现角色",
        "对话",
        "说话人",
        "情感"
    ]
    
    print("\n检查必需字段:")
    for field in required_fields:
        if field in prompt:
            print(f"  ✅ {field}")
        else:
            print(f"  ❌ {field} (缺失)")
            raise AssertionError(f"Prompt 缺少必需字段: {field}")
    
    print("\n✅ Prompt 结构完整！")


def test_different_parameters():
    """测试不同参数组合"""
    print("\n" + "=" * 80)
    print("测试不同参数组合")
    print("=" * 80)
    
    test_cases = [
        {
            "name": "最小配置",
            "params": {
                "theme": "爱情",
                "num_scenes": 5,
                "num_characters": 2,
                "num_chapters": 1
            }
        },
        {
            "name": "中等配置",
            "params": {
                "theme": "悬疑",
                "outline": "一个侦探调查连环案件",
                "num_scenes": 10,
                "num_characters": 3,
                "num_chapters": 3
            }
        },
        {
            "name": "大型配置",
            "params": {
                "theme": "史诗奇幻",
                "outline": "英雄拯救世界的冒险旅程",
                "num_scenes": 20,
                "num_characters": 5,
                "num_chapters": 5
            }
        }
    ]
    
    for test_case in test_cases:
        print(f"\n测试: {test_case['name']}")
        print(f"  参数: {test_case['params']}")
        
        try:
            prompt = generate_enhanced_script_prompt(**test_case['params'])
            print(f"  ✅ 生成成功，长度: {len(prompt)} 字符")
        except Exception as e:
            print(f"  ❌ 生成失败: {e}")
            raise
    
    print("\n✅ 所有参数组合测试通过！")


if __name__ == "__main__":
    try:
        test_enhanced_prompt_generation()
        test_prompt_structure()
        test_different_parameters()
        
        print("\n" + "=" * 80)
        print("🎉 所有测试通过！增强版剧本生成功能正常工作。")
        print("=" * 80)
        
    except Exception as e:
        print(f"\n❌ 测试失败: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
