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
