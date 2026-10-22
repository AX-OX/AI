"""Retrieval coverage and complete context contracts; no paid API calls."""
import copy
import json
from uuid import uuid4
import pytest
from agent.app.config import Settings
from agent.app.contexts import assessment_context, context_json
from agent.app.graph.nodes.implemented import build_nodes
from agent.app.mock import MockGateway
from agent.app.reasoning import MockReasoner


async def retrieved():
    cfg = Settings(mode='mock');gateway = MockGateway(cfg)
    nodes = build_nodes(gateway, MockReasoner(cfg), cfg)
    state = {'task_id':str(uuid4()), 'company_id':1, 'request':'3억 원 내 AX 과제', 'user_id':602}
    state.update(await nodes['collect'](state))
    state.update(await nodes['retrieve'](state))
    return state, gateway


@pytest.mark.asyncio
async def test_separate_readiness_and_business_retrieval_retains_required_sections():
    state,gateway = await retrieved()
    assert len(state['evidence']) == 28
    assert len(state['assessment_evidence']) == 19
    assert len(state['business_evidence']) == 9
    sections={(r['document_id'], r['section']) for r in state['assessment_evidence']}
    assert {(404,'개인정보 처리'),(405,'업무 연결'),(407,'표준화 점검'),(408,'가상 사전 실험')} <= sections
    criteria=json.loads((Settings().data_dir/'config/assessment_criteria_v1.json').read_text())
    context=assessment_context(state, criteria)
    text=context_json(context, stage='assess', limit=28000)
    assert len(json.loads(text)['evidence']) == 19
    assert '가상 사전 실험' in text and '표준화 점검' in text
    assert len(text) < 28000


def test_oversized_context_rejected_not_sliced_into_invalid_json():
    with pytest.raises(ValueError, match='ASSESS_CONTEXT_LIMIT'):
        context_json({'evidence':[{'content':'x'*100}]}, stage='assess', limit=20)
    assert json.loads(context_json({'content':'마지막 문장'}, stage='assess', limit=100))['content']=='마지막 문장'


@pytest.mark.asyncio
async def test_readiness_batch_and_business_search_call_counts():
    state,gateway = await retrieved()
    assert sum(name=='get_assessment_evidence' for name,_ in gateway.calls) == 1
    searches=[args for name,args in gateway.calls if name=='search_docs']
    assert len(searches)==9 and all(args['top_k']==5 for args in searches)
    assert {r['section'].split(' ',1)[0] for r in state['business_evidence']} == {str(i) for i in range(201,210)}


@pytest.mark.asyncio
async def test_department_scope_reduces_business_queries_only():
    cfg=Settings(mode='mock');gateway=MockGateway(cfg);nodes=build_nodes(gateway,MockReasoner(cfg),cfg)
    state={'task_id':str(uuid4()),'company_id':1,'request':'개발팀에서 자동화 효과가 큰 업무','user_id':602}
    state.update(await nodes['collect'](state));state.update(await nodes['retrieve'](state))
    assert len(state['assessment_evidence'])==19 and len(state['business_evidence'])==3
    assert {args['process_id'] for name,args in gateway.calls if name=='search_docs'}=={207,208,209}


def draft_for(registry,criteria):
    from agent.app.schemas import AssessmentDraft
    types={'data_score':'DATA_QUALITY','infra_score':'SYSTEM_SPEC','automation_score':'PROJECT_REPORT',
           'ai_capability_score':'AI_STATUS','governance_score':'POLICY'}
    return AssessmentDraft(areas=[{'area':area,'score':50.,'evidence_ids':[next(key for key,row in registry.items()
                if row['doc_type']==types[area])],'summary':'실제 문서에 연결한 테스트 근거','missing_reason':None}
                for area in criteria['weights']])


@pytest.mark.asyncio
async def test_grounded_id_schema_and_spring_dto_reconstruction():
    from agent.app.assessment import evidence_catalog, draft_schema, load_policy, resolve_draft
    from pydantic import ValidationError
    state,_=await retrieved();registry=evidence_catalog(state);criteria=load_policy(Settings())
    draft=draft_for(registry,criteria);schema=draft_schema(registry)
    schema.model_validate(draft.model_dump())
    bad=draft.model_dump();bad['areas'][0]['evidence_ids']=['E_DOES_NOT_EXIST']
    with pytest.raises(ValidationError):schema.model_validate(bad)
    canonical=resolve_draft(draft,registry,criteria)
    assert set(canonical)=={'scores','evidence','insufficient_data'}
    assert 'total_score' not in canonical
    assert all((e['document_id'],e['section']) in {(r['document_id'],r['section']) for r in registry.values()}
               for e in canonical['evidence'])
    assert all('evidence_ids' not in e for e in canonical['evidence'])
    assert criteria['rubrics']['data_score']['rubric']


