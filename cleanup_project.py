#!/usr/bin/env python3
"""
项目清理脚本

清理所有临时文件、开发工具文件和无关文件，
准备项目上传到 GitHub
"""

import os
import shutil
from pathlib import Path

# 需要删除的文件列表
FILES_TO_DELETE = [
    # 临时脚本
    "创建推送快捷方式.bat",
    "如何推送到GitHub.md",
    "afk-ralph.sh",
    "ralph-once.sh",
    "auto-install-skill.ps1",
    "commit_all_tests.bat",
    "commit_changes.bat",
    "commit_final.bat",
    "final_commit.bat",
    "install-frontend-design.bat",
    "install-frontend-design.ps1",
    "install-frontend-skill.bat",
    "PUSH_NOW.bat",
    "push_to_github.bat",
    "run_all_tests.bat",
    
    # 临时状态文件
    "ALL_TASKS_COMPLETE.md",
    "COMMIT_MESSAGE.txt",
    "COMPLETION_SUMMARY.md",
    "FINAL_CHECK.md",
    "FINAL_PROJECT_STATUS.md",
    "FINAL_STATUS_REPORT.md",
    "NO_MORE_TASKS.md",
    "progress.txt",
    "PROJECT_COMPLETE.md",
    "PROJECT_STATUS.md",
    "PUSH_TO_GITHUB_GUIDE.md",
    "READY_TO_PUSH.md",
    "TASK_COMPLETION_SUMMARY.md",
    "TASK_EXECUTION_RESULT.md",
    "skills-lock.json",
    
    # 数据库文件（开发用）
    "short_drama.db",
    "test_short_drama.db",
]

# 需要删除的目录列表
DIRS_TO_DELETE = [
    ".kiro",
    ".agents",
    ".trae",
    ".hypothesis",
    ".pytest_cache",
    ".vscode",
    "models",  # 模型文件太大，不上传
]

# 需要清空的目录（保留目录结构，但删除内容）
DIRS_TO_CLEAN = [
    "storage/projects",
    "storage/images",
    "storage/videos",
    "storage/audios",
    "storage/subtitles",
    "storage/temp",
]


def delete_file(file_path: Path):
    """删除文件"""
    if file_path.exists():
        try:
            file_path.unlink()
            print(f"✅ 已删除文件: {file_path}")
        except Exception as e:
            print(f"❌ 删除文件失败 {file_path}: {e}")


def delete_directory(dir_path: Path):
    """删除目录"""
    if dir_path.exists():
        try:
            shutil.rmtree(dir_path)
            print(f"✅ 已删除目录: {dir_path}")
        except Exception as e:
            print(f"❌ 删除目录失败 {dir_path}: {e}")


def clean_directory(dir_path: Path):
    """清空目录内容但保留目录"""
    if dir_path.exists():
        try:
            for item in dir_path.iterdir():
                if item.is_file():
                    item.unlink()
                elif item.is_dir():
                    shutil.rmtree(item)
            
            # 创建 .gitkeep 文件以保留空目录
            gitkeep = dir_path / ".gitkeep"
            gitkeep.touch()
            print(f"✅ 已清空目录: {dir_path}")
        except Exception as e:
            print(f"❌ 清空目录失败 {dir_path}: {e}")


def main():
    """主函数"""
    print("=" * 60)
    print("🧹 开始清理项目...")
    print("=" * 60)
    
    project_root = Path(".")
    
    # 删除文件
    print("\n📄 删除临时文件...")
    for file_name in FILES_TO_DELETE:
        file_path = project_root / file_name
        delete_file(file_path)
    
    # 删除目录
    print("\n📁 删除临时目录...")
    for dir_name in DIRS_TO_DELETE:
        dir_path = project_root / dir_name
        delete_directory(dir_path)
    
    # 清空目录
    print("\n🗂️  清空生成文件目录...")
    for dir_name in DIRS_TO_CLEAN:
        dir_path = project_root / dir_name
        clean_directory(dir_path)
    
    # 删除 Python 缓存
    print("\n🐍 清理 Python 缓存...")
    for pycache in project_root.rglob("__pycache__"):
        delete_directory(pycache)
    
    for pyc in project_root.rglob("*.pyc"):
        delete_file(pyc)
    
    print("\n" + "=" * 60)
    print("✨ 项目清理完成！")
    print("=" * 60)
    print("\n📝 下一步操作：")
    print("1. 检查 .gitignore 文件")
    print("2. 运行: git add .")
    print("3. 运行: git commit -m '项目清理和重构完成'")
    print("4. 运行: git push origin main")
    print("\n⚠️  注意：models 目录已删除，需要在 README.md 中说明如何下载模型")


if __name__ == "__main__":
    main()
