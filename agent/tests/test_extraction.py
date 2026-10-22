"""Unconfirmed company: extract from uploaded chunks -> Spring draft -> wait -> confirm -> assessment-only DONE."""
from uuid import uuid4

import httpx
import pytest
from agent.app.assessment import AssessmentReferenceError
from agent.app.extraction import chunk_catalog, resolve_draft
from agent.app.main import create_app
from agent.app.mock import MockGateway
from agent.tests.test_agent import settings, wait_job

COMPANY, DOCUMENT = 2, 9001
CHUNKS = [{'document_id': DOCUMENT, 'title': '가온 회사 소개.pdf', 'doc_type': 'UPLOADED', 'section': 'p.1', 'page': 1, 'chunk_index': 0,
           'content': '인사팀은 매월 120건의 규정 문의에 답한다. 건당 15분, 시간당 인건비 35,000원.'},
          {'document_id': DOCUMENT, 'title': '가온 회사 소개.pdf', 'doc_type': 'UPLOADED', 'section': 'p.2', 'page': 2, 'chunk_index': 1,
           'content': '그룹웨어로 결재를 처리하며 보안 정책상 개인정보는 외부로 보내지 않는다.'}]


class NewCompany(MockGateway):
    """Spring이 확정 데이터를 저장한 뒤의 회사 2. 카탈로그에는 회사 2 업무용 솔루션이 없다."""
    def __init__(self, cfg):
        super().__init__(cfg)
        self.uploads[COMPANY] = [dict(c) for c in CHUNKS]

    def _call(self, task_id, name, args):
        if name == 'get_company_profile':
            return {'company_id': COMPANY, 'company_name': '가온', 'departments': [{'department_id': 201, 'department_name': '인사팀'}]}
        if name == 'get_business_processes':
            return [{'process_id': 900, 'department_id': 201, 'process_name': '규정 문의 응답', 'purpose': '반복 문의 응답',
                     'standardization_level': None, 'requires_approval': False, 'exception_rules': None}]
        if name == 'get_operational_metrics': return []
        if name == 'get_system_inventory': return {'systems': [], 'process_systems': []}
        if name == 'get_project_budget': return {'ax_budget_krw': None}
        return super()._call(task_id, name, args)


def run_body(**extra):
    return {'companyId': COMPANY, 'userId': 700, 'requestText': '우리 회사 AX 성숙도를 진단해 줘',
            'companyDataConfirmed': False, 'documentIds': [DOCUMENT], **extra}


@pytest.mark.asyncio
async def test_extract_wait_confirm_then_assessment_only_done():
    cfg = settings()
    gateway = NewCompany(cfg)
    app = create_app(cfg, gateway=gateway)
    key = str(uuid4())
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test',
                                     headers={'X-Internal-Token': 'test-token'}) as client:
            assert (await client.post(f'/tasks/{key}/run', json=run_body())).status_code == 202
            await wait_job(app, key)
            state = (await client.get(f'/tasks/{key}')).json()
            assert state['status'] == 'WAITING_CONFIRMATION', state
            saved = next(args for name, args in gateway.calls if name == 'save_extraction')
            assert saved['document_ids'] == [DOCUMENT]
            assert saved['payload']['processes'][0]['source'] == {'documentId': DOCUMENT, 'page': 1}
            assert saved['payload']['metrics'] == []  # 숫자는 만들지 않는다
            event = next(e['body'] for e in gateway.events if e['body'].get('type') == 'CONFIRMATION_REQUIRED')
            assert event['data'] == {'draftId': 7001}
            assert not any(e['body'].get('status') == 'WAITING_APPROVAL' for e in gateway.events if e['method'] == 'PATCH')
            assert not any(name in {'get_company_profile', 'save_assessment'} for name, _ in gateway.calls)

            assert (await client.post(f'/tasks/{key}/resume', json={'decision': 'APPROVE', 'userId': 700})).status_code == 409
            assert (await client.post(f'/tasks/{key}/confirm', json={'userId': 701})).status_code == 403
            assert (await client.post(f'/tasks/{key}/confirm', json={'userId': 700})).status_code == 202
            await wait_job(app, key)
            done = (await client.get(f'/tasks/{key}')).json()
            assert done['status'] == 'DONE', done
            assert done['result']['roadmap'] is None and done['result']['extraction'] == {'draftId': 7001}
            assert 'AX 성숙도 진단을 완료했습니다.' in done['result']['answer']
            assert sum(name == 'save_assessment' for name, _ in gateway.calls) == 1
            assert not any(name in {'calculate_ax_roi', 'optimize_ax_portfolio'} or name.startswith('create_') for name, _ in gateway.calls)
            assert gateway.events[-1]['body']['type'] == 'DONE'
            assert (await client.post(f'/tasks/{key}/confirm', json={'userId': 700})).status_code == 409


