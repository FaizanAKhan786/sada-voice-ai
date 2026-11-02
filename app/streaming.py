"""Incremental 16 kHz mono PCM endpointing for the local streaming demo.

Uses WebRTC VAD if installed. In an environment without its optional wheel,
falls back to a conservative RMS threshold (development only). 20 ms frames.
This is utterance-level streaming, not streaming word-by-word ASR.
"""
from __future__ import annotations

from collections import deque
from math import sqrt
from array import array
import sys

SAMPLE_RATE = 16000
FRAME_MS = 20
FRAME_BYTES = SAMPLE_RATE * FRAME_MS // 1000 * 2
MAX_UTTERANCE_SECONDS = 20


class AudioSegmenter:
    def __init__(self, *, use_webrtc: bool = True, threshold: float = 550.0,
                 start_frames: int = 3, end_frames: int = 30):
        self.threshold = threshold
        self.start_frames = start_frames
        self.end_frames = end_frames
        self._vad = None
        if use_webrtc:
            try:
                import webrtcvad
                self._vad = webrtcvad.Vad(2)
            except ImportError:
                pass
        self.reset()

    @property
    def detector(self) -> str:
        return "webrtcvad" if self._vad else "energy_fallback"

    def reset(self) -> None:
        self.pending = bytearray()
        self.preroll: deque[bytes] = deque(maxlen=15)
        self.frames: list[bytes] = []
        self.speaking = False
        self.voiced = 0
        self.silent = 0

    def _is_speech(self, frame: bytes) -> bool:
        if self._vad is not None:
            return bool(self._vad.is_speech(frame, SAMPLE_RATE))
        samples = array("h")
        samples.frombytes(frame)
        if sys.byteorder != "little":
            samples.byteswap()
        rms = sqrt(sum(int(x) ** 2 for x in samples) / max(len(samples), 1))
        return rms >= self.threshold

    def push(self, pcm: bytes) -> list[tuple[str, bytes | None]]:
        if len(pcm) > FRAME_BYTES * 100:
            raise ValueError("Audio packet too large (max 2 seconds)")
        self.pending.extend(pcm)
        events: list[tuple[str, bytes | None]] = []
        while len(self.pending) >= FRAME_BYTES:
            frame = bytes(self.pending[:FRAME_BYTES])
            del self.pending[:FRAME_BYTES]
            voiced = self._is_speech(frame)
            if not self.speaking:
                self.preroll.append(frame)
                self.voiced = self.voiced + 1 if voiced else 0
                if self.voiced >= self.start_frames:
                    self.speaking = True
                    self.frames = list(self.preroll)
                    self.preroll.clear()
                    self.silent = 0
                    events.append(("speech_started", None))
            else:
                self.frames.append(frame)
                self.silent = 0 if voiced else self.silent + 1
                if self.silent >= self.end_frames or len(self.frames) * FRAME_MS >= MAX_UTTERANCE_SECONDS * 1000:
                    # End-silence remains to preserve natural sentence endings.
                    utterance = b"".join(self.frames)
                    events.append(("speech_ended", utterance))
                    # Do not discard unread frames in a multi-frame packet.
                    unprocessed = self.pending
                    self.reset()
                    self.pending = unprocessed
        return events

    def flush(self) -> bytes | None:
        utterance = b"".join(self.frames) if self.speaking else None
        self.reset()
        return utterance
