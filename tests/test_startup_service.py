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
