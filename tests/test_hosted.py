"""Hosted inference integration tested without external keys or API calls."""
import asyncio
import json

import httpx
from fastapi.testclient import TestClient

from app import main, live, hosted


def api_stream(*parts):
    return (''.join('data: '+json.dumps({'choices':[{'delta':{'content':p}}]})+'\n\n' for p in parts)
            + 'data: [DONE]\n\n').encode()


def test_groq_streaming_uses_server_secret_and_bounded_context(monkeypatch):
    monkeypatch.setenv('ENABLE_HOSTED_LLM', '1')
    monkeypatch.setenv('GROQ_API_KEY', 'secret-for-test')
    sent = []
    def handler(request):
        assert str(request.url) == hosted.GROQ_ENDPOINT
        assert request.headers['authorization'] == 'Bearer secret-for-test'
        data = json.loads(request.content)
        sent.append(data)
        assert data['stream'] is True
        assert data['model'] == hosted.DEFAULT_MODEL
        assert data['messages'][0]['role'] == 'system'
        assert 'demo' in data['messages'][0]['content'].lower()
        assert data['messages'][-1]['content'] == 'Explain the sample refunds'
        return httpx.Response(200, content=api_stream('This is a ', 'demo policy.'))
    async def run():
        return await hosted.answer_hosted('Explain the sample refunds', [{'role':'user','text':'A previous message'}],
                                         transport=httpx.MockTransport(handler))
    assert asyncio.run(run()) == 'This is a demo policy.'
    assert len(sent) == 1


def test_groq_failure_and_incomplete_stream(monkeypatch):
    monkeypatch.setenv('ENABLE_HOSTED_LLM', '1')
    monkeypatch.setenv('GROQ_API_KEY', 'secret-for-test')
    async def run(code, body):
        def handler(request):
            return httpx.Response(code, content=body)
        return await hosted.answer_hosted('Explain returns', transport=httpx.MockTransport(handler))
    for code, body in [(429,b'rate limit'), (200,b'data: {"choices":[{"delta":{"content":"partial"}}]}\n')]:
        try:
            asyncio.run(run(code,body))
            assert False, 'Expected fallback exception'
        except RuntimeError as e:
            assert 'secret-for-test' not in str(e)


def test_hosted_configuration_is_secret_free(monkeypatch):
    monkeypatch.setenv('ENABLE_HOSTED_LLM','1')
    monkeypatch.setenv('GROQ_API_KEY', 'top-secret-credential')
    data=TestClient(main.app).get('/api/config').json()
    assert data['hosted_llm_enabled'] is True
    assert data['model_provider'] == 'Groq'
    assert 'top-secret-credential' not in json.dumps(data)
    monkeypatch.delenv('GROQ_API_KEY')
    assert TestClient(main.app).get('/api/config').json()['hosted_llm_enabled'] is False


def test_live_hosted_streams_for_general_question_only(monkeypatch):
    monkeypatch.setenv('ENABLE_HOSTED_LLM','1')
    monkeypatch.setenv('GROQ_API_KEY', 'test-secret')
    monkeypatch.setattr(live.HOSTED_QUOTA,'allow', lambda:True)
    messages=[]
    async def stream(question, previous_turns):
        messages.append((question,previous_turns))
        yield 'I can explain '
        yield 'the demo policy.'
    monkeypatch.setattr(live,'stream_hosted',stream)
    with TestClient(main.app).websocket_connect('/ws/live') as ws:
        ws.receive_json()
        ws.send_json({'type':'message','text':'Could you clarify how the demo works?'})
        assert ws.receive_json()['type']=='answer_start'
        assert ws.receive_json()['delta']=='I can explain '
        assert ws.receive_json()['delta']=='the demo policy.'
        result=ws.receive_json()
        assert result['source']=='hosted_groq_unverified'
        assert result['text']=='I can explain the demo policy.'
        assert len(messages)==1
        ws.send_json({'type':'message','text':'Where is ORD-1001?'})
        result=ws.receive_json()
        assert result['intent']=='order_status'
        assert result['source']=='demo_orders'
        assert len(messages)==1
        ws.send_json({'type':'message','text':'I need a real agent'})
        result=ws.receive_json()
        assert result['intent']=='handoff'
        assert len(messages)==1


def test_legacy_socket_hosted_and_fallback(monkeypatch):
    monkeypatch.setenv('ENABLE_HOSTED_LLM','1')
    monkeypatch.setenv('GROQ_API_KEY','test-secret')
    monkeypatch.setattr(main.HOSTED_QUOTA,'allow', lambda:True)
    async def good(*args): return 'This is a synthetic demonstration.'
    monkeypatch.setattr(main,'answer_hosted',good)
    with TestClient(main.app).websocket_connect('/ws') as ws:
        ws.receive_json()
        ws.send_json({'type':'message','text':'What is SADA?'})
        result=ws.receive_json()
        assert result['text']=='This is a synthetic demonstration.'
        assert result['source']=='hosted_groq_unverified'
    async def bad(*args): raise RuntimeError('service unavailable')
    monkeypatch.setattr(main,'answer_hosted',bad)
    with TestClient(main.app).websocket_connect('/ws') as ws:
        ws.receive_json()
        ws.send_json({'type':'message','text':'Please explain in more detail'})
        result=ws.receive_json()
        assert result['source']=='scripted_hosted_unavailable'
        assert 'demo' in result['text'].lower()


def test_global_quota_per_minute():
    quota=hosted.GlobalQuota(per_minute=2)
    assert quota.allow(now=120)
    assert quota.allow(now=125)
    assert not quota.allow(now=130)
    assert quota.allow(now=180)
