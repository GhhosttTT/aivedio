#!/bin/bash
# AI 短剧自动化生产平台 - 服务状态检查脚本

set -e

echo "========================================="
echo "AI 短剧自动化生产平台 - 服务状态"
echo "========================================="

# 检查 Docker Compose 服务状态（Docker 不可用时不影响其余检查）
echo "Docker Compose 服务状态："
if ! command -v docker &> /dev/null; then
    echo "未安装 Docker，跳过容器状态"
elif docker compose version &> /dev/null; then
    docker compose ps 2>/dev/null || echo "Docker 守护进程未运行或无权限访问"
elif command -v docker-compose &> /dev/null; then
    docker-compose ps 2>/dev/null || echo "Docker 守护进程未运行或无权限访问"
else
    echo "未安装 Docker Compose，跳过容器状态"
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

# 检查 API 进程与依赖就绪状态
echo -n "API 进程: "
if curl -s http://localhost:8000/health > /dev/null 2>&1; then
    echo "✓ 运行中"
else
    echo "✗ 未运行"
fi

echo -n "API 就绪: "
if curl -fsS http://localhost:8000/ready > /dev/null 2>&1; then
    echo "✓ 数据库/Redis 就绪"
else
    echo "✗ 未就绪（检查 /ready 返回详情）"
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
df -h | grep -E "Filesystem|/app|models|storage" || true

echo ""
echo "========================================="
