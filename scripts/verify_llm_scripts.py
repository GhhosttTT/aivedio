#!/usr/bin/env python3
"""
LLM 脚本验证工具

功能：
- 验证脚本文件是否存在
- 检查脚本语法是否正确
- 验证依赖是否安装
- 检查环境配置
"""

import os
import sys
import ast
from pathlib import Path
from typing import List, Tuple

# 添加项目根目录到 Python 路径
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))


class ScriptVerifier:
    """脚本验证器"""
    
    def __init__(self):
        self.project_root = project_root
        self.scripts_dir = self.project_root / "scripts"
        self.errors: List[str] = []
        self.warnings: List[str] = []
    
    def verify_all(self) -> bool:
        """
        验证所有内容
        
        Returns:
            是否全部通过
        """
        print("=" * 60)
        print("LLM 脚本验证工具")
        print("=" * 60)
        print()
        
        # 验证脚本文件
        print("1. 验证脚本文件...")
        self.verify_script_files()
        print()
        
        # 验证 Python 语法
        print("2. 验证 Python 语法...")
        self.verify_python_syntax()
        print()
        
        # 验证依赖
        print("3. 验证依赖...")
        self.verify_dependencies()
        print()
        
        # 验证环境配置
        print("4. 验证环境配置...")
        self.verify_environment()
        print()
        
        # 显示结果
        self.print_results()
        
        return len(self.errors) == 0
    
    def verify_script_files(self):
        """验证脚本文件是否存在"""
        required_files = [
            "start_llm_service.py",
            "start_llm_service.sh",
            "test_llm_performance.py",
            "verify_llm_scripts.py",
            "README_LLM_TESTING.md"
        ]
        
        for filename in required_files:
            filepath = self.scripts_dir / filename
            if filepath.exists():
                print(f"   ✓ {filename}")
            else:
                self.errors.append(f"脚本文件不存在: {filename}")
                print(f"   ✗ {filename} (不存在)")
    
    def verify_python_syntax(self):
        """验证 Python 脚本语法"""
        python_files = [
            "start_llm_service.py",
            "test_llm_performance.py",
            "verify_llm_scripts.py"
        ]
        
        for filename in python_files:
            filepath = self.scripts_dir / filename
            if not filepath.exists():
                continue
            
            try:
                with open(filepath, "r", encoding="utf-8") as f:
                    code = f.read()
                
                # 尝试解析 AST
                ast.parse(code)
                print(f"   ✓ {filename} (语法正确)")
                
            except SyntaxError as e:
                self.errors.append(f"{filename} 语法错误: {e}")
                print(f"   ✗ {filename} (语法错误: {e})")
            except Exception as e:
                self.warnings.append(f"{filename} 检查失败: {e}")
                print(f"   ⚠ {filename} (检查失败: {e})")
    
    def verify_dependencies(self):
        """验证依赖是否安装"""
        dependencies = [
            ("llama_cpp", "llama-cpp-python", False),  # LLM 服务依赖（可选）
            ("psutil", "psutil", True),  # 系统信息（必需）
        ]
        
        for module_name, package_name, required in dependencies:
            try:
                __import__(module_name)
                print(f"   ✓ {package_name}")
            except ImportError:
                if required:
                    self.errors.append(f"缺少必需依赖: {package_name}")
                    print(f"   ✗ {package_name} (未安装，必需)")
                else:
                    self.warnings.append(f"缺少可选依赖: {package_name}")
                    print(f"   ⚠ {package_name} (未安装，可选)")
    
    def verify_environment(self):
        """验证环境配置"""
        # 检查 .env 文件
        env_file = self.project_root / ".env"
        if env_file.exists():
            print(f"   ✓ .env 文件存在")
            
            # 检查必需的环境变量
            with open(env_file, "r", encoding="utf-8") as f:
                env_content = f.read()
            
            required_vars = [
                "LLM_MODEL_PATH",
                "LLM_N_GPU_LAYERS",
                "LLM_N_CTX",
                "LLM_N_THREADS"
            ]
            
            for var in required_vars:
                if var in env_content:
                    print(f"   ✓ {var} 已配置")
                else:
                    self.warnings.append(f"环境变量未配置: {var}")
                    print(f"   ⚠ {var} (未配置)")
        else:
            self.warnings.append(".env 文件不存在")
            print(f"   ⚠ .env 文件不存在")
        
        # 检查模型文件
        model_path = os.getenv("LLM_MODEL_PATH")
        if model_path:
            if os.path.exists(model_path):
                print(f"   ✓ 模型文件存在: {model_path}")
            else:
                self.warnings.append(f"模型文件不存在: {model_path}")
                print(f"   ⚠ 模型文件不存在: {model_path}")
        else:
            self.warnings.append("未设置 LLM_MODEL_PATH 环境变量")
            print(f"   ⚠ 未设置 LLM_MODEL_PATH")
    
    def print_results(self):
        """打印验证结果"""
        print("=" * 60)
        print("验证结果")
        print("=" * 60)
        print()
        
        if self.errors:
            print(f"错误 ({len(self.errors)}):")
            for error in self.errors:
                print(f"  ✗ {error}")
            print()
        
        if self.warnings:
            print(f"警告 ({len(self.warnings)}):")
            for warning in self.warnings:
                print(f"  ⚠ {warning}")
            print()
        
        if not self.errors and not self.warnings:
            print("✓ 所有检查通过，脚本可以正常使用")
        elif not self.errors:
            print("⚠ 存在警告，但脚本可以使用")
            print("  建议解决警告以获得最佳体验")
        else:
            print("✗ 存在错误，请先解决错误")
            print()
            print("解决建议:")
            print("  1. 确保所有脚本文件已创建")
            print("  2. 安装缺少的依赖: pip install -r requirements.txt")
            print("  3. 创建 .env 文件并配置环境变量")
            print("  4. 下载模型文件到指定路径")


def main():
    """主函数"""
    verifier = ScriptVerifier()
    success = verifier.verify_all()
    
    return 0 if success else 1


if __name__ == "__main__":
    sys.exit(main())
