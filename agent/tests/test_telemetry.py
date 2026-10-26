import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
import httpx
from fastapi.testclient import TestClient
from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatGeneration, LLMResult
from prometheus_client.parser import text_string_to_metric_families

from agent.app.config import Settings
from agent.app.main import create_app
from agent.app.mock import MockGateway
from agent.app.reasoning import Reasoner
from agent.app.runner import TaskRunner
from agent.app.telemetry import AgentMetrics, TokenUsageCallback


def sample(metrics, name, labels=None):
    for family in text_string_to_metric_families(metrics.render().decode()):
        for value in family.samples:
            if value.name == name and (labels is None or value.labels == labels):
                return value.value
    return None


def test_metrics_require_auth_and_http_labels_never_contain_ids(monkeypatch):
    monkeypatch.setenv('METRICS_TOKEN', 'metrics-secret')
    app = create_app(Settings(mode='mock', internal_token='internal-secret'))
    with TestClient(app) as client:
        assert client.get('/metrics').status_code == 403
        assert client.get('/metrics', headers={'Authorization': 'Bearer internal-secret'}).status_code == 403
        key = str(uuid4())
        client.get(f'/tasks/{key}', headers={'X-Internal-Token': 'internal-secret'})
        response = client.get('/metrics', headers={'Authorization': 'Bearer metrics-secret'})
        assert response.status_code == 200
        assert 'route="/tasks/{task_id}"' in response.text
        assert key not in response.text and 'secret' not in response.text
        assert 'mode="mock"' in response.text
        assert sample(app.state.metrics, 'ax_agent_ready') == 1
    assert sample(app.state.metrics, 'ax_agent_ready') == 0


@pytest.mark.asyncio
async def test_tool_failure_and_success_are_counted_without_arguments():
    settings = Settings(mode='mock', internal_token='test')
    gateway = MockGateway(settings)
    gateway.metrics = AgentMetrics(settings)
    await gateway.tool('private-task', 'collect', 'get_company_profile', {'company_id': 1})
    with pytest.raises(Exception):
        await gateway.tool('private-task', 'collect', 'optimize_ax_portfolio', {'company_id': 999})
    assert sample(gateway.metrics, 'ax_agent_tool_calls_total', {'tool': 'get_company_profile', 'outcome': 'success'}) == 1
    assert sample(gateway.metrics, 'ax_agent_tool_calls_total', {'tool': 'optimize_ax_portfolio', 'outcome': 'error'}) == 1
    assert 'private-task' not in gateway.metrics.render().decode()


@pytest.mark.asyncio
async def test_failed_and_cancelled_executions_release_active_gauge():
    cfg = Settings(mode='mock')
    gateway = MockGateway(cfg)
    gateway.metrics = AgentMetrics(cfg)
    graph = SimpleNamespace(ainvoke=AsyncMock(side_effect=ValueError('private')), aupdate_state=AsyncMock())
    runner = TaskRunner(graph, gateway, cfg)
    await runner.execute('private-id', {})
    assert sample(gateway.metrics, 'ax_agent_executions_total', {'outcome': 'FAILED'}) == 1
    graph.ainvoke.side_effect = asyncio.CancelledError()
    with pytest.raises(asyncio.CancelledError):
        await runner.execute('private-id', {})
    assert sample(gateway.metrics, 'ax_agent_executions_total', {'outcome': 'CANCELLED'}) == 1
    assert sample(gateway.metrics, 'ax_agent_active_executions') == 0


@pytest.mark.asyncio
async def test_llm_retry_and_structured_output_token_usage(monkeypatch):
    cfg = Settings(mode='llm-demo', model='test-model')
    metrics = AgentMetrics(cfg)
    callbacks = []
    monkeypatch.setattr('agent.app.reasoning.ChatOpenAI', lambda **kwargs: callbacks.extend(kwargs['callbacks']) or object())
    reasoner = Reasoner(cfg)
    reasoner.metrics = metrics
    attempts = 0

    async def method(model):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            request = httpx.Request('POST', 'https://example.test')
            raise httpx.HTTPStatusError('rate limited', request=request, response=httpx.Response(429, request=request))
        response = LLMResult(generations=[[ChatGeneration(message=AIMessage(
            content='private text', usage_metadata={'input_tokens': 12, 'output_tokens': 8, 'total_tokens': 20}
        ))]])
        callbacks[0].on_llm_end(response)
        return {'parsed': True}

    assert await reasoner.invoke(method, stage='chat_route') == {'parsed': True}
    assert sample(metrics, 'ax_agent_llm_requests_total', {'model': 'test-model', 'stage': 'chat_route', 'outcome': 'error'}) == 1
    assert sample(metrics, 'ax_agent_llm_requests_total', {'model': 'test-model', 'stage': 'chat_route', 'outcome': 'success'}) == 1
    assert sample(metrics, 'ax_agent_llm_tokens_total', {'model': 'test-model', 'kind': 'input'}) == 12
    assert sample(metrics, 'ax_agent_llm_tokens_total', {'model': 'test-model', 'kind': 'output'}) == 8
    assert 'private text' not in metrics.render().decode()


def test_missing_provider_usage_is_not_invented():
    metrics = AgentMetrics(Settings(mode='mock'))
    TokenUsageCallback(metrics, 'unused').on_llm_end(LLMResult(generations=[[ChatGeneration(message=AIMessage(content='x'))]]))
    assert sample(metrics, 'ax_agent_llm_tokens_total') is None
