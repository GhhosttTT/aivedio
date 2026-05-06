"""
API 速率限制中间件

使用 Redis 实现基于令牌桶算法的速率限制
"""
import time
from typing import Callable, Optional

from fastapi import Request, Response, HTTPException, status
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

from src.config import settings
from src.utils.logger import get_logger

logger = get_logger(__name__)


class RateLimitExceeded(HTTPException):
    """
    速率限制超出异常
    """
    def __init__(self, retry_after: int):
        """
        初始化速率限制异常

        Args:
            retry_after: 重试等待时间（秒）
        """
        super().__init__(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"速率限制超出，请在 {retry_after} 秒后重试"
        )
        self.retry_after = retry_after


class RateLimiter:
    """
    速率限制器

    使用令牌桶算法实现速率限制
    """

    def __init__(
        self,
        rate: int = 10,
        period: int = 60,
        redis_client: Optional[object] = None
    ):
        """
        初始化速率限制器

        Args:
            rate: 时间窗口内允许的最大请求数
            period: 时间窗口大小（秒）
            redis_client: Redis 客户端（可选，用于分布式限流）
        """
        self.rate = rate
        self.period = period
        self.redis_client = redis_client
        
        # 本地内存存储（用于单机限流）
        self._local_storage = {}

    def _get_key(self, identifier: str) -> str:
        """
        生成 Redis 键

        Args:
            identifier: 标识符（如 IP 地址或用户 ID）

        Returns:
            Redis 键
        """
        return f"rate_limit:{identifier}"

    def _check_rate_limit_local(self, identifier: str) -> tuple[bool, int]:
        """
        检查速率限制（本地内存）

        Args:
            identifier: 标识符

        Returns:
            (是否允许请求, 重试等待时间)
        """
        now = time.time()
        key = identifier
        
        # 获取或初始化请求记录
        if key not in self._local_storage:
            self._local_storage[key] = []
        
        # 清理过期记录
        requests = self._local_storage[key]
        cutoff_time = now - self.period
        requests = [req_time for req_time in requests if req_time > cutoff_time]
        self._local_storage[key] = requests
        
        # 检查是否超出限制
        if len(requests) >= self.rate:
            # 计算最早请求的剩余时间
            oldest_request = min(requests)
            retry_after = int(self.period - (now - oldest_request)) + 1
            return False, retry_after
        
        # 记录当前请求
        requests.append(now)
        return True, 0

    def _check_rate_limit_redis(self, identifier: str) -> tuple[bool, int]:
        """
        检查速率限制（Redis）

        Args:
            identifier: 标识符

        Returns:
            (是否允许请求, 重试等待时间)
        """
        if not self.redis_client:
            return self._check_rate_limit_local(identifier)
        
        try:
            key = self._get_key(identifier)
            now = time.time()
            
            # 使用 Redis 的 ZSET 实现滑动窗口
            pipe = self.redis_client.pipeline()
            
            # 移除过期记录
            cutoff_time = now - self.period
            pipe.zremrangebyscore(key, 0, cutoff_time)
            
            # 获取当前窗口内的请求数
            pipe.zcard(key)
            
            # 添加当前请求
            pipe.zadd(key, {str(now): now})
            
            # 设置过期时间
            pipe.expire(key, self.period + 1)
            
            results = pipe.execute()
            count = results[1]
            
            # 检查是否超出限制
            if count >= self.rate:
                # 获取最早的请求时间
                oldest = self.redis_client.zrange(key, 0, 0, withscores=True)
                if oldest:
                    oldest_time = oldest[0][1]
                    retry_after = int(self.period - (now - oldest_time)) + 1
                    # 移除刚才添加的请求
                    self.redis_client.zrem(key, str(now))
                    return False, retry_after
            
            return True, 0
            
        except Exception as e:
            logger.warning(f"Redis 速率限制检查失败，回退到本地限流: {e}")
            return self._check_rate_limit_local(identifier)

    def check(self, identifier: str) -> tuple[bool, int]:
        """
        检查速率限制

        Args:
            identifier: 标识符（如 IP 地址或用户 ID）

        Returns:
            (是否允许请求, 重试等待时间)
        """
        if self.redis_client:
            return self._check_rate_limit_redis(identifier)
        else:
            return self._check_rate_limit_local(identifier)


