#!/bin/bash
# AI 短剧自动化生产平台 - 服务停止脚本

set -e

echo "========================================="
echo "AI 短剧自动化生产平台 - 停止服务"
echo "========================================="

# 停止服务
echo "停止 Docker Compose 服务..."
if docker compose version &> /dev/null; then
    docker compose down
else
    docker-compose down
fi

echo ""
echo "========================================="
echo "服务已停止！"
echo "========================================="
echo "重新启动: ./scripts/start_services.sh"
echo "========================================="
