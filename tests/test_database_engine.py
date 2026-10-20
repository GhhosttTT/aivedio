"""Database engine tuning tests."""

import pytest
from sqlalchemy.pool import StaticPool

from src.database import database


def _pragma(engine, name: str):
    with engine.connect() as connection:
        return connection.exec_driver_sql(f"PRAGMA {name}").scalar()


def test_file_database_enables_wal_and_busy_timeout(tmp_path):
    engine = database.create_database_engine(f"sqlite:///{tmp_path / 'app.db'}")
    try:
        assert _pragma(engine, "journal_mode").lower() == "wal"
        assert _pragma(engine, "busy_timeout") == database.SQLITE_BUSY_TIMEOUT_SECONDS * 1000
        assert _pragma(engine, "foreign_keys") == 1
        assert _pragma(engine, "synchronous") == 1  # NORMAL
    finally:
        engine.dispose()


def test_file_engine_uses_a_real_pool_instead_of_one_shared_connection(tmp_path):
    engine = database.create_database_engine(f"sqlite:///{tmp_path / 'pool.db'}")
    try:
        assert not isinstance(engine.pool, StaticPool)
    finally:
        engine.dispose()


def test_in_memory_database_keeps_static_pool():
    engine = database.create_database_engine("sqlite://")
    try:
        assert isinstance(engine.pool, StaticPool)
        assert _pragma(engine, "foreign_keys") == 1
    finally:
        engine.dispose()


def test_check_database_connection_uses_executable_statement(tmp_path, monkeypatch):
    engine = database.create_database_engine(f"sqlite:///{tmp_path / 'check.db'}")
    monkeypatch.setattr(database, "engine", engine)
    try:
        assert database.check_database_connection() is True
    finally:
        engine.dispose()


def test_check_database_connection_reports_unusable_database(tmp_path, monkeypatch):
    missing_directory = tmp_path / "missing"
    engine = database.create_database_engine(f"sqlite:///{missing_directory / 'check.db'}")
    monkeypatch.setattr(database, "engine", engine)
    try:
        assert database.check_database_connection() is False
    finally:
        engine.dispose()


def test_postgres_urls_keep_server_pool_settings():
    engine = database.create_database_engine("postgresql+psycopg2://user:pass@localhost/db")
    try:
        assert engine.pool.size() == 10
        assert engine.pool._max_overflow == 20
    finally:
        engine.dispose()


@pytest.mark.parametrize("url", ["sqlite://", "sqlite:///:memory:"])
def test_in_memory_urls_are_detected(url):
    engine = database.create_database_engine(url)
    try:
        assert isinstance(engine.pool, StaticPool)
    finally:
        engine.dispose()
