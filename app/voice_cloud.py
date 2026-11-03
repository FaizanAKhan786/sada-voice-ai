"""Groq-hosted utterance ASR and bounded English/Arabic TTS for public SADA demos.

No raw audio or API keys are saved. PCM is accumulated in memory until VAD
signals a pause; this is NOT word-by-word STT. HTTP requests are cancellable.
"""
from __future__ import annotations

import asyncio
import io
import os
import re
import wave
from collections import deque
from time import monotonic

import httpx

from app.streaming import SAMPLE_RATE, MAX_UTTERANCE_SECONDS

STT_URL = "https://api.groq.com/openai/v1/audio/transcriptions"
TTS_URL = "https://api.groq.com/openai/v1/audio/speech"
STT_MODEL = "whisper-large-v3-turbo"
ENGLISH_TTS_MODEL = "canopylabs/orpheus-v1-english"
ARABIC_TTS_MODEL = "canopylabs/orpheus-arabic-saudi"
MAX_WAV_BYTES = 2_500_000
MAX_CHUNKS = 3


def cloud_voice_enabled() -> bool:
    return os.getenv("ENABLE_CLOUD_VOICE", "0") == "1" and bool(os.getenv("GROQ_API_KEY", "").strip())


def hosted_tts_enabled() -> bool:
    return cloud_voice_enabled() and os.getenv("ENABLE_HOSTED_TTS", "0") == "1"


class VoiceQuota:
    """Per-process cost guard only, not a substitute for edge rate limiting."""

    def __init__(self, minute: int, day: int):
        self.minute, self.day = minute, day
        self._recent: deque[float] = deque()
        self._daily: deque[float] = deque()

    def allow(self, now: float | None = None) -> bool:
        now = monotonic() if now is None else now
        for q, span in ((self._recent, 60), (self._daily, 86400)):
            while q and q[0] <= now - span:
                q.popleft()
        if len(self._recent) >= self.minute or len(self._daily) >= self.day:
            return False
        self._recent.append(now)
        self._daily.append(now)
        return True


ASR_QUOTA = VoiceQuota(minute=12, day=160)
TTS_QUOTA = VoiceQuota(minute=15, day=240)
ASR_SEMAPHORE = asyncio.Semaphore(2)
TTS_SEMAPHORE = asyncio.Semaphore(2)


def pcm_to_wav(pcm: bytes) -> bytes:
    if not pcm or len(pcm) % 2 or len(pcm) > SAMPLE_RATE * 2 * MAX_UTTERANCE_SECONDS:
        raise ValueError("Invalid audio length")
    out = io.BytesIO()
    with wave.open(out, "wb") as f:
        f.setnchannels(1)
        f.setsampwidth(2)
        f.setframerate(SAMPLE_RATE)
        f.writeframes(pcm)
    return out.getvalue()


def identify_language(detected: str, text: str, chosen: str) -> str:
    if chosen in {"en", "ar"}:
        return chosen
    value = str(detected or "").strip().lower()
    if value in {"ar", "arabic"}:
        return "ar"
    if value in {"en", "english"}:
        return "en"
    return "ar" if re.search(r"[\u0600-\u06ff]", text) else "en"


async def transcribe_cloud(
    pcm: bytes, chosen: str = "auto", *, transport: httpx.AsyncBaseTransport | None = None
) -> tuple[str, str]:
    if not cloud_voice_enabled():
        raise RuntimeError("Cloud speech is not configured")
    if chosen not in {"auto", "ar", "en"}:
        raise ValueError("Unsupported language")
    audio = pcm_to_wav(pcm)
    if not ASR_QUOTA.allow():
        raise RuntimeError("Speech recognition usage limit reached")
    try:
        await asyncio.wait_for(ASR_SEMAPHORE.acquire(), timeout=2.0)
    except asyncio.TimeoutError:
        raise RuntimeError("Speech recognition busy") from None
    try:
        fields = {"model": os.getenv("GROQ_STT_MODEL", STT_MODEL), "response_format": "verbose_json"}
        if chosen != "auto":
            fields["language"] = chosen
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(32, connect=5, read=25), transport=transport, trust_env=False
        ) as client:
            response = await client.post(
                STT_URL,
                headers={"Authorization": "Bearer " + os.environ["GROQ_API_KEY"].strip()},
                data=fields,
                files={"file": ("utterance.wav", audio, "audio/wav")},
            )
        if response.status_code != 200:
            raise RuntimeError("Speech recognition service unavailable")
        data = response.json()
        text = data.get("text", "") if isinstance(data, dict) else ""
        if not isinstance(text, str) or len(text) > 1500:
            raise RuntimeError("Invalid transcription")
        return text.strip(), identify_language(data.get("language", ""), text, chosen)
    except (httpx.HTTPError, ValueError) as exc:
        raise RuntimeError("Speech recognition failed") from exc
    finally:
        ASR_SEMAPHORE.release()