@pytest.mark.asyncio
async def test_unconfirmed_company_without_documents_fails_without_writes():
    cfg = settings()
    gateway = NewCompany(cfg)
    app = create_app(cfg, gateway=gateway)
    key = str(uuid4())
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test',
                                     headers={'X-Internal-Token': 'test-token'}) as client:
            assert (await client.post(f'/tasks/{key}/run', json=run_body(documentIds=[]))).status_code == 202
            await wait_job(app, key)
            assert (await client.get(f'/tasks/{key}')).json()['status'] == 'FAILED'
            failed = next(e['body'] for e in gateway.events if e['body'].get('type') == 'FAILED')
            assert 'PDF를 먼저 업로드' in failed['data']['message']
            assert not any(name == 'save_extraction' for name, _ in gateway.calls)


@pytest.mark.asyncio
async def test_confirmed_seed_company_still_waits_for_approval():
    cfg = settings()
    app = create_app(cfg, gateway=MockGateway(cfg))
    key = str(uuid4())
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test',
                                     headers={'X-Internal-Token': 'test-token'}) as client:
            body = {'companyId': 1, 'userId': 602, 'requestText': '추천', 'companyDataConfirmed': True, 'documentIds': []}
            assert (await client.post(f'/tasks/{key}/run', json=body)).status_code == 202
            await wait_job(app, key)
            assert (await client.get(f'/tasks/{key}')).json()['status'] == 'WAITING_APPROVAL'
            assert (await client.post(f'/tasks/{key}/confirm', json={'userId': 602})).status_code == 409


def draft(**changes):
    value = {'company': {'industry': None, 'employeeCount': None},
             'departments': [{'key': 'd1', 'name': '인사팀'}],
             'processes': [{'key': 'p1', 'departmentKey': 'd1', 'name': '규정 문의 응답', 'purpose': None, 'steps': [],
                            'standardizationLevel': 0.833, 'requiresApproval': False, 'exceptionRules': None, 'sourceId': 'C001'}],
             'metrics': [{'processKey': 'p1', 'monthlyCount': 120, 'avgMinutes': 15.004, 'hourlyLaborCostKrw': 35000,
                          'errorRate': None, 'sourceId': 'C001'}],
             'systems': [{'key': 's1', 'name': '그룹웨어', 'type': 'GROUPWARE', 'apiAvailable': False,
                          'dataAccessLevel': 'RESTRICTED', 'cloudBased': False, 'processKeys': ['p1']}]}
    value.update(changes)
    return value


def test_resolve_maps_sources_and_rounds_for_spring():
    payload = resolve_draft(draft(), chunk_catalog(CHUNKS, [DOCUMENT]))
    assert payload['processes'][0]['source'] == {'documentId': DOCUMENT, 'page': 1}
    assert payload['processes'][0]['standardizationLevel'] == 0.83
    assert payload['metrics'][0] | {} == {'processKey': 'p1', 'monthlyCount': 120, 'avgMinutes': 15.0, 'hourlyLaborCostKrw': 35000,
                                          'errorRate': None, 'source': {'documentId': DOCUMENT, 'page': 1}, 'dataSource': 'EXTRACTED'}
    assert 'sourceId' not in payload['processes'][0]


@pytest.mark.parametrize('changes,code', [
    ({'departments': [{'key': 'd1', 'name': 'a'}, {'key': 'd1', 'name': 'b'}]}, 'EXTRACTION_DUPLICATE_DEPARTMENT'),
    ({'departments': [{'key': 'd9', 'name': '인사팀'}]}, 'EXTRACTION_UNKNOWN_DEPARTMENT'),
    ({'systems': [{'key': 's1', 'name': 'ERP', 'type': 'ERP', 'apiAvailable': True, 'dataAccessLevel': 'OPEN',
                   'cloudBased': True, 'processKeys': ['p9']}]}, 'EXTRACTION_UNKNOWN_PROCESS'),
])
def test_resolve_rejects_broken_references(changes, code):
    with pytest.raises(AssessmentReferenceError) as caught:
        resolve_draft(draft(**changes), chunk_catalog(CHUNKS, [DOCUMENT]))
    assert caught.value.code == code


def test_chunk_catalog_only_uses_task_documents():
    other = {**CHUNKS[0], 'document_id': 9999}
    assert {row['document_id'] for row in chunk_catalog(CHUNKS + [other], [DOCUMENT]).values()} == {DOCUMENT}
    with pytest.raises(ValueError, match='INSUFFICIENT_DATA'):
        chunk_catalog([other], [DOCUMENT])
