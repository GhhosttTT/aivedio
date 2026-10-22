"""Service launcher log handling."""

import sys

import start_services


def test_start_service_reports_immediate_exit(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(start_services, "LOG_DIR", tmp_path / "logs")

    started = start_services.start_service(
        "Broken",
        [sys.executable, "-c", "print('boom'); raise SystemExit(2)"],
        delay=0.5,
    )

    assert started is False
    output = capsys.readouterr().out
    assert "boom" in output
    assert "退出码 2" in output
    assert (tmp_path / "logs" / "broken.log").exists()


def test_new_window_streams_logs_on_posix(monkeypatch):
    import pytest
    import start_services_with_logs

    if sys.platform == "win32":
        pytest.skip("Windows uses a separate window")

    calls = []

    def fake_stream(name, cmd, cwd=None):
        calls.append((name, cmd, cwd))
        return object()

    monkeypatch.setattr(start_services_with_logs, "start_service_with_logs", fake_stream)

    assert start_services_with_logs.start_service_in_new_window("Demo", ["true"]) is True
    assert calls == [("Demo", ["true"], None)]


def test_build_services_adds_redis_when_available(tmp_path, monkeypatch):
    (tmp_path / "ComfyUI").mkdir()
    (tmp_path / "ComfyUI" / "main.py").write_text("", encoding="utf-8")
    monkeypatch.setattr(start_services.shutil, "which", lambda name: "/usr/bin/redis-server")

    services = start_services.build_services(tmp_path)
    names = [service["name"] for service in services]

    assert names[0] == "Redis"
    assert {"ComfyUI", "FastAPI Backend", "Celery Worker", "Frontend (Vite)"} <= set(names)
    fastapi = next(service for service in services if service["name"] == "FastAPI Backend")
    assert fastapi["cmd"][0] == sys.executable


def test_build_services_skips_missing_redis(tmp_path, monkeypatch):
    monkeypatch.setattr(start_services.shutil, "which", lambda name: None)

    names = [service["name"] for service in start_services.build_services(tmp_path)]

    assert names == ["FastAPI Backend"]


def test_build_services_names_and_ports_are_unique(tmp_path, monkeypatch):
    monkeypatch.setattr(start_services.shutil, "which", lambda name: "/usr/bin/redis-server")

    services = start_services.build_services(tmp_path)
    names = [service["name"] for service in services]
    ports = [service["port"] for service in services if service["port"]]

    assert len(names) == len(set(names))
    assert len(ports) == len(set(ports))


def test_main_reports_failure_when_a_service_does_not_start(monkeypatch):
    monkeypatch.setattr(start_services, "check_python", lambda: True)
    monkeypatch.setattr(start_services, "check_virtualenv", lambda: True)
    monkeypatch.setattr(start_services, "check_database", lambda: True)
    monkeypatch.setattr(start_services, "build_services", lambda root: [
        {"name": "Broken", "cmd": ["broken"], "cwd": None, "delay": 0, "port": None},
    ])
    monkeypatch.setattr(start_services, "start_service", lambda **kwargs: False)

    assert start_services.main() is False


def test_log_launcher_reports_failure_when_window_start_fails(monkeypatch):
    import start_services_with_logs

    monkeypatch.setattr(start_services_with_logs, "check_python", lambda: True)
    monkeypatch.setattr(start_services_with_logs, "check_virtualenv", lambda: True)
    monkeypatch.setattr(start_services_with_logs, "check_database", lambda: True)
    monkeypatch.setattr(start_services_with_logs, "start_redis", lambda: False)
    monkeypatch.setattr(
        "start_services.build_services",
        lambda root: [{"name": "Broken", "cmd": ["broken"], "cwd": None, "delay": 0, "port": None}],
    )
    monkeypatch.setattr(start_services_with_logs, "start_service_in_new_window", lambda **kwargs: False)

    assert start_services_with_logs.main() is False


def test_build_services_skips_missing_comfyui(tmp_path):
    names = [service["name"] for service in start_services.build_services(tmp_path)]

    assert "ComfyUI" not in names


def test_build_services_skips_missing_celery_and_npm(tmp_path, monkeypatch):
    monkeypatch.setattr(start_services.shutil, "which", lambda name: None)

    names = [service["name"] for service in start_services.build_services(tmp_path)]

    assert "Celery Worker" not in names
    assert "Frontend (Vite)" not in names


def test_main_treats_occupied_port_as_already_running(monkeypatch):
    monkeypatch.setattr(start_services, "check_python", lambda: True)
    monkeypatch.setattr(start_services, "check_virtualenv", lambda: True)
    monkeypatch.setattr(start_services, "check_database", lambda: True)
    monkeypatch.setattr(start_services, "build_services", lambda root: [
        {"name": "FastAPI Backend", "cmd": ["python", "main.py"], "cwd": None, "delay": 0, "port": 8000},
    ])
    monkeypatch.setattr(start_services, "port_in_use", lambda port: True)
    monkeypatch.setattr(
        start_services,
        "start_service",
        lambda **kwargs: (_ for _ in ()).throw(AssertionError("should not start an occupied service")),
    )

    assert start_services.main() is True
