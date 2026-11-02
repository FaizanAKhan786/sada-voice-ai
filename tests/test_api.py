from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)


def test_health_and_config():
    assert client.get("/api/health").json()["status"] == "ok"
    assert client.get("/api/config").json()["mode"] == "synthetic_demo"
    assert len(client.get("/api/demo-orders").json()) == 3


def test_websocket_end_to_end():
    with client.websocket_connect("/ws") as ws:
        assert ws.receive_json()["type"] == "ready"
        ws.send_json({"type": "message", "text": "Where is my order?"})
        answer = ws.receive_json()
        assert answer["intent"] == "order_status"
        ws.send_json({"type": "message", "text": "ORD-1003"})
        answer = ws.receive_json()
        assert answer["order_id"] == "ORD-1003"
        ws.send_json({"type": "set_language", "language": "ar"})
        assert ws.receive_json()["language"] == "ar"
        ws.send_json({"type": "message", "text": "مرحبا"})
        assert ws.receive_json()["language"] == "ar"
        ws.send_json({"type": "reset"})
        assert ws.receive_json()["type"] == "reset_complete"


def test_websocket_validation():
    with client.websocket_connect("/ws") as ws:
        ws.receive_json()
        ws.send_json({"type": "message", "text": ""})
        assert ws.receive_json()["type"] == "error"
        ws.send_json({"type": "set_language", "language": "unsupported"})
        assert ws.receive_json()["type"] == "error"


def test_transcribe_disabled():
    response = client.post('/api/transcribe', files={'file': ('audio.webm', b'abc', 'audio/webm')})
    assert response.status_code == 503
