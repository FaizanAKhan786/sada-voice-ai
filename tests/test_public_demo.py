"""Public hosting guardrails. Synthetic records only."""
from fastapi.testclient import TestClient
from fastapi import WebSocketDisconnect
import pytest

from app.main import app
from app.public_demo import TurnLimiter, origin_allowed


def test_same_origin_handshake(monkeypatch):
    monkeypatch.setenv("PUBLIC_DEMO_MODE", "1")
    assert origin_allowed({"origin": "https://sada.example", "host": "sada.example"})
    assert not origin_allowed({"origin": "https://evil.example", "host": "sada.example"})
    assert not origin_allowed({"host": "sada.example"})
    assert not origin_allowed({"origin": "https://sada.example.evil.test", "host": "sada.example"})
    with TestClient(app).websocket_connect('/ws/live', headers={'origin':'https://example.com','host':'example.com'}) as ws:
        assert ws.receive_json()['type'] == 'ready'
    with pytest.raises(WebSocketDisconnect):
        with TestClient(app).websocket_connect('/ws/live', headers={'origin':'https://other.example','host':'example.com'}):
            pass


def test_per_session_turn_limiter():
    limit = TurnLimiter(limit=2, window_seconds=60)
    assert limit.allow(now=100)
    assert limit.allow(now=101)
    assert not limit.allow(now=110)
    assert limit.allow(now=160)
