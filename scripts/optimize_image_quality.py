"""
图像质量优化脚本

自动应用图像质量优化配置
"""

import json
import shutil
from pathlib import Path


def backup_file(file_path):
    """备份文件"""
    backup_path = f"{file_path}.backup"
    if Path(file_path).exists():
        shutil.copy(file_path, backup_path)
        print(f"✅ 已备份: {file_path} -> {backup_path}")
    return backup_path


def optimize_image_task():
    """优化图像生成任务参数"""
    file_path = "src/tasks/image_tasks.py"
    
    print("\n" + "="*60)
    print("优化图像生成任务参数")
    print("="*60)
    
    # 备份原文件
    backup_file(file_path)
    
    # 读取文件
    with open(file_path, "r", encoding="utf-8") as f:
        content = f.read()
    
    # 替换参数
    replacements = [
        ('width=kwargs.get("width", 1024)', 'width=kwargs.get("width", 1280)'),
        ('height=kwargs.get("height", 576)', 'height=kwargs.get("height", 720)'),
        ('steps=kwargs.get("steps", 30)', 'steps=kwargs.get("steps", 35)'),
        ('cfg_scale=kwargs.get("cfg_scale", 7.5)', 'cfg_scale=kwargs.get("cfg_scale", 8.0)'),
    ]
    
    modified = False
    for old, new in replacements:
        if old in content:
            content = content.replace(old, new)
            modified = True
            print(f"  ✅ 已修改: {old} -> {new}")
    
    if modified:
        # 写回文件
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(content)
        print(f"\n✅ 文件已更新: {file_path}")
    else:
        print(f"\n⚠️  未找到需要修改的内容")


def optimize_prompt_enhancer():
    """优化提示词增强器"""
    file_path = "src/services/prompt_enhancer.py"
    
    print("\n" + "="*60)
    print("优化提示词增强器")
    print("="*60)
    
    # 备份原文件
    backup_file(file_path)
    
    # 读取文件
    with open(file_path, "r", encoding="utf-8") as f:
        content = f.read()
    
    # 新的 system_prompt
    new_system_prompt = '''"""你是一个专业的 Stable Diffusion XL 图像提示词工程师。你的任务是将简短的场景描述转换为高质量、专业的图像生成提示词。

要求：
1. 使用英文输出（Stable Diffusion 对英文理解更好）
2. **必须包含以下要素**：
   - **质量标签（必须放在最前面）**：(masterpiece:1.2), (best quality:1.2), (ultra-detailed:1.2), (photorealistic:1.3), (8k:1.1)
   - **主体描述（人物必须明确出现）**：如果有角色，用 "1girl/1boy/1man/1woman [角色名]" 明确标注
   - **细节描述**：面部细节、服装细节、动作、表情、姿态
   - **环境/背景**：具体的场景、道具、氛围
   - **光影效果**：cinematic lighting, dramatic shadows, natural light, soft ambient light
   - **艺术风格**：professional photography, cinematic composition, film grain
   - **构图和视角**：camera angle, depth of field, focus
3. **强制规则**：
   - 质量标签必须放在最前面，使用权重语法 (tag:1.2)
   - 如果场景中有角色，必须在质量标签后立即标注人物
   - 添加详细的光影描述（cinematic lighting, dramatic shadows等）
   - 添加摄影专业术语（shallow depth of field, bokeh, film grain等）
   - 确保人物的面部、服装、动作都有详细描述
4. 保持详细但不冗余，80-120 个单词
5. 使用逗号分隔不同的描述元素

示例输入："白月光车祸现场"
示例输出："(masterpiece:1.2), (best quality:1.2), (ultra-detailed:1.2), (photorealistic:1.3), cinematic shot of a car accident scene at night, broken glass scattered on wet asphalt road, emergency lights flashing red and blue, dramatic lighting with rain falling, smoke rising from damaged vehicle, professional photography, moody atmosphere, shallow depth of field, film grain, 8k resolution, high detail, realistic textures, cinematic composition"

示例输入："苏晚拿着匿名信站在花园里"
示例输出："(masterpiece:1.2), (best quality:1.2), (ultra-detailed:1.2), (photorealistic:1.3), 1woman Su Wan, standing in elegant garden holding anonymous letter, calm and thoughtful expression, detailed facial features, beautiful eyes, elegant traditional dress with intricate patterns, Lin Family estate background with blooming flowers, soft natural lighting, golden hour, cinematic composition, shallow depth of field, bokeh background, professional photography, 8k resolution, film grain, realistic skin texture"

请严格按照上述要求生成提示词。**确保质量标签在最前面，人物描述详细具体**。"""'''
    
    # 查找并替换 system_prompt
    import re
    pattern = r'system_prompt = """.*?"""'
    if re.search(pattern, content, re.DOTALL):
        content = re.sub(pattern, f'system_prompt = {new_system_prompt}', content, flags=re.DOTALL)
        print("  ✅ 已更新 system_prompt")
        
        # 写回文件
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(content)
        print(f"\n✅ 文件已更新: {file_path}")
    else:
        print(f"\n⚠️  未找到 system_prompt")


