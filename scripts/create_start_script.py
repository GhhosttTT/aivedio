#!/usr/bin/env python3
"""创建 ComfyUI 启动脚本"""

script_content = """#!/bin/bash
# ComfyUI 启动脚本
COMFYUI_DIR="./comfyui"
PORT=8188

if [ ! -d "$COMFYUI_DIR" ]; then
    echo "错误: ComfyUI 未安装"
    exit 1
fi

cd "$COMFYUI_DIR"

if [ -d "venv" ]; then
    source venv/bin/activate 2>/dev/null || source venv/Scripts/activate
fi

python main.py --listen 0.0.0.0 --port $PORT
"""

with open('scripts/start_comfyui.sh', 'w', encoding='utf-8', newline='\n') as f:
    f.write(script_content)

print("✓ 创建 scripts/start_comfyui.sh 完成")
