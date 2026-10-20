"""LLM 출력은 후보·근거로 제한한다. 비용과 절감률은 도구 결과로만 사용한다."""
import asyncio
import json
from pathlib import Path
from langchain_core.messages import HumanMessage, SystemMessage, ToolMessage
from langchain_core.tools import StructuredTool
from langchain_openai import ChatOpenAI
from .clients import READS, mask
from .schemas import Discovery, Assessment, Narrative

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
                    self.observe(task_id, stage, 'LLM_ERROR', {'model':name, 'errorType':type(exc).__name__, 'httpStatus':getattr(exc, 'status_code', None)})
                    if getattr(exc, 'status_code', None) not in {429, 503}: break
                    await asyncio.sleep(0.5 * 2**attempt)
        raise RuntimeError('LLM 호출 실패') from last

    async def collect(self, state, gateway):
        results = {}
        counts = {}
        tools = []
        for name in sorted(READS):
            async def execute(company_id: int | None = None, department_id: int | None = None, _name=name):
                counts[_name] = counts.get(_name, 0) + 1
                if counts[_name] > 3:
                    self.observe(state['task_id'],'collect','TOOL_REJECTED',{'tool':_name,'reason':'같은 도구는 최대 3회'})
                    return '오류: 같은 도구는 최대 3회입니다.'
                if company_id is not None and company_id != state['company_id']: return '오류: 작업의 회사 ID를 사용하세요.'
                if department_id is not None: return '오류: collect 단계에서는 department_id 없이 회사 전체를 조회하세요.'
                args = {} if _name == 'get_solution_catalog' else {'company_id': state['company_id']}
                if _name in {'get_business_processes', 'get_operational_metrics'} and department_id is not None:
                    args['department_id'] = department_id
                try:
                    value = await gateway.tool(state['task_id'], 'collect', _name, args)
                    results[_name] = value
                    return compact(value, 2000)
                except Exception as exc:
                    return f'도구 오류: {str(exc)[:500]}'
            # 모델에 내부 _name 인자를 노출하지 않도록 명시적 schema 사용
            tools.append(StructuredTool.from_function(coroutine=execute, name=name,
                description=f'{name}: 회사 업무 정보를 조회한다. company_id는 작업 컨텍스트에서 얻는다.',
                args_schema={'type':'object', 'properties':{} if name=='get_solution_catalog' else {'company_id':{'type':'integer'}},
                             'required':[] if name=='get_solution_catalog' else ['company_id'], 'additionalProperties':False}))
        messages = [SystemMessage(content=prompt('collect')), HumanMessage(content=compact({'company_id': state['company_id'], 'request': state['request']}))]
        by_name = {t.name: t for t in tools}
        for _ in range(8):
            async def choose(model): return await model.bind_tools(tools, strict=True).ainvoke(messages)
            response = await self.invoke(choose, task_id=state['task_id'], stage='collect')
            messages.append(response)
            if not response.tool_calls: break
            for call in response.tool_calls:
                self.observe(state['task_id'],'collect','LLM_TOOL_CALL',{'tool':call['name'],'arguments':call['args']})
                tool = by_name.get(call['name'])
                result = await tool.ainvoke(call['args']) if tool else '허용되지 않은 도구'
                messages.append(ToolMessage(content=str(result), tool_call_id=call['id']))
            if READS <= results.keys(): break
        if not READS <= results.keys():
            raise ValueError(f'필수 조회 도구 결과 부족: {sorted(READS - results.keys())}')
        return results

    async def assess(self, state, criteria):
        context = {'criteria':criteria, 'evidence':state['evidence'],
                   'processes':state['processes'], 'systems':state['systems'], 'metrics':state['metrics']}
        async def generate(model):
            return await model.with_structured_output(Assessment, method='function_calling', strict=False).ainvoke([
                SystemMessage(content=prompt('assess')),HumanMessage(content=compact(context,28000))])
        return (await self.invoke(generate, task_id=state['task_id'], stage='assess')).model_dump()

    async def discover(self, state):
        # 긴 절차·카탈로그가 실제 문서 근거를 컨텍스트 밖으로 밀어내지 않게 요약한다.
        process_fields = ('process_id', 'department_id', 'process_name', 'purpose', 'standardization_level', 'requires_approval', 'exception_rules')
        solution_fields = ('solution_id', 'target_process_id', 'depends_on_solution_id', 'solution_name', 'solution_type', 'description', 'min_standardization_level', 'requires_api')
        context = {
            'request': state['request'],
            'evaluation_policy': state.get('evaluation_policy', {}),
            'evidence': [{**{k: r.get(k) for k in ('document_id','title','section')}, 'content': r['content'][:400]} for r in state['evidence']],
            'processes': [{k: str(p[k])[:350] if isinstance(p.get(k),str) else p.get(k) for k in process_fields} for p in state['processes'][:12]],
            'solutions': [{k: str(s[k])[:250] if isinstance(s.get(k),str) else s.get(k) for k in solution_fields} for s in state['solutions'][:20]],
            'scope': state.get('scope'),
            'execution_mode': self.settings.mode, 'previous_portfolio': state.get('portfolio'),
            'previous': state.get('candidates', []), 'retry': state.get('retry_count', 0)
        }
        async def generate(model):
            return await model.with_structured_output(Discovery, method='function_calling', strict=False).ainvoke([
                SystemMessage(content=prompt('discover')), HumanMessage(content=compact(context, 24000))])
        candidates=[c.model_dump() for c in (await self.invoke(generate, task_id=state['task_id'], stage='discover')).candidates]
        self.observe(state['task_id'],'discover','CANDIDATES_PROPOSED',{'candidates':candidates})
        return candidates

    async def respond(self, state):
        context = {'request':state['request'], 'mode':self.settings.mode,
                   'portfolio':state['portfolio'], 'roadmap':state['roadmap'],
                   'selected_processes':[{k:p[k] for k in ('process_id','process_name','purpose','requires_approval','exception_rules')}
                                         for p in state['processes'] if int(p['process_id']) in {c['processId'] for c in state['portfolio']['selected']}],
                   'evidence':[{'document_id':r['document_id'], 'section':r['section'], 'content':r['content'][:300]} for r in state['evidence']]}
        async def generate(model):
            return await model.with_structured_output(Narrative, method='function_calling', strict=False).ainvoke([
                SystemMessage(content=prompt('respond')), HumanMessage(content=compact(context, 24000))])
        return (await self.invoke(generate, task_id=state['task_id'], stage='respond')).model_dump()

