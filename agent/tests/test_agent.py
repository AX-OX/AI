import asyncio
from pathlib import Path
from uuid import uuid4

import httpx
import pytest
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command
from agent.app.config import Settings
from agent.app.graph import build_graph
from agent.app.main import create_app
from agent.app.mock import MockGateway
from agent.app.reasoning import MockReasoner

ROOT = Path(__file__).resolve().parents[2]


def settings():
    return Settings(mode='mock', internal_token='test-token', data_dir=ROOT / 'AX_Navigator_AI_MVP_v3')


async def wait_job(app, key):
    job = app.state.jobs.get(key)
    if job: await asyncio.wait_for(job, 10)

@pytest.mark.asyncio
async def test_approval_rejection_auth_and_duplicate():
    cfg = settings()
    gateway = MockGateway(cfg)
    app = create_app(cfg, gateway=gateway)
    key = str(uuid4())
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
            body = {'companyId': 1, 'userId': 602, 'requestText': '과제 추천'}
            assert (await client.post(f'/tasks/{key}/run', json=body)).status_code == 403
            client.headers['X-Internal-Token'] = 'test-token'
            assert (await client.post(f'/tasks/{key}/run', json=body)).status_code == 202
            await wait_job(app, key)
            result = (await client.get(f'/tasks/{key}')).json()
            assert result['status'] == 'WAITING_APPROVAL', result
            assert not any(n.startswith('create_') for n, _ in gateway.calls)
            assert (await client.post(f'/tasks/{key}/run', json=body)).status_code == 409
            assert (await client.post(f'/tasks/{key}/resume', json={'decision': 'APPROVE', 'userId': 601})).status_code == 403
            assert (await client.post(f'/tasks/{key}/resume', json={'decision': 'REJECT', 'userId': 602})).status_code == 202
            await wait_job(app, key)
            assert (await client.get(f'/tasks/{key}')).json()['status'] == 'REJECTED'
            assert not any(n.startswith('create_') for n, _ in gateway.calls)
            assert (await client.post(f'/tasks/{key}/resume', json={'decision': 'APPROVE', 'userId': 602})).status_code == 409

@pytest.mark.asyncio
async def test_approve_registers_once():
    cfg = settings()
    gateway = MockGateway(cfg)
    app = create_app(cfg, gateway=gateway)
    key = str(uuid4())
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test', headers={'X-Internal-Token': 'test-token'}) as client:
            await client.post(f'/tasks/{key}/run', json={'companyId': 1, 'userId': 602, 'requestText': '추천'})
            await wait_job(app, key)
            assert (await client.post(f'/tasks/{key}/resume', json={'decision': 'APPROVE', 'userId': 602})).status_code == 202
            await wait_job(app, key)
            result = (await client.get(f'/tasks/{key}')).json()
            assert result['status'] == 'DONE', result
            assert sum(n == 'create_ax_roadmap' for n, _ in gateway.calls) == 1
            assert sum(n == 'create_ax_project' for n, _ in gateway.calls) == 3
            assert gateway.events[-1]['body']['type'] == 'DONE'

@pytest.mark.asyncio
async def test_checkpoint_survives_graph_recreation_and_insufficient_scores():
    cfg = settings()
    gateway = MockGateway(cfg)
    saver = InMemorySaver()
    config = {'configurable': {'thread_id': str(uuid4())}}
    state = {'task_id': config['configurable']['thread_id'], 'company_id': 1, 'user_id': 602, 'request': '추천', 'retry_count': 0}
    graph = build_graph(gateway, MockReasoner(), saver, cfg)
    result = await graph.ainvoke(state, config)
    assert result.get('__interrupt__')
    assert result['maturity']['assessment_id'] == 701
    assert result['maturity']['total_score'] == 49.75
    assert all(v['dataConfidence'] == 'ASSUMED' for v in result['opportunities'])
    assert result['evaluation_policy']['weights'] == {'impact': .6, 'feasibility': .4}
    assert sum(n == 'save_assessment' for n, _ in gateway.calls) == 1
    graph2 = build_graph(gateway, MockReasoner(), saver, cfg)
    result = await graph2.ainvoke(Command(resume={'decision': 'APPROVE', 'userId': 602}), config)
    assert result['status'] == 'DONE'

