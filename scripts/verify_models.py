#!/usr/bin/env python3
"""
AI 短剧自动化生产平台 - 模型验证脚本
验证所有下载的模型文件是否完整且可用
"""

import os
import sys
import hashlib
from pathlib import Path
from typing import Dict, Optional, Tuple


# 颜色输出
class Colors:
    RED = '\033[0;31m'
    GREEN = '\033[0;32m'
    YELLOW = '\033[1;33m'
    BLUE = '\033[0;34m'
    NC = '\033[0m'  # No Color


def print_colored(message: str, color: str = Colors.NC):
    """打印带颜色的消息"""
    print(f"{color}{message}{Colors.NC}")


def calculate_file_hash(file_path: Path, algorithm: str = 'sha256') -> Optional[str]:
    """
    计算文件的哈希值
    
    Args:
        file_path: 文件路径
        algorithm: 哈希算法（md5, sha256）
    
    Returns:
        文件哈希值，如果文件不存在则返回 None
    """
    if not file_path.exists():
        return None
    
    hash_func = hashlib.new(algorithm)
    
    try:
        with open(file_path, 'rb') as f:
            # 分块读取以处理大文件
            for chunk in iter(lambda: f.read(8192), b''):
                hash_func.update(chunk)
        return hash_func.hexdigest()
    except Exception as e:
        print_colored(f"计算哈希值时出错: {e}", Colors.RED)
        return None


def format_file_size(size_bytes: int) -> str:
    """
    格式化文件大小
    
    Args:
        size_bytes: 文件大小（字节）
    
    Returns:
        格式化后的文件大小字符串
    """
    for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
        if size_bytes < 1024.0:
            return f"{size_bytes:.2f} {unit}"
        size_bytes /= 1024.0
    return f"{size_bytes:.2f} PB"


def check_model_file(
    model_name: str,
    file_path: Path,
    expected_size_range: Optional[Tuple[int, int]] = None,
    expected_hash: Optional[str] = None
) -> bool:
    """
    检查模型文件
    
    Args:
        model_name: 模型名称
        file_path: 文件路径
        expected_size_range: 期望的文件大小范围（最小值，最大值）字节
        expected_hash: 期望的 SHA256 哈希值
    
    Returns:
        True 如果检查通过，否则 False
    """
    print_colored(f"\n检查 {model_name}...", Colors.BLUE)
    print(f"路径: {file_path}")
    
    # 检查文件是否存在
    if not file_path.exists():
        print_colored("✗ 文件不存在", Colors.RED)
        return False
    
    print_colored("✓ 文件存在", Colors.GREEN)
    
    # 检查文件大小
    file_size = file_path.stat().st_size
    print(f"文件大小: {format_file_size(file_size)}")
    
    if expected_size_range:
        min_size, max_size = expected_size_range
        if file_size < min_size:
            print_colored(
                f"✗ 文件大小过小（期望 >= {format_file_size(min_size)}）",
                Colors.RED
            )
            print_colored("  文件可能下载不完整，请重新下载", Colors.YELLOW)
            return False
        elif file_size > max_size:
            print_colored(
                f"⚠ 文件大小超出预期（期望 <= {format_file_size(max_size)}）",
                Colors.YELLOW
            )
        else:
            print_colored("✓ 文件大小正常", Colors.GREEN)
    
    # 检查文件哈希（可选）
    if expected_hash:
        print("计算文件哈希值（可能需要几分钟）...")
        actual_hash = calculate_file_hash(file_path)
        
        if actual_hash is None:
            print_colored("✗ 无法计算哈希值", Colors.RED)
            return False
        
        if actual_hash.lower() == expected_hash.lower():
            print_colored("✓ 文件完整性验证通过", Colors.GREEN)
        else:
            print_colored("✗ 文件完整性验证失败", Colors.RED)
            print(f"期望: {expected_hash}")
            print(f"实际: {actual_hash}")
            return False
    
    return True


def verify_all_models() -> bool:
    """
    验证所有模型文件
    
    Returns:
        True 如果所有模型都通过验证，否则 False
    """
    print_colored("=== AI 模型验证脚本 ===", Colors.GREEN)
    print()
    
    models_dir = Path("./models")
    
    if not models_dir.exists():
        print_colored(f"错误: 模型目录不存在: {models_dir}", Colors.RED)
        print("请先运行 scripts/download_models.sh 下载模型")
        return False
    
    all_passed = True
    
    # 1. 验证 Qwen2.5-14B GGUF 模型
    qwen_model = models_dir / "qwen2.5-14b-instruct-q4_k_m.gguf"
    # Q4_K_M 量化版本约 8GB (7.5GB - 8.5GB)
    if not check_model_file(
        "Qwen2.5-14B-Instruct (Q4_K_M)",
        qwen_model,
        expected_size_range=(7 * 1024**3, 9 * 1024**3)  # 7GB - 9GB
    ):
        all_passed = False
    
    # 2. 验证 Stable Diffusion XL 模型
    sdxl_model = models_dir / "stable-diffusion-xl-base-1.0" / "sd_xl_base_1.0.safetensors"
    # SDXL 模型约 6.9GB (6.5GB - 7.5GB)
    if not check_model_file(
        "Stable Diffusion XL Base 1.0",
        sdxl_model,
        expected_size_range=(6 * 1024**3, 8 * 1024**3)  # 6GB - 8GB
    ):
        all_passed = False
    
    # 3. 验证 Stable Video Diffusion 模型
    svd_model = models_dir / "stable-video-diffusion-img2vid-xt" / "svd_xt.safetensors"
    # SVD 模型约 3.8GB (3.5GB - 4.5GB)
    if not check_model_file(
        "Stable Video Diffusion (SVD-XT)",
        svd_model,
        expected_size_range=(3 * 1024**3, 5 * 1024**3)  # 3GB - 5GB
    ):
        all_passed = False
    
    # 显示总结
    print()
    print_colored("=== 验证总结 ===", Colors.GREEN)
    
    if all_passed:
        print_colored("✓ 所有模型文件验证通过！", Colors.GREEN)
        print()
        print("下一步:")
        print("  1. 配置 ComfyUI 服务（任务 1.1.6）")
        print("  2. 测试模型加载（任务 1.6）")
        return True
    else:
        print_colored("✗ 部分模型文件验证失败", Colors.RED)
        print()
        print("请检查:")
        print("  1. 模型文件是否下载完整")
        print("  2. 网络连接是否稳定")
        print("  3. 磁盘空间是否充足")
        print()
        print("建议:")
        print("  - 重新运行 scripts/download_models.sh")
        print("  - 或手动下载缺失的模型文件")
        return False


def main():
    """主函数"""
    try:
        success = verify_all_models()
        sys.exit(0 if success else 1)
    except KeyboardInterrupt:
        print()
        print_colored("验证已取消", Colors.YELLOW)
        sys.exit(1)
    except Exception as e:
        print_colored(f"发生错误: {e}", Colors.RED)
        sys.exit(1)


if __name__ == "__main__":
    main()
