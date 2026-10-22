"""No paid calls: exercise llm-demo wiring and actual Reasoner loop with a fake provider."""
from dataclasses import replace
import json
from uuid import uuid4
import httpx
import pytest
from langchain_core.messages import AIMessage
from agent.app.config import Settings
from agent.app.main import create_app
from agent.app.reasoning import Reasoner
from agent.app.schemas import Assessment, AssessmentDraft, Discovery, DiscoveryDraft, Narrative
from agent.app.trace import PublicTrace


@pytest.mark.asyncio
async def test_llm_demo_requires_key(monkeypatch):
    monkeypatch.delenv('OPENAI_API_KEY',raising=False)
    app=create_app(Settings(mode='llm-demo',model='test-model',internal_token='test'))
    with pytest.raises(RuntimeError,match='OPENAI_API_KEY'):
        async with app.router.lifespan_context(app): pass


@pytest.mark.asyncio
async def test_real_reasoner_two_turn_tool_loop_and_answer_without_external_services(monkeypatch):
    monkeypatch.setenv('OPENAI_API_KEY','test-placeholder')
    turns={'collect':0}
    reads=['get_company_profile','get_business_processes','get_operational_metrics',
           'get_system_inventory','get_project_budget','get_solution_catalog','get_solution_candidates']
    class FakeProvider:
        def __init__(self,**kwargs):
            assert kwargs['use_responses_api'] is True
            self.schema=None
        def bind_tools(self,tools,**kwargs):
            assert {t.name for t in tools}==set(reads)
            return self
        def with_structured_output(self,schema,**kwargs):
            self.schema=schema
            return self
        async def ainvoke(self,messages):
            if self.schema is None:
                start=turns['collect']*3;turns['collect']+=1
                return AIMessage(content='',tool_calls=[{'name':name,'args':{} if name=='get_solution_catalog' else {'company_id':1},'id':name,'type':'tool_call'} for name in reads[start:start+3]])
            if isinstance(self.schema,type) and issubclass(self.schema,AssessmentDraft):
                scores={'data_score':61.,'infra_score':62.,'automation_score':43.,'ai_capability_score':34.,'governance_score':46.}
                docs=[407,405,408,406,404]
                context=json.loads(messages[1].content)
                return self.schema(areas=[{'area':area,'score':scores[area],
                    'evidence_ids':[next(r['evidence_id'] for r in context['evidence'] if r['document_id']==doc)],
                    'summary':'테스트 근거','missing_reason':None} for area,doc in zip(scores,docs)])
            if isinstance(self.schema,type) and issubclass(self.schema,DiscoveryDraft):
                context=json.loads(messages[1].content)
                return self.schema(candidates=[{'candidate_id':key,'reason':'문서 기반 테스트 후보',
                    'evidence_ids':entry['evidence_ids']} for key,entry in context['candidate_catalog'].items()])
            assert self.schema is Narrative
            return Narrative(summary='선정 결과와 선행 과제를 문서 기준으로 설명합니다.',recommendations=[{'process_id':sid-300,'solution_id':sid,'reason':'반복 업무와 사람 검토 조건을 고려했습니다.','document_ids':[403]} for sid in (507,508,509)])
    monkeypatch.setattr('agent.app.reasoning.ChatOpenAI',FakeProvider)
    cfg=Settings(mode='llm-demo',model='test-model',internal_token='test')
    app=create_app(cfg);key=str(uuid4())
    async with app.router.lifespan_context(app):
        assert isinstance(app.state.reasoner,Reasoner)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://test',headers={'X-Internal-Token':'test'}) as client:
            assert (await client.post(f'/tasks/{key}/run',json={'companyId':1,'userId':602,'requestText':'추천'})).status_code==202
            job=app.state.jobs.get(key)
            if job: await job
            body=(await client.get(f'/tasks/{key}')).json()
            assert body['status']=='WAITING_APPROVAL',body
            assert turns['collect']==3
            assert body['result']['answer'].startswith('선정 결과와')
            assert '295,000,000' in body['result']['answer']
            assert 'total_score' not in body['result']['assessment']  # LLM scores differ from fixture; do not attach a false weighted total
            types=[e['type'] for e in body['trace']]
            assert 'LLM_REQUEST' in types and 'LLM_RESPONSE' in types and 'TOOL_CALL' in types
            assert 'test-placeholder' not in json.dumps(body)
            await client.post(f'/tasks/{key}/resume',json={'decision':'APPROVE','userId':602})
            job=app.state.jobs.get(key)
            if job: await job
            assert (await client.get(f'/tasks/{key}')).json()['status']=='DONE'


def test_trace_is_bounded_and_redacts_credentials():
    trace=PublicTrace(max_tasks=1,max_events=2)
    for i in range(3): trace.add('a','collect','TEST',{'api_key':'private','message':'sk-abcdefghijklmnop'})
    events=trace.get('a')
    assert [e['seq'] for e in events]==[2,3]
    assert events[0]['data']=={'message':'[API_KEY]'}
    trace.add('b','collect','TEST')
    assert trace.get('a')==[]
