"""
GPU 工具模块

提供 GPU 显存监控和缓存清理功能
"""

from typing import Dict, Optional
import logging

logger = logging.getLogger(__name__)


def is_gpu_available() -> bool:
    """
    检查 GPU 是否可用
    
    Returns:
        GPU 是否可用
    """
    try:
        import torch
        return torch.cuda.is_available()
    except ImportError:
        logger.warning("PyTorch 未安装，GPU 功能不可用")
        return False


def get_gpu_memory_info(device_id: int = 0) -> Optional[Dict]:
    """
    获取 GPU 显存信息
    
    Args:
        device_id: GPU 设备 ID
        
    Returns:
        显存信息字典，包含 total、used、free 字段（单位：MB）
        如果 GPU 不可用则返回 None
    """
    try:
        import torch
        
        if not torch.cuda.is_available():
            return None
        
        if device_id >= torch.cuda.device_count():
            logger.error(f"GPU 设备 {device_id} 不存在")
            return None
        
        torch.cuda.set_device(device_id)
        
        # 获取显存信息（转换为 MB）
        total = torch.cuda.get_device_properties(device_id).total_memory / (1024**2)
        allocated = torch.cuda.memory_allocated(device_id) / (1024**2)
        reserved = torch.cuda.memory_reserved(device_id) / (1024**2)
        free = total - allocated
        
        return {
            "device_id": device_id,
            "device_name": torch.cuda.get_device_name(device_id),
            "total": round(total, 2),
            "used": round(allocated, 2),
            "reserved": round(reserved, 2),
            "free": round(free, 2),
            "usage_percent": round((allocated / total) * 100, 2)
        }
        
    except Exception as e:
        logger.error(f"获取 GPU 显存信息失败: {e}")
        return None


def clear_gpu_cache(device_id: Optional[int] = None) -> bool:
    """
    清理 GPU 缓存
    
    Args:
        device_id: GPU 设备 ID，None 表示清理所有设备
        
    Returns:
        是否清理成功
    """
    try:
        import torch
        
        if not torch.cuda.is_available():
            logger.warning("GPU 不可用，跳过缓存清理")
            return False
        
        if device_id is not None:
            # 清理指定设备
            torch.cuda.set_device(device_id)
            before = torch.cuda.memory_allocated(device_id) / (1024**2)
            torch.cuda.empty_cache()
            after = torch.cuda.memory_allocated(device_id) / (1024**2)
            freed = before - after
            
            logger.info(f"GPU {device_id} 缓存清理完成，释放 {freed:.2f} MB")
        else:
            # 清理所有设备
            for i in range(torch.cuda.device_count()):
                torch.cuda.set_device(i)
                before = torch.cuda.memory_allocated(i) / (1024**2)
                torch.cuda.empty_cache()
                after = torch.cuda.memory_allocated(i) / (1024**2)
                freed = before - after
                
                logger.info(f"GPU {i} 缓存清理完成，释放 {freed:.2f} MB")
        
        return True
        
    except Exception as e:
        logger.error(f"清理 GPU 缓存失败: {e}")
        return False


def check_gpu_memory_threshold(device_id: int = 0, threshold_percent: float = 95.0) -> bool:
    """
    检查 GPU 显存使用率是否超过阈值
    
    Args:
        device_id: GPU 设备 ID
        threshold_percent: 阈值百分比（默认 95%）
        
    Returns:
        是否超过阈值
    """
    memory_info = get_gpu_memory_info(device_id)
    
    if memory_info is None:
        return False
    
    usage_percent = memory_info["usage_percent"]
    
    if usage_percent > threshold_percent:
        logger.warning(
            f"GPU {device_id} 显存使用率 {usage_percent:.1f}% 超过阈值 {threshold_percent}%"
        )
        return True
    
    return False


