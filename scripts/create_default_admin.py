#!/usr/bin/env python3
"""
创建默认管理员账户
"""

import sys
import os

# 添加项目根目录到 Python 路径
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from src.database.session import get_db_session
from src.database.models import User
from src.api.auth import hash_password


def create_default_admin():
    """创建默认管理员账户"""
    print("=" * 50)
    print("创建默认管理员账户")
    print("=" * 50)
    
    db = next(get_db_session())
    
    try:
        # 检查是否已存在 admin 用户
        existing_user = db.query(User).filter(User.username == "admin").first()
        if existing_user:
            print("⚠️  admin 用户已存在")
            return
        
        # 创建 admin 用户
        hashed_pwd = hash_password("admin123")
        admin_user = User(
            username="admin",
            email="admin@example.com",
            hashed_password=hashed_pwd,
            is_active=True
        )
        
        db.add(admin_user)
        db.commit()
        db.refresh(admin_user)
        
        print("✅ 默认管理员账户创建成功！")
        print(f"   用户名: admin")
        print(f"   密码: admin123")
        print(f"   邮箱: admin@example.com")
        print("=" * 50)
        
    except Exception as e:
        db.rollback()
        print(f"❌ 创建失败: {e}")
        raise
    finally:
        db.close()


if __name__ == "__main__":
    try:
        create_default_admin()
    except KeyboardInterrupt:
        print("\n\n已取消")
        sys.exit(1)
    except Exception as e:
        print(f"\n✗ 错误: {e}")
        sys.exit(1)
