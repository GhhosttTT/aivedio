#!/bin/bash

# AI 短剧自动化生产平台 - 模型下载脚本
# 此脚本用于下载所有必需的 AI 模型

set -e  # 遇到错误立即退出

# 颜色输出
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# 模型存储目录
MODELS_DIR="./models"
mkdir -p "$MODELS_DIR"

echo -e "${GREEN}=== AI 模型下载脚本 ===${NC}"
echo "模型将下载到: $MODELS_DIR"
echo ""

# 检查是否安装了必要的工具
check_dependencies() {
    echo -e "${YELLOW}检查依赖工具...${NC}"
    
    if ! command -v wget &> /dev/null && ! command -v curl &> /dev/null; then
        echo -e "${RED}错误: 需要安装 wget 或 curl${NC}"
        exit 1
    fi
    
    if ! command -v sha256sum &> /dev/null && ! command -v shasum &> /dev/null; then
        echo -e "${YELLOW}警告: 未找到 sha256sum 或 shasum，将跳过文件完整性校验${NC}"
    fi
    
    echo -e "${GREEN}✓ 依赖检查完成${NC}"
    echo ""
}

# 下载文件函数
download_file() {
    local url=$1
    local output=$2
    
    echo -e "${YELLOW}下载: $output${NC}"
    echo "URL: $url"
    
    if command -v wget &> /dev/null; then
        wget -c "$url" -O "$output" || return 1
    elif command -v curl &> /dev/null; then
        curl -L -C - "$url" -o "$output" || return 1
    fi
    
    return 0
}

# 验证文件完整性
verify_checksum() {
    local file=$1
    local expected_checksum=$2
    
    if [ -z "$expected_checksum" ]; then
        echo -e "${YELLOW}跳过校验（未提供校验和）${NC}"
        return 0
    fi
    
    echo -e "${YELLOW}验证文件完整性...${NC}"
    
    if command -v sha256sum &> /dev/null; then
        local actual_checksum=$(sha256sum "$file" | awk '{print $1}')
    elif command -v shasum &> /dev/null; then
        local actual_checksum=$(shasum -a 256 "$file" | awk '{print $1}')
    else
        echo -e "${YELLOW}跳过校验（未找到校验工具）${NC}"
        return 0
    fi
    
    if [ "$actual_checksum" = "$expected_checksum" ]; then
        echo -e "${GREEN}✓ 文件完整性验证通过${NC}"
        return 0
    else
        echo -e "${RED}✗ 文件完整性验证失败${NC}"
        echo "期望: $expected_checksum"
        echo "实际: $actual_checksum"
        return 1
    fi
}

# 下载 Qwen2.5-14B GGUF 模型
download_qwen_model() {
    echo -e "${GREEN}=== 1. 下载 Qwen2.5-14B-Instruct GGUF 模型 ===${NC}"
    echo "大小: ~8GB"
    echo "用途: 剧本生成"
    echo ""
    
    local model_file="$MODELS_DIR/qwen2.5-14b-instruct-q4_k_m.gguf"
    
    if [ -f "$model_file" ]; then
        echo -e "${YELLOW}模型文件已存在，跳过下载${NC}"
        echo "如需重新下载，请删除: $model_file"
        echo ""
        return 0
    fi
    
    # HuggingFace 下载链接
    local model_url="https://huggingface.co/Qwen/Qwen2.5-14B-Instruct-GGUF/resolve/main/qwen2.5-14b-instruct-q4_k_m.gguf"
    
    echo -e "${YELLOW}提示: 此文件约 8GB，下载可能需要较长时间${NC}"
    echo -e "${YELLOW}如果下载中断，可以重新运行此脚本继续下载${NC}"
    echo ""
    
    if download_file "$model_url" "$model_file"; then
        echo -e "${GREEN}✓ Qwen2.5-14B 模型下载完成${NC}"
        # 注意: HuggingFace 不总是提供 SHA256，这里跳过校验
        echo ""
    else
        echo -e "${RED}✗ Qwen2.5-14B 模型下载失败${NC}"
        echo "请检查网络连接或手动下载"
        echo "下载地址: $model_url"
        return 1
    fi
}

# 下载 Stable Diffusion XL 模型
download_sdxl_model() {
    echo -e "${GREEN}=== 2. 下载 Stable Diffusion XL Base 模型 ===${NC}"
    echo "大小: ~6.9GB"
    echo "用途: 图像生成"
    echo ""
    
    local model_dir="$MODELS_DIR/stable-diffusion-xl-base-1.0"
    mkdir -p "$model_dir"
    
    local model_file="$model_dir/sd_xl_base_1.0.safetensors"
    
    if [ -f "$model_file" ]; then
        echo -e "${YELLOW}模型文件已存在，跳过下载${NC}"
        echo "如需重新下载，请删除: $model_file"
        echo ""
        return 0
    fi
    
    # HuggingFace 下载链接
    local model_url="https://huggingface.co/stabilityai/stable-diffusion-xl-base-1.0/resolve/main/sd_xl_base_1.0.safetensors"
    
    echo -e "${YELLOW}提示: 此文件约 6.9GB，下载可能需要较长时间${NC}"
    echo ""
    
    if download_file "$model_url" "$model_file"; then
        echo -e "${GREEN}✓ SDXL 模型下载完成${NC}"
        echo ""
    else
        echo -e "${RED}✗ SDXL 模型下载失败${NC}"
        echo "请检查网络连接或手动下载"
        echo "下载地址: $model_url"
        return 1
    fi
}

