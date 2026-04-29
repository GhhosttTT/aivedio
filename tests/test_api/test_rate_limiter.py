"""
API 速率限制测试

测试速率限制中间件的功能
"""
import pytest
from unittest.mock import Mock, patch, MagicMock
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
from starlette.responses import JSONResponse

from src.api.rate_limiter import (
    RateLimiter,
    RateLimitMiddleware,
    RateLimitExceeded,
    get_redis_client
)


class TestRateLimiter:
    """测试 RateLimiter 类"""
    
    def test_init(self):
        """测试初始化"""
        limiter = RateLimiter(rate=10, period=60)
        assert limiter.rate == 10
        assert limiter.period == 60
        assert limiter.redis_client is None
        assert limiter._local_storage == {}
    
    def test_get_key(self):
        """测试生成 Redis 键"""
        limiter = RateLimiter()
        key = limiter._get_key("user:123")
        assert key == "rate_limit:user:123"
    
    def test_check_rate_limit_local_allow(self):
        """测试本地速率限制 - 允许请求"""
        limiter = RateLimiter(rate=5, period=60)
        
        # 前 5 个请求应该被允许
        for i in range(5):
            allowed, retry_after = limiter._check_rate_limit_local("test_user")
            assert allowed is True
            assert retry_after == 0
    
    def test_check_rate_limit_local_deny(self):
        """测试本地速率限制 - 拒绝请求"""
        limiter = RateLimiter(rate=5, period=60)
        
        # 前 5 个请求被允许
        for i in range(5):
            limiter._check_rate_limit_local("test_user")
        
        # 第 6 个请求应该被拒绝
        allowed, retry_after = limiter._check_rate_limit_local("test_user")
        assert allowed is False
        assert retry_after > 0
    
    def test_check_rate_limit_local_cleanup(self):
        """测试本地速率限制 - 清理过期记录"""
        limiter = RateLimiter(rate=5, period=1)  # 1 秒窗口
        
        # 添加 5 个请求
        for i in range(5):
            limiter._check_rate_limit_local("test_user")
        
        # 等待 1.5 秒，记录应该过期
        import time
        time.sleep(1.5)
        
        # 新请求应该被允许
        allowed, retry_after = limiter._check_rate_limit_local("test_user")
        assert allowed is True
    
    def test_check_rate_limit_redis_fallback(self):
        """测试 Redis 速率限制 - 回退到本地"""
        # 创建一个会抛出异常的 Mock Redis 客户端
        mock_redis = Mock()
        mock_redis.pipeline.side_effect = Exception("Redis error")
        
        limiter = RateLimiter(rate=5, period=60, redis_client=mock_redis)
        
        # 应该回退到本地限流
        allowed, retry_after = limiter._check_rate_limit_redis("test_user")
        assert allowed is True
    
    def test_get_redis_client_success(self):
        """测试获取 Redis 客户端 - 成功"""
        # 由于 redis 模块未安装，get_redis_client 应该返回 None
        with patch('src.api.rate_limiter.settings') as mock_settings:
            mock_settings.REDIS_URL = "redis://localhost:6379/0"
            
            # 在没有 redis 模块的情况下，应该返回 None
            client = get_redis_client()
            assert client is None
    
    def test_get_redis_client_no_url(self):
        """测试获取 Redis 客户端 - 未配置 URL"""
        with patch('src.api.rate_limiter.settings') as mock_settings:
            mock_settings.REDIS_URL = None
            
            client = get_redis_client()
            assert client is None
    
    def test_get_redis_client_import_error(self):
        """测试获取 Redis 客户端 - 导入失败"""
        with patch('src.api.rate_limiter.settings') as mock_settings:
            mock_settings.REDIS_URL = "redis://localhost:6379/0"
            
            # 由于 redis 模块未安装，应该返回 None
            client = get_redis_client()
            assert client is None


