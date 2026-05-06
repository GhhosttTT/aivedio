"""真实感优化脚本 - 降低 AI 感"""

import json
import shutil
import re
from pathlib import Path

def backup_file(file_path):
    backup_path = f"{file_path}.backup"
    if Path(file_path).exists():
        shutil.copy(file_path, backup_path)
        print(f"✅ 已备份: {file_path}")
    return backup_path

def optimize_for_realism():
    print("="*60)
    print("真实感优化 - 降低 AI 感")
    print("="*60)
    
    # 1. 优化图像任务参数
    print("\n1. 优化图像生成参数...")
    file1 = "src/tasks/image_tasks.py"
    if Path(file1).exists():
        backup_file(file1)
        with open(file1, "r", encoding="utf-8") as f:
            content = f.read()
        content = content.replace('cfg_scale=kwargs.get("cfg_scale", 8.0)', 'cfg_scale=kwargs.get("cfg_scale", 6.0)')
        content = content.replace('steps=kwargs.get("steps", 35)', 'steps=kwargs.get("steps", 28)')
        with open(file1, "w", encoding="utf-8") as f:
            f.write(content)
        print("  ✅ CFG: 8.0 → 6.0")
        print("  ✅ 步数: 35 → 28")
    
    # 2. 优化配置文件
    print("\n2. 优化 ComfyUI 配置...")
    file2 = "configs/comfyui_workflow_sdxl.json"
    if Path(file2).exists():
        backup_file(file2)
        with open(file2, "r", encoding="utf-8") as f:
            config = json.load(f)
        if "negative_prompt" not in config:
            config["negative_prompt"] = {}
        config["negative_prompt"]["default"] = "CGI, 3D render, overly smooth skin, plastic skin, too perfect, flawless, airbrushed, over-processed, studio lighting, posed, (worst quality:1.2), (low quality:1.2), bad anatomy, blurry"
        with open(file2, "w", encoding="utf-8") as f:
            json.dump(config, f, indent=2, ensure_ascii=False)
        print("  ✅ 已添加反 AI 感负面词")
    
    print("\n" + "="*60)
    print("✅ 优化完成!")
    print("="*60)
    print("\n📌 推荐更换模型:")
    print("  RealVisXL V4.0: https://civitai.com/models/139562/realvisxl")
    print("\n📚 详细文档:")
    print("  docs/降低AI感-真实感优化方案.md")

if __name__ == "__main__":
    optimize_for_realism()