# 下载 Stable Video Diffusion 模型
download_svd_model() {
    echo -e "${GREEN}=== 3. 下载 Stable Video Diffusion (SVD) 模型 ===${NC}"
    echo "大小: ~3.8GB"
    echo "用途: 图生视频"
    echo ""
    
    local model_dir="$MODELS_DIR/stable-video-diffusion-img2vid-xt"
    mkdir -p "$model_dir"
    
    local model_file="$model_dir/svd_xt.safetensors"
    
    if [ -f "$model_file" ]; then
        echo -e "${YELLOW}模型文件已存在，跳过下载${NC}"
        echo "如需重新下载，请删除: $model_file"
        echo ""
        return 0
    fi
    
    # HuggingFace 下载链接
    local model_url="https://huggingface.co/stabilityai/stable-video-diffusion-img2vid-xt/resolve/main/svd_xt.safetensors"
    
    echo -e "${YELLOW}提示: 此文件约 3.8GB，下载可能需要较长时间${NC}"
    echo ""
    
    if download_file "$model_url" "$model_file"; then
        echo -e "${GREEN}✓ SVD 模型下载完成${NC}"
        echo ""
    else
        echo -e "${RED}✗ SVD 模型下载失败${NC}"
        echo "请检查网络连接或手动下载"
        echo "下载地址: $model_url"
        return 1
    fi
}

# 更新 .env 文件
update_env_file() {
    echo -e "${GREEN}=== 4. 更新 .env 配置文件 ===${NC}"
    
    local env_file=".env"
    
    if [ ! -f "$env_file" ]; then
        if [ -f ".env.example" ]; then
            echo "复制 .env.example 到 .env"
            cp .env.example .env
        else
            echo "创建新的 .env 文件"
            touch .env
        fi
    fi
    
    # 更新模型路径
    echo ""
    echo "配置模型路径到 .env 文件..."
    
    # 使用绝对路径
    local abs_models_dir=$(cd "$MODELS_DIR" && pwd)
    
    # 更新或添加配置
    if grep -q "^LLM_MODEL_PATH=" "$env_file"; then
        sed -i.bak "s|^LLM_MODEL_PATH=.*|LLM_MODEL_PATH=$abs_models_dir/qwen2.5-14b-instruct-q4_k_m.gguf|" "$env_file"
    else
        echo "LLM_MODEL_PATH=$abs_models_dir/qwen2.5-14b-instruct-q4_k_m.gguf" >> "$env_file"
    fi
    
    if grep -q "^SDXL_MODEL_PATH=" "$env_file"; then
        sed -i.bak "s|^SDXL_MODEL_PATH=.*|SDXL_MODEL_PATH=$abs_models_dir/stable-diffusion-xl-base-1.0/sd_xl_base_1.0.safetensors|" "$env_file"
    else
        echo "SDXL_MODEL_PATH=$abs_models_dir/stable-diffusion-xl-base-1.0/sd_xl_base_1.0.safetensors" >> "$env_file"
    fi
    
    if grep -q "^SVD_MODEL_PATH=" "$env_file"; then
        sed -i.bak "s|^SVD_MODEL_PATH=.*|SVD_MODEL_PATH=$abs_models_dir/stable-video-diffusion-img2vid-xt|" "$env_file"
    else
        echo "SVD_MODEL_PATH=$abs_models_dir/stable-video-diffusion-img2vid-xt" >> "$env_file"
    fi
    
    # 删除备份文件
    rm -f "$env_file.bak"
    
    echo -e "${GREEN}✓ .env 文件更新完成${NC}"
    echo ""
}

# 显示下载摘要
show_summary() {
    echo -e "${GREEN}=== 下载摘要 ===${NC}"
    echo ""
    echo "模型文件位置:"
    echo "  - Qwen2.5-14B: $MODELS_DIR/qwen2.5-14b-instruct-q4_k_m.gguf"
    echo "  - SDXL: $MODELS_DIR/stable-diffusion-xl-base-1.0/sd_xl_base_1.0.safetensors"
    echo "  - SVD: $MODELS_DIR/stable-video-diffusion-img2vid-xt/svd_xt.safetensors"
    echo ""
    echo "总大小: ~18-20GB"
    echo ""
    echo -e "${GREEN}✓ 所有模型下载完成！${NC}"
    echo ""
    echo "下一步:"
    echo "  1. 检查 .env 文件中的模型路径配置"
    echo "  2. 安装和配置 ComfyUI（任务 1.1.6）"
    echo "  3. 测试模型加载（任务 1.6）"
    echo ""
}

# 主函数
main() {
    check_dependencies
    
    # 下载所有模型
    download_qwen_model || exit 1
    download_sdxl_model || exit 1
    download_svd_model || exit 1
    
    # 更新配置文件
    update_env_file
    
    # 显示摘要
    show_summary
}

# 运行主函数
main
