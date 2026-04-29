#!/bin/bash
# 数据库迁移管理脚本
case "$1" in
  init) alembic revision --autogenerate -m "Initial migration" ;;
  create) alembic revision --autogenerate -m "$2" ;;
  upgrade) alembic upgrade head ;;
  downgrade) alembic downgrade -1 ;;
  current) alembic current ;;
  history) alembic history ;;
  *) echo "用法: bash scripts/manage_migrations_simple.sh [init|create|upgrade|downgrade|current|history]" ;;
esac