@pytest.mark.asyncio
async def test_unknown_reference_and_missing_area_still_fail():
    from agent.app.assessment import evidence_catalog, load_policy, resolve_draft, AssessmentReferenceError
    state,_=await retrieved();registry=evidence_catalog(state);criteria=load_policy(Settings())
    draft=draft_for(registry,criteria)
    draft.areas[0].evidence_ids=['E_BAD']
    with pytest.raises(AssessmentReferenceError,match='INVALID_REFERENCE'):resolve_draft(draft,registry,criteria)
    draft=draft_for(registry,criteria);draft.areas[0].evidence_ids=[]
    with pytest.raises(AssessmentReferenceError,match='EVIDENCE_MISSING'):resolve_draft(draft,registry,criteria)
    draft=draft_for(registry,criteria);draft.areas[0].area=draft.areas[1].area
    with pytest.raises(AssessmentReferenceError,match='AREA_MISMATCH'):resolve_draft(draft,registry,criteria)


@pytest.mark.asyncio
async def test_genuine_missing_information_is_not_filled():
    from agent.app.assessment import evidence_catalog,load_policy,resolve_draft
    state,_=await retrieved();registry=evidence_catalog(state);criteria=load_policy(Settings())
    draft=draft_for(registry,criteria);draft.areas[0].score=None;draft.areas[0].evidence_ids=[]
    draft.areas[0].missing_reason='실제 데이터 품질 정보가 확인되지 않음'
    result=resolve_draft(draft,registry,criteria)
    assert 'data_score' not in result['scores']
    assert result['insufficient_data']==['data_score']


@pytest.mark.asyncio
@pytest.mark.parametrize('repair_succeeds',[True,False])
async def test_reference_repair_once_without_repeating_retrieval(monkeypatch,repair_succeeds):
    from agent.app.assessment import evidence_catalog,load_policy,AssessmentReferenceError
    from agent.app.reasoning import Reasoner
    state,gateway=await retrieved();registry=evidence_catalog(state);criteria=load_policy(Settings())
    valid=draft_for(registry,criteria);invalid=copy.deepcopy(valid);invalid.areas[0].evidence_ids=[]
    reasoner=Reasoner(Settings(mode='mock'));calls=[]
    async def invoke(*args,**kwargs):
        calls.append(1)
        return invalid if len(calls)==1 or not repair_succeeds else valid
    monkeypatch.setattr(reasoner,'invoke',invoke)
    initial=len(gateway.calls)
    if repair_succeeds:
        result=await reasoner.assess(state,criteria)
        assert len(result['scores'])==5
    else:
        with pytest.raises(AssessmentReferenceError,match='EVIDENCE_MISSING'):await reasoner.assess(state,criteria)
    assert len(calls)==2 and len(gateway.calls)==initial


@pytest.mark.asyncio
async def test_real_insufficiency_does_not_trigger_reference_retry(monkeypatch):
    from agent.app.assessment import evidence_catalog,load_policy
    from agent.app.reasoning import Reasoner
    state,_=await retrieved();criteria=load_policy(Settings());draft=draft_for(evidence_catalog(state),criteria)
    draft.areas[0].score=None;draft.areas[0].evidence_ids=[];draft.areas[0].missing_reason='Unknown'
    reasoner=Reasoner(Settings());calls=[]
    async def invoke(*args,**kwargs):calls.append(1);return draft
    monkeypatch.setattr(reasoner,'invoke',invoke)
    result=await reasoner.assess(state,criteria)
    assert result['insufficient_data']==['data_score'] and len(calls)==1


@pytest.mark.asyncio
async def test_candidate_ids_bind_process_solution_and_require_full_coverage():
    from agent.app.candidate_refs import candidate_catalog,discovery_schema,resolve_candidates
    from agent.app.assessment import AssessmentReferenceError
    from pydantic import ValidationError
    state,_=await retrieved();choices,evidence=candidate_catalog(state);schema=discovery_schema(choices,evidence)
    payload={'candidates':[{'candidate_id':key,'reason':'근거가 있는 평가 후보','evidence_ids':entry['evidence_ids']}
                           for key,entry in choices.items()]}
    result=resolve_candidates(schema.model_validate(payload),choices,evidence)
    assert len(result)==8
    assert next(r for r in result if r['solution_id']==509)['process_id']==209
    invalid=copy.deepcopy(payload);invalid['candidates'][0]['candidate_id']='S_UNKNOWN'
    with pytest.raises(ValidationError):schema.model_validate(invalid)
    omitted=copy.deepcopy(payload);omitted['candidates'].pop()
    with pytest.raises(AssessmentReferenceError,match='COVERAGE_MISMATCH'):resolve_candidates(omitted,choices,evidence)
    wrong=copy.deepcopy(payload);wrong['candidates'][0]['evidence_ids']=payload['candidates'][-1]['evidence_ids']
    with pytest.raises(AssessmentReferenceError,match='INVALID_REFERENCE'):resolve_candidates(wrong,choices,evidence)
