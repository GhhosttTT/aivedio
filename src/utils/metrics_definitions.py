"""
Prometheus 监控指标定义
"""

from prometheus_client import Counter, Histogram, Gauge

# API 指标
api_requests_total = Counter(
    "api_requests_total",
    "API 请求总数",
    ["method", "endpoint", "status"]
)

api_response_time = Histogram(
    "api_response_time_seconds",
    "API 响应时间（秒）",
    ["method", "endpoint"],
    buckets=(0.01, 0.05, 0.1, 0.5, 1.0, 2.5, 5.0, 10.0)
)

# 任务指标
task_executions_total = Counter(
    "task_executions_total",
    "任务执行总数",
    ["task_type", "status"]
)

task_execution_time = Histogram(
    "task_execution_time_seconds",
    "任务执行时间（秒）",
    ["task_type"],
    buckets=(1, 5, 10, 30, 60, 120, 300, 600, 1800, 3600)
)

# GPU 指标
gpu_memory_usage = Gauge(
    "gpu_memory_usage_percent",
    "GPU 显存使用率（%）",
    ["gpu_id"]
)

gpu_utilization = Gauge(
    "gpu_utilization_percent",
    "GPU 利用率（%）",
    ["gpu_id"]
)

# 系统指标
cpu_usage = Gauge(
    "cpu_usage_percent",
    "CPU 使用率（%）"
)

memory_usage = Gauge(
    "memory_usage_percent",
    "内存使用率（%）"
)
