#!/bin/bash
# AI 短剧自动化生产平台 - 服务停止脚本

set -e

echo "========================================="
echo "AI 短剧自动化生产平台 - 停止服务"
echo "========================================="

# 停止服务
echo "停止 Docker Compose 服务..."
if ! command -v docker &> /dev/null && ! command -v docker-compose &> /dev/null; then
    echo "未安装 Docker / Docker Compose，无需停止容器"
elif docker compose version &> /dev/null; then
    docker compose down 2>/dev/null || echo "Docker 守护进程未运行或无权限访问"
elif command -v docker-compose &> /dev/null; then
    docker-compose down 2>/dev/null || echo "Docker 守护进程未运行或无权限访问"
else
    echo "未安装 Docker Compose，无需停止容器"
fi

echo ""
echo "========================================="
echo "服务已停止！"
echo "========================================="
echo "重新启动: ./scripts/start_services.sh"
echo "========================================="
