"""Global exception handler and request-id contract tests."""

from fastapi.testclient import TestClient

from src.api.app import create_app


def _client_with_routes():
    app = create_app()

    @app.get("/__test/value-error")
    def value_error():
        raise ValueError("bad input")

    @app.get("/__test/missing")
    def missing():
        raise FileNotFoundError("/srv/private/secret.mp4")

    @app.get("/__test/boom")
    def boom():
        raise RuntimeError("database password leaked at /srv/private")

    return TestClient(app, raise_server_exceptions=False)


def _get(path, **kwargs):
    return _client_with_routes().get(path, **kwargs)


def test_value_error_maps_to_400():
    response = _get("/__test/value-error")
    assert response.status_code == 400
    assert response.json()["error"] == "输入验证失败"


def test_missing_file_maps_to_404():
    response = _get("/__test/missing")
    assert response.status_code == 404
    assert response.json()["error"] == "资源不存在"


def test_unhandled_exception_is_generic_and_keeps_request_id():
    response = _get("/__test/boom", headers={"X-Request-ID": "req-123"})

    assert response.status_code == 500
    body = response.json()
    assert body["error"] == "服务器内部错误"
    assert body["detail"] == "处理请求时发生错误，请稍后重试"
    assert body["request_id"] == "req-123"
    assert "database password" not in response.text
    assert response.headers["X-Request-ID"] == "req-123"


def test_production_4xx_detail_hides_absolute_paths(monkeypatch):
    from src.api import app as app_module

    monkeypatch.setattr(app_module.settings, "ENVIRONMENT", "production")
    response = _get("/__test/missing")

    assert response.status_code == 404
    detail = response.json()["detail"]
    assert "/srv/private" not in detail
    assert "secret.mp4" in detail
    assert "…/" in detail


def test_development_4xx_detail_keeps_full_path(monkeypatch):
    from src.api import app as app_module

    monkeypatch.setattr(app_module.settings, "ENVIRONMENT", "development")
    response = _get("/__test/missing")

    assert "/srv/private/secret.mp4" in response.json()["detail"]