@pytest.mark.asyncio
async def test_mcp_failure_reports_failed_without_writes():
    cfg = settings()
    class Broken(MockGateway):
        async def tool(self, task_id, node, name, args): raise ConnectionError('MCP offline')
    gateway = Broken(cfg)
    app = create_app(cfg, gateway=gateway)
    key = str(uuid4())
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test', headers={'X-Internal-Token': 'test-token'}) as client:
            await client.post(f'/tasks/{key}/run', json={'companyId': 1, 'userId': 602, 'requestText': '추천'})
            await wait_job(app, key)
            assert (await client.get(f'/tasks/{key}')).json()['status'] == 'FAILED'
            assert gateway.events[-1]['body']['type'] == 'FAILED'

@pytest.mark.asyncio
async def test_insufficient_portfolio_retries_only_twice():
    cfg = settings()
    class NoPortfolio(MockGateway):
        def _call(self, task_id, name, args):
            if name == 'optimize_ax_portfolio': return {'selected': [], 'insufficient': True}
            return super()._call(task_id, name, args)
    gateway = NoPortfolio(cfg)
    graph = build_graph(gateway, MockReasoner(), InMemorySaver(), cfg)
    with pytest.raises(ValueError, match='찾지 못했습니다'):
        await graph.ainvoke({'task_id': str(uuid4()), 'company_id': 1, 'user_id': 602, 'request': '추천', 'retry_count': 0}, {'configurable': {'thread_id': str(uuid4())}})
    assert sum(n == 'optimize_ax_portfolio' for n, _ in gateway.calls) == 3
    assert not any(n.startswith('create_') for n, _ in gateway.calls)

@pytest.mark.asyncio
async def test_tampered_roi_never_reaches_approval_or_writes():
    cfg = settings()
    class Tampered(MockGateway):
        def _call(self, task_id, name, args):
            value = super()._call(task_id, name, args)
            if name == 'calculate_ax_roi': value['scenarios']['base']['roiPct'] = float('nan')
            return value
    gateway = Tampered(cfg)
    graph = build_graph(gateway, MockReasoner(), InMemorySaver(), cfg)
    with pytest.raises(ValueError, match='finite'):
        await graph.ainvoke({'task_id': str(uuid4()), 'company_id': 1, 'user_id': 602, 'request': '추천', 'retry_count': 0}, {'configurable': {'thread_id': str(uuid4())}})
    assert not any(n.startswith('create_') for n, _ in gateway.calls)

@pytest.mark.asyncio
async def test_company_scope_rejects_before_tools():
    cfg = settings()
    gateway = MockGateway(cfg)
    app = create_app(cfg, gateway=gateway)
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test', headers={'X-Internal-Token': 'test-token'}) as client:
            response = await client.post(f'/tasks/{uuid4()}/run', json={'companyId': 2, 'userId': 602, 'requestText': '추천'})
            assert response.status_code == 403
            assert not gateway.calls

@pytest.mark.asyncio
async def test_legacy_score_contract_rejected():
    cfg=settings()
    class Legacy(MockGateway):
        def _call(self,task_id,name,args):
            value=super()._call(task_id,name,args)
            if name=='calculate_ax_roi':value.pop('axScore')
            return value
    gateway=Legacy(cfg)
    graph=build_graph(gateway,MockReasoner(),InMemorySaver(),cfg)
    with pytest.raises(ValueError,match='axScore'):
        await graph.ainvoke({'task_id':str(uuid4()),'company_id':1,'user_id':602,'request':'추천','retry_count':0},{'configurable':{'thread_id':str(uuid4())}})

@pytest.mark.asyncio
async def test_missing_prerequisite_cannot_reach_approval():
    cfg=settings()
    class MissingDependency(MockGateway):
        def _call(self,task_id,name,args):
            value=super()._call(task_id,name,args)
            if name=='optimize_ax_portfolio':
                lookup={c['solutionId']:c for c in self.expected['per_candidate']}
                value['selected']=[lookup[s] for s in (501,507,508)]
            return value
    graph=build_graph(MissingDependency(cfg),MockReasoner(),InMemorySaver(),cfg)
    with pytest.raises(ValueError,match='선행 과제'):
        await graph.ainvoke({'task_id':str(uuid4()),'company_id':1,'user_id':602,'request':'추천','retry_count':0},{'configurable':{'thread_id':str(uuid4())}})

