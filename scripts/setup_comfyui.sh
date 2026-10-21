#!/bin/bash

# AI 短剧自动化生产平台 - ComfyUI 安装和配置脚本
# 此脚本用于安装和配置 ComfyUI 服务

set -e  # 遇到错误立即退出

# 颜色输出
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# ComfyUI 目录（兼容 ComfyUI/ 与 comfyui/，可用 COMFYUI_DIR 覆盖）
COMFYUI_DIR="${COMFYUI_DIR:-}"
if [ -z "$COMFYUI_DIR" ]; then
    for candidate in ./ComfyUI ./comfyui; do
        if [ -d "$candidate" ]; then
            COMFYUI_DIR="$candidate"
            break
        fi
    done
fi
COMFYUI_DIR="${COMFYUI_DIR:-./ComfyUI}"
MODELS_DIR="./models"

echo -e "${GREEN}=== ComfyUI 安装和配置脚本 ===${NC}"
echo ""

# 检查依赖
check_dependencies() {
    echo -e "${YELLOW}检查依赖...${NC}"
    
    # 检查 Git
    if ! command -v git &> /dev/null; then
        echo -e "${RED}错误: 需要安装 Git${NC}"
        exit 1
    fi
    
    # 检查 Python
    PYTHON_BIN="$(command -v python3 || command -v python || true)"
    if [ -z "$PYTHON_BIN" ]; then
        echo -e "${RED}错误: 需要安装 Python 3.10+${NC}"
        exit 1
    fi

    # 检查 Python 版本（避免依赖 bc）
    python_version="$("$PYTHON_BIN" -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')"
    if ! "$PYTHON_BIN" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)'; then
        echo -e "${RED}错误: Python 版本需要 >= 3.10，当前版本: $python_version${NC}"
        exit 1
    fi
    
    echo -e "${GREEN}✓ 依赖检查完成${NC}"
    echo ""
}

# 克隆 ComfyUI 仓库
clone_comfyui() {
    echo -e "${GREEN}=== 1. 克隆 ComfyUI 仓库 ===${NC}"
    
    if [ -d "$COMFYUI_DIR" ]; then
        echo -e "${YELLOW}ComfyUI 目录已存在，跳过克隆${NC}"
        echo "如需重新安装，请删除目录: $COMFYUI_DIR"
        echo ""
        return 0
    fi
    
    echo "克隆 ComfyUI 仓库..."
    git clone https://github.com/comfyanonymous/ComfyUI.git "$COMFYUI_DIR"
    
    if [ $? -eq 0 ]; then
        echo -e "${GREEN}✓ ComfyUI 克隆完成${NC}"
        echo ""
    else
        echo -e "${RED}✗ ComfyUI 克隆失败${NC}"
        exit 1
    fi
}

# 安装 ComfyUI 依赖
install_dependencies() {
    echo -e "${GREEN}=== 2. 安装 ComfyUI 依赖 ===${NC}"
    
    cd "$COMFYUI_DIR"
    
    # 检查是否有虚拟环境
    if [ ! -d "venv" ]; then
        echo "创建 Python 虚拟环境..."
        "${PYTHON_BIN:-python3}" -m venv venv
    fi
    
    # 激活虚拟环境
    echo "激活虚拟环境..."
    source venv/bin/activate || source venv/Scripts/activate
    
    # 升级 pip
    echo "升级 pip..."
    pip install --upgrade pip
    
    # 安装依赖
    echo "安装 ComfyUI 依赖..."
    pip install -r requirements.txt
    
    # 安装 PyTorch（GPU 版本）
    echo "安装 PyTorch (CUDA 11.8)..."
    pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu118
    
    cd ..
    
    echo -e "${GREEN}✓ 依赖安装完成${NC}"
    echo ""
}

