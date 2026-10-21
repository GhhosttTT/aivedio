"""Tests for the Redis -> WebSocket event bridge."""

import asyncio
import json

import pytest

from src.api.websocket import redis_event_listener


@pytest.mark.asyncio
async def test_redis_bridge_forwards_events_and_stops(monkeypatch):
    stop_event = asyncio.Event()
    payload = {"project_id": 7, "message": {"type": "progress", "progress": 0.5}}

    class FakePubSub:
        def __init__(self):
            self.sent = False

        async def subscribe(self, channel):
            self.channel = channel

        async def get_message(self, **kwargs):
            if not self.sent:
                self.sent = True
                return {"type": "message", "data": json.dumps(payload)}
            stop_event.set()
            return None

        async def close(self):
            pass

    class FakeClient:
        async def ping(self):
            return True

        def pubsub(self):
            return FakePubSub()

        async def aclose(self):
            pass

    def fake_from_url(*args, **kwargs):
        return FakeClient()

    monkeypatch.setattr("redis.asyncio.from_url", fake_from_url)
    broadcast_calls = []

    async def fake_broadcast(project_id, message):
        broadcast_calls.append((project_id, message))

    monkeypatch.setattr("src.api.websocket.manager.broadcast", fake_broadcast)

    await asyncio.wait_for(redis_event_listener(stop_event), timeout=2)

    assert broadcast_calls == [(7, payload["message"])]


@pytest.mark.asyncio
async def test_redis_bridge_keeps_retrying_until_stopped(monkeypatch):
    stop_event = asyncio.Event()

    def failing_from_url(*args, **kwargs):
        raise ConnectionError("redis down")

    monkeypatch.setattr("redis.asyncio.from_url", failing_from_url)
    task = asyncio.create_task(redis_event_listener(stop_event))
    await asyncio.sleep(0.05)
    stop_event.set()

    await asyncio.wait_for(task, timeout=2)


@pytest.mark.asyncio
async def test_redis_bridge_exits_immediately_when_already_stopped(monkeypatch):
    stop_event = asyncio.Event()
    stop_event.set()
    called = False

    def unexpected_from_url(*args, **kwargs):
        nonlocal called
        called = True
        raise AssertionError("should not connect when already stopped")

    monkeypatch.setattr("redis.asyncio.from_url", unexpected_from_url)

    await asyncio.wait_for(redis_event_listener(stop_event), timeout=0.5)

    assert called is False
