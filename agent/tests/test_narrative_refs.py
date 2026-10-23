import copy
import json

import pytest

from agent.app.config import Settings
from agent.app.narrative_refs import (
    NarrativeReferenceError, draft_schema, reference_catalog, resolve_narrative,
)
from agent.app.reasoning import Reasoner


def state():
    return {
        'task_id': 'narrative-test', 'request': '로드맵 설명', 'processes': [], 'evidence': [],
        'portfolio': {'selected': [
            {'processId': 1226, 'solutionId': 501}, {'processId': 1227, 'solutionId': 501}],
            'runnerUp': [{'processId': 9999, 'solutionId': 509}]},
        'roadmap': {'items': [
            {'process_id': 1226, 'solution_id': 501, 'item_name': '규정 검색',
             'evidence': [{'document_id': 418}]},
            {'process_id': 1227, 'solution_id': 501, 'item_name': '기술 검색',
             'evidence': [{'document_id': 419}]}]},
    }


def draft():
    return {'summary': '선정 결과 설명', 'recommendations': [
        {'recommendation_id': 'R1', 'reason': '비공개 근거 문장', 'document_ids': [418]},
        {'recommendation_id': 'R2', 'reason': '다른 근거', 'document_ids': [419]}]}


def test_new_company_ids_and_reused_template_are_bound_in_canonical_order():
    catalog = reference_catalog(state())
    raw = draft()
    raw['recommendations'].reverse()
    result = resolve_narrative(raw, catalog)
    assert [(r['process_id'], r['solution_id']) for r in result['recommendations']] == [(1226, 501), (1227, 501)]
    assert result['recommendations'][0]['document_ids'] == [418]
    schema = draft_schema(catalog).model_json_schema()
    props = schema['$defs']['SelectedRecommendation']['properties']
    assert props['recommendation_id']['enum'] == ['R1', 'R2']
    assert 'process_id' not in props and 'solution_id' not in props


@pytest.mark.parametrize('kind', ['duplicate', 'missing', 'unknown', 'wrong-document'])
def test_invalid_references_are_rejected(kind):
    raw = draft()
    if kind == 'duplicate': raw['recommendations'][1]['recommendation_id'] = 'R1'
    elif kind == 'missing': raw['recommendations'].pop()
    elif kind == 'unknown': raw['recommendations'][1]['recommendation_id'] = 'private-secret'
    else: raw['recommendations'][0]['document_ids'] = [419]
    with pytest.raises(NarrativeReferenceError) as error:
        resolve_narrative(raw, reference_catalog(state()))
    assert 'private-secret' not in str(error.value)
    assert '비공개 근거 문장' not in str(error.value)


@pytest.mark.parametrize('count', [1, 2, 3])
def test_schema_accepts_exact_selected_count(count):
    catalog = {f'R{i}': {'process_id': 1000+i, 'solution_id': 501,
                       'document_ids': [418]} for i in range(1, count+1)}
    schema = draft_schema(catalog)
    value = schema(summary='요약', recommendations=[
        {'recommendation_id': key, 'reason': '근거', 'document_ids': [418]} for key in catalog])
    assert len(resolve_narrative(value, catalog)['recommendations']) == count


@pytest.mark.asyncio
@pytest.mark.parametrize('failure_kind', ['duplicate', 'schema'])
async def test_one_repair_then_canonical_output(monkeypatch, caplog, failure_kind):
    monkeypatch.setenv('OPENAI_API_KEY', 'test-placeholder')
    calls = []

    class Provider:
        def __init__(self, **kwargs): pass
        def with_structured_output(self, schema, **kwargs):
            self.schema = schema
            return self
        async def ainvoke(self, messages):
            calls.append(list(messages))
            context = json.loads(messages[1].content)
            assert 'runnerUp' not in context['portfolio']
            raw = draft()
            if len(calls) == 1:
                raw['recommendations'][1]['recommendation_id'] = 'R1' if failure_kind == 'duplicate' else 'R99'
            return self.schema.model_validate(raw)

    monkeypatch.setattr('agent.app.reasoning.ChatOpenAI', Provider)
    result = await Reasoner(Settings(mode='live', model='test-model')).respond(state())
    assert len(calls) == 2
    assert len(calls[1]) == 3
    assert result['recommendations'][1]['process_id'] == 1227
    assert '비공개 근거 문장' not in caplog.text
    assert 'NARRATIVE_' in caplog.text


@pytest.mark.asyncio
async def test_repeated_failure_is_bounded_and_logs_missing_duplicate(caplog):
    reasoner = Reasoner(Settings(mode='live'))
    calls = []
    async def invoke(*args, **kwargs):
        calls.append(1)
        raw = copy.deepcopy(draft())
        raw['recommendations'][1]['recommendation_id'] = 'R1'
        return raw
    reasoner.invoke = invoke
    with pytest.raises(NarrativeReferenceError, match='NARRATIVE_REFERENCE_MISMATCH'):
        await reasoner.respond(state())
    assert len(calls) == 2
    records = [json.loads(r.message) for r in caplog.records if r.name == 'agent.app.reasoning']
    assert records[-1]['missing'] == ['R2']
    assert records[-1]['duplicates'] == ['R1']
    assert records[-1]['expected'][1]['processId'] == 1227
    assert records[-1]['severity'] == 'ERROR'
    assert '비공개 근거 문장' not in caplog.text


@pytest.mark.asyncio
async def test_service_error_does_not_trigger_semantic_repair():
    reasoner = Reasoner(Settings(mode='live'))
    calls = []
    async def invoke(*args, **kwargs):
        calls.append(1)
        raise RuntimeError('서비스 호출 실패')
    reasoner.invoke = invoke
    with pytest.raises(RuntimeError, match='서비스 호출 실패'):
        await reasoner.respond(state())
    assert len(calls) == 1
