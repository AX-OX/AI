"""LLM 출력은 후보·근거로 제한한다. 비용과 절감률은 도구 결과로만 사용한다."""
import asyncio
import json
from pathlib import Path
from langchain_core.messages import HumanMessage, SystemMessage, ToolMessage
from langchain_core.tools import StructuredTool
from langchain_openai import ChatOpenAI
from .clients import READS, mask
from .concurrency import ordered_map
from .schemas import Narrative
from .contexts import assessment_context, discovery_context, response_context, context_json
from .assessment import evidence_catalog, draft_schema, resolve_draft, AssessmentReferenceError
from .candidate_refs import candidate_catalog, discovery_schema, resolve_candidates
from .extraction import chunk_catalog, draft_schema as extraction_schema, resolve_draft as resolve_extraction
from .harness.limits import LoopGuard, LimitExceeded
from .harness.tool_output import prepare_tool_output
from .harness.recovery import is_retryable

PROMPTS = Path(__file__).resolve().parents[1] / 'prompts'

def prompt(name):
    return (PROMPTS / f'{name}.md').read_text(encoding='utf-8')

def compact(data, limit=16000):
    return json.dumps(mask(data), ensure_ascii=False, default=str)[:limit]

class Reasoner:
    def __init__(self, settings, observer=None):
        self.settings, self.observer = settings, observer

    def observe(self, task_id, stage, type_, data):
        if self.observer: self.observer(task_id, stage, type_, data)

    async def invoke(self, method, *args, task_id='', stage=''):
        models = list(dict.fromkeys(filter(None, [self.settings.model, self.settings.fallback_model])))
        last = None
        for name in models:
            model = ChatOpenAI(model=name, temperature=None, use_responses_api=True, timeout=45, max_retries=0)
            for attempt in range(3):
                self.observe(task_id, stage, 'LLM_REQUEST', {'model':name, 'attempt':attempt+1})
                try:
                    result = await method(model, *args)
                    info = {'model':name, 'responseType':type(result).__name__}
                    usage = getattr(result, 'usage_metadata', None)
                    if usage: info['usage'] = usage
                    calls = getattr(result, 'tool_calls', None)
                    if calls: info['toolCalls'] = [c['name'] for c in calls]
                    self.observe(task_id, stage, 'LLM_RESPONSE', info)
                    return result
                except Exception as exc:
                    last = exc
                    info={'model':name,'errorType':type(exc).__name__,'httpStatus':getattr(exc,'status_code',None)}
                    from pydantic import ValidationError
                    if isinstance(exc,ValidationError):
                        info['validationErrors']=[{'field':list(e['loc']),'type':e['type']} for e in exc.errors(include_input=False,include_url=False)]
                    self.observe(task_id, stage, 'LLM_ERROR', info)
                    if not is_retryable(exc):
                        raise RuntimeError('LLM 호출 실패') from exc
                    await asyncio.sleep(0.5 * 2**attempt)
        raise RuntimeError('LLM 호출 실패') from last

    async def collect(self, state, gateway):
        results = {}
        guard = LoopGuard(self.settings)
        tools = []
        for name in sorted(READS):
            async def execute(company_id: int | None = None, department_id: int | None = None, _name=name):
                try:
                    guard.record_tool(_name)
                except LimitExceeded as exc:
                    self.observe(state['task_id'],'collect','TOOL_REJECTED',{'tool':_name,'reason':str(exc)})
                    return str(exc)
                if company_id is not None and company_id != state['company_id']: return '오류: 작업의 회사 ID를 사용하세요.'
                if department_id is not None: return '오류: collect 단계에서는 department_id 없이 회사 전체를 조회하세요.'
                args = {} if _name == 'get_solution_catalog' else {'company_id': state['company_id']}
                if _name in {'get_business_processes', 'get_operational_metrics'} and department_id is not None:
                    args['department_id'] = department_id
                if _name in results:
                    self.observe(state['task_id'],'collect','TOOL_CACHE_HIT',{'tool':_name})
                    return prepare_tool_output(compact(results[_name], 100000), self.settings)
                try:
                    value = await gateway.tool(state['task_id'], 'collect', _name, args)
                    results[_name] = value
                    return prepare_tool_output(compact(value, 100000), self.settings)
                except Exception as exc:
                    return f'도구 오류: {str(exc)[:500]}'
            # 모델에 내부 _name 인자를 노출하지 않도록 명시적 schema 사용
            tools.append(StructuredTool.from_function(coroutine=execute, name=name,
                description=f'{name}: 회사 업무 정보를 조회한다. company_id는 작업 컨텍스트에서 얻는다.',
                args_schema={'type':'object', 'properties':{} if name=='get_solution_catalog' else {'company_id':{'type':'integer'}},
                             'required':[] if name=='get_solution_catalog' else ['company_id'], 'additionalProperties':False}))
        messages = [SystemMessage(content=prompt('collect')+'\n필수 조회 도구: '+', '.join(sorted(READS))), HumanMessage(content=compact({'company_id': state['company_id'], 'request': state['request']}))]
        by_name = {t.name: t for t in tools}
        for _ in range(self.settings.max_agent_turns):
            guard.next_turn()
            async def choose(model): return await model.bind_tools(tools, strict=True).ainvoke(messages)
            response = await self.invoke(choose, task_id=state['task_id'], stage='collect')
            messages.append(response)
            if not response.tool_calls:
                missing=sorted(READS-results.keys())
                if not missing: break
                messages.append(HumanMessage(content='필수 조회가 아직 누락됐습니다. 다음 도구를 호출하세요: '+', '.join(missing)))
                continue
            # Reuse identical calls only within this LLM batch/task. Errors are
            # not cached across batches, so the existing bounded retry can repair them.
            calls = {}
            for call in response.tool_calls:
                key = (call['name'], json.dumps(call['args'], sort_keys=True))
                calls.setdefault(key, call)

            async def run_call(call):
                self.observe(state['task_id'],'collect','LLM_TOOL_CALL',{'tool':call['name'],'arguments':call['args']})
                tool = by_name.get(call['name'])
                return await tool.ainvoke(call['args']) if tool else '허용되지 않은 도구'

            values = await ordered_map(run_call, list(calls.values()), self.settings.read_concurrency)
            by_call = dict(zip(calls, values))
            # Preserve the LLM's tool-call ordering regardless of completion order.
            for call in response.tool_calls:
                key = (call['name'], json.dumps(call['args'], sort_keys=True))
                messages.append(ToolMessage(content=str(by_call[key]), tool_call_id=call['id']))
            if READS <= results.keys(): break
        if not READS <= results.keys():
            raise ValueError(f'필수 조회 도구 결과 부족: {sorted(READS - results.keys())}')
        return results

    async def extract(self, state, chunks):
        catalog = chunk_catalog(chunks, state['document_ids'])
        schema = extraction_schema(catalog)
        context = {'request': state['request'],
                   'chunks': [{'chunk_id': key, 'document_id': row['document_id'], 'title': row['title'],
                               'page': row['page'], 'content': row['content']} for key, row in catalog.items()]}
        content = context_json(context, stage='extract', limit=60000)
        self.observe(state['task_id'], 'extract', 'CONTEXT_BUILT', {'characters': len(content), 'chunkCount': len(catalog)})
        messages = [SystemMessage(content=prompt('extract')), HumanMessage(content=content)]
        for attempt in range(2):
            async def generate(model):
                return await model.with_structured_output(schema, method='function_calling', strict=True).ainvoke(messages)
            draft = await self.invoke(generate, task_id=state['task_id'], stage='extract')
            try:
                payload = resolve_extraction(draft, catalog)
                self.observe(state['task_id'], 'extract', 'EXTRACTION_VALIDATED',
                             {key: len(payload[key]) for key in ('departments', 'processes', 'metrics', 'systems')} | {'repairAttempts': attempt})
                return payload
            except AssessmentReferenceError as exc:
                self.observe(state['task_id'], 'extract', 'EXTRACTION_REFERENCE_ERROR', {'code': exc.code, **exc.details, 'attempt': attempt+1})
                if attempt: raise
                previous = draft.model_dump() if hasattr(draft, 'model_dump') else draft
                messages.append(HumanMessage(content=context_json(
                    {'previous': previous, 'validation_error': {'code': exc.code, **exc.details},
                     'instruction': 'key 중복과 참조를 고치고 sourceId는 제공된 chunk_id만 쓰세요. 문서에 없는 값은 만들지 마세요.'},
                    stage='extract_repair', limit=30000)))

    async def assess(self, state, criteria):
        registry = evidence_catalog(state)
        schema = draft_schema(registry)
        context = assessment_context(state, criteria)
        context['evidence'] = [
            {'evidence_id':key, 'document_id':row['document_id'], 'title':row['title'],
             'doc_type':row['doc_type'], 'section':row['section'], 'content':row['content']}
            for key,row in registry.items()]
        content = context_json(context, stage='assess', limit=28000)
        self.observe(state['task_id'], 'assess', 'CONTEXT_BUILT',
                     {'characters':len(content), 'evidenceCount':len(registry), 'truncated':False})
        messages = [SystemMessage(content=prompt('assess')), HumanMessage(content=content)]
        for attempt in range(2):
            async def generate(model):
                return await model.with_structured_output(schema, method='function_calling', strict=True).ainvoke(messages)
            draft = await self.invoke(generate, task_id=state['task_id'], stage='assess')
            try:
                result = resolve_draft(draft, registry, criteria)
                self.observe(state['task_id'],'assess','ASSESSMENT_VALIDATED',
                             {'areas':sorted(result['scores']), 'evidenceCount':len(result['evidence']),
                              'insufficientAreas':result['insufficient_data'], 'repairAttempts':attempt})
                return result
            except AssessmentReferenceError as exc:
                self.observe(state['task_id'],'assess','ASSESSMENT_REFERENCE_ERROR',
                             {'code':exc.code, **exc.details, 'attempt':attempt+1})
                if attempt: raise
                # Repair references/area coverage once. Never retry a genuine lack
                # of information or synthesize a missing score to force success.
                previous = draft.model_dump() if hasattr(draft,'model_dump') else draft
                messages.append(HumanMessage(content=context_json(
                    {'previous':previous, 'validation_error':{'code':exc.code,**exc.details},
                     'instruction':'근거 ID와 영역 연결을 제공 목록으로 보정하세요. 정보가 부족하면 score=null과 missing_reason을 반환하세요.'},
                    stage='assess_repair',limit=10000)))

    async def discover(self, state):
        choices,evidence = candidate_catalog(state)
        schema = discovery_schema(choices,evidence)
        context = discovery_context(state, self.settings.mode)
        context['candidate_catalog'] = choices
        context['business_evidence'] = [
            {'evidence_id':key, 'document_id':row['document_id'], 'section':row['section'], 'content':row['content']}
            for key,row in evidence.items()]
        content = context_json(context, stage='discover', limit=28000)
        self.observe(state['task_id'], 'discover', 'CONTEXT_BUILT',
                     {'characters':len(content), 'evidenceCount':len(evidence), 'truncated':False})
        messages = [SystemMessage(content=prompt('discover')),HumanMessage(content=content)]
        for attempt in range(2):
            async def generate(model):
                return await model.with_structured_output(schema,method='function_calling',strict=True).ainvoke(messages)
            draft = await self.invoke(generate,task_id=state['task_id'],stage='discover')
            try:
                candidates = resolve_candidates(draft,choices,evidence)
                self.observe(state['task_id'],'discover','CANDIDATES_PROPOSED',{'candidates':candidates})
                return candidates
            except AssessmentReferenceError as exc:
                self.observe(state['task_id'],'discover','CANDIDATE_REFERENCE_ERROR',
                             {'code':exc.code,**exc.details,'attempt':attempt+1})
                if attempt:raise
                previous=draft.model_dump() if hasattr(draft,'model_dump') else draft
                messages.append(HumanMessage(content=context_json(
                    {'previous':previous,'validation_error':{'code':exc.code,**exc.details},
                     'instruction':'제공된 candidate_catalog를 각각 한 번씩 포함하고 각 후보의 허용된 근거 ID만 사용하세요.'},
                    stage='discover_repair',limit=10000)))

    async def respond(self, state):
        context = {**response_context(state), 'mode':self.settings.mode}
        content = context_json(context, stage='respond', limit=24000)
        async def generate(model):
            return await model.with_structured_output(Narrative, method='function_calling', strict=True).ainvoke([
                SystemMessage(content=prompt('respond')), HumanMessage(content=content)])
        return (await self.invoke(generate, task_id=state['task_id'], stage='respond')).model_dump()

