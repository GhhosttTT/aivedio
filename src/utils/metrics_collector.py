"""
Prometheus 指标收集器
"""

import psutil
from prometheus_client import generate_latest, CONTENT_TYPE_LATEST
from src.utils.metrics_definitions import (
    gpu_memory_usage,
    gpu_utilization,
    cpu_usage,
    memory_usage
)


def collect_gpu_metrics():
    """收集 GPU 指标"""
    try:
        import GPUtil
        gpus = GPUtil.getGPUs()
        for gpu in gpus:
            gpu_id = str(gpu.id)
            gpu_memory_usage.labels(gpu_id=gpu_id).set(gpu.memoryUtil * 100)
            gpu_utilization.labels(gpu_id=gpu_id).set(gpu.load * 100)
    except Exception:
        pass


def collect_system_metrics():
    """收集系统指标"""
    cpu_usage.set(psutil.cpu_percent(interval=1))
    memory = psutil.virtual_memory()
    memory_usage.set(memory.percent)


def collect_all_metrics():
    """收集所有指标"""
    collect_gpu_metrics()
    collect_system_metrics()


def get_metrics():
    """获取 Prometheus 指标"""
    collect_all_metrics()
    return generate_latest(), CONTENT_TYPE_LATEST