@pytest.mark.asyncio
async def test_v3_oracle_payload_and_exact_saved_values():
    import json
    cfg=settings(); gateway=MockGateway(cfg)
    expected=json.loads((cfg.data_dir/'eval/demo_expected_portfolio.json').read_text())
    app=create_app(cfg,gateway=gateway);key=str(uuid4())
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://test',headers={'X-Internal-Token':'test-token'}) as client:
            await client.post(f'/tasks/{key}/run',json={'companyId':1,'userId':602,'requestText':'3억 원 내 3개 추천'})
            await wait_job(app,key)
            pending=(await client.get(f'/tasks/{key}')).json()
            assert pending['status']=='WAITING_APPROVAL'
            result=pending['result']
            assert result['portfolio']['totalAxScore']==expected['total_ax_score']
            assert result['portfolio']['totalFirstYearTcoKrw']==expected['total_first_year_tco_krw']
            assert [{k: c[k] for k in expected['per_candidate'][0]} for c in result['candidates']]==expected['per_candidate']
            assert all(c['processName'] and c['priority']==c['axScore'] for c in result['candidates'])
            assert result['excluded']==expected['excluded']
            assert [i['solutionId'] for i in result['roadmap']['items']]==[507,509,508]
            assert result['roadmap']['items'][2]['startMonth']>=result['roadmap']['items'][1]['startMonth']+result['roadmap']['items'][1]['durationMonths']
            assert all(i['humanReviewRequired'] for i in result['roadmap']['items'] if i['solutionId'] in (508,509))
            event=next(e['body'] for e in gateway.events if e['body'].get('type')=='APPROVAL_REQUIRED')
            assert event['data']['items']==result['roadmap']['items']
            assert result['assessment']['assessment_id']==701
            assert sum(n=='save_assessment' for n,_ in gateway.calls)==1
            assert not any(n.startswith('create_') for n,_ in gateway.calls)
            await client.post(f'/tasks/{key}/resume',json={'decision':'APPROVE','userId':602})
            await wait_job(app,key)
            saved=next(args for n,args in gateway.calls if n=='create_ax_roadmap')
            assert saved['assessment_id']==701
            lookup={c['solutionId']:c for c in expected['per_candidate']}
            for item in saved['items']:
                c=lookup[item['solution_id']]
                assert item['ax_score']==c['axScore']
                assert item['impact_score']==c['impactScore']
                assert item['feasibility_score']==c['feasibilityScore']
                assert item['three_year_net_value_krw']==c['scenarios']['base']['threeYearNetKrw']
                assert 'humanReviewRequired' not in item  # display field must not leak into Spring storage DTO


@pytest.mark.asyncio
async def test_catalog_pair_mismatch_and_excluded_candidate():
    cfg=settings()
    class WrongPair(MockReasoner):
        async def discover(self,state):
            result=await super().discover(state)
            result[0]['solution_id']=507
            return result
    graph=build_graph(MockGateway(cfg),WrongPair(cfg),InMemorySaver(),cfg)
    with pytest.raises(ValueError,match='target_process_id'):
        await graph.ainvoke({'task_id':str(uuid4()),'company_id':1,'user_id':602,'request':'추천'}, {'configurable':{'thread_id':str(uuid4())}})
    class WithExcluded(MockReasoner):
        async def discover(self,state):
            result=await super().discover(state)
            return result+[{'process_id':203,'solution_id':503,'reason':'사람 최종 평가 자동화 요청','document_ids':[401]}]
    gateway=MockGateway(cfg)
    result=await build_graph(gateway,WithExcluded(cfg),InMemorySaver(),cfg).ainvoke(
        {'task_id':str(uuid4()),'company_id':1,'user_id':602,'request':'추천'}, {'configurable':{'thread_id':str(uuid4())}})
    assert result.get('__interrupt__')
    assert not any(name=='calculate_ax_roi' and args['process_id']==203 for name,args in gateway.calls)