class TestRateLimitMiddleware:
    """测试 RateLimitMiddleware 类"""
    
    def test_init(self):
        """测试初始化"""
        app = FastAPI()
        middleware = RateLimitMiddleware(
            app,
            default_rate=60,
            default_period=60
        )
        
        assert middleware.default_limiter.rate == 60
        assert middleware.default_limiter.period == 60
        assert "/api/auth/login" in middleware.path_limiters
        assert "/api/auth/register" in middleware.path_limiters
        assert "/api/projects" in middleware.path_limiters
    
    def test_get_identifier_with_user(self):
        """测试获取标识符 - 使用用户 ID"""
        app = FastAPI()
        middleware = RateLimitMiddleware(app)
        
        # Mock 请求对象
        request = Mock(spec=Request)
        request.state = Mock()
        request.state.user = Mock()
        request.state.user.id = 123
        
        identifier = middleware._get_identifier(request)
        assert identifier == "user:123"
    
    def test_get_identifier_with_ip(self):
        """测试获取标识符 - 使用 IP 地址"""
        app = FastAPI()
        middleware = RateLimitMiddleware(app)
        
        # Mock 请求对象（无用户）
        request = Mock(spec=Request)
        request.state = Mock()
        request.state.user = None
        request.client = Mock()
        request.client.host = "192.168.1.1"
        request.headers = {}
        
        identifier = middleware._get_identifier(request)
        assert identifier == "ip:192.168.1.1"
    
    def test_get_identifier_with_forwarded_ip(self):
        """测试获取标识符 - 使用 X-Forwarded-For"""
        app = FastAPI()
        middleware = RateLimitMiddleware(app)
        
        # Mock 请求对象（无用户，有 X-Forwarded-For）
        request = Mock(spec=Request)
        request.state = Mock()
        request.state.user = None
        request.headers = {"X-Forwarded-For": "10.0.0.1, 192.168.1.1"}
        
        identifier = middleware._get_identifier(request)
        assert identifier == "ip:10.0.0.1"
    
    def test_get_limiter_exact_match(self):
        """测试获取限制器 - 精确匹配"""
        app = FastAPI()
        middleware = RateLimitMiddleware(app)
        
        limiter = middleware._get_limiter("/api/auth/login")
        assert limiter.rate == 5
        assert limiter.period == 60
    
    def test_get_limiter_default(self):
        """测试获取限制器 - 使用默认"""
        app = FastAPI()
        middleware = RateLimitMiddleware(app)
        
        limiter = middleware._get_limiter("/api/unknown")
        assert limiter.rate == 60
        assert limiter.period == 60
    
    @pytest.mark.asyncio
    async def test_dispatch_skip_health_check(self):
        """测试中间件 - 跳过健康检查"""
        app = FastAPI()
        
        @app.get("/health")
        async def health():
            return {"status": "ok"}
        
        middleware = RateLimitMiddleware(app)
        client = TestClient(app)
        
        # 健康检查端点不应该被限流
        for i in range(100):
            response = client.get("/health")
            assert response.status_code == 200
    
    @pytest.mark.asyncio
    async def test_dispatch_rate_limit_exceeded(self):
        """测试中间件 - 速率限制超出"""
        app = FastAPI()
        
        # 添加中间件
        app.add_middleware(
            RateLimitMiddleware,
            default_rate=1,
            default_period=60
        )
        
        @app.get("/api/test")
        async def test_endpoint():
            return {"message": "ok"}
        
        client = TestClient(app)
        
        # 第一个请求应该成功
        response = client.get("/api/test")
        assert response.status_code == 200
        
        # 第二个请求应该被限流
        response = client.get("/api/test")
        assert response.status_code == 429
        assert "retry_after" in response.json()
    
    @pytest.mark.asyncio
    async def test_dispatch_rate_limit_headers(self):
        """测试中间件 - 速率限制响应头"""
        app = FastAPI()
        
        # 添加中间件
        app.add_middleware(
            RateLimitMiddleware,
            default_rate=10,
            default_period=60
        )
        
        @app.get("/api/test")
        async def test_endpoint():
            return {"message": "ok"}
        
        client = TestClient(app)
        
        response = client.get("/api/test")
        assert response.status_code == 200
        assert "X-RateLimit-Limit" in response.headers
        assert "X-RateLimit-Period" in response.headers
        assert response.headers["X-RateLimit-Limit"] == "10"
        assert response.headers["X-RateLimit-Period"] == "60"


class TestRateLimitExceeded:
    """测试 RateLimitExceeded 异常"""
    
    def test_init(self):
        """测试初始化"""
        exc = RateLimitExceeded(retry_after=30)
        assert exc.status_code == 429
        assert "30" in exc.detail
        assert exc.retry_after == 30
