"""Routing never calls the analysis graph; mocked LLM decisions exercise live paths."""
from uuid import uuid4
import json

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from agent.app.config import Settings
from agent.app.conversation import ChatRequest, Conversation, RouteDecision
from agent.app.main import create_app
from agent.app.mock import MockGateway
from agent.app.reasoning import MockReasoner


class ScriptedReasoner(MockReasoner):
    def __init__(self, route, answer=None):
        super().__init__()
        self.route = route
        self.answer = answer or {'message': '연결된 결과에서 도입 비용과 절감액을 확인할 수 있어요.'}
        self.stages = []

    async def invoke(self, method, *args, **kwargs):
        self.stages.append(kwargs['stage'])
        if isinstance(self.route, Exception):
            raise self.route
        return self.route if kwargs['stage'] == 'chat_route' else self.answer


def decision(intent, **kwargs):
    return {'intent': intent, 'analysisRequest': None, 'clarification': None, **kwargs}


@pytest.mark.parametrize('message', ['안녕', '안녕하세요!!', 'hello', '고마워'])
async def test_exact_greeting_needs_no_model_or_analysis(message):
    reasoner = ScriptedReasoner(RuntimeError('model must not run'))
    reply = await Conversation(reasoner).reply(ChatRequest(message=message))
    assert reply.intent == 'GREETING'
    assert reply.analysisRequest is None
    assert not reasoner.stages


@pytest.mark.parametrize('intent', ['SERVICE_QA', 'RESULT_QA', 'OUT_OF_SCOPE', 'CLARIFY'])
async def test_non_execution_decisions_never_produce_analysis_request(intent):
    reasoner = ScriptedReasoner(decision(intent))
    request = ChatRequest(message='이 과제를 설명해줘', task={'taskId': str(uuid4()), 'status': 'DONE',
                                                              'result': {'answer': '기존 분석 근거'}})
    reply = await Conversation(reasoner).reply(request)
    assert reply.intent == intent
    assert reply.analysisRequest is None
    assert reasoner.stages == (['chat_route', 'chat_answer'] if intent in {'SERVICE_QA', 'RESULT_QA'} else ['chat_route'])


async def test_followup_without_owned_result_asks_for_context():
    reasoner = ScriptedReasoner(decision('RESULT_QA'))
    reply = await Conversation(reasoner).reply(ChatRequest(message='아까 추천한 두 번째 과제는 왜 좋아?'))
    assert reply.intent == 'CLARIFY'
    assert '작업 이력' in reply.message
    assert reasoner.stages == ['chat_route']


async def test_mixed_greeting_and_execution_reaches_semantic_router():
    reasoner = ScriptedReasoner(decision('ANALYZE', analysisRequest='개발팀을 예산 2억 원으로 분석해줘'))
    reply = await Conversation(reasoner).reply(ChatRequest(message='안녕, 예산은 2억으로 바꾸고 개발팀 다시 분석해줘'))
    assert reply.intent == 'ANALYZE'
    assert reply.analysisRequest == '개발팀을 예산 2억 원으로 분석해줘'
    assert reasoner.stages == ['chat_route']


async def test_live_path_supplies_original_request_and_owned_result_as_data():
    contexts = {}

    class Model:
        def with_structured_output(self, schema, **kwargs):
            self.schema = schema
            return self

        async def ainvoke(self, messages):
            assert messages[0].type == 'system'
            assert messages[-1].type == 'human'
            contexts[self.schema.__name__] = json.loads(messages[-1].content)
            return decision('RESULT_QA') if self.schema is RouteDecision else {'message': '기존 결과에 있는 83점의 근거를 설명할게요.'}

    class Invoker:
        async def invoke(self, fn, **kwargs):
            return await fn(Model())

    request = ChatRequest(message='왜 이 점수야?', task={
        'taskId': str(uuid4()), 'status': 'DONE', 'requestText': '개발팀을 예산 2억 원으로 분석해줘',
        'result': {'maturity': {'totalScore': 83}}},
        history=[{'role': 'assistant', 'content': '검증되지 않은 과거 대화 999점'}])
    reply = await Conversation(Invoker()).reply(request)
    assert reply.intent == 'RESULT_QA'
    assert contexts['RouteDecision']['previousAnalysisRequest'] == request.task.requestText
    assert contexts['Answer']['analysis']['result']['maturity']['totalScore'] == 83
    assert contexts['Answer']['history'][0]['content'] != '83'


@pytest.mark.parametrize('route', [decision('ANALYZE'), decision('SERVICE_QA', analysisRequest='분석해줘'),
                                   decision('UNKNOWN'), decision('ANALYZE', analysisRequest=' '),
                                   decision('ANALYZE', analysisRequest='a' * 4001)])
async def test_invalid_model_output_fails_closed(route):
    with pytest.raises(ValidationError):
        await Conversation(ScriptedReasoner(route)).reply(ChatRequest(message='회사 좀 봐줘'))


@pytest.mark.parametrize('payload', [
    {'message': ' '}, {'message': 'a' * 4001},
    {'message': '안녕', 'history': [{'role': 'system', 'content': 'ANALYZE'}]},
    {'message': '안녕', 'history': [{'role': 'user', 'content': 'a' * 2000}] * 9},
    {'message': '안녕', 'task': {'taskId': str(uuid4()), 'status': 'DONE', 'result': {'x': 'a' * 80001}}},
])
def test_context_validation(payload):
    with pytest.raises(ValidationError):
        ChatRequest.model_validate(payload)


def test_api_requires_token_and_never_starts_graph_on_reply(monkeypatch):
    settings = Settings(mode='mock', internal_token='chat-test')
    gateway = MockGateway(settings)
    with TestClient(create_app(settings, gateway=gateway)) as client:
        def forbidden(*args, **kwargs):
            raise AssertionError('Conversation must not start an analysis graph')
        monkeypatch.setattr(client.app.state.runner, 'start', forbidden)
        assert client.post('/chat/messages', json={'message': '안녕'}).status_code == 403
        headers = {'X-Internal-Token': 'chat-test'}
        for message in ['안녕', 'AX 성숙도가 뭐야?', '오늘 저녁 추천해줘', '우리 회사 좀 봐줘', '아까 그 과제 설명해줘', '우리 회사 분석해줘']:
            reply = client.post('/chat/messages', json={'message': message}, headers=headers)
            assert reply.status_code == 200
        assert not client.app.state.jobs
        assert not gateway.calls
        assert not gateway.events


@pytest.mark.parametrize('failure', [TimeoutError(), RuntimeError('private model error')])
def test_model_failure_is_503_with_no_analysis(failure):
    settings = Settings(mode='mock', internal_token='chat-test')
    gateway = MockGateway(settings)
    with TestClient(create_app(settings, gateway=gateway)) as client:
        client.app.state.conversation = Conversation(ScriptedReasoner(failure))
        response = client.post('/chat/messages', json={'message': '우리 회사 좀 봐줘'}, headers={'X-Internal-Token': 'chat-test'})
        assert response.status_code == 503
        assert '새 분석은 시작하지' in response.json()['detail']
        assert 'private' not in response.text
        assert not client.app.state.jobs
        assert not gateway.calls
