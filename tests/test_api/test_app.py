"""
FastAPI 应用测试

测试 FastAPI 应用的基本功能
"""

import pytest
from fastapi.testclient import TestClient
from src.api.app import create_app


@pytest.fixture
def client():
    """
    创建测试客户端
    
    Returns:
        TestClient 实例
    """
    app = create_app()
    return TestClient(app)


def test_health_check(client):
    """
    测试健康检查端点
    
    验证 /health 端点返回正确的健康状态
    """
    response = client.get("/health")
    
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "healthy"
    assert data["service"] == "AI 短剧自动化生产平台"
    assert data["version"] == "1.0.0"


def test_readiness_check_reports_database_and_optional_redis(client):
    response = client.get("/ready")

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ready"
    assert data["checks"]["database"] == "ok"
    assert data["checks"]["redis"] == "not_required"


def test_readiness_requires_redis_in_production(client, monkeypatch):
    monkeypatch.setattr("src.api.app.settings.ENVIRONMENT", "production")
    monkeypatch.setattr("src.api.rate_limiter.get_redis_client", lambda: None)

    response = client.get("/ready")

    assert response.status_code == 503
    data = response.json()
    assert data["status"] == "not_ready"
    assert data["checks"]["redis"] == "unavailable"


def test_root_endpoint(client):
    """
    测试根路径端点
    
    验证 / 端点返回正确的欢迎信息
    """
    response = client.get("/")
    
    assert response.status_code == 200
    data = response.json()
    assert "message" in data
    assert "欢迎使用" in data["message"]
    assert data["version"] == "1.0.0"
    assert data["docs"] == "/docs"
    assert data["health"] == "/health"


def test_cors_headers(client):
    """
    测试 CORS 配置
    
    验证响应包含正确的 CORS 头
    """
    response = client.options(
        "/health",
        headers={
            "Origin": "http://localhost:3000",
            "Access-Control-Request-Method": "GET"
        }
    )
    
    # 检查 CORS 头是否存在
    assert "access-control-allow-origin" in response.headers


def test_cors_wildcard_does_not_advertise_credentials(client):
    response = client.options(
        "/health",
        headers={
            "Origin": "http://localhost:3000",
            "Access-Control-Request-Method": "GET",
        },
    )

    assert response.headers["access-control-allow-origin"] == "*"
    assert "access-control-allow-credentials" not in response.headers


def test_cors_explicit_origin_allows_credentials(monkeypatch):
    monkeypatch.setenv("CORS_ORIGINS", " http://localhost:5173 , http://localhost:3000 ")
    app = create_app()
    client = TestClient(app)
    response = client.options(
        "/health",
        headers={
            "Origin": "http://localhost:5173",
            "Access-Control-Request-Method": "GET",
        },
    )

    assert response.headers["access-control-allow-origin"] == "http://localhost:5173"
    assert response.headers["access-control-allow-credentials"] == "true"


def test_request_logging_middleware(client):
    """
    测试请求日志中间件
    
    验证响应包含处理时间头
    """
    response = client.get("/health")
    
    assert response.status_code == 200
    # 检查是否添加了处理时间头
    assert "x-process-time" in response.headers
    # 验证处理时间是一个有效的数字
    process_time = float(response.headers["x-process-time"])
    assert process_time >= 0


def test_value_error_handler(client):
    """
    测试 ValueError 异常处理
    
    验证 ValueError 返回 400 错误
    """
    # 这个测试需要一个会抛出 ValueError 的端点
    # 目前只有健康检查和根路径，不会抛出 ValueError
    # 这个测试将在实现业务端点后完善
    pass


def test_not_found_error(client):
    """
    测试 404 错误
    
    验证访问不存在的端点返回 404
    """
    response = client.get("/nonexistent")
    
    assert response.status_code == 404


def test_openapi_docs(client):
    """
    测试 OpenAPI 文档端点
    
    验证 /docs 和 /openapi.json 可访问
    """
    # 测试 OpenAPI JSON
    response = client.get("/openapi.json")
    assert response.status_code == 200
    data = response.json()
    assert "openapi" in data
    assert data["info"]["title"] == "AI 短剧自动化生产平台"
    
    # 测试 Swagger UI
    response = client.get("/docs")
    assert response.status_code == 200


def test_app_metadata(client):
    """
    测试应用元数据
    
    验证应用标题、描述和版本
    """
    response = client.get("/openapi.json")
    data = response.json()
    
    assert data["info"]["title"] == "AI 短剧自动化生产平台"
    assert data["info"]["description"] == "基于 AI 的短剧自动化生产系统 API"
    assert data["info"]["version"] == "1.0.0"


def test_readiness_probe_timeout_returns_503(client, monkeypatch):
    import time

    import src.api.app as app_module

    monkeypatch.setattr(app_module, "READINESS_TIMEOUT_SECONDS", 0.01)

    def slow_probe():
        time.sleep(0.2)
        return {"database": "ok", "redis": "not_required"}

    monkeypatch.setattr(app_module, "collect_readiness_checks", slow_probe)

    response = client.get("/ready")

    assert response.status_code == 503
    body = response.json()
    assert body["status"] == "not_ready"
    assert body["checks"]["database"] == "timeout"
