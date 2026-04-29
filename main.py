"""
FastAPI 应用启动脚本

使用 uvicorn 启动 FastAPI 应用
"""

import uvicorn
import os
from dotenv import load_dotenv

# 加载环境变量
load_dotenv()


def main():
    """
    启动 FastAPI 应用
    
    从环境变量读取配置，默认值：
    - HOST: 0.0.0.0
    - PORT: 8000
    - RELOAD: False（生产环境）
    - LOG_LEVEL: info
    """
    host = os.getenv("API_HOST", "0.0.0.0")
    port = int(os.getenv("API_PORT", "8000"))
    reload = os.getenv("API_RELOAD", "false").lower() == "true"
    log_level = os.getenv("LOG_LEVEL", "info").lower()
    
    print(f"启动 FastAPI 应用...")
    print(f"  - 地址: http://{host}:{port}")
    print(f"  - 文档: http://{host}:{port}/docs")
    print(f"  - 重载: {reload}")
    print(f"  - 日志级别: {log_level}")
    
    uvicorn.run(
        "src.api.app:app",
        host=host,
        port=port,
        reload=reload,
        log_level=log_level,
        access_log=True
    )


if __name__ == "__main__":
    main()
