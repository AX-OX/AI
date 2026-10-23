"""Template contract regression. Numeric values here are recorded fixture values, not a calculator."""
import copy
from uuid import uuid4
import pytest
from pydantic import ValidationError
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command
from agent.app.mock import MockGateway
from agent.app.reasoning import MockReasoner
from agent.app.graph import build_graph
from agent.app.candidate_refs import candidate_catalog, discovery_schema
from agent.app.presentation import candidates_dto
from agent.app.contracts import normalize_read
from agent.app.schemas import ProcessExtract
from agent.tests.test_agent import settings
from agent.tests.test_extraction import draft


class UploadedCompany(MockGateway):
    def __init__(self, cfg, count=1, missing=False, other=False):
        super().__init__(cfg)
        self.count, self.missing, self.other = count, missing, other
        self.uploads[2]=[{'document_id':9001,'title':'업무 현황.pdf','doc_type':'UPLOADED','section':'p.1',
                         'page':1,'chunk_index':0,'content':'인사팀은 규정 문의와 휴가 문의를 처리한다. 개인정보는 마스킹하고 담당자가 답변을 검토한다.'}]
        self.processes=[{'process_id':900+i,'department_id':900,'process_name':f'규정 문의 {i}',
                         'purpose':'규정 문의 응답','standardization_level':.8,'requires_approval':False,
                         'exception_rules':None,'work_type':'OTHER' if other else 'KNOWLEDGE_QA'} for i in range(count)]
        self.matches=[] if other else [{'process_id':p['process_id'],'solution_id':501,'work_type':'KNOWLEDGE_QA',
                     'depends_on':None,'excluded_reason':None,'metrics_sufficient':not missing} for p in self.processes]

    def _call(self, task_id, name, args):
        if name=='get_company_profile': return {'company_id':2,'departments':[{'department_id':900,'department_name':'인사'}]}
        if name=='get_business_processes': return copy.deepcopy(self.processes)
        if name=='get_operational_metrics': return []
        if name=='get_system_inventory': return {'systems':[],'process_systems':[]}
        if name=='get_project_budget': return {'ax_budget_krw':None}
        if name=='get_solution_candidates': return copy.deepcopy(self.matches)
        if name=='calculate_ax_roi':
            value=copy.deepcopy(next(c for c in self.expected['per_candidate'] if c['solutionId']==501))
            value['processId']=args['process_id'];value['dataConfidence']='SURVEY'
            return value
        if name=='optimize_ax_portfolio':
            assert args['max_items']==self.count
            selected=[self._call(task_id,'calculate_ax_roi',c) for c in args['candidates']]
            return {'insufficient':False,'selected':selected,'excluded':[],
                    'totalAxScore':sum(c['axScore'] for c in selected),
                    'totalFirstYearTcoKrw':sum(c['firstYearTcoKrw'] for c in selected),
                    'budgetKrw':None,'remainingBudgetKrw':None,'warnings':[],
                    'evaluatedCombinations':1,'validCombinations':1}
        return super()._call(task_id,name,args)


async def execute(gateway, reasoner=None):
    cfg=settings()
    graph=build_graph(gateway,reasoner or MockReasoner(cfg),InMemorySaver(),cfg)
    config={'configurable':{'thread_id':str(uuid4())}}
    result=await graph.ainvoke({'task_id':str(uuid4()),'company_id':2,'user_id':700,'request':'추천'},config)
    return result,graph,config


@pytest.mark.asyncio
@pytest.mark.parametrize('count',[1,2])
async def test_new_company_and_same_template_multiple_processes(count):
    gateway=UploadedCompany(settings(),count)
    result,graph,config=await execute(gateway)
    assert result.get('__interrupt__')
    assert {(c['processId'],c['solutionId']) for c in result['portfolio']['selected']}=={(900+i,501) for i in range(count)}
    assert f'과제가 {count}개뿐' in result['answer']
    assert len(result['roadmap']['humanReviewByCandidate'])==count
    done=await graph.ainvoke(Command(resume={'decision':'APPROVE','userId':700}),config)
    assert done['status']=='DONE' and len(done['registration']['projects'])==count


