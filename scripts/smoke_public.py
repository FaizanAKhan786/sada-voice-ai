"""One synthetic public hosted-chat smoke check via the real WebSocket.

Called from GitHub Actions after a push. Sends no real customer information
and does not expose the Groq credential to the CI runner.
"""
import asyncio
import json
import time
from urllib.request import urlopen

from websockets.asyncio.client import connect

BASE = "https://sada-voice-ai.onrender.com"
MODEL = "openai/gpt-oss-120b"


def wait_for_updated_service():
    for attempt in range(36):
        try:
            with urlopen(BASE + "/api/config", timeout=20) as response:
                data = json.load(response)
            if data.get("hosted_llm_enabled") and data.get("hosted_model") == MODEL:
                print("Deployed service reports hosted AI enabled (key not exposed).")
                return
        except Exception:
            pass
        if attempt < 35:
            time.sleep(10)
    raise RuntimeError("Public service did not report the expected hosted configuration")


async def test_real_chat():
    async with connect(
        "wss://sada-voice-ai.onrender.com/ws/live",
        origin=BASE,
        open_timeout=40,
        close_timeout=10,
    ) as ws:
        first = json.loads(await asyncio.wait_for(ws.recv(), 20))
        assert first.get("type") == "ready", "WebSocket handshake did not complete"
        await ws.send(json.dumps({"type": "message", "text": "Could you clarify how this demo works?"}))
        seen_deltas = 0
        for _ in range(90):
            data = json.loads(await asyncio.wait_for(ws.recv(), 40))
            if data.get("type") == "answer_delta":
                seen_deltas += 1
            if data.get("type") == "answer":
                assert data.get("source") == "hosted_groq_unverified", (
                    "Hosted provider failed or demo quota was reached; scripted fallback used"
                )
                assert data.get("text", "").strip(), "No answer text returned"
                assert seen_deltas, "No provider response tokens streamed"
                print("Real hosted model streaming succeeded, with no secret logged.")
                return
            if data.get("type") == "error":
                raise RuntimeError("Public chat returned an application error")
        raise RuntimeError("No final response received")


if __name__ == "__main__":
    wait_for_updated_service()
    asyncio.run(test_real_chat())
