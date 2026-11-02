"""Small guardrails for the public, synthetic-data SADA demonstration.

These limits are per WebSocket session, not distributed rate limiting.
Deployments accepting real customer data need authenticated connections,
centralized limits, logging/privacy controls, and infrastructure protection.
"""
from __future__ import annotations

import os
import time
from collections import deque
from urllib.parse import urlsplit


def public_demo_enabled() -> bool:
    return os.getenv("PUBLIC_DEMO_MODE", "0") == "1"


def origin_allowed(headers) -> bool:
    """Browsers must connect over a same-origin WebSocket in public mode."""
    if not public_demo_enabled():
        return True
    origin = headers.get("origin", "")
    host = headers.get("host", "")
    try:
        parsed = urlsplit(origin)
    except ValueError:
        return False
    return (parsed.scheme in {"https", "http"} and bool(host)
            and parsed.netloc.lower() == host.lower() and not parsed.username
            and not parsed.password and parsed.path in {"", "/"}
            and not parsed.query and not parsed.fragment)


class TurnLimiter:
    def __init__(self, limit: int = 30, window_seconds: int = 60):
        self.limit = limit
        self.window_seconds = window_seconds
        self.timestamps = deque()

    def allow(self, now: float | None = None) -> bool:
        now = time.monotonic() if now is None else now
        while self.timestamps and self.timestamps[0] <= now - self.window_seconds:
            self.timestamps.popleft()
        if len(self.timestamps) >= self.limit:
            return False
        self.timestamps.append(now)
        return True
