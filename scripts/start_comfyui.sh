#!/bin/bash
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
