#!/usr/bin/env python3
"""
GPU 环境检查脚本

检查 CUDA、PyTorch GPU 支持和显存信息
"""

import sys


def check_cuda():
    """检查 CUDA 安装和版本"""
    try:
        import torch
        
        print("=" * 50)
        print("CUDA 环境检查")
        print("=" * 50)
        
        # 检查 CUDA 是否可用
        cuda_available = torch.cuda.is_available()
        print(f"CUDA 可用: {cuda_available}")
        
        if cuda_available:
            # CUDA 版本
            cuda_version = torch.version.cuda
            print(f"CUDA 版本: {cuda_version}")
            
            # 检查版本是否满足要求（11.8+）
            if cuda_version:
                major, minor = map(int, cuda_version.split('.')[:2])
                version_ok = (major > 11) or (major == 11 and minor >= 8)
                print(f"版本满足要求 (>=11.8): {version_ok}")
                
                if not version_ok:
                    print("⚠️  警告: CUDA 版本低于 11.8，可能影响性能")
            
            # GPU 设备数量
            device_count = torch.cuda.device_count()
            print(f"GPU 设备数量: {device_count}")
            
            # 每个 GPU 的详细信息
            for i in range(device_count):
                print(f"\nGPU {i}:")
                print(f"  名称: {torch.cuda.get_device_name(i)}")
                print(f"  计算能力: {torch.cuda.get_device_capability(i)}")
                
                # 显存信息
                total_memory = torch.cuda.get_device_properties(i).total_memory / (1024**3)
                print(f"  总显存: {total_memory:.2f} GB")
            
            return True
        else:
            print("❌ CUDA 不可用")
            print("可能的原因:")
            print("  1. 未安装 NVIDIA 驱动")
            print("  2. 未安装 CUDA Toolkit")
            print("  3. PyTorch 未编译 CUDA 支持")
            print("  4. 系统无 NVIDIA GPU")
            return False
            
    except ImportError:
        print("❌ PyTorch 未安装")
        print("请运行: pip install torch")
        return False
    except Exception as e:
        print(f"❌ 检查失败: {e}")
        return False


def check_pytorch_gpu():
    """检查 PyTorch GPU 支持"""
    try:
        import torch
        
        print("\n" + "=" * 50)
        print("PyTorch GPU 支持检查")
        print("=" * 50)
        
        print(f"PyTorch 版本: {torch.__version__}")
        print(f"CUDA 编译支持: {torch.cuda.is_available()}")
        print(f"cuDNN 版本: {torch.backends.cudnn.version() if torch.cuda.is_available() else 'N/A'}")
        print(f"cuDNN 可用: {torch.backends.cudnn.enabled}")
        
        # 测试简单的 GPU 操作
        if torch.cuda.is_available():
            print("\n测试 GPU 操作...")
            try:
                # 创建测试张量
                x = torch.randn(1000, 1000).cuda()
                y = torch.randn(1000, 1000).cuda()
                z = torch.matmul(x, y)
                print("✓ GPU 矩阵运算测试通过")
                
                # 清理
                del x, y, z
                torch.cuda.empty_cache()
                
                return True
            except Exception as e:
                print(f"❌ GPU 操作测试失败: {e}")
                return False
        else:
            return False
            
    except ImportError:
        print("❌ PyTorch 未安装")
        return False


def get_gpu_memory_info():
    """获取 GPU 显存信息"""
    try:
        import torch
        
        if not torch.cuda.is_available():
            return None
        
        print("\n" + "=" * 50)
        print("GPU 显存信息")
        print("=" * 50)
        
        memory_info = []
        
        for i in range(torch.cuda.device_count()):
            torch.cuda.set_device(i)
            
            # 获取显存信息（单位：MB）
            total = torch.cuda.get_device_properties(i).total_memory / (1024**2)
            reserved = torch.cuda.memory_reserved(i) / (1024**2)
            allocated = torch.cuda.memory_allocated(i) / (1024**2)
            free = total - allocated
            
            info = {
                'device_id': i,
                'device_name': torch.cuda.get_device_name(i),
                'total_mb': total,
                'reserved_mb': reserved,
                'allocated_mb': allocated,
                'free_mb': free,
                'usage_percent': (allocated / total) * 100
            }
            
            memory_info.append(info)
            
            print(f"\nGPU {i} ({info['device_name']}):")
            print(f"  总显存: {info['total_mb']:.2f} MB ({info['total_mb']/1024:.2f} GB)")
            print(f"  已分配: {info['allocated_mb']:.2f} MB ({info['usage_percent']:.1f}%)")
            print(f"  已预留: {info['reserved_mb']:.2f} MB")
            print(f"  可用: {info['free_mb']:.2f} MB ({info['free_mb']/1024:.2f} GB)")
        
        return memory_info
        
    except Exception as e:
        print(f"❌ 获取显存信息失败: {e}")
        return None


def test_gpu_cache_clear():
    """测试 GPU 缓存清理功能"""
    try:
        import torch
        
        if not torch.cuda.is_available():
            print("\n⚠️  跳过缓存清理测试（CUDA 不可用）")
            return False
        
        print("\n" + "=" * 50)
        print("GPU 缓存清理测试")
        print("=" * 50)
        
        # 分配一些显存
        print("分配测试显存...")
        tensors = []
        for _ in range(10):
            tensors.append(torch.randn(1000, 1000).cuda())
        
        allocated_before = torch.cuda.memory_allocated() / (1024**2)
        print(f"清理前已分配: {allocated_before:.2f} MB")
        
        # 删除张量
        del tensors
        
        # 清理缓存
        print("执行缓存清理...")
        torch.cuda.empty_cache()
        
        allocated_after = torch.cuda.memory_allocated() / (1024**2)
        print(f"清理后已分配: {allocated_after:.2f} MB")
        print(f"释放显存: {allocated_before - allocated_after:.2f} MB")
        
        print("✓ GPU 缓存清理测试通过")
        return True
        
    except Exception as e:
        print(f"❌ 缓存清理测试失败: {e}")
        return False


def main():
    """主函数"""
    print("开始 GPU 环境检查...\n")
    
    results = {
        'cuda': check_cuda(),
        'pytorch_gpu': check_pytorch_gpu(),
        'memory_info': get_gpu_memory_info() is not None,
        'cache_clear': test_gpu_cache_clear()
    }
    
    print("\n" + "=" * 50)
    print("检查结果汇总")
    print("=" * 50)
    
    for key, value in results.items():
        status = "✓ 通过" if value else "❌ 失败"
        print(f"{key}: {status}")
    
    all_passed = all(results.values())
    
    if all_passed:
        print("\n✓ 所有检查通过！GPU 环境配置正确")
        return 0
    else:
        print("\n❌ 部分检查失败，请检查 GPU 环境配置")
        return 1


if __name__ == "__main__":
    sys.exit(main())