def optimize_comfyui_config():
    """优化 ComfyUI 配置"""
    file_path = "configs/comfyui_workflow_sdxl.json"
    
    print("\n" + "="*60)
    print("优化 ComfyUI 配置")
    print("="*60)
    
    if not Path(file_path).exists():
        print(f"⚠️  配置文件不存在: {file_path}")
        return
    
    # 备份原文件
    backup_file(file_path)
    
    # 读取配置
    with open(file_path, "r", encoding="utf-8") as f:
        config = json.load(f)
    
    # 更新负面提示词
    if "negative_prompt" not in config:
        config["negative_prompt"] = {}
    
    config["negative_prompt"]["default"] = "(worst quality:1.4), (low quality:1.4), (normal quality:1.4), lowres, bad anatomy, bad hands, text, error, missing fingers, extra digit, fewer digits, cropped, jpeg artifacts, signature, watermark, username, blurry, artist name, monochrome, grayscale, deformed, disfigured, ugly, gross proportions, malformed limbs, missing arms, missing legs, extra arms, extra legs, mutated hands, fused fingers, too many fingers, long neck, cross-eyed, mutated, mutation, poorly drawn hands, poorly drawn face, bad proportions, duplicate, cloned face, out of frame"
    
    print("  ✅ 已更新负面提示词")
    
    # 更新默认参数
    if "parameters" not in config:
        config["parameters"] = {}
    if "default" not in config["parameters"]:
        config["parameters"]["default"] = {}
    
    config["parameters"]["default"].update({
        "width": 1280,
        "height": 720,
        "steps": 35,
        "cfg_scale": 8.0,
        "sampler_name": "dpmpp_2m_karras",
        "scheduler": "karras"
    })
    
    print("  ✅ 已更新默认参数")
    
    # 写回文件
    with open(file_path, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=2, ensure_ascii=False)
    
    print(f"\n✅ 文件已更新: {file_path}")


def print_next_steps():
    """打印后续步骤"""
    print("\n" + "="*60)
    print("✅ 优化完成!")
    print("="*60)
    print("\n📝 后续步骤:")
    print("\n1. 下载高质量模型:")
    print("   - Juggernaut XL v9: https://civitai.com/models/133005/juggernaut-xl")
    print("   - 放置到: ComfyUI/models/checkpoints/")
    print("\n2. 修改 ComfyUI 工作流配置:")
    print("   - 编辑: configs/comfyui_workflow_sdxl.json")
    print("   - 修改 CheckpointLoaderSimple 的 ckpt_name 为新模型名称")
    print("\n3. 重启服务:")
    print("   - 重启 ComfyUI")
    print("   - 重启 Celery Worker")
    print("   - 重启后端")
    print("\n4. 测试:")
    print("   - 创建新项目")
    print("   - 生成剧本")
    print("   - 开始制作")
    print("   - 查看图像质量")
    print("\n📚 详细文档:")
    print("   - docs/图像质量优化方案.md")
    print("\n" + "="*60)


def main():
    """主函数"""
    print("="*60)
    print("图像质量优化脚本")
    print("="*60)
    print("\n⚠️  注意: 此脚本会修改以下文件:")
    print("  - src/tasks/image_tasks.py")
    print("  - src/services/prompt_enhancer.py")
    print("  - configs/comfyui_workflow_sdxl.json")
    print("\n原文件会自动备份为 .backup 文件")
    
    response = input("\n是否继续? (y/n): ")
    if response.lower() != 'y':
        print("已取消")
        return
    
    # 执行优化
    optimize_image_task()
    optimize_prompt_enhancer()
    optimize_comfyui_config()
    
    # 打印后续步骤
    print_next_steps()


if __name__ == "__main__":
    main()
