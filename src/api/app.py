"""
FastAPI 应用主文件

创建和配置 FastAPI 应用实例
"""

from fastapi import FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from contextlib import asynccontextmanager
import time
import os

from src.utils.logger import get_logger

logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    应用生命周期管理
    
    启动时执行初始化，关闭时执行清理
    """
    # 启动时执行
    logger.info("FastAPI 应用启动中...")
    
    # 创建必要的目录
    storage_path = os.getenv("STORAGE_PATH", "./storage")
    os.makedirs(storage_path, exist_ok=True)
    
    logger.info("FastAPI 应用启动完成")
    
    yield
    
    # 关闭时执行
    logger.info("FastAPI 应用关闭中...")
    logger.info("FastAPI 应用已关闭")


def create_app() -> FastAPI:
    """
    创建并配置 FastAPI 应用实例
    
    Returns:
        配置好的 FastAPI 应用实例
    """
    app = FastAPI(
        title="AI 短剧自动化生产平台",
        description="基于 AI 的短剧自动化生产系统 API",
        version="1.0.0",
        lifespan=lifespan
    )
    
    # 配置 CORS
    configure_cors(app)
    
    # 配置中间件
    configure_middlewares(app)
    
    # 配置静态文件服务
    configure_static_files(app)
    
    # 注册路由
    register_routes(app)
    
    # 配置异常处理
    configure_exception_handlers(app)
    
    return app


def configure_cors(app: FastAPI):
    """
    配置 CORS（跨域资源共享）
    
    允许前端应用跨域访问 API
    """
    # 从环境变量获取允许的源
    allowed_origins = os.getenv("CORS_ORIGINS", "*").split(",")
    
    app.add_middleware(
        CORSMiddleware,
        allow_origins=allowed_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    
    logger.info(f"CORS 配置完成: allowed_origins={allowed_origins}")


def configure_middlewares(app: FastAPI):
    """
    配置中间件
    
    包括请求日志、性能监控等
    """
    @app.middleware("http")
    async def log_requests(request: Request, call_next):
        """
        请求日志中间件
        
        记录每个请求的基本信息和响应时间
        """
        start_time = time.time()
        
        # 记录请求信息
        logger.info(
            f"请求开始: {request.method} {request.url.path} "
            f"client={request.client.host if request.client else 'unknown'}"
        )
        
        # 处理请求
        response = await call_next(request)
        
        # 计算处理时间
        process_time = time.time() - start_time
        
        # 记录响应信息
        logger.info(
            f"请求完成: {request.method} {request.url.path} "
            f"status={response.status_code} "
            f"duration={process_time:.3f}s"
        )
        
        # 添加响应头
        response.headers["X-Process-Time"] = str(process_time)
        
        return response
    
    logger.info("中间件配置完成")



def configure_static_files(app: FastAPI):
    """
    配置静态文件服务
    
    提供生成的视频、图片等文件的访问
    """
    storage_path = os.getenv("STORAGE_PATH", "./storage")
    
    # 确保存储目录存在
    os.makedirs(storage_path, exist_ok=True)
    
    # 挂载静态文件目录
    app.mount(
        "/static",
        StaticFiles(directory=storage_path),
        name="static"
    )
    
    logger.info(f"静态文件服务配置完成: path={storage_path}")


def register_routes(app: FastAPI):
    """
    注册 API 路由
    
    包括健康检查、项目管理、任务管理、WebSocket、认证等路由
    """
    # 导入路由
    from src.api.routes import projects_router, tasks_router
    from src.api.routes.websocket import router as websocket_router
    from src.api.routes.auth import router as auth_router
    
    # 注册业务路由
    app.include_router(auth_router)
    app.include_router(projects_router)
    app.include_router(tasks_router)
    app.include_router(websocket_router)
    
    # 健康检查端点
    @app.get("/health", tags=["健康检查"])
    async def health_check():
        """
        健康检查端点
        
        用于监控系统是否正常运行
        
        Returns:
            健康状态信息
        """
        return {
            "status": "healthy",
            "service": "AI 短剧自动化生产平台",
            "version": "1.0.0"
        }
    
    # 根路径
    @app.get("/", tags=["根路径"])
    async def root():
        """
        根路径端点
        
        返回 API 基本信息
        """
        return {
            "message": "欢迎使用 AI 短剧自动化生产平台 API",
            "version": "1.0.0",
            "docs": "/docs",
            "health": "/health"
        }
    
    logger.info("路由注册完成")


def configure_exception_handlers(app: FastAPI):
    """
    配置全局异常处理器
    
    统一处理各种异常，返回标准错误格式
    """
    @app.exception_handler(ValueError)
    async def value_error_handler(request: Request, exc: ValueError):
        """
        处理 ValueError 异常
        
        通常是输入验证失败
        """
        logger.warning(f"输入验证失败: {exc}")
        return JSONResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            content={
                "error": "输入验证失败",
                "detail": str(exc),
                "path": request.url.path
            }
        )
    
    @app.exception_handler(FileNotFoundError)
    async def file_not_found_handler(request: Request, exc: FileNotFoundError):
        """
        处理 FileNotFoundError 异常
        
        通常是请求的资源不存在
        """
        logger.warning(f"资源不存在: {exc}")
        return JSONResponse(
            status_code=status.HTTP_404_NOT_FOUND,
            content={
                "error": "资源不存在",
                "detail": str(exc),
                "path": request.url.path
            }
        )
    
    @app.exception_handler(Exception)
    async def general_exception_handler(request: Request, exc: Exception):
        """
        处理所有未捕获的异常
        
        记录错误日志并返回通用错误响应
        """
        logger.error(f"未捕获的异常: {exc}", exc_info=True)
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={
                "error": "服务器内部错误",
                "detail": "处理请求时发生错误，请稍后重试",
                "path": request.url.path
            }
        )
    
    logger.info("异常处理器配置完成")


# 创建应用实例
app = create_app()
