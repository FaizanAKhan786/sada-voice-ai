"""Hosted speech endpoints tested with fake Groq HTTP, no real credentials."""
import asyncio
from array import array
import base64
import io
import wave

import httpx
import pytest
from fastapi.testclient import TestClient

from app import live, main, voice_cloud
from app.streaming import AudioSegmenter, FRAME_BYTES


def pcm(value=1500, frames=5):
    return array('h', [value] * (FRAME_BYTES // 2) * frames).tobytes()


def wav_bytes():
    with io.BytesIO() as buf:
        with wave.open(buf, 'wb') as f:
            f.setnchannels(1)
            f.setsampwidth(2)
            f.setframerate(24000)
            f.writeframes(b'\x00\x00' * 200)
        return buf.getvalue()


def test_cloud_pcm_wav_conversion_and_input_limits():
    buf = voice_cloud.pcm_to_wav(pcm(1200))
    with wave.open(io.BytesIO(buf)) as f:
        assert f.getframerate() == 16000
        assert f.getnchannels() == 1
        assert f.getsampwidth() == 2
    for invalid in (b'', b'\x00', b'\x00\x00' * (16000 * 21)):
        with pytest.raises(ValueError):
            voice_cloud.pcm_to_wav(invalid)


def test_transcription_sends_wav_server_side_and_detects_arabic(monkeypatch):
    monkeypatch.setenv('ENABLE_CLOUD_VOICE', '1')
    monkeypatch.setenv('GROQ_API_KEY', 'test-key-redacted')
    monkeypatch.setattr(voice_cloud.ASR_QUOTA, 'allow', lambda: True)
    def callback(request):
        assert str(request.url) == voice_cloud.STT_URL
        assert request.headers['authorization'] == 'Bearer test-key-redacted'
        assert b'utterance.wav' in request.content
        assert b'whisper-large-v3-turbo' in request.content
        return httpx.Response(200, json={'text': 'وين طلبي', 'language': 'arabic'})
    text, lang = asyncio.run(voice_cloud.transcribe_cloud(
        pcm(), 'auto', transport=httpx.MockTransport(callback)))
    assert text == 'وين طلبي' and lang == 'ar'
    assert voice_cloud.identify_language('English', 'Hi', 'auto') == 'en'
    assert voice_cloud.identify_language('none', 'شكرا', 'auto') == 'ar'
    assert voice_cloud.identify_language('arabic', 'Hello', 'en') == 'en'


def test_transcription_provider_failure_hides_credentials(monkeypatch):
    monkeypatch.setenv('ENABLE_CLOUD_VOICE', '1')
    monkeypatch.setenv('GROQ_API_KEY', 'private-test-token')
    monkeypatch.setattr(voice_cloud.ASR_QUOTA, 'allow', lambda: True)
    def cb(request):
        return httpx.Response(401, json={'error': 'private-test-token'})
    with pytest.raises(RuntimeError) as err:
        asyncio.run(voice_cloud.transcribe_cloud(pcm(), transport=httpx.MockTransport(cb)))
    assert 'private-test-token' not in str(err.value)


@pytest.mark.parametrize('lang,model,voice',[('en', voice_cloud.ENGLISH_TTS_MODEL, 'autumn'),('ar', voice_cloud.ARABIC_TTS_MODEL, 'noura')])
def test_tts_uses_correct_model_and_voice(monkeypatch, lang, model, voice):
    monkeypatch.setenv('ENABLE_CLOUD_VOICE', '1')
    monkeypatch.setenv('ENABLE_HOSTED_TTS', '1')
    monkeypatch.setenv('GROQ_API_KEY', 'private-test-token')
    monkeypatch.setattr(voice_cloud.TTS_QUOTA,'allow',lambda: True)
    def cb(request):
        assert str(request.url) == voice_cloud.TTS_URL
        data = __import__('json').loads(request.content)
        assert data['model'] == model
        assert data['voice'] == voice
        assert data['input'] == 'Hello' or data['input'] == 'مرحبا'
        return httpx.Response(200, content=wav_bytes())
    assert asyncio.run(voice_cloud.speak_cloud('Hello' if lang=='en' else 'مرحبا',lang,transport=httpx.MockTransport(cb))) == wav_bytes()


def test_tts_segment_length_and_rejection(monkeypatch):
    assert all(len(segment) <=175 for segment in voice_cloud.voice_segments('a ' * 150))
    assert len(voice_cloud.voice_segments('word ' * 300)) <= voice_cloud.MAX_CHUNKS
    assert voice_cloud.voice_segments('') == []
    monkeypatch.setenv('ENABLE_CLOUD_VOICE','1')
    monkeypatch.setenv('ENABLE_HOSTED_TTS','1')
    monkeypatch.setenv('GROQ_API_KEY','test')
    with pytest.raises(ValueError):
        asyncio.run(voice_cloud.speak_cloud('x'*201,'en'))


def test_live_voice_to_voice_with_mock_provider(monkeypatch):
    monkeypatch.setattr(live, 'cloud_voice_enabled', lambda: True)
    monkeypatch.setattr(live, 'hosted_tts_enabled', lambda: True)
    monkeypatch.setattr(live, 'AudioSegmenter', lambda: AudioSegmenter(use_webrtc=False))
    seen=[]
    async def fake_stt(data, lang):
        seen.append(('stt', lang))
        return 'Where is ORD-1001?', 'en'
    async def fake_tts(text, lang):
        seen.append(('tts', lang))
        return wav_bytes()
    monkeypatch.setattr(live, 'transcribe_cloud', fake_stt)
    monkeypatch.setattr(live, 'speak_cloud', fake_tts)
    with TestClient(main.app).websocket_connect('/ws/live') as ws:
        ready = ws.receive_json()
        assert ready['cloud_voice'] is True and ready['cloud_tts'] is True
        ws.send_bytes(pcm(1800,3))
        assert ws.receive_json()['type'] == 'speech_started'
        ws.send_bytes(pcm(0,30))
        assert ws.receive_json()['type'] == 'speech_ended'
        assert ws.receive_json()['type'] == 'transcript'
        result = ws.receive_json()
        assert result['type'] == 'answer' and result['intent'] == 'order_status'
        voice = ws.receive_json()
        assert voice['type'] == 'voice_audio' and voice['turn_id'] == result['turn_id']
        assert base64.b64decode(voice['audio_base64']).startswith(b'RIFF')
        assert ws.receive_json()['type'] == 'voice_done'
    assert ('stt','auto') in seen and ('tts','en') in seen


def test_interrupt_cancels_hosted_speech_generation(monkeypatch):
    monkeypatch.setattr(live,'cloud_voice_enabled',lambda:True)
    monkeypatch.setattr(live,'hosted_tts_enabled',lambda:True)
    monkeypatch.setattr(live, 'AudioSegmenter', lambda: AudioSegmenter(use_webrtc=False))
    async def fake_stt(data, lang):
        return 'Where is ORD-1001?', 'en'
    async def slow_speech(text, lang):
        await asyncio.sleep(20)
        return wav_bytes()
    monkeypatch.setattr(live,'transcribe_cloud',fake_stt)
    monkeypatch.setattr(live,'speak_cloud',slow_speech)
    with TestClient(main.app).websocket_connect('/ws/live') as ws:
        assert ws.receive_json()['type']=='ready'
        ws.send_bytes(pcm(1800,3))
        assert ws.receive_json()['type']=='speech_started'
        ws.send_bytes(pcm(0,30))
        assert ws.receive_json()['type']=='speech_ended'
        assert ws.receive_json()['type']=='transcript'
        assert ws.receive_json()['type']=='answer'
        ws.send_bytes(pcm(1800,3))
        assert ws.receive_json()['type']=='interrupted'
        assert ws.receive_json()['type']=='speech_started'


def test_muted_voice_does_not_trigger_provider_tts(monkeypatch):
    monkeypatch.setattr(live,'cloud_voice_enabled',lambda:True)
    monkeypatch.setattr(live,'hosted_tts_enabled',lambda:True)
    monkeypatch.setattr(live, 'AudioSegmenter', lambda: AudioSegmenter(use_webrtc=False))
    async def fake_stt(data, lang):
        return 'Where is ORD-1001?', 'en'
    async def error_tts(text,lang):
        raise AssertionError('Should never synthesize muted audio')
    monkeypatch.setattr(live,'transcribe_cloud',fake_stt)
    monkeypatch.setattr(live,'speak_cloud',error_tts)
    with TestClient(main.app).websocket_connect('/ws/live') as ws:
        ws.receive_json()
        ws.send_json({'type':'set_voice_output','enabled':False})
        ws.send_bytes(pcm(1800,3))
        assert ws.receive_json()['type']=='speech_started'
        ws.send_bytes(pcm(0,30))
        assert ws.receive_json()['type']=='speech_ended'
        assert ws.receive_json()['type']=='transcript'
        assert ws.receive_json()['type']=='answer'