class RateLimitMiddleware(BaseHTTPMiddleware):
    """
    速率限制中间件
    """

    def __init__(
        self,
        app,
        default_rate: int = 60,
        default_period: int = 60,
        redis_client: Optional[object] = None
    ):
        """
        初始化速率限制中间件

        Args:
            app: FastAPI 应用
            default_rate: 默认速率限制（请求数/时间窗口）
            default_period: 默认时间窗口（秒）
            redis_client: Redis 客户端（可选）
        """
        super().__init__(app)
        self.default_limiter = RateLimiter(
            rate=default_rate,
            period=default_period,
            redis_client=redis_client
        )
        self.redis_client = redis_client
        
        # 特定路径的速率限制配置
        self.path_limiters = {
            "/api/auth/login": RateLimiter(30, 60, redis_client),  # 登录：30次/分钟
            "/api/auth/register": RateLimiter(3, 60, redis_client),  # 注册：3次/分钟
            "/api/projects": RateLimiter(30, 60, redis_client),  # 项目列表：30次/分钟
        }

    def _get_identifier(self, request: Request) -> str:
        """
        获取请求标识符

        优先使用用户 ID，否则使用 IP 地址

        Args:
            request: 请求对象

        Returns:
            标识符
        """
        # 尝试从请求状态中获取用户信息
        user = getattr(request.state, "user", None)
        if user and hasattr(user, "id"):
            return f"user:{user.id}"
        
        # 使用 IP 地址
        forwarded = request.headers.get("X-Forwarded-For")
        if forwarded:
            ip = forwarded.split(",")[0].strip()
        else:
            ip = request.client.host if request.client else "unknown"
        
        return f"ip:{ip}"

    def _get_limiter(self, path: str) -> RateLimiter:
        """
        获取路径对应的速率限制器

        Args:
            path: 请求路径

        Returns:
            速率限制器
        """
        # 检查是否有精确匹配的路径
        if path in self.path_limiters:
            return self.path_limiters[path]
        
        # 检查是否有前缀匹配的路径
        for pattern, limiter in self.path_limiters.items():
            if path.startswith(pattern):
                return limiter
        
        return self.default_limiter

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        """
        处理请求

        Args:
            request: 请求对象
            call_next: 下一个中间件或路由处理器

        Returns:
            响应对象
        """
        # 跳过健康检查、静态文件和 OPTIONS 预检请求
        if request.url.path in ["/health", "/", "/docs", "/redoc", "/openapi.json"]:
            return await call_next(request)
        
        if request.url.path.startswith("/storage/"):
            return await call_next(request)
        
        # 跳过 OPTIONS 请求（CORS 预检）
        if request.method == "OPTIONS":
            return await call_next(request)
        
        # 获取标识符和限制器
        identifier = self._get_identifier(request)
        limiter = self._get_limiter(request.url.path)
        
        # 检查速率限制
        allowed, retry_after = limiter.check(identifier)
        
        if not allowed:
            logger.warning(
                f"速率限制超出: {identifier} 访问 {request.url.path}, "
                f"重试等待时间: {retry_after}秒"
            )
            return JSONResponse(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                content={
                    "detail": f"速率限制超出，请在 {retry_after} 秒后重试",
                    "retry_after": retry_after
                },
                headers={"Retry-After": str(retry_after)}
            )
        
        # 继续处理请求
        response = await call_next(request)
        
        # 添加速率限制头
        response.headers["X-RateLimit-Limit"] = str(limiter.rate)
        response.headers["X-RateLimit-Period"] = str(limiter.period)
        
        return response


def get_redis_client():
    """
    获取 Redis 客户端

    Returns:
        Redis 客户端或 None
    """
    try:
        import redis
        
        # 从配置中获取 Redis URL
        redis_url = getattr(settings, "REDIS_URL", None)
        if not redis_url:
            logger.info("未配置 Redis，使用本地内存进行速率限制")
            return None
        
        client = redis.from_url(redis_url, decode_responses=True)
        # 测试连接
        client.ping()
        logger.info("Redis 连接成功，使用 Redis 进行速率限制")
        return client
        
    except ImportError:
        logger.warning("未安装 redis 包，使用本地内存进行速率限制")
        return None
    except Exception as e:
        logger.warning(f"Redis 连接失败，使用本地内存进行速率限制: {e}")
        return None