def voice_segments(text: str, limit: int = 175, max_chunks: int = MAX_CHUNKS) -> list[str]:
    """TTS API permits 200 chars/request. Avoid huge/billable generated replies."""
    text = re.sub(r"\s+", " ", text.replace("**", "").replace("`", "")).strip()
    text = re.sub(r"https?://\S+", "", text).strip()
    if not text:
        return []
    parts: list[str] = []
    while text and len(parts) < max_chunks:
        if len(text) <= limit:
            parts.append(text)
            break
        cut = max(text.rfind(c, 0, limit) + 1 for c in (".", "?", "!", "؟"))
        if cut < limit // 3:
            cut = text.rfind(" ", 0, limit + 1)
        if cut <= 0:
            cut = limit
        part = text[:cut].strip()
        if part:
            parts.append(part)
        text = text[cut:].strip()
    return parts


async def speak_cloud(
    text: str, language: str, *, transport: httpx.AsyncBaseTransport | None = None
) -> bytes:
    if not hosted_tts_enabled():
        raise RuntimeError("Hosted speech not configured")
    if language not in {"en", "ar"} or not text.strip() or len(text) > 200:
        raise ValueError("Invalid voice request")
    if not TTS_QUOTA.allow():
        raise RuntimeError("Speech output usage limit reached")
    try:
        await asyncio.wait_for(TTS_SEMAPHORE.acquire(), timeout=2.0)
    except asyncio.TimeoutError:
        raise RuntimeError("Speech output busy") from None
    try:
        payload = {
            "model": ARABIC_TTS_MODEL if language == "ar" else ENGLISH_TTS_MODEL,
            "input": text,
            "voice": "noura" if language == "ar" else "autumn",
            "response_format": "wav",
        }
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(36, connect=5, read=30), transport=transport, trust_env=False
        ) as client:
            response = await client.post(
                TTS_URL,
                headers={"Authorization": "Bearer " + os.environ["GROQ_API_KEY"].strip()},
                json=payload,
            )
        if response.status_code != 200:
            # Never log source text, credentials, or the full provider error body.
            details = {}
            try:
                details = response.json().get("error", {})
            except (ValueError, AttributeError):
                pass
            if not isinstance(details, dict):
                details = {}
            code = str(details.get("code") or "")[:45]
            kind = str(details.get("type") or "")[:45]
            param = str(details.get("param") or "")[:45]
            description = str(details.get("message") or "").lower()
            keywords = ("permission", "billing", "rate limit", "unsupported", "voice",
                        "model", "character", "input", "length", "validation", "quota")
            category = ",".join(k for k in keywords if k in description)
            raise RuntimeError(
                f"Speech output HTTP {response.status_code}, code={code!r}, "
                f"type={kind!r}, param={param!r}, category={category!r}, "
                f"chars={len(text)}, language={language}"
            )
        sound = response.content
        if not sound.startswith(b"RIFF") or sound[8:12] != b"WAVE" or len(sound) > MAX_WAV_BYTES:
            raise RuntimeError("Speech service returned invalid audio")
        return sound
    except httpx.HTTPError as exc:
        raise RuntimeError("Speech output failed") from exc
    finally:
        TTS_SEMAPHORE.release()
