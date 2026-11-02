"""Optional offline speech transcription using faster-whisper.

Requires `pip install -r requirements-stt.txt`. With a local model directory,
no external speech API is called. First use of a model *name* may download it.
"""
from __future__ import annotations
import os
import threading

_model = None
_lock = threading.Lock()


def transcribe_file(path: str, language: str = "auto") -> tuple[str, str]:
    global _model
    try:
        from faster_whisper import WhisperModel
    except ImportError as exc:
        raise RuntimeError("Install optional offline STT dependencies: pip install -r requirements-stt.txt") from exc
    with _lock:
        if _model is None:
            model_name = os.getenv("WHISPER_MODEL", "small")
            device = os.getenv("WHISPER_DEVICE", "cpu")
            compute = os.getenv("WHISPER_COMPUTE", "int8")
            _model = WhisperModel(model_name, device=device, compute_type=compute)
    segments, info = _model.transcribe(
        path,
        beam_size=3,
        vad_filter=True,
        language=language if language in {"en", "ar"} else None,
    )
    return " ".join(s.text.strip() for s in segments).strip(), info.language


def transcribe_pcm16(pcm: bytes, language: str = "auto") -> tuple[str, str]:
    """Decode raw little-endian 16 kHz mono signed PCM from streamed packets."""
    import numpy as np
    if len(pcm) < 3200 or len(pcm) % 2:
        raise RuntimeError("Not enough valid audio for transcription")
    # faster-whisper accepts mono float32 arrays, assumed at 16 kHz.
    audio = np.frombuffer(pcm, dtype="<i2").astype(np.float32) / 32768.0
    global _model
    try:
        from faster_whisper import WhisperModel
    except ImportError as exc:
        raise RuntimeError("Install faster-whisper: pip install -r requirements-stt.txt") from exc
    with _lock:
        if _model is None:
            _model = WhisperModel(
                os.getenv("WHISPER_MODEL", "small"),
                device=os.getenv("WHISPER_DEVICE", "cpu"),
                compute_type=os.getenv("WHISPER_COMPUTE", "int8"),
            )
    segments, info = _model.transcribe(
        audio, language=language if language in {"en", "ar"} else None,
        beam_size=3, vad_filter=False, condition_on_previous_text=False,
    )
    return " ".join(seg.text.strip() for seg in segments).strip(), info.language
