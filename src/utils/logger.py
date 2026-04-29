"""
日志配置模块
使用 loguru 实现结构化日志
"""

import os
import sys
from loguru import logger
from pathlib import Path


# 日志配置
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
LOG_FILE_PATH = os.getenv("LOG_FILE_PATH", "./logs/app.log")
LOG_ROTATION = "100 MB"  # 日志文件轮转大小
LOG_RETENTION = "30 days"  # 日志保留时间
LOG_FORMAT = (
    "<green>{time:YYYY-MM-DD HH:mm:ss.SSS}</green> | "
    "<level>{level: <8}</level> | "
    "<cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> | "
    "<level>{message}</level>"
)


def setup_logger():
    """
    配置日志系统
    设置控制台和文件日志输出
    """
    # 移除默认的 logger
    logger.remove()
    
    # 添加控制台输出
    logger.add(
        sys.stdout,
        format=LOG_FORMAT,
        level=LOG_LEVEL,
        colorize=True,
        backtrace=True,
        diagnose=True,
    )
    
    # 创建日志目录
    log_dir = Path(LOG_FILE_PATH).parent
    log_dir.mkdir(parents=True, exist_ok=True)
    
    # 添加文件输出
    logger.add(
        LOG_FILE_PATH,
        format=LOG_FORMAT,
        level=LOG_LEVEL,
        rotation=LOG_ROTATION,
        retention=LOG_RETENTION,
        compression="zip",  # 压缩旧日志
        backtrace=True,
        diagnose=True,
        enqueue=True,  # 异步写入
    )
    
    # 添加错误日志文件
    error_log_path = str(Path(LOG_FILE_PATH).parent / "error.log")
    logger.add(
        error_log_path,
        format=LOG_FORMAT,
        level="ERROR",
        rotation=LOG_ROTATION,
        retention=LOG_RETENTION,
        compression="zip",
        backtrace=True,
        diagnose=True,
        enqueue=True,
    )
    
    logger.info("日志系统初始化完成")
    logger.info(f"日志级别: {LOG_LEVEL}")
    logger.info(f"日志文件: {LOG_FILE_PATH}")


# 导出 logger
__all__ = ["logger", "setup_logger"]
