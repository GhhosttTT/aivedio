"""
Celery 应用配置
定义 Celery 应用实例和任务队列配置
"""

import os
from celery import Celery
from kombu import Queue, Exchange

# 从环境变量获取配置
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
CELERY_BROKER_URL = os.getenv("CELERY_BROKER_URL", "redis://localhost:6379/1")
CELERY_RESULT_BACKEND = os.getenv("CELERY_RESULT_BACKEND", "redis://localhost:6379/2")
CELERY_WORKER_CONCURRENCY = int(os.getenv("CELERY_WORKER_CONCURRENCY", "2"))

# 创建 Celery 应用实例
celery_app = Celery(
    "short_drama_production",
    broker=CELERY_BROKER_URL,
    backend=CELERY_RESULT_BACKEND,
    include=[
        "src.tasks.image_tasks",
        "src.tasks.video_tasks",
        "src.tasks.audio_tasks",
        "src.tasks.subtitle_tasks",
        "src.tasks.composition_tasks",
    ]
)

# Celery 配置
celery_app.conf.update(
    # 任务序列化
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="Asia/Shanghai",
    enable_utc=True,
    
    # 任务结果配置
    result_expires=3600,  # 结果过期时间（秒）
    result_backend_transport_options={
        "master_name": "mymaster",
        "visibility_timeout": 3600,
    },
    
    # 任务执行配置
    task_acks_late=True,  # 任务完成后才确认
    task_reject_on_worker_lost=True,  # Worker 丢失时拒绝任务
    task_track_started=True,  # 跟踪任务开始状态
    
    # 任务重试配置
    task_default_retry_delay=60,  # 默认重试延迟（秒）
    task_max_retries=3,  # 默认最大重试次数
    task_soft_time_limit=3600,  # 软时间限制（秒）
    task_time_limit=3900,  # 硬时间限制（秒）
    
    # Worker 配置
    worker_prefetch_multiplier=1,  # 预取任务数
    worker_max_tasks_per_child=100,  # 每个 Worker 子进程最多执行任务数
    worker_disable_rate_limits=False,
    
    # 任务路由配置
    task_routes={
        "src.tasks.image_tasks.*": {"queue": "image"},
        "src.tasks.video_tasks.*": {"queue": "video"},
        "src.tasks.audio_tasks.*": {"queue": "audio"},
        "src.tasks.subtitle_tasks.*": {"queue": "default"},
        "src.tasks.composition_tasks.*": {"queue": "default"},
    },
    
    # 任务队列定义
    task_queues=(
        Queue("default", Exchange("default"), routing_key="default"),
        Queue("image", Exchange("image"), routing_key="image"),
        Queue("video", Exchange("video"), routing_key="video"),
        Queue("audio", Exchange("audio"), routing_key="audio"),
    ),
    
    # 任务默认队列
    task_default_queue="default",
    task_default_exchange="default",
    task_default_routing_key="default",
    
    # 任务优先级
    task_queue_max_priority=10,
    task_default_priority=5,
    
    # 任务重试策略（指数退避）
    task_autoretry_for=(Exception,),
    task_retry_backoff=True,  # 启用指数退避
    task_retry_backoff_max=600,  # 最大退避时间（秒）
    task_retry_jitter=True,  # 添加随机抖动
)


# 任务基类配置
class BaseTask(celery_app.Task):
    """
    任务基类
    提供统一的错误处理和重试逻辑
    """
    
    autoretry_for = (Exception,)
    retry_kwargs = {"max_retries": 3}
    retry_backoff = True
    retry_backoff_max = 600
    retry_jitter = True
    
    def on_failure(self, exc, task_id, args, kwargs, einfo):
        """
        任务失败时的回调
        
        Args:
            exc: 异常对象
            task_id: 任务ID
            args: 任务位置参数
            kwargs: 任务关键字参数
            einfo: 异常信息
        """
        print(f"任务失败: {task_id}")
        print(f"异常: {exc}")
        print(f"详细信息: {einfo}")
        
        # 可以在这里添加失败通知逻辑
        # 例如：发送邮件、更新数据库状态等
    
    def on_retry(self, exc, task_id, args, kwargs, einfo):
        """
        任务重试时的回调
        
        Args:
            exc: 异常对象
            task_id: 任务ID
            args: 任务位置参数
            kwargs: 任务关键字参数
            einfo: 异常信息
        """
        print(f"任务重试: {task_id}")
        print(f"异常: {exc}")
        print(f"重试次数: {self.request.retries}")
    
    def on_success(self, retval, task_id, args, kwargs):
        """
        任务成功时的回调
        
        Args:
            retval: 任务返回值
            task_id: 任务ID
            args: 任务位置参数
            kwargs: 任务关键字参数
        """
        print(f"任务成功: {task_id}")


# 设置默认任务基类
celery_app.Task = BaseTask


# 导出 Celery 应用
__all__ = ["celery_app"]
