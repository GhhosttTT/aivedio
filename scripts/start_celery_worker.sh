#!/bin/bash
# Celery Worker 启动脚本

WORKER_NAME="short_drama_worker"
CONCURRENCY=2
QUEUES="default,image,video,audio"
LOG_LEVEL="info"

echo "=== 启动 Celery Worker ==="
echo "Worker 名称: $WORKER_NAME"
echo "并发数: $CONCURRENCY"
echo "队列: $QUEUES"
echo ""

celery -A src.tasks.celery_app worker \
  --hostname=$WORKER_NAME@%h \
  --concurrency=$CONCURRENCY \
  --queues=$QUEUES \
  --loglevel=$LOG_LEVEL \
  --max-tasks-per-child=100 \
  --time-limit=3900 \
  --soft-time-limit=3600
