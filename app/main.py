"""FastAPI server for the SADA bilingual voice-support demo."""
from __future__ import annotations

import asyncio
import os
import pathlib
import tempfile
import time
from collections import Counter
from threading import Lock

from fastapi import FastAPI, File, HTTPException, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.engine import ORDERS, Session, route_message
from app.public_demo import TurnLimiter, origin_allowed, public_demo_enabled

ROOT = pathlib.Path(__file__).resolve().parent.parent
WEB = ROOT / "web"
MAX_AUDIO_BYTES = 8 * 1024 * 1024
STT_ENABLED = os.getenv("ENABLE_STT", "0") == "1"
USE_GRAPH = os.getenv("USE_LANGGRAPH", "0") == "1"
OLLAMA_ENABLED = os.getenv("ENABLE_OLLAMA", "0") == "1"

app = FastAPI(title="SADA Voice AI", version="0.2.0", description="A synthetic-data customer-support voice agent demo")
app.mount("/static", StaticFiles(directory=str(WEB)), name="static")

_stats = Counter()
_stats_lock = Lock()
_graph = None
if USE_GRAPH:
    from app.graph import make_graph
    _graph = make_graph()


@app.get("/")
def index():
    return FileResponse(str(WEB / "index.html"))


@app.get("/api/health")
def health():
    return {"status": "ok", "service": "sada-voice-ai", "version": "0.2.0"}


@app.get("/api/config")
def config():
    return {"stt_enabled": STT_ENABLED, "graph_enabled": USE_GRAPH, "ollama_enabled": OLLAMA_ENABLED, "mode": "synthetic_demo", "streaming_enabled": STT_ENABLED, "stream_protocol": "pcm_s16le_16000", "llm_model": os.getenv("OLLAMA_MODEL", "qwen3:4b") if OLLAMA_ENABLED else None}


@app.get("/api/demo-orders")
def demo_orders():
    return [{"id": order_id, **data} for order_id, data in ORDERS.items()]


@app.get("/api/stats")
def stats():
    with _stats_lock:
        counts = dict(_stats)
    return {"total_turns": counts.get("total", 0), "handoffs": counts.get("handoff", 0), "orders_checked": counts.get("order_status", 0), "other_intents": {k: v for k, v in counts.items() if k not in {"total", "handoff", "order_status"}}}


@app.post("/api/transcribe")
async def transcribe(file: UploadFile = File(...), language: str = "auto"):
    if not STT_ENABLED:
        raise HTTPException(503, "Offline STT is disabled. Set ENABLE_STT=1 and install requirements-stt.txt.")
    if language not in {"auto", "en", "ar"}:
        raise HTTPException(400, "Unsupported language")
    suffix = pathlib.Path(file.filename or "audio.webm").suffix.lower()
    if suffix not in {".webm", ".wav", ".mp3", ".ogg", ".m4a", ".mp4", ".flac"}:
        raise HTTPException(400, "Audio file type not supported")
    data = await file.read(MAX_AUDIO_BYTES + 1)
    if not data:
        raise HTTPException(400, "Empty audio file")
    if len(data) > MAX_AUDIO_BYTES:
        raise HTTPException(413, "Audio file exceeds 8 MB")
    path = ""
    try:
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as f:
            path = f.name
            f.write(data)
        from app.speech import transcribe_file
        text, detected_language = await asyncio.to_thread(transcribe_file, path, language)
    except RuntimeError as exc:
        raise HTTPException(503, str(exc)) from exc
    except Exception as exc:
        raise HTTPException(422, "Audio decoding or transcription failed") from exc
    finally:
        if path:
            pathlib.Path(path).unlink(missing_ok=True)
    return {"text": text, "language": detected_language}


@app.websocket("/ws")
async def websocket_chat(socket: WebSocket):
    if not origin_allowed(socket.headers):
        await socket.close(code=1008, reason="Origin not allowed")
        return
    await socket.accept()
    session = Session()
    limiter = TurnLimiter()
    await socket.send_json({"type": "ready", "message": "Connected to SADA demo", "language": session.language})
    try:
        while True:
            try:
                payload = await socket.receive_json()
                action = payload.get("type", "message")
                if action == "set_language":
                    value = payload.get("language", "auto")
                    if value not in {"auto", "en", "ar"}:
                        await socket.send_json({"type": "error", "message": "Invalid language"})
                        continue
                    session.language = value
                    await socket.send_json({"type": "language", "language": value})
                    continue
                if action == "reset":
                    session = Session(language=session.language)
                    await socket.send_json({"type": "reset_complete"})
                    continue
                if action != "message" or not isinstance(payload.get("text"), str):
                    await socket.send_json({"type": "error", "message": "Expected {type: message, text: string}"})
                    continue
                msg = payload["text"]
                if not msg.strip() or len(msg) > 1500:
                    await socket.send_json({"type": "error", "message": "Message must contain 1–1500 characters"})
                    continue
                if public_demo_enabled() and not limiter.allow():
                    await socket.send_json({"type": "error", "message": "Demo request limit reached. Please retry shortly."})
                    continue
                started = time.perf_counter()
                if _graph is None:
                    answer = route_message(msg, session).to_dict()
                else:
                    state = await asyncio.to_thread(_graph.invoke, {"text": msg, "session": session})
                    answer = state["result"]
                # LLM mode only embellishes the general FAQ path. Never let
                # free-form generation override sample order records or actions.
                if OLLAMA_ENABLED and answer["intent"] == "general":
                    try:
                        from app.llm import answer_with_ollama
                        generated = await answer_with_ollama(msg)
                        answer["text"] = generated
                        answer["source"] = "local_ollama_unverified"
                        session.history[-1]["text"] = generated
                    except Exception:
                        # Graceful fallback when local Ollama is not running.
                        answer["source"] = "scripted_ollama_unavailable"
                duration = int((time.perf_counter() - started) * 1000)
                with _stats_lock:
                    _stats["total"] += 1
                    _stats[answer["intent"]] += 1
                await socket.send_json({"type": "answer", **answer, "latency_ms": duration})
            except (TypeError, ValueError, AttributeError) as exc:
                await socket.send_json({"type": "error", "message": str(exc)[:200]})
    except WebSocketDisconnect:
        pass


@app.websocket("/ws/live")
async def websocket_live(socket: WebSocket):
    if not origin_allowed(socket.headers):
        await socket.close(code=1008, reason="Origin not allowed")
        return
    from app.live import handle_live

    def count(intent: str) -> None:
        with _stats_lock:
            _stats["total"] += 1
            _stats[intent] += 1

    await handle_live(socket, stt_enabled=STT_ENABLED, ollama_enabled=OLLAMA_ENABLED,
                      graph=_graph, on_answer=count)
