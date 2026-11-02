"""Streaming VAD, live protocol and mocked local speech/LLM tests."""
import asyncio
from array import array

from fastapi.testclient import TestClient

from app import main
from app import live
from app import speech
from app.streaming import AudioSegmenter, FRAME_BYTES


def pcm(value, frames=1):
    return array("h", [value] * (FRAME_BYTES // 2) * frames).tobytes()


def test_segmenter_endpoints_and_preroll():
    vad = AudioSegmenter(use_webrtc=False)
    assert vad.detector == "energy_fallback"
    assert vad.push(pcm(0, 12)) == []
    assert vad.push(pcm(1400, 2)) == []
    events = vad.push(pcm(1400, 1))
    assert events == [("speech_started", None)]
    events = vad.push(pcm(0, 30))
    assert len(events) == 1 and events[0][0] == "speech_ended"
    assert len(events[0][1]) >= (3 + 30) * FRAME_BYTES
    assert vad.flush() is None


def test_segmenter_flush_and_validation():
    vad = AudioSegmenter(use_webrtc=False)
    events = vad.push(pcm(1600, 3))
    assert events[0][0] == "speech_started"
    assert len(vad.flush()) >= 3 * FRAME_BYTES
    assert vad.flush() is None
    try:
        vad.push(pcm(1600, 101))
        assert False, "expected validation error"
    except ValueError:
        pass


def test_live_text_and_controls():
    with TestClient(main.app).websocket_connect("/ws/live") as ws:
        ready = ws.receive_json()
        assert ready["type"] == "ready" and ready["sample_rate"] == 16000
        ws.send_json({"type": "message", "text": "where is my order?"})
        answer = ws.receive_json()
        assert answer["type"] == "answer" and answer["intent"] == "order_status"
        ws.send_json({"type": "message", "text": "ORD-1001"})
        assert ws.receive_json()["order_id"] == "ORD-1001"
        ws.send_json({"type": "set_language", "language": "ar"})
        assert ws.receive_json()["language"] == "ar"
        ws.send_json({"type": "message", "text": "مرحبا"})
        assert ws.receive_json()["language"] == "ar"
        ws.send_json({"type": "reset"})
        assert ws.receive_json()["type"] == "reset_complete"
        ws.send_json({"type": "unknown"})
        assert ws.receive_json()["type"] == "error"


def test_live_audio_streaming_with_mock_asr(monkeypatch):
    monkeypatch.setattr(main, "STT_ENABLED", True)
    monkeypatch.setattr(live, "AudioSegmenter", lambda: AudioSegmenter(use_webrtc=False))
    monkeypatch.setattr(speech, "transcribe_pcm16", lambda payload, language: ("Track ORD-1002", "en"))
    with TestClient(main.app).websocket_connect("/ws/live") as ws:
        assert ws.receive_json()["audio"] is True
        ws.send_bytes(pcm(1800, 3))
        assert ws.receive_json()["type"] == "speech_started"
        ws.send_bytes(pcm(0, 30))
        assert ws.receive_json()["type"] == "speech_ended"
        assert ws.receive_json()["type"] == "transcript"
        answer = ws.receive_json()
        assert answer["type"] == "answer" and answer["order_id"] == "ORD-1002"


def test_ollama_token_streaming_and_fallback(monkeypatch):
    from app import llm
    monkeypatch.setattr(main, "OLLAMA_ENABLED", True)
    async def fake_stream(question, previous_turns):
        assert question == "please tell me more"
        yield "These are "
        yield "demo policies."
    monkeypatch.setattr(llm, "stream_ollama", fake_stream)
    with TestClient(main.app).websocket_connect("/ws/live") as ws:
        ws.receive_json()
        ws.send_json({"type": "message", "text": "please tell me more"})
        assert ws.receive_json()["type"] == "answer_start"
        assert ws.receive_json()["delta"] == "These are "
        assert ws.receive_json()["delta"] == "demo policies."
        result = ws.receive_json()
        assert result["type"] == "answer"
        assert result["text"] == "These are demo policies."
        assert result["source"] == "local_ollama_unverified"


def test_interrupt_cancels_pending_model(monkeypatch):
    from app import llm
    monkeypatch.setattr(main, "OLLAMA_ENABLED", True)
    async def slow_stream(question, previous_turns):
        yield "Sorry, "
        await asyncio.sleep(20)
        yield "delayed"
    monkeypatch.setattr(llm, "stream_ollama", slow_stream)
    with TestClient(main.app).websocket_connect("/ws/live") as ws:
        ws.receive_json()
        ws.send_json({"type": "message", "text": "please tell me more"})
        assert ws.receive_json()["type"] == "answer_start"
        assert ws.receive_json()["type"] == "answer_delta"
        ws.send_json({"type": "interrupt"})
        assert ws.receive_json()["type"] == "interrupted"
        ws.send_json({"type": "message", "text": "hello"})
        assert ws.receive_json()["intent"] == "greeting"
