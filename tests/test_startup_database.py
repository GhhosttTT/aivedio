"""Startup database bootstrap tests."""

import pytest
from sqlalchemy import create_engine, inspect, text

import start_services
import start_services_with_logs


def _columns(engine, table: str) -> set[str]:
    return {column["name"] for column in inspect(engine).get_columns(table)}


@pytest.mark.parametrize("module", [start_services, start_services_with_logs])
def test_check_database_creates_missing_schema(tmp_path, monkeypatch, module):
    engine = create_engine(f"sqlite:///{tmp_path / 'fresh.db'}")
    monkeypatch.setattr("src.database.session.engine", engine)
    try:
        assert module.check_database() is True
        tables = set(inspect(engine).get_table_names())
        assert {"characters", "projects", "scenes", "tasks"} <= tables
        assert {"personality", "appearance"} <= _columns(engine, "characters")
    finally:
        engine.dispose()


@pytest.mark.parametrize("module", [start_services, start_services_with_logs])
def test_check_database_adds_legacy_character_columns(tmp_path, monkeypatch, module):
    engine = create_engine(f"sqlite:///{tmp_path / 'legacy.db'}")
    with engine.begin() as connection:
        connection.execute(
            text(
                "CREATE TABLE characters ("
                "id INTEGER PRIMARY KEY, project_id INTEGER, name VARCHAR(100))"
            )
        )
    monkeypatch.setattr("src.database.session.engine", engine)
    try:
        assert module.check_database() is True
        columns = _columns(engine, "characters")
        assert "personality" in columns
        assert "appearance" in columns
    finally:
        engine.dispose()
