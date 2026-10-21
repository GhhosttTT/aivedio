#!/usr/bin/env python3
"""
创建默认管理员账户
"""

import argparse
import os
import secrets
import sys

# 添加项目根目录到 Python 路径
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from src.database.session import get_db_session
from src.database.models import User
from src.api.auth import hash_password


def _parse_args():
    parser = argparse.ArgumentParser(description="创建初始管理员账户")
    parser.add_argument("--username", default=None, help="默认取 DEFAULT_ADMIN_USERNAME 或 admin")
    parser.add_argument("--email", default=None, help="默认取 DEFAULT_ADMIN_EMAIL 或 admin@example.com")
    return parser.parse_args()


def create_default_admin(username: str | None = None, email: str | None = None):
    """创建初始管理员账户；密码优先取环境变量，否则生成随机密码。"""
    print("=" * 50)
    print("创建初始管理员账户")
    print("=" * 50)

    username = (username or os.getenv("DEFAULT_ADMIN_USERNAME") or "admin").strip() or "admin"
    email = (email or os.getenv("DEFAULT_ADMIN_EMAIL") or "admin@example.com").strip() or "admin@example.com"
    supplied_password = os.getenv("DEFAULT_ADMIN_PASSWORD") or ""
    password = supplied_password or secrets.token_urlsafe(12)

    db = next(get_db_session())

    try:
        existing_user = db.query(User).filter(User.username == username).first()
        if existing_user:
            print(f"⚠️  用户 {username} 已存在")
            return

        admin_user = User(
            username=username,
            email=email,
            hashed_password=hash_password(password),
            is_active=True,
        )
        db.add(admin_user)
        db.commit()
        db.refresh(admin_user)

        print("✅ 管理员账户创建成功！")
        print(f"   用户名: {username}")
        print(f"   邮箱: {email}")
        if supplied_password:
            print("   密码: 来自 DEFAULT_ADMIN_PASSWORD（未回显）")
        else:
            print(f"   初始密码: {password}")
            print("   请登录后立即修改此密码。")
        print("=" * 50)

    except Exception as e:
        db.rollback()
        print(f"❌ 创建失败: {e}")
        raise
    finally:
        db.close()


if __name__ == "__main__":
    args = _parse_args()
    try:
        create_default_admin(args.username, args.email)
    except KeyboardInterrupt:
        print("\n\n已取消")
        sys.exit(1)
    except Exception as e:
        print(f"\n✗ 错误: {e}")
        sys.exit(1)
