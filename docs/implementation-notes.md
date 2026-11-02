# Implementation notes · SADA v0.2

## Streaming transport

The browser captures audio with `getUserMedia` and `AudioWorklet`, downsampling from the AudioContext device sample rate to 16kHz mono. It packs 320 signed 16-bit samples into each 20ms binary WebSocket message. The client drops audio frames when the WebSocket buffered amount exceeds 512 KiB; this is deliberate backpressure rather than silent unbounded buffering.

`/ws/live` ingests audio frames and sends endpointing events. With `webrtcvad-wheels` installed, the segmenter uses WebRTC VAD; without it, an RMS threshold detector provides a less accurate development fallback. After three voiced 20ms frames, the segmenter emits `speech_started` and cancels the currently generating assistant reply. After 30 silent frames (~600ms), the segmenter emits `speech_ended`, runs local faster-whisper transcription on the completed in-memory audio and routes the recognized utterance through the auditable workflow engine. Speech segments cap at 20 seconds. Underlying STT runs in `asyncio.to_thread`; cancellation doesn't forcibly terminate Whisper inference once started.

## Local model response streaming

For unhandled generic questions, optionally call Ollama `/api/chat` with streaming NDJSON enabled and a bounded policy-grounded, short-history prompt. Stream tokens as `answer_delta` events and allow browser TTS to start after a completed sentence. Receipt of user speech cancels the in-flight model task and browser speech synthesis queue. If Ollama is unavailable, return a deterministic fallback. The LLM is never given tools with side effects, and all order workflows stay deterministic.

## Safety and limitations

This is a synthetic demo and uses neither real credentials nor personal customer information. Browser recognition may rely on cloud processing; local Whisper voice modes do not use vendor STT APIs but may download weights at first load. Browser TTS voice availability is platform-dependent. Test with headphones: microphone playback feedback can cause false barge-in even with available noise/echo suppression. No telephony, persistent CRM, online payments or real human handoff is included.

The unit suite uses mock ASR and model streams. Meaningful model benchmarks need representative hardware, audio samples, Arabic dialect coverage and manually checked answers. The VAD and transport work without actual model weights, but full voice inference must be installed and tested separately.
