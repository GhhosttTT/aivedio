#!/bin/bash
# ComfyUI 启动脚本
PORT="${COMFYUI_PORT:-8188}"
COMFYUI_DIR="${COMFYUI_DIR:-}"

if [ -z "$COMFYUI_DIR" ]; then
    for candidate in ./ComfyUI ./comfyui ../ComfyUI; do
        if [ -d "$candidate" ]; then
            COMFYUI_DIR="$candidate"
            break
        fi
    done
fi

if [ -z "$COMFYUI_DIR" ] || [ ! -d "$COMFYUI_DIR" ]; then
    echo "错误: 未找到 ComfyUI 目录（可通过 COMFYUI_DIR 指定）"
    exit 1
fi

cd "$COMFYUI_DIR" || exit 1

if [ -d "venv" ]; then
    # shellcheck disable=SC1091
    source venv/bin/activate 2>/dev/null || source venv/Scripts/activate
fi

PYTHON_BIN="python3"
command -v python3 >/dev/null 2>&1 || PYTHON_BIN="python"
exec "$PYTHON_BIN" main.py --listen 0.0.0.0 --port "$PORT"
