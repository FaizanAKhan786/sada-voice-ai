"""Streaming speech and cancellable conversational turns over /ws/live.

JSON controls share a WebSocket with binary 16 kHz/16-bit mono audio frames.
Audio is continuously ingested, then faster-whisper transcribes completed
utterances locally. This is NOT streaming partial-word transcription or live
telephony. Audio stays in server memory for the duration of the utterance.
"""
from __future__ import annotations

import asyncio
import base64
import os
import time
from contextlib import suppress

from fastapi import WebSocket, WebSocketDisconnect

from app.engine import Session, route_message
from app.hosted import GENERATIVE_INTENTS, HOSTED_QUOTA, hosted_enabled, stream_hosted
from app.public_demo import TurnLimiter, public_demo_enabled
from app.voice_cloud import cloud_voice_enabled, hosted_tts_enabled, transcribe_cloud, speak_cloud, voice_segments
from app.streaming import AudioSegmenter


async def handle_live(socket: WebSocket, *, stt_enabled: bool, ollama_enabled: bool,
                      graph=None, on_answer=None):
    await socket.accept()
    session = Session()
    vad = AudioSegmenter()
    send_lock = asyncio.Lock()
    active: asyncio.Task | None = None
    turn_counter = 0
    limiter = TurnLimiter()
    voice_output_enabled = True

    async def send(payload: dict):
        async with send_lock:
            await socket.send_json(payload)

    async def cancel_active():
        nonlocal active
        task = active
        active = None
        if task is not None and not task.done():
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task
            await send({"type": "interrupted"})

    async def process_text(text: str, *, origin: str = "text"):
        nonlocal turn_counter
        turn_counter += 1
        turn_id = turn_counter
        started = time.perf_counter()
        try:
            if graph is None:
                answer = route_message(text, session).to_dict()
            else:
                state = await asyncio.to_thread(graph.invoke, {"text": text, "session": session})
                answer = state["result"]
            if hosted_enabled() and answer["intent"] in GENERATIVE_INTENTS:
                # The deterministic engine remains authoritative for orders and
                # handoffs. Hosted AI can phrase/clarify synthetic FAQs only.
                if not HOSTED_QUOTA.allow():
                    answer["source"] = "scripted_hosted_quota"
                else:
                    context = session.history[:-2]
                    full = ""
                    sent_start = False
                    try:
                        async for token in stream_hosted(text, context):
                            if not sent_start:
                                await send({"type": "answer_start", "turn_id": turn_id, "language": answer["language"]})
                                sent_start = True
                            full += token
                            await send({"type": "answer_delta", "turn_id": turn_id, "delta": token})
                        if not full.strip():
                            raise RuntimeError("Empty hosted answer")
                        answer["text"] = full.strip()
                        answer["source"] = "hosted_groq_unverified"
                        session.history[-1]["text"] = answer["text"]
                    except asyncio.CancelledError:
                        raise
                    except Exception:
                        # Existing browser code replaces partial streamed text
                        # with the safe deterministic response at final event.
                        answer["source"] = "scripted_hosted_unavailable"
            elif ollama_enabled and answer["intent"] == "general":
                # Routing has already appended the scripted answer to history.
                context = session.history[:-2]
                from app.llm import stream_ollama
                full = ""
                sent_start = False
                try:
                    async for token in stream_ollama(text, context):
                        if not sent_start:
                            await send({"type": "answer_start", "turn_id": turn_id, "language": answer["language"]})
                            sent_start = True
                        full += token
                        await send({"type": "answer_delta", "turn_id": turn_id, "delta": token})
                    if not full.strip():
                        raise RuntimeError("Local model returned no answer")
                    answer["text"] = full.strip()
                    answer["source"] = "local_ollama_unverified"
                    session.history[-1]["text"] = answer["text"]
                except asyncio.CancelledError:
                    raise
                except Exception:
                    # Once streamed, cannot safely retract partial text; client
                    # replaces it with deterministic policy fallback at final event.
                    answer["source"] = "scripted_ollama_unavailable"
            if on_answer is not None:
                on_answer(answer["intent"])
            await send({"type": "answer", "turn_id": turn_id, **answer,
                        "latency_ms": int((time.perf_counter() - started) * 1000)})
            # Hosted TTS is only requested for an actual recognized voice turn.
            # Strictly bound output to the assistant's words, never browser input.
            if origin == "voice" and hosted_tts_enabled() and voice_output_enabled:
                try:
                    spoken_lang = answer["language"] if answer["language"] in {"en", "ar"} else "en"
                    segments = voice_segments(answer["text"])
                    for part in segments:
                        wav = await speak_cloud(part, spoken_lang)
                        await send({"type": "voice_audio", "turn_id": turn_id,
                                    "audio_base64": base64.b64encode(wav).decode("ascii"),
                                    "language": spoken_lang, "format": "wav"})
                    await send({"type": "voice_done", "turn_id": turn_id})
                except asyncio.CancelledError:
                    raise
                except Exception:
                    await send({"type": "voice_fallback", "turn_id": turn_id,
                                "text": answer["text"], "language": answer["language"]})
        except asyncio.CancelledError:
            raise
        except Exception:
            await send({"type": "error", "message": "Unable to process this request"})

    async def process_pcm(pcm: bytes):
        try:
            if cloud_voice_enabled():
                text, lang = await transcribe_cloud(pcm, session.language)
            else:
                from app.speech import transcribe_pcm16
                text, lang = await asyncio.to_thread(transcribe_pcm16, pcm, session.language)
            if not text.strip():
                await send({"type": "no_speech"})
                return
            if len(text) > 1500:
                await send({"type": "error", "message": "Transcription exceeded the message limit"})
                return
            await send({"type": "transcript", "text": text, "language": lang})
            await process_text(text, origin="voice")
        except asyncio.CancelledError:
            raise
        except Exception:
            await send({"type": "error", "message": "Speech transcription unavailable. Try text input or retry."})

    available_audio = stt_enabled or cloud_voice_enabled()
    await send({"type": "ready", "message": "Connected to SADA live demo", "language": session.language,
                "audio": available_audio, "cloud_voice": cloud_voice_enabled(),
                "cloud_tts": hosted_tts_enabled(),
                "sample_rate": 16000, "audio_format": "pcm_s16le"})
    try:
        while True:
            packet = await socket.receive()
            if packet.get("type") == "websocket.disconnect":
                break
            binary = packet.get("bytes")
            if binary is not None:
                if not available_audio:
                    await send({"type": "error", "message": "Streaming voice unavailable."})
                    continue
                try:
                    events = vad.push(binary)
                except ValueError:
                    await send({"type": "error", "message": "Invalid audio packet"})
                    vad.reset()
                    continue
                for name, content in events:
                    if name == "speech_started":
                        await cancel_active()
                        await send({"type": "speech_started"})
                    else:
                        if public_demo_enabled() and not limiter.allow():
                            await send({"type": "error", "message": "Voice request limit reached; try again shortly."})
                            continue
                        await send({"type": "speech_ended"})
                        await cancel_active()
                        active = asyncio.create_task(process_pcm(content))
                continue
            try:
                import json
                payload = json.loads(packet.get("text") or "null")
                if not isinstance(payload, dict):
                    raise ValueError("Invalid command")
                action = payload.get("type")
                if action == "set_language":
                    lang = payload.get("language")
                    if lang not in {"auto", "en", "ar"}:
                        raise ValueError("Invalid language")
                    session.language = lang
                    await send({"type": "language", "language": lang})
                elif action == "set_voice_output":
                    if not isinstance(payload.get("enabled"), bool):
                        raise ValueError("Invalid voice output setting")
                    voice_output_enabled = payload["enabled"]
                elif action == "reset":
                    await cancel_active()
                    vad.reset()
                    session = Session(language=session.language)
                    await send({"type": "reset_complete"})
                elif action == "interrupt":
                    await cancel_active()
                elif action == "flush":
                    pcm = vad.flush()
                    if pcm is not None:
                        if public_demo_enabled() and not limiter.allow():
                            await send({"type": "error", "message": "Voice request limit reached; try again shortly."})
                            continue
                        await send({"type": "speech_ended"})
                        await cancel_active()
                        active = asyncio.create_task(process_pcm(pcm))
                elif action == "message":
                    if public_demo_enabled() and not limiter.allow():
                        await send({"type": "error", "message": "Demo request limit reached. Please retry shortly."})
                        continue
                    text = payload.get("text")
                    if not isinstance(text, str) or not text.strip() or len(text) > 1500:
                        raise ValueError("Message must contain 1–1500 characters")
                    await cancel_active()
                    active = asyncio.create_task(process_text(text))
                else:
                    raise ValueError("Unknown command")
            except (ValueError, TypeError) as exc:
                await send({"type": "error", "message": str(exc)[:160]})
    except WebSocketDisconnect:
        pass
    finally:
        if active and not active.done():
            active.cancel()
            with suppress(asyncio.CancelledError):
                await active
