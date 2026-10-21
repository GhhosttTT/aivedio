#!/bin/bash
# LLM 服务启动脚本（Shell 版本）
#
# 功能：
# - 检查环境配置
# - 启动 LLM 服务
# - 运行基本测试

set -e  # 遇到错误立即退出

# 颜色定义
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# 打印带颜色的消息
print_info() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

print_warn() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

print_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# 检查环境变量
check_environment() {
    print_info "检查环境配置..."
    
    # 检查 .env 文件
    if [ ! -f ".env" ]; then
        print_warn ".env 文件不存在"
        print_info "请创建 .env 文件并配置以下变量："
        echo "  LLM_MODEL_PATH=./models/qwen2.5-14b-instruct-q4_k_m.gguf"
        echo "  LLM_N_GPU_LAYERS=20"
        echo "  LLM_N_CTX=4096"
        echo "  LLM_N_THREADS=8"
        return 1
    fi
    
    # 加载环境变量
    source .env
    
    # 检查模型路径
    if [ -z "$LLM_MODEL_PATH" ]; then
        print_error "未设置环境变量 LLM_MODEL_PATH"
        return 1
    fi
    
    if [ ! -f "$LLM_MODEL_PATH" ]; then
        print_error "模型文件不存在: $LLM_MODEL_PATH"
        print_info "请从以下地址下载模型："
        echo "  https://huggingface.co/Qwen/Qwen2.5-14B-Instruct-GGUF"
        return 1
    fi
    
    print_info "模型路径: $LLM_MODEL_PATH"
    
    # 检查 Python
    if ! command -v python &> /dev/null; then
        print_error "未找到 Python，请先安装 Python 3.10+"
        return 1
    fi
    
    print_info "Python 版本: $(python --version)"
    
    # 检查依赖
    if ! python -c "import llama_cpp" &> /dev/null; then
        print_warn "llama-cpp-python 未安装"
        print_info "正在安装依赖..."
        pip install llama-cpp-python==0.2.20
    fi
    
    print_info "✓ 环境检查通过"
    return 0
}

# 启动服务
start_service() {
    print_info "启动 LLM 服务..."
    
    # 解析命令行参数
    TEST_FLAG=""
    VERBOSE_FLAG=""
    
    while [[ $# -gt 0 ]]; do
        case $1 in
            --test)
                TEST_FLAG="--test"
                shift
                ;;
            --verbose)
                VERBOSE_FLAG="--verbose"
                shift
                ;;
            *)
                print_error "未知参数: $1"
                echo "用法: $0 [--test] [--verbose]"
                exit 1
                ;;
        esac
    done
    
    # 运行 Python 脚本
    python scripts/start_llm_service.py $TEST_FLAG $VERBOSE_FLAG
}

# 主函数
main() {
    echo "========================================"
    echo "LLM 服务启动脚本"
    echo "========================================"
    echo ""
    
    # 检查环境
    if ! check_environment; then
        print_error "环境检查失败，请检查配置"
        exit 1
    fi
    
    echo ""
    
    # 启动服务
    start_service "$@"
}

# 执行主函数
main "$@"
