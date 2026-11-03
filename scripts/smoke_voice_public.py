"""Real public voice smoke test: synthetic English audio -> Groq STT -> answer -> Groq TTS.

No API key is available to the runner. Calls go through the same WebSocket used
by visitors. Test costs one synthetic utterance and one small speech reply.
"""
from __future__ import annotations

import asyncio
import base64
import json
from pathlib import Path
from urllib.request import urlopen
import wave
import time

from websockets.asyncio.client import connect

URL = "https://sada-voice-ai.onrender.com"
FIXTURE = Path(__file__).resolve().parents[1] / "tests/fixtures/synthetic_voice_en.wav"


def check_config():
    # Render often deploys a new commit after GitHub Actions starts.
    for retry in range(42):
        try:
            with urlopen(URL + "/api/config", timeout=30) as reply:
                config = json.load(reply)
            if all(config.get(k) is True for k in
                   ("cloud_voice_enabled", "cloud_tts_enabled", "hosted_llm_enabled")):
                print("Public STT, TTS and LLM enabled; no credential sent to CI.")
                return
        except Exception:
            pass
        if retry < 41:
            time.sleep(10)
    raise RuntimeError("Hosted voice flags were not enabled on public Render after checks")


async def run():
    with wave.open(str(FIXTURE), "rb") as sound:
        assert sound.getnchannels() == 1 and sound.getsampwidth() == 2
        assert sound.getframerate() == 16000
        pcm = sound.readframes(sound.getnframes())

    counts = {}
    async with connect("wss://sada-voice-ai.onrender.com/ws/live", origin=URL,
                       open_timeout=40, max_size=4 * 1024 * 1024) as ws:
        ready = json.loads(await ws.recv())
        assert ready.get("type") == "ready" and ready.get("cloud_voice") is True
        await ws.send(json.dumps({"type": "set_language", "language": "en"}))
        await ws.send(json.dumps({"type": "set_voice_output", "enabled": True}))
        # Original audio is 16 kHz PCM16 mono; 640 bytes = one 20 ms frame.
        for i in range(0, len(pcm), 640):
            await ws.send(pcm[i:i + 640])
        for _ in range(36):
            await ws.send(b"\x00" * 640)
        answer_turn = None
        got_transcript = got_audio = False
        deadline = asyncio.get_running_loop().time() + 110
        while asyncio.get_running_loop().time() < deadline:
            remaining = min(40, deadline - asyncio.get_running_loop().time())
            event = json.loads(await asyncio.wait_for(ws.recv(), remaining))
            kind = event.get("type")
            counts[kind] = counts.get(kind, 0) + 1
            if kind == "transcript":
                assert event.get("text", "").strip(), "Cloud STT returned empty text"
                got_transcript = True
            elif kind == "answer":
                assert event.get("text", "").strip()
                answer_turn = event.get("turn_id")
            elif kind == "voice_audio":
                assert event.get("turn_id") == answer_turn
                wav = base64.b64decode(event.get("audio_base64", ""), validate=True)
                assert wav.startswith(b"RIFF") and wav[8:12] == b"WAVE"
                got_audio = True
            elif kind == "voice_fallback":
                raise RuntimeError("Hosted TTS failed and returned browser voice fallback")
            elif kind == "error":
                raise RuntimeError("Public voice endpoint returned a sanitized error")
            elif kind == "voice_done":
                assert got_transcript and answer_turn and got_audio
                print("PASS: synthetic speech -> real hosted STT -> SADA -> hosted TTS WAV")
                return
        raise RuntimeError("Voice check timed out. Events only: " + str(counts))


if __name__ == "__main__":
    check_config()
    asyncio.run(run())
