#!/usr/bin/env python3
"""
数据库初始化脚本
创建所有数据库表并执行初始化操作
"""

import sys
import os

# 添加项目根目录到 Python 路径
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from src.database.database import (
    init_database,
    check_database_connection,
    drop_tables,
    create_tables
)


def main():
    """主函数"""
    print("=" * 50)
    print("AI 短剧自动化生产平台 - 数据库初始化")
    print("=" * 50)
    print()
    
    # 检查数据库连接
    print("1. 检查数据库连接...")
    if not check_database_connection():
        print("✗ 数据库连接失败，请检查配置")
        sys.exit(1)
    print("✓ 数据库连接正常")
    print()
    
    # 询问是否重置数据库
    print("2. 数据库初始化选项:")
    print("   a) 创建新表（保留现有数据）")
    print("   b) 重置数据库（删除所有数据）")
    print("   c) 取消")
    print()
    
    choice = input("请选择 (a/b/c): ").strip().lower()
    print()
    
    if choice == "c":
        print("已取消")
        sys.exit(0)
    elif choice == "b":
        # 确认重置
        confirm = input("警告：此操作将删除所有数据！确认重置？(yes/no): ").strip().lower()
        if confirm != "yes":
            print("已取消")
            sys.exit(0)
        
        print("3. 删除现有表...")
        drop_tables()
        print()
        
        print("4. 创建新表...")
        create_tables()
        print()
    elif choice == "a":
        print("3. 创建新表...")
        create_tables()
        print()
    else:
        print("无效选择")
        sys.exit(1)
    
    print("=" * 50)
    print("✓ 数据库初始化完成！")
    print("=" * 50)
    print()
    print("下一步:")
    print("  1. 配置 Redis 和 Celery（任务 1.3）")
    print("  2. 实现业务服务（任务 2.1）")
    print()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\n已取消")
        sys.exit(1)
    except Exception as e:
        print(f"\n✗ 错误: {e}")
        sys.exit(1)