def get_optimal_gpu_layers(total_memory_gb: float, model_size_gb: float) -> int:
    """
    根据 GPU 显存大小计算最优的 GPU 层数（用于 LLM offload）
    
    Args:
        total_memory_gb: GPU 总显存（GB）
        model_size_gb: 模型大小（GB）
        
    Returns:
        建议的 GPU 层数
    """
    # 预留 8GB 给 SD 和 SVD
    available_for_llm = total_memory_gb - 8
    
    if available_for_llm <= 0:
        logger.warning("GPU 显存不足，建议使用 CPU 运行 LLM")
        return 0
    
    # 估算每层占用的显存（假设模型均匀分布）
    # Qwen2.5-14B 约有 40 层
    total_layers = 40
    memory_per_layer = model_size_gb / total_layers
    
    # 计算可以加载的层数
    gpu_layers = int(available_for_llm / memory_per_layer)
    
    # 限制在合理范围内
    gpu_layers = max(0, min(gpu_layers, total_layers))
    
    logger.info(
        f"GPU 显存 {total_memory_gb:.1f}GB，建议加载 {gpu_layers} 层到 GPU"
    )
    
    return gpu_layers


def log_gpu_status(device_id: int = 0):
    """
    记录 GPU 状态到日志
    
    Args:
        device_id: GPU 设备 ID
    """
    memory_info = get_gpu_memory_info(device_id)
    
    if memory_info is None:
        logger.info("GPU 不可用")
        return
    
    logger.info(
        f"GPU {device_id} ({memory_info['device_name']}): "
        f"总显存 {memory_info['total']:.0f}MB, "
        f"已用 {memory_info['used']:.0f}MB ({memory_info['usage_percent']:.1f}%), "
        f"可用 {memory_info['free']:.0f}MB"
    )


def get_gpu_info(device_id: int = 0) -> Optional[Dict]:
    """
    获取 GPU 基本信息
    
    Args:
        device_id: GPU 设备 ID
        
    Returns:
        GPU 信息字典，包含 name、memory_total_mb、driver_version 等字段
        如果 GPU 不可用则返回 None
    """
    try:
        import torch
        
        if not torch.cuda.is_available():
            return None
        
        if device_id >= torch.cuda.device_count():
            logger.error(f"GPU 设备 {device_id} 不存在")
            return None
        
        props = torch.cuda.get_device_properties(device_id)
        
        return {
            "device_id": device_id,
            "name": torch.cuda.get_device_name(device_id),
            "memory_total_mb": round(props.total_memory / (1024**2), 2),
            "compute_capability": f"{props.major}.{props.minor}",
            "multi_processor_count": props.multi_processor_count
        }
        
    except Exception as e:
        logger.error(f"获取 GPU 信息失败: {e}")
        return None


def get_gpu_memory_usage(device_id: int = 0) -> Optional[Dict]:
    """
    获取 GPU 显存使用情况（简化版本）
    
    Args:
        device_id: GPU 设备 ID
        
    Returns:
        显存使用情况字典，包含 used_mb、free_mb 等字段
        如果 GPU 不可用则返回 None
    """
    try:
        import torch
        
        if not torch.cuda.is_available():
            return None
        
        if device_id >= torch.cuda.device_count():
            return None
        
        torch.cuda.set_device(device_id)
        
        total = torch.cuda.get_device_properties(device_id).total_memory / (1024**2)
        allocated = torch.cuda.memory_allocated(device_id) / (1024**2)
        free = total - allocated
        
        return {
            "total_mb": round(total, 2),
            "used_mb": round(allocated, 2),
            "free_mb": round(free, 2)
        }
        
    except Exception as e:
        logger.error(f"获取 GPU 显存使用情况失败: {e}")
        return None


def print_gpu_info(device_id: int = 0):
    """
    打印 GPU 信息到控制台
    
    Args:
        device_id: GPU 设备 ID
    """
    gpu_info = get_gpu_info(device_id)
    
    if gpu_info is None:
        print("  GPU 不可用")
        return
    
    print(f"  GPU {device_id}: {gpu_info['name']}")
    print(f"  显存: {gpu_info['memory_total_mb']:.0f} MB")
    print(f"  计算能力: {gpu_info.get('compute_capability', 'N/A')}")
    
    # 显示显存使用情况
    memory_usage = get_gpu_memory_usage(device_id)
    if memory_usage:
        print(f"  已用显存: {memory_usage['used_mb']:.0f} MB")
        print(f"  可用显存: {memory_usage['free_mb']:.0f} MB")
