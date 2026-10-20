"""Actual teammate DTO shapes and FE fields; no changes to BE/FE source required."""
from uuid import uuid4

import httpx
import pytest

from agent.app.config import Settings
from agent.app.contracts import normalize_read
from agent.app.main import create_app
from agent.app.mock import MockGateway
from agent.app.presentation import maturity_dto
from agent.app.clients import Gateway
from agent.app.clients.spring import SpringClient


def test_spring_months_and_system_links_are_preserved():
    rows = normalize_read('get_operational_metrics', [
        {'processId': 207, 'annualHours': None, 'missingMonths': ['2026-08'],
         'months': [{'metricId': 1, 'processingCount': 10, 'periodStart': '2026-07-01'}]},
        {'processId': 208, 'annualHours': None, 'missingMonths': ['2026-07'], 'months': []},
    ])
    assert rows[0]['process_id'] == 207 and rows[0]['processing_count'] == 10
    assert rows[0]['missing_months'] == ['2026-08'] and rows[0]['annual_hours'] is None
    assert rows[1]['process_id'] == 208
    systems = normalize_read('get_system_inventory', [
        {'systemId': 303, 'apiAvailable': True, 'processes': [{'processId': 207, 'usagePurpose': '티켓'}]}])
    assert systems == {'systems': [{'system_id': 303, 'api_available': True}],
                       'process_systems': [{'system_id': 303, 'process_id': 207, 'usage_purpose': '티켓'}]}
    assert normalize_read('get_system_inventory', systems) == systems


def test_no_invented_maturity_total():
    assert maturity_dto({'scores': {'data_score': 55}}) is None


@pytest.mark.asyncio
async def test_team_spring_client_preserves_internal_prefix_and_callback_contract():
    cfg = Settings(mode='mock', internal_token='test-token', spring_url='http://spring/internal')
    requests = []
    def respond(request):
        requests.append(request)
        return httpx.Response(200, json={'ok':True})
    async with httpx.AsyncClient(base_url=cfg.spring_url+'/', transport=httpx.MockTransport(respond)) as http:
        spring = SpringClient(cfg, client=http)
        gateway = Gateway(cfg)
        gateway._spring = spring.request
        await gateway.status('task-id', 'RUNNING', trace_url='https://example.com/trace', error_message=None)
        await spring.emit('task-id', 'TOKEN', node='roadmap', data={'text':'검증된 설명'})
    import json
    assert requests[0].url.path == '/internal/tasks/task-id'
    assert json.loads(requests[0].content)['traceUrl'] == 'https://example.com/trace'
    assert 'errorMessage' in json.loads(requests[0].content)
    assert requests[1].url.path == '/internal/tasks/task-id/events'
    assert requests[1].headers['content-type'] == 'application/json'
    assert all(r.headers['x-internal-token'] == 'test-token' for r in requests)


@pytest.mark.asyncio
async def test_fe_snapshot_events_approval_and_registered_projects():
    cfg = Settings(mode='mock', internal_token='test-token')
    gateway = MockGateway(cfg)
    app = create_app(cfg, gateway=gateway)
    key = str(uuid4())
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test',
                                     headers={'X-Internal-Token': cfg.internal_token}) as client:
            assert (await client.post(f'/tasks/{key}/run', json={
                'companyId': 1, 'userId': 602, 'requestText': '개발부 AX 과제 선정'})).status_code == 202
            await app.state.jobs[key]
            pending = (await client.get(f'/tasks/{key}')).json()
            result = pending['result']
            assert pending['status'] == 'WAITING_APPROVAL'
            assert not result['projects']
            assert result['roadmap']['approvalStatus'] == 'PENDING'
            assert result['roadmap']['budgetLimitKrw'] == 300000000
            assert all(c['priority'] == c['axScore'] and c['selected'] for c in result['candidates'])
            assert all(c['firstYearCostKrw'] == c['firstYearTcoKrw'] for c in result['candidates'])
            assert all(i['departmentName'] and i['solutionType'] and i['evidence'][0]['documentId']
                       for i in result['roadmap']['items'])
            assert result['maturity']['totalScore'] == result['assessment']['total_score']
            events = [e['body'] for e in gateway.events if e['path'].endswith('/events')]
            text = ''.join(e['data']['text'] for e in events if e['type'] == 'TOKEN')
            assert text == result['answer']
            assert next(e for e in events if e['type'] == 'APPROVAL_REQUIRED')['data']['items'] == result['roadmap']['items']
            assert (await client.post(f'/tasks/{key}/resume', json={'decision':'APPROVE','userId':601})).status_code == 403
            assert (await client.post(f'/tasks/{key}/resume', json={'decision':'APPROVE','userId':602})).status_code == 202
            await app.state.jobs[key]
            final = (await client.get(f'/tasks/{key}')).json()
            assert final['status'] == 'DONE'
            assert final['result']['roadmap']['approvalStatus'] == 'APPROVED'
            assert len(final['result']['projects']) == 3
            assert all(p['projectId'] > 0 and p['itemId'] > 0 and p['projectName'] and p['ownerDepartmentId'] == 103
                       for p in final['result']['projects'])
            assert '요청자 승인 후' not in final['result']['answer']


@pytest.mark.asyncio
async def test_missing_spring_callback_is_reported_as_endpoint_error():
    cfg = Settings(mode='mock', internal_token='test-token')
    class MissingCallbacks(MockGateway):
        async def _spring(self, method, path, body):
            request = httpx.Request(method, 'http://spring/internal' + path)
            httpx.Response(404, request=request).raise_for_status()
    app = create_app(cfg, gateway=MissingCallbacks(cfg))
    key = str(uuid4())
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test',
                                     headers={'X-Internal-Token': cfg.internal_token}) as client:
            await client.post(f'/tasks/{key}/run', json={'companyId':1,'userId':602,'requestText':'과제 선정'})
            await app.state.jobs[key]
            body = (await client.get(f'/tasks/{key}')).json()
            assert body['status'] == 'FAILED'
            assert f'Spring HTTP 404: PATCH /internal/tasks/{key}' in body['errors'][0]
            assert not body['result']['projects']
