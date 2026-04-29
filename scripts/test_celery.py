#!/usr/bin/env python3
"""
Celery 测试脚本
测试 Celery 任务队列是否正常工作
"""

import sys
import os
import time

# 添加项目根目录到 Python 路径
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from src.tasks.celery_app import celery_app
from src.tasks.image_tasks import generate_image_task


def test_celery():
    """测试 Celery"""
    print("=" * 50)
    print("Celery 测试")
    print("=" * 50)
    print()
    
    try:
        # 检查 Celery 配置
        print("1. 检查 Celery 配置...")
        print(f"   Broker: {celery_app.conf.broker_url}")
        print(f"   Backend: {celery_app.conf.result_backend}")
        print(f"   任务队列: {[q.name for q in celery_app.conf.task_queues]}")
        print("✓ 配置正常")
        print()
        
        # 检查 Worker 状态
        print("2. 检查 Worker 状态...")
        inspect = celery_app.control.inspect()
        
        # 获取活跃的 Worker
        active_workers = inspect.active()
        if active_workers:
            print(f"✓ 发现 {len(active_workers)} 个活跃 Worker:")
            for worker_name in active_workers.keys():
                print(f"   - {worker_name}")
        else:
            print("⚠ 未发现活跃 Worker")
            print("   请先启动 Worker:")
            print("   bash scripts/start_celery_worker.sh")
            print()
            print("   继续测试任务提交...")
        print()
        
        # 测试任务提交
        print("3. 测试任务提交...")
        result = generate_image_task.delay(
            scene_id=1,
            prompt="test image generation"
        )
        print(f"✓ 任务已提交: {result.id}")
        print()
        
        # 等待任务完成
        print("4. 等待任务完成...")
        print("   (最多等待 10 秒)")
        
        try:
            task_result = result.get(timeout=10)
            print("✓ 任务完成")
            print(f"   结果: {task_result}")
        except Exception as e:
            print(f"⚠ 任务未完成: {e}")
            print("   这可能是因为:")
            print("   1. Worker 未启动")
            print("   2. 任务执行时间过长")
            print("   3. 任务执行失败")
        
        print()
        print("=" * 50)
        print("✓ Celery 测试完成！")
        print("=" * 50)
        return True
        
    except Exception as e:
        print(f"✗ 测试失败: {e}")
        print()
        print("请检查:")
        print("  1. Redis 服务是否已启动")
        print("  2. Celery 配置是否正确")
        print("  3. Worker 是否已启动")
        return False


if __name__ == "__main__":
    success = test_celery()
    sys.exit(0 if success else 1)