# 链接模型文件
link_models() {
    echo -e "${GREEN}=== 3. 链接模型文件 ===${NC}"
    
    # 创建 ComfyUI 模型目录
    mkdir -p "$COMFYUI_DIR/models/checkpoints"
    mkdir -p "$COMFYUI_DIR/models/vae"
    mkdir -p "$COMFYUI_DIR/models/loras"
    
    # 链接 SDXL 模型
    local sdxl_model="$MODELS_DIR/stable-diffusion-xl-base-1.0/sd_xl_base_1.0.safetensors"
    local comfyui_checkpoint="$COMFYUI_DIR/models/checkpoints/sd_xl_base_1.0.safetensors"
    
    if [ -f "$sdxl_model" ]; then
        if [ ! -f "$comfyui_checkpoint" ]; then
            echo "链接 SDXL 模型到 ComfyUI..."
            # Windows 使用 mklink，Linux/Mac 使用 ln
            if [[ "$OSTYPE" == "msys" || "$OSTYPE" == "win32" ]]; then
                cmd //c mklink "$comfyui_checkpoint" "$(cygpath -w $sdxl_model)"
            else
                ln -s "$(pwd)/$sdxl_model" "$comfyui_checkpoint"
            fi
            echo -e "${GREEN}✓ SDXL 模型链接完成${NC}"
        else
            echo -e "${YELLOW}SDXL 模型已链接，跳过${NC}"
        fi
    else
        echo -e "${RED}✗ SDXL 模型文件不存在: $sdxl_model${NC}"
        echo "请先运行 scripts/download_models.sh 下载模型"
        exit 1
    fi
    
    echo ""
}

# 创建 ComfyUI 配置文件
create_config() {
    echo -e "${GREEN}=== 4. 创建 ComfyUI 配置文件 ===${NC}"
    
    local config_file="$COMFYUI_DIR/extra_model_paths.yaml"
    
    if [ -f "$config_file" ]; then
        echo -e "${YELLOW}配置文件已存在，跳过创建${NC}"
        echo ""
        return 0
    fi
    
    cat > "$config_file" << EOF
# ComfyUI 额外模型路径配置
# 用于指定自定义模型目录

# Stable Diffusion 模型路径
checkpoints: $(pwd)/$MODELS_DIR/stable-diffusion-xl-base-1.0

# VAE 模型路径
vae: $(pwd)/$MODELS_DIR/vae

# LoRA 模型路径
loras: $(pwd)/$MODELS_DIR/loras
EOF
    
    echo -e "${GREEN}✓ 配置文件创建完成${NC}"
    echo ""
}

# 创建启动脚本
create_startup_script() {
    echo -e "${GREEN}=== 5. 创建启动脚本 ===${NC}"
    
    local startup_script="scripts/start_comfyui.sh"
    
    cat > "$startup_script" << 'EOF'
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
EOF
    
    chmod +x "$startup_script"
    
    echo -e "${GREEN}✓ 启动脚本创建完成: $startup_script${NC}"
    echo ""
}

# 测试 ComfyUI API
test_comfyui_api() {
    echo -e "${GREEN}=== 6. 测试 ComfyUI API ===${NC}"
    
    echo -e "${YELLOW}提示: 需要先启动 ComfyUI 服务才能测试 API${NC}"
    echo ""
    echo "启动 ComfyUI:"
    echo "  bash scripts/start_comfyui.sh"
    echo ""
    echo "测试 API:"
    echo "  curl http://127.0.0.1:8188/system_stats"
    echo ""
}

# 显示安装摘要
show_summary() {
    echo -e "${GREEN}=== 安装摘要 ===${NC}"
    echo ""
    echo "ComfyUI 安装位置: $COMFYUI_DIR"
    echo "工作流配置文件: configs/comfyui_workflow.json"
    echo "启动脚本: scripts/start_comfyui.sh"
    echo ""
    echo -e "${GREEN}✓ ComfyUI 安装和配置完成！${NC}"
    echo ""
    echo "下一步:"
    echo "  1. 启动 ComfyUI 服务:"
    echo "     bash scripts/start_comfyui.sh"
    echo ""
    echo "  2. 验证 API 可访问性:"
    echo "     curl http://127.0.0.1:8188/system_stats"
    echo ""
    echo "  3. 访问 Web 界面:"
    echo "     http://127.0.0.1:8188"
    echo ""
}

# 主函数
main() {
    check_dependencies
    clone_comfyui
    install_dependencies
    link_models
    create_config
    create_startup_script
    test_comfyui_api
    show_summary
}

# 运行主函数
main
