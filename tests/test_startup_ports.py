"""Startup port diagnostics."""

import socket

import start_services


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def test_port_in_use_detects_listener():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind(("127.0.0.1", 0))
        listener.listen(1)
        port = int(listener.getsockname()[1])
        assert start_services.port_in_use(port) is True


def test_port_in_use_false_for_closed_port():
    assert start_services.port_in_use(_free_port()) is False


def test_describe_port_owner_returns_none_when_unused():
    assert start_services.describe_port_owner(_free_port()) is None


def test_log_launcher_delegates_port_check(monkeypatch):
    import start_services_with_logs

    calls = []

    def fake_check(port, timeout=10):
        calls.append((port, timeout))
        return True

    monkeypatch.setattr(start_services, "check_port", fake_check)
    assert start_services_with_logs.check_port(8080, timeout=3) is True
    assert calls == [(8080, 3)]