@pytest.mark.asyncio
@pytest.mark.parametrize('missing,other',[(True,False),(False,True)])
async def test_no_eligible_candidates_assessment_only(missing,other):
    gateway=UploadedCompany(settings(),missing=missing,other=other)
    result,_,_=await execute(gateway)
    assert result['status']=='DONE' and not result.get('roadmap')
    assert not any(name in {'calculate_ax_roi','optimize_ax_portfolio','create_ax_roadmap'} for name,args in gateway.calls)
    if missing: assert '지표를 입력하면' in result['answer']


@pytest.mark.asyncio
async def test_pair_grounding_and_selected_badges():
    gateway=UploadedCompany(settings(),2)
    result,_,_=await execute(gateway)
    choices,evidence=candidate_catalog(result)
    assert set(choices)=={'S501P900','S501P901'}
    schema=discovery_schema(choices,evidence)
    with pytest.raises(ValidationError):
        schema.model_validate({'candidates':[{'candidate_id':'S501P999','reason':'bad','evidence_ids':['B001']}]})
    result['portfolio']['selected']=result['portfolio']['selected'][:1]
    assert [r['selected'] for r in candidates_dto(result)]==[True,False]


@pytest.mark.asyncio
async def test_missing_dependency_pair_is_not_rebound_by_agent():
    gateway=UploadedCompany(settings())
    gateway.matches[0]['depends_on']={'process_id':999,'solution_id':509}
    with pytest.raises(ValueError,match='선행 후보 쌍'):
        await execute(gateway)
    assert not any(name=='calculate_ax_roi' for name,args in gateway.calls)


@pytest.mark.asyncio
async def test_wrong_process_same_solution_narrative_rejected():
    class WrongNarrative(MockReasoner):
        async def respond(self,state):
            value=await super().respond(state)
            value['recommendations'][0]['process_id']=999
            return value
    with pytest.raises(ValueError,match='선정 솔루션 ID 불일치'):
        await execute(UploadedCompany(settings()),WrongNarrative(settings()))


def test_work_type_required_enum_and_nested_candidate_normalization():
    value=draft()['processes'][0]
    assert ProcessExtract.model_validate(value).workType=='KNOWLEDGE_QA'
    with pytest.raises(ValidationError): ProcessExtract.model_validate({**value,'workType':'INVENTED'})
    value.pop('workType')
    with pytest.raises(ValidationError): ProcessExtract.model_validate(value)
    assert normalize_read('get_solution_candidates',[{'processId':900,'solutionId':508,
               'dependsOn':{'processId':901,'solutionId':509}}])[0]['depends_on']=={'process_id':901,'solution_id':509}

@pytest.mark.asyncio
@pytest.mark.parametrize('name',['get_business_processes','get_operational_metrics','get_system_inventory','get_solution_catalog','get_solution_candidates'])
async def test_real_business_mcp_preserves_empty_arrays(name):
    import importlib.util,sys
    from pathlib import Path
    from unittest.mock import AsyncMock,patch
    from fastmcp import Client
    from agent.app.clients.mcp import decode_tool_result
    root=Path(__file__).resolve().parents[2]
    sys.path.insert(0,str(root/'business-mcp'))
    spec=importlib.util.spec_from_file_location('empty_array_business',root/'business-mcp/server.py')
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    with patch.object(module,'call',AsyncMock(return_value=[])):
        async with Client(module.mcp) as client:
            result=await client.call_tool(name,{} if name=='get_solution_catalog' else {'company_id':2})
    assert decode_tool_result(result)==[]

