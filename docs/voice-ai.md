# SADA hosted English-Arabic voice demonstration

SADA supports interruptible, browser-to-browser speech conversations over WebSockets. The input is **16 kHz PCM16 mono**, sent in 20 ms frames through the browser's AudioWorklet. Server-side WebRTC VAD detects natural pauses; an in-memory utterance is then sent as WAV to Groq's hosted Whisper `whisper-large-v3-turbo` transcriptions API. Chat responses use Groq's hosted GPT-OSS model if enabled, or predefined synthetic support policy workflows. The spoken response uses Groq Orpheus English or Arabic voices, transferred as bounded WAV chunks to the browser. The assistant's speech can be interrupted by starting a new utterance, which cancels the pending model/TTS task and browser playback.

**This is utterance-level streaming, not simultaneous/full-duplex word-by-word speech recognition.** A new input is processed after a pause, and the reply can be spoken sentence by sentence in chunks. Network and model latency vary. Audio is transient and not stored; voice/transcript material is sent to Groq, so never enter real orders, personal details, or payments. The Arabic TTS is a *Saudi dialect* voice, not a general-purpose promise of all dialects.

## Hosted configuration

Render environment flags (do not add credentials to GitHub):

```env
ENABLE_HOSTED_LLM=1
ENABLE_CLOUD_VOICE=1
ENABLE_HOSTED_TTS=1
GROQ_STT_MODEL=whisper-large-v3-turbo
GROQ_MODEL=openai/gpt-oss-120b
# GROQ_API_KEY = set in Render only
```

The browser offers **Live AI voice · English / العربية** when `/api/config` reports `cloud_voice_enabled=true`. Press the microphone, grant microphone access, and speak English or Arabic. Use headphones and Chrome/Edge on a HTTPS site. Tap the microphone again to stop. Browser speech synthesis is an alternative for unsupported hosted voice or browsers.

## Protocol / cancellation

- Same-origin `wss://.../ws/live`; browser requests do not contain credentials.
- 20ms signed little-endian frames, WebRTC VAD on the server.
- VAD emits `speech_started`, triggering cancellation of the in-flight answer or TTS response. The browser immediately stops queued audio on that event.
- On a pause: `speech_ended` → Groq transcript → `transcript` → `answer_start`/`answer_delta`/`answer` → `voice_audio` (base64 WAV) → `voice_done`.
- `voice_fallback` carries the already generated *text* when provider TTS fails, permitting browser TTS. No provider error contents or credentials are returned.
- `set_voice_output` can mute hosted speech to avoid unnecessary TTS costs. On `interrupt` or `reset`, the active server task is cancelled.

## Cost and security

- Groq requests happen server-side; one secret is shared across STT, LLM, and TTS. **Rotate any previously exposed key** before public traffic.
- Per-process request quotas cap TTS, STT and hosted chat, and per-session message quotas apply on the WebSocket. These are rudimentary budget controls, **not IP-based or distributed rate limiting**. Set a provider spending cap before sharing widely.
- Only browser same-origin WebSocket handshakes are accepted in public-demo mode. A motivated abusive client can still consume public demo resources. Add authenticated sessions, proxy/WAF edge limits and global rate limiting before production use.
- No recording is persisted or logged; client transcript exports are user-triggered only. Consent/privacy messaging remains required for customer deployments.
- Mock unit tests cover Groq requests, Arabic/English voice selection, WAV validation, fallback and interruption; a separate GitHub Actions smoke test uses *synthetic* generated English speech against the real public service, with no provider secret in CI.

## Model documentation

- [Groq STT](https://console.groq.com/docs/speech-to-text)
- [Groq TTS](https://console.groq.com/docs/text-to-speech/orpheus)

## One-time Groq Orpheus model approval

Groq requires an owner of the API-key organization to **accept the terms for both Orpheus models** before hosted TTS can generate WAV audio. Without approval, Groq returns HTTP 400 `model_terms_required`. Whisper speech recognition and hosted chat still work, and SADA emits a `voice_fallback` event for supported browsers to speak the answer.

- [Accept English Orpheus terms](https://console.groq.com/playground?model=canopylabs/orpheus-v1-english)
- [Accept Arabic Orpheus terms](https://console.groq.com/playground?model=canopylabs/orpheus-arabic-saudi)

The automated smoke test verifies hosted transcription, an AI response, and either Groq WAV output or the browser fallback event. Once the terms are accepted, manually run the GitHub **Hosted voice smoke test** workflow with `require_hosted_tts` selected to confirm genuine hosted audio. Never claim hosted TTS is verified before that strict test passes.
