#!/bin/bash
# AI 短剧自动化生产平台 - 服务启动脚本

set -e

echo "========================================="
echo "AI 短剧自动化生产平台 - 启动服务"
echo "========================================="

# 检查 Docker 和 Docker Compose
if ! command -v docker &> /dev/null; then
    echo "错误：未安装 Docker"
    exit 1
fi

if ! command -v docker-compose &> /dev/null && ! docker compose version &> /dev/null; then
    echo "错误：未安装 Docker Compose"
    exit 1
fi

# 检查 NVIDIA Docker 支持（GPU 模式）
if command -v nvidia-smi &> /dev/null; then
    echo "✓ 检测到 NVIDIA GPU"
    nvidia-smi --query-gpu=name,memory.total --format=csv,noheader
else
    echo "⚠ 未检测到 NVIDIA GPU，将使用 CPU 模式"
fi

# 检查 .env 文件
if [ ! -f ".env" ]; then
    echo "⚠ 未找到 .env 文件，从 .env.example 复制..."
    cp .env.example .env
    echo "请编辑 .env 文件配置必要的环境变量"
fi

# 创建必要的目录
echo "创建必要的目录..."
mkdir -p models storage logs configs

# 启动服务
echo "启动 Docker Compose 服务..."
if docker compose version &> /dev/null; then
    docker compose up -d
else
    docker-compose up -d
fi

# 等待服务启动
echo "等待服务启动..."
sleep 10

# 检查服务状态
echo ""
echo "========================================="
echo "服务状态："
echo "========================================="
if docker compose version &> /dev/null; then
    docker compose ps
else
    docker-compose ps
fi

echo ""
echo "========================================="
echo "服务已启动！"
echo "========================================="
echo "API 服务: http://localhost:8000"
echo "API 文档: http://localhost:8000/docs"
echo "ComfyUI: http://localhost:8188"
echo ""
echo "查看日志: docker-compose logs -f"
echo "停止服务: ./scripts/stop_services.sh"
echo "========================================="
