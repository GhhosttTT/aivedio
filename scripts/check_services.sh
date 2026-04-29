#!/bin/bash
# AI 短剧自动化生产平台 - 服务状态检查脚本

set -e

echo "========================================="
echo "AI 短剧自动化生产平台 - 服务状态"
echo "========================================="

# 检查 Docker Compose 服务状态
echo "Docker Compose 服务状态："
if docker compose version &> /dev/null; then
    docker compose ps
else
    docker-compose ps
fi

echo ""
echo "========================================="
echo "服务健康检查："
echo "========================================="

# 检查 Redis
echo -n "Redis: "
if curl -s http://localhost:6379 > /dev/null 2>&1 || redis-cli ping > /dev/null 2>&1; then
    echo "✓ 运行中"
else
    echo "✗ 未运行"
fi

# 检查 API
echo -n "API: "
if curl -s http://localhost:8000/health > /dev/null 2>&1; then
    echo "✓ 运行中"
else
    echo "✗ 未运行"
fi

# 检查 ComfyUI
echo -n "ComfyUI: "
if curl -s http://localhost:8188 > /dev/null 2>&1; then
    echo "✓ 运行中"
else
    echo "✗ 未运行"
fi

echo ""
echo "========================================="
echo "GPU 状态："
echo "========================================="
if command -v nvidia-smi &> /dev/null; then
    nvidia-smi --query-gpu=index,name,temperature.gpu,utilization.gpu,memory.used,memory.total --format=csv,noheader,nounits
else
    echo "未检测到 NVIDIA GPU"
fi

echo ""
echo "========================================="
echo "磁盘使用："
echo "========================================="
df -h | grep -E "Filesystem|/app|models|storage"

echo ""
echo "========================================="
