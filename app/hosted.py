"""Optional hosted Groq chat completions for SADA's synthetic customer-support demo.

No secrets or direct provider calls are exposed to the browser. Public deployment
requires the owner to set GROQ_API_KEY in Render's secret environment variables.
"""
from __future__ import annotations

import json
import os
import asyncio
from collections import deque
from time import monotonic
from typing import AsyncIterator

import httpx

from app.llm import make_messages

GROQ_ENDPOINT = "https://api.groq.com/openai/v1/chat/completions"
DEFAULT_MODEL = "llama-3.3-70b-versatile"
GENERATIVE_INTENTS = frozenset({"general", "greeting", "returns", "refunds", "shipping"})


def hosted_enabled() -> bool:
    return os.getenv("ENABLE_HOSTED_LLM", "0") == "1" and bool(os.getenv("GROQ_API_KEY", "").strip())


class GlobalQuota:
    """Bound provider calls per process to reduce accidental bills (not a DDoS defence)."""

    def __init__(self, per_minute: int = 12, per_day: int = 200):
        self.per_minute = per_minute
        self.per_day = per_day
        self.recent: deque[float] = deque()
        self.daily: deque[float] = deque()

    def allow(self, now: float | None = None) -> bool:
        now = monotonic() if now is None else now
        while self.recent and self.recent[0] <= now - 60:
            self.recent.popleft()
        while self.daily and self.daily[0] <= now - 86400:
            self.daily.popleft()
        if len(self.recent) >= self.per_minute or len(self.daily) >= self.per_day:
            return False
        self.recent.append(now)
        self.daily.append(now)
        return True


HOSTED_QUOTA = GlobalQuota()
HOSTED_CONCURRENCY = asyncio.Semaphore(3)


async def stream_hosted(
    question: str,
    previous_turns: list[dict[str, str]] | None = None,
    *,
    transport: httpx.AsyncBaseTransport | None = None,
) -> AsyncIterator[str]:
    """Yield streamed answer text via an OpenAI-compatible Groq SSE endpoint.

    Only a bounded number of recent messages are sent; models cannot call tools
    or alter demo orders. A fixed endpoint prevents arbitrary user-controlled URLs.
    """
    if not hosted_enabled():
        raise RuntimeError("Hosted LLM is not configured")

    body = {
        "model": os.getenv("GROQ_MODEL", DEFAULT_MODEL),
        "messages": make_messages(question, (previous_turns or [])[-4:]),
        "stream": True,
        "temperature": 0.2,
        "max_tokens": 280,
    }
    headers = {
        "Authorization": "Bearer " + os.environ["GROQ_API_KEY"].strip(),
        "Content-Type": "application/json",
        "Accept": "text/event-stream",
    }
    limit = 2000
    # Reject overloaded requests instead of accumulating a billable inference queue.
    try:
        await asyncio.wait_for(HOSTED_CONCURRENCY.acquire(), timeout=3.0)
    except asyncio.TimeoutError:
        raise RuntimeError("Hosted model is busy") from None
    try:
        async for token in _perform_request(headers, body, transport=transport, limit=limit):
            yield token
    finally:
        HOSTED_CONCURRENCY.release()


async def _perform_request(headers, body, *, transport, limit: int) -> AsyncIterator[str]:
    total = 0
    done = False
    async with httpx.AsyncClient(
        timeout=httpx.Timeout(38, connect=5, read=25),
        transport=transport,
        trust_env=False,
    ) as client:
        async with client.stream("POST", GROQ_ENDPOINT, headers=headers, json=body) as response:
            if response.status_code != 200:
                # Never include provider error body in an end-user message or logs.
                raise RuntimeError("Hosted model request unsuccessful")
            async for line in response.aiter_lines():
                if not line.startswith("data: "):
                    continue
                raw = line[6:].strip()
                if raw == "[DONE]":
                    done = True
                    break
                try:
                    event = json.loads(raw)
                except json.JSONDecodeError:
                    raise RuntimeError("Malformed hosted model event") from None
                if not isinstance(event, dict) or event.get("error"):
                    raise RuntimeError("Hosted model returned an error")
                choices = event.get("choices", [])
                delta = choices[0].get("delta", {}) if choices else {}
                chunk = delta.get("content") if isinstance(delta, dict) else None
                if isinstance(chunk, str) and chunk:
                    total += len(chunk)
                    if total > limit:
                        raise RuntimeError("Hosted answer exceeded safe length")
                    yield chunk
            if not done or total == 0:
                raise RuntimeError("Hosted model returned an incomplete or empty response")


async def answer_hosted(question: str, previous_turns=None, *, transport=None) -> str:
    chunks = []
    async for piece in stream_hosted(question, previous_turns, transport=transport):
        chunks.append(piece)
    return "".join(chunks).strip()