class MockReasoner:
    def __init__(self, settings=None):
        from .config import Settings
        self.settings = settings or Settings(mode='mock')

    async def collect(self, state, gateway):
        return {name: await gateway.tool(state['task_id'],'collect',name,{} if name=='get_solution_catalog' else {'company_id':state['company_id']}) for name in sorted(READS)}

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
            found=next((r for r in state['evidence'] if r['doc_type']==typ),None)
            if not found: missing.append(area);continue
            evidence.append({'area':area,'document_id':found['document_id'],'section':found['section'],
                             'summary':'MOCK 가상 전문가 영역 점수. '+found['content'][:200]})
        return {'scores':{k:row[k] for k in criteria['weights'] if k not in missing},'evidence':evidence,'insufficient_data':missing}

    async def discover(self, state):
        excluded={e['process_id'] for e in state['evaluation_policy']['exclusions']}
        candidates=[]
        for solution in state['solutions']:
            pid,sid=int(solution['target_process_id']),int(solution['solution_id'])
            if pid in excluded: continue
            docs=[r['document_id'] for r in state['evidence'] if str(pid) in r['section']]
            if not docs: continue
            candidates.append({'process_id':pid,'solution_id':sid,'reason':'MOCK: v3 카탈로그·문서 연결 검증용 후보. 실제 추천이 아님.',
                               'document_ids':list(dict.fromkeys(docs))})
        return candidates

    async def respond(self, state):
        return {'summary':'MOCK: 가정 데이터의 AX점수와 예산·선행 조건에 맞춘 로드맵 초안입니다.',
                'recommendations':[{'solution_id':item['solution_id'], 'reason':item['rationale'],
                                    'document_ids':list(dict.fromkeys(e['document_id'] for e in item['evidence']))}
                                   for item in state['roadmap']['items']]}