@pytest.mark.asyncio
async def test_missing_maturity_evidence_does_not_fabricate_scores():
    cfg=settings();gateway=MockGateway(cfg)
    class Missing(MockReasoner):
        async def assess(self,state,criteria):
            result=await super().assess(state,criteria)
            result['scores'].pop('governance_score')
            result['insufficient_data']=['governance_score']
            return result
    graph=build_graph(gateway,Missing(cfg),InMemorySaver(),cfg)
    with pytest.raises(ValueError,match='INSUFFICIENT_DATA'):
        await graph.ainvoke({'task_id':str(uuid4()),'company_id':1,'user_id':602,'request':'추천'}, {'configurable':{'thread_id':str(uuid4())}})
    assert not any(name=='save_assessment' or name.startswith('create_') for name,_ in gateway.calls)


@pytest.mark.asyncio
async def test_wrong_portfolio_totals_rejected():
    cfg=settings()
    class WrongTotals(MockGateway):
        def _call(self,task_id,name,args):
            value=super()._call(task_id,name,args)
            if name=='optimize_ax_portfolio': value['totalAxScore']+=1
            return value
    graph=build_graph(WrongTotals(cfg),MockReasoner(cfg),InMemorySaver(),cfg)
    with pytest.raises(ValueError,match='AX점수 합계'):
        await graph.ainvoke({'task_id':str(uuid4()),'company_id':1,'user_id':602,'request':'추천'}, {'configurable':{'thread_id':str(uuid4())}})


def test_mock_uses_precomputed_department_subset_counts():
    cfg=settings();gateway=MockGateway(cfg)
    result=gateway._call('test','optimize_ax_portfolio',{
        'company_id':1,'max_items':3,
        'candidates':[{'process_id':207,'solution_id':507},{'process_id':208,'solution_id':508},{'process_id':209,'solution_id':509}]})
    assert result['insufficient'] is False
    assert result['evaluatedCombinations']==result['validCombinations']==1
    assert result['totalAxScore']==265.0
    assert result['totalFirstYearTcoKrw']==295000000


@pytest.mark.asyncio
async def test_development_request_scopes_candidates_and_completes():
    cfg=settings();gateway=MockGateway(cfg);app=create_app(cfg,gateway=gateway);key=str(uuid4())
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://test',headers={'X-Internal-Token':'test-token'}) as client:
            await client.post(f'/tasks/{key}/run',json={'companyId':1,'userId':602,'requestText':'개발부에서 지금 AX 과제 도출해줘'})
            await wait_job(app,key)
            result=(await client.get(f'/tasks/{key}')).json()
            assert result['status']=='WAITING_APPROVAL',result
            assert result['result']['scope']['departmentIds']==[103]
            assert {c['processId'] for c in result['result']['candidates']}=={207,208,209}
            assert result['result']['portfolio']['evaluatedCombinations']==1
            await client.post(f'/tasks/{key}/resume',json={'decision':'APPROVE','userId':602})
            await wait_job(app,key)
            assert (await client.get(f'/tasks/{key}')).json()['status']=='DONE'


@pytest.mark.asyncio
async def test_validation_failure_explains_which_candidate_failed():
    cfg=settings();gateway=MockGateway(cfg)
    class Wrong(MockReasoner):
        async def discover(self,state):
            result=await super().discover(state)
            result[0]['solution_id']=501
            return result
    app=create_app(cfg,gateway=gateway,reasoner=Wrong(cfg));key=str(uuid4())
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://test',headers={'X-Internal-Token':'test-token'}) as client:
            await client.post(f'/tasks/{key}/run',json={'companyId':1,'userId':602,'requestText':'개발부에서 AX 과제 추천'})
            await wait_job(app,key)
            result=(await client.get(f'/tasks/{key}')).json()
            assert result['status']=='FAILED'
            assert 'process_id=207, solution_id=501' in result['errors'][0]
            assert 'target_process_id' in next(e['data']['message'] for e in result['trace'] if e['type']=='NODE_ERROR')
