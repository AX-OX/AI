"""실제 FastMCP 프로토콜과 선택적 PostgreSQL 체크포인터 통합 검사."""
import importlib.util
import os
import sys
from pathlib import Path
from uuid import uuid4
from unittest.mock import patch
import httpx
import pytest
from fastmcp import FastMCP, Client
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from langgraph.types import Command
from agent.app.clients import Gateway
from agent.app.config import Settings
from agent.app.graph import build_graph
from agent.app.mock import MockGateway
from agent.app.reasoning import MockReasoner, Reasoner
from langchain_core.messages import AIMessage

ROOT = Path(__file__).resolve().parents[2]

@pytest.mark.asyncio
async def test_real_mcp_protocol_gateway_decodes_tool():
    server = FastMCP('test')
    @server.tool
    def get_company_profile(company_id: int) -> dict:
        return {'company_id': company_id, 'email': 'person@example.com'}
    cfg = Settings(mode='mock', internal_token='test')
    gateway = Gateway(cfg)
    async def no_callback(*args, **kwargs): pass
    gateway._spring = no_callback
    with patch('agent.app.clients.StreamableHttpTransport', return_value=server):
        value = await gateway.tool('task', 'collect', 'get_company_profile', {'company_id': 1})
    assert value == {'company_id': 1, 'email': '[EMAIL]'}

@pytest.mark.asyncio
async def test_real_business_mcp_forwards_spring_body():
    sys.path.insert(0, str(ROOT / 'business-mcp'))
    spec = importlib.util.spec_from_file_location('business_integration', ROOT / 'business-mcp/server.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    requests = []
    original = httpx.AsyncClient
    def response(request):
        requests.append(request)
        return httpx.Response(200, json={'scenarios': {'base': {'roiPct': 10}}})
    def client_factory(**kwargs):
        return original(transport=httpx.MockTransport(response), **kwargs)
    with patch.dict(os.environ, {'INTERNAL_TOKEN': 'test'}), patch('spring_client.httpx.AsyncClient', client_factory):
        async with Client(module.mcp) as client:
            result = await client.call_tool('calculate_ax_roi', {'process_id': 201, 'solution_id': 501})
            tools = await client.list_tools()
    assert result.data['scenarios']['base']['roiPct'] == 10
    assert requests[0].headers['x-internal-token'] == 'test'
    assert b'"processId":201' in requests[0].content
    writes = {t.name for t in tools if t.annotations and t.annotations.destructiveHint}
    assert {'create_ax_roadmap', 'create_ax_project', 'update_project_status'} <= writes

@pytest.mark.asyncio
async def test_collect_llm_tool_loop_uses_all_six_tools():
    from agent.app.clients import READS
    cfg = Settings(mode='mock', internal_token='test', data_dir=ROOT / 'AX_Navigator_AI_MVP_v3')
    reasoner = Reasoner(cfg)
    gateway = MockGateway(cfg)
    class FakeModel:
        def bind_tools(self, tools, **kwargs):
            assert {t.name for t in tools} == READS
            return self
        async def ainvoke(self, messages):
            return AIMessage(content='', tool_calls=[{'name': name, 'args': {'company_id': 1}, 'id': name, 'type': 'tool_call'} for name in READS])
    async def invoke(method, *args, **kwargs): return await method(FakeModel(), *args)
    reasoner.invoke = invoke
    results = await reasoner.collect({'task_id': 'test', 'company_id': 1, 'request': '추천'}, gateway)
    assert results.keys() == READS
    assert results['get_solution_catalog']

@pytest.mark.asyncio
@pytest.mark.skipif(not os.getenv('AGENT_TEST_DATABASE_URL'), reason='임시 PostgreSQL 접속 정보 필요')
async def test_real_postgres_restart_resume():
    cfg = Settings(mode='mock', internal_token='test', data_dir=ROOT / 'AX_Navigator_AI_MVP_v3')
    gateway = MockGateway(cfg)
    thread_id = str(uuid4())
    config = {'configurable': {'thread_id': thread_id}}
    url = os.environ['AGENT_TEST_DATABASE_URL']
    async with AsyncPostgresSaver.from_conn_string(url) as saver:
        await saver.setup()
        graph = build_graph(gateway, MockReasoner(), saver, cfg)
        result = await graph.ainvoke({'task_id': thread_id, 'company_id': 1, 'user_id': 602, 'request': '추천', 'retry_count': 0}, config)
        assert result.get('__interrupt__')
    async with AsyncPostgresSaver.from_conn_string(url) as saver:
        graph = build_graph(gateway, MockReasoner(), saver, cfg)
        result = await graph.ainvoke(Command(resume={'decision': 'APPROVE', 'userId': 602}), config)
        assert result['status'] == 'DONE'

@pytest.mark.asyncio
async def test_rag_real_mcp_list_output_and_company_filter():
    sys.path.insert(0, str(ROOT / 'rag-mcp'))
    spec = importlib.util.spec_from_file_location('rag_integration', ROOT / 'rag-mcp/server.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    common = sys.modules['common']
    seen = []
    class FakeStore:
        def search(self, query, doc_type, process_id, top_k):
            seen.append((query,doc_type,process_id,top_k))
            return [{'document_id':401, 'title':'인사', 'doc_type':'MANUAL', 'section':'업무', 'page':0,
                     'content':'담당자 a@example.com 010-1234-5678', 'score':.1}]
    with patch.object(common, 'CORPUS', ROOT / 'AX_Navigator_AI_MVP_v3/rag'), patch.object(module, 'PgVectorStore', FakeStore):
        gateway = Gateway(Settings(mode='mock', internal_token='test'))
        async def no_callback(*args, **kwargs): pass
        gateway._spring = no_callback
        with patch('agent.app.clients.StreamableHttpTransport', return_value=module.mcp):
            result = await gateway.tool('task', 'retrieve', 'search_docs', {'query': '인사', 'process_id': 202})
    assert result[0]['content'] == '담당자 [EMAIL] [PHONE]'
    assert seen == [('인사', None, 202, 5)]