@pytest.mark.asyncio
async def test_immediate_resume_waits_for_previous_notification():
    import asyncio
    from agent.app.main import create_app
    from agent.app.schemas import RunRequest,ResumeRequest
    entered,release=asyncio.Event(),asyncio.Event()
    class SlowNotification(MockGateway):
        async def event(self,task_id,type_,node='',data=None):
            if type_=='APPROVAL_REQUIRED':
                entered.set();await release.wait()
            await super().event(task_id,type_,node,data)
    cfg=settings();gateway=SlowNotification(cfg);app=create_app(cfg,gateway=gateway)
    key=str(uuid4())
    async with app.router.lifespan_context(app):
        runner=app.state.runner
        await runner.start(key,RunRequest(companyId=1,userId=602,requestText='예산 3억 원 내 추천'))
        await asyncio.wait_for(entered.wait(),5)
        continuation=asyncio.create_task(runner.resume(key,ResumeRequest(userId=602,decision='APPROVE')))
        await asyncio.sleep(.01)
        assert not continuation.done()
        release.set()
        assert (await continuation)['status']=='RUNNING'
        job=runner.jobs.get(key)
        if job:await job
        assert (await runner.graph.aget_state(runner._cfg(key))).values['status']=='DONE'

@pytest.mark.asyncio
async def test_collect_repairs_early_model_stop_with_missing_tool_names():
    from agent.app.reasoning import Reasoner
    from agent.app.clients.mcp import READS
    from langchain_core.messages import AIMessage
    reasoner=Reasoner(settings());gateway=MockGateway(settings());turns=[]
    class Provider:
        def bind_tools(self,tools,**kwargs):return self
        async def ainvoke(self,messages):
            turns.append(messages[-1].content)
            if len(turns)==1:return AIMessage(content='수집 완료')
            assert all(name in turns[-1] for name in READS)
            return AIMessage(content='',tool_calls=[{'name':name,'args':{} if name=='get_solution_catalog' else {'company_id':1},
                                                    'id':name,'type':'tool_call'} for name in sorted(READS)])
    async def invoke(fn,**kwargs):return await fn(Provider())
    reasoner.invoke=invoke
    result=await reasoner.collect({'task_id':'early-stop','company_id':1,'request':'추천'},gateway)
    assert set(result)==READS and len(turns)==2

@pytest.mark.asyncio
async def test_seed_small_department_uses_precomputed_two_item_fixture():
    cfg=settings();gateway=MockGateway(cfg)
    graph=build_graph(gateway,MockReasoner(cfg),InMemorySaver(),cfg)
    result=await graph.ainvoke({'task_id':str(uuid4()),'company_id':1,'user_id':602,'request':'인사팀에서 과제 추천'},
                              {'configurable':{'thread_id':str(uuid4())}})
    assert result.get('__interrupt__')
    assert len(result['portfolio']['selected'])==2
    assert next(args for name,args in gateway.calls if name=='optimize_ax_portfolio')['max_items']==2
    assert all(row['section'].startswith(str(item['process_id'])+' ') for item in result['roadmap']['items'] for row in item['evidence'])


def test_uploaded_grounding_keeps_selected_chunk_not_only_document_id():
    from agent.app.candidate_refs import resolve_candidates
    state={'processes':[{'process_id':900}], 'solution_candidates':[{'process_id':900,'solution_id':501,
           'excluded_reason':None,'metrics_sufficient':True,'depends_on':None}],
           'evidence':[{'document_id':9001,'doc_type':'UPLOADED','section':'p.1','content':'첫 조각'},
                       {'document_id':9001,'doc_type':'UPLOADED','section':'p.1','content':'둘째 조각'}]}
    choices,evidence=candidate_catalog(state)
    key=next(k for k,row in evidence.items() if row['content']=='둘째 조각')
    candidates=resolve_candidates({'candidates':[{'candidate_id':'S501P900','reason':'근거 설명','evidence_ids':[key]}]},choices,evidence)
    assert [r['content'] for r in candidates[0]['evidence_refs']]==['둘째 조각']
