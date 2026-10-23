"""Protect grounded discovery from duplicated document bodies and enforce size limits."""
import json
import pytest
from agent.app.contexts import discovery_context, context_json
from agent.app.candidate_refs import candidate_catalog
from agent.app.reasoning import Reasoner
from agent.tests.test_catalog_templates import UploadedCompany, execute
from agent.tests.test_agent import settings


@pytest.mark.asyncio
async def test_uploaded_document_body_sent_once_with_all_grounded_refs():
    state,_,_=await execute(UploadedCompany(settings(),2))
    # Valid upload-style chunks large enough to overflow if sent twice.
    rows=[{'document_id':9001,'doc_type':'UPLOADED','section':f'p.{i+1}',
           'title':'운영 현황.pdf','content':f'UNIQUE_BODY_{i} '+('한글 업무 근거 '*100)} for i in range(10)]
    state.update(evidence=rows,business_evidence=rows,assessment_evidence=rows)
    choices,evidence=candidate_catalog(state)
    context=discovery_context(state,'live')
    assert 'evidence' not in context
    context['candidate_catalog']=choices
    context['business_evidence']=[{'evidence_id':k,'document_id':r['document_id'],
                                 'section':r['section'],'content':r['content']} for k,r in evidence.items()]
    text=context_json(context,stage='discover',limit=24000)
    decoded=json.loads(text)
    assert {r['content'] for r in decoded['business_evidence']}=={r['content'] for r in rows}
    assert all(text.count(f'UNIQUE_BODY_{i}')==1 for i in range(10))
    assert all(set(c['evidence_ids'])<=evidence.keys() for c in choices.values())
    # Reproduce the old duplicate-body failure at the same unmodified limit.
    with pytest.raises(ValueError,match='DISCOVER_CONTEXT_LIMIT'):
        context_json({**context,'evidence':rows},stage='discover',limit=24000)


@pytest.mark.asyncio
async def test_actual_reasoner_discover_accepts_compact_context_and_logs_count(monkeypatch):
    state,_,_=await execute(UploadedCompany(settings(),2))
    import agent.app.reasoning as reasoning_module
    def checked_context(data, *, stage, limit):
        assert stage == 'discover' and limit == 28000
        return context_json(data, stage=stage, limit=limit)
    monkeypatch.setattr(reasoning_module, 'context_json', checked_context)
    cfg=settings();observed=[]
    reasoner=Reasoner(cfg,observer=lambda *args:observed.append(args))
    class Model:
        def with_structured_output(self,schema,**kwargs):self.schema=schema;return self
        async def ainvoke(self,messages):
            data=json.loads(messages[1].content)
            assert 'evidence' not in data
            refs={r['evidence_id'] for r in data['business_evidence']}
            assert refs
            return self.schema(candidates=[{'candidate_id':k,'reason':'문서에 근거한 업무',
                'evidence_ids':[v['evidence_ids'][0]]} for k,v in data['candidate_catalog'].items()])
    async def invoke(method,**kwargs):return await method(Model())
    reasoner.invoke=invoke
    result=await reasoner.discover(state)
    assert len(result)==2 and all(c['evidence_refs'] for c in result)
    event=next(args for args in observed if args[2]=='CONTEXT_BUILT')
    assert event[3]['evidenceCount']==len(candidate_catalog(state)[1])


@pytest.mark.parametrize('size', [24001, 28000, 28001])
def test_discovery_context_28000_character_boundary(size):
    overhead = len(context_json({'content': ''}, stage='discover', limit=28000))
    data = {'content': '가' * (size-overhead)}
    if size > 28000:
        with pytest.raises(ValueError, match='DISCOVER_CONTEXT_LIMIT'):
            context_json(data, stage='discover', limit=28000)
    else:
        result = context_json(data, stage='discover', limit=28000)
        assert len(result) == size and json.loads(result) == data
