"""Tests for the short-lived production readiness report cache."""

import pytest

from src.services import production_readiness
from src.services.production_readiness import get_cached_production_readiness


@pytest.fixture(autouse=True)
def clear_cache():
    production_readiness.clear_production_readiness_cache()
    yield
    production_readiness.clear_production_readiness_cache()


@pytest.fixture()
def build_calls(monkeypatch):
    calls = []

    def fake_build(_self, project_id, **_kwargs):
        calls.append(project_id)
        return {"status": "ready", "checks": {"project": project_id}}

    monkeypatch.setattr(
        "src.services.production_readiness.ProductionReadinessService.build_report",
        fake_build,
    )
    return calls


def test_ready_report_is_reused(build_calls):
    first = get_cached_production_readiness(None, 7, project_version="v1")
    second = get_cached_production_readiness(None, 7, project_version="v1")

    assert len(build_calls) == 1
    assert first == second


def test_cache_returns_isolated_copies(build_calls):
    first = get_cached_production_readiness(None, 7, project_version="v1")
    first["checks"]["caller"] = "mutation"

    second = get_cached_production_readiness(None, 7, project_version="v1")
    assert "caller" not in second["checks"]


def test_blocked_report_is_not_cached(build_calls, monkeypatch):
    def fake_build(_self, project_id, **_kwargs):
        build_calls.append(project_id)
        return {"status": "blocked", "blockers": [{"code": "missing"}]}

    monkeypatch.setattr(
        "src.services.production_readiness.ProductionReadinessService.build_report",
        fake_build,
    )

    get_cached_production_readiness(None, 7, project_version="v1")
    get_cached_production_readiness(None, 7, project_version="v1")

    assert len(build_calls) == 2


def test_project_version_change_invalidates_cache(build_calls):
    get_cached_production_readiness(None, 7, project_version="v1")
    get_cached_production_readiness(None, 7, project_version="v2")

    assert len(build_calls) == 2


def test_cache_expires_after_ttl(build_calls, monkeypatch):
    monkeypatch.setattr(production_readiness, "_READY_REPORT_TTL_SECONDS", 0)

    get_cached_production_readiness(None, 7, project_version="v1")
    get_cached_production_readiness(None, 7, project_version="v1")

    assert len(build_calls) == 2


def test_overrides_are_part_of_the_cache_key(build_calls):
    get_cached_production_readiness(None, 7, project_version="v1", model_override="model-a")
    get_cached_production_readiness(None, 7, project_version="v1", model_override="model-b")

    assert len(build_calls) == 2
