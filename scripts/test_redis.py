#!/usr/bin/env python3
"""
Redis 连接测试脚本
测试 Redis 连接是否正常
"""

import sys
import os

# 添加项目根目录到 Python 路径
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import redis


def test_redis_connection():
    """测试 Redis 连接"""
    print("=" * 50)
    print("Redis 连接测试")
    print("=" * 50)
    print()
    
    # 从环境变量获取 Redis URL
    redis_url = os.getenv("REDIS_URL", "redis://localhost:6379/0")
    print(f"Redis URL: {redis_url}")
    print()
    
    try:
        # 创建 Redis 客户端
        print("1. 连接 Redis...")
        r = redis.from_url(redis_url)
        
        # 测试 PING
        print("2. 测试 PING...")
        response = r.ping()
        if response:
            print("✓ PING 成功")
        else:
            print("✗ PING 失败")
            return False
        
        # 测试 SET/GET
        print("3. 测试 SET/GET...")
        test_key = "test:connection"
        test_value = "Hello, Redis!"
        
        r.set(test_key, test_value)
        retrieved_value = r.get(test_key).decode("utf-8")
        
        if retrieved_value == test_value:
            print(f"✓ SET/GET 成功: {retrieved_value}")
        else:
            print("✗ SET/GET 失败")
            return False
        
        # 清理测试数据
        r.delete(test_key)
        
        # 获取 Redis 信息
        print("4. 获取 Redis 信息...")
        info = r.info()
        print(f"   Redis 版本: {info['redis_version']}")
        print(f"   已用内存: {info['used_memory_human']}")
        print(f"   连接的客户端数: {info['connected_clients']}")
        
        print()
        print("=" * 50)
        print("✓ Redis 连接测试通过！")
        print("=" * 50)
        return True
        
    except redis.ConnectionError as e:
        print(f"✗ Redis 连接失败: {e}")
        print()
        print("请检查:")
        print("  1. Redis 服务是否已启动")
        print("  2. Redis URL 配置是否正确")
        print("  3. 防火墙设置")
        return False
    except Exception as e:
        print(f"✗ 测试失败: {e}")
        return False


if __name__ == "__main__":
    success = test_redis_connection()
    sys.exit(0 if success else 1)