class MockReasoner:
    def __init__(self, settings=None):
        from .config import Settings
        self.settings = settings or Settings(mode='mock')

    async def collect(self, state, gateway):
        names = sorted(READS)
        async def read(name):
            return await gateway.tool(state['task_id'],'collect',name,{} if name=='get_solution_catalog' else {'company_id':state['company_id']})
        return dict(zip(names, await ordered_map(read, names, self.settings.read_concurrency)))

    async def extract(self, state, chunks):
        # 문서 제목마다 업무 하나. 수치는 만들지 않으므로 metrics는 비운다 (사용자가 확정 화면에서 입력).
        catalog = chunk_catalog(chunks, state['document_ids'])
        first = {}
        for key, row in catalog.items(): first.setdefault(row['document_id'], (key, row))
        processes = [{'key': f'p{i+1}', 'departmentKey': 'd1', 'name': ('MOCK ' + row['title'])[:100], 'purpose': row['content'][:200],
                      'workType': 'OTHER', 'steps': [], 'standardizationLevel': None, 'requiresApproval': False, 'exceptionRules': None, 'sourceId': key}
                     for i, (key, row) in enumerate(list(first.values())[:3])]
        draft = {'company': {'industry': None, 'employeeCount': None}, 'departments': [{'key': 'd1', 'name': '전사'}],
                 'processes': processes, 'metrics': [], 'systems': []}
        return resolve_extraction(draft, catalog)

    async def assess(self, state, criteria):
        import sqlite3
        with sqlite3.connect(f'file:{self.settings.data_dir}/ax_navigator_demo_approved.sqlite?mode=ro',uri=True) as db:
            db.row_factory=sqlite3.Row
            row=dict(db.execute('SELECT * FROM ax_assessments WHERE assessment_id=701').fetchone())
        evidence=[]
        missing=[]
        types={'data_score':'DATA_QUALITY','infra_score':'SYSTEM_SPEC','automation_score':'PROJECT_REPORT',
               'ai_capability_score':'AI_STATUS','governance_score':'POLICY'}
        for area,typ in types.items():
            found=next((r for r in state['evidence'] if r['doc_type']==typ),None) or next((r for r in state['evidence'] if r['doc_type']=='UPLOADED'),None)
            if not found: missing.append(area);continue
            evidence.append({'area':area,'document_id':found['document_id'],'section':found['section'],
                             'summary':'MOCK 가상 전문가 영역 점수. '+found['content'][:200]})
        return {'scores':{k:row[k] for k in criteria['weights'] if k not in missing},'evidence':evidence,'insufficient_data':missing}

    async def discover(self, state):
        choices,evidence = candidate_catalog(state)
        return [{'process_id':c['process_id'],'solution_id':c['solution_id'],
                 'reason':'MOCK: Spring 후보·문서 연결 검증용. 실제 LLM 추천이 아님.',
                 'document_ids':list(dict.fromkeys(evidence[k]['document_id'] for k in c['evidence_ids']))}
                for c in choices.values()]

    async def respond(self, state):
        return {'summary':'MOCK: 가정 데이터의 AX점수와 예산·선행 조건에 맞춘 로드맵 초안입니다.',
                'recommendations':[{'process_id':item['process_id'],'solution_id':item['solution_id'], 'reason':item['rationale'],
                                    'document_ids':list(dict.fromkeys(e['document_id'] for e in item['evidence']))}
                                   for item in state['roadmap']['items']]}
