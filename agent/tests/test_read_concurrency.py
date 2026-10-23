import asyncio
from uuid import uuid4

import pytest
from agent.app.clients import READS
from agent.app.config import Settings
from agent.app.concurrency import ordered_map
from agent.app.graph import build_nodes, build_graph
from agent.app.mock import MockGateway
from agent.app.reasoning import Reasoner, MockReasoner
from agent.tests.test_agent import settings
from langgraph.checkpoint.memory import InMemorySaver


@pytest.mark.asyncio
async def test_order_limit_and_overlap():
    active = peak = 0
    async def read(index):
        nonlocal active, peak
        active += 1
        peak = max(active, peak)
        await asyncio.sleep((5-index)*.005)
        active -= 1
        return index
    assert await ordered_map(read, range(5), 2) == list(range(5))
    assert peak == 2 and active == 0


@pytest.mark.asyncio
async def test_failure_cancels_and_drains_siblings():
    started = asyncio.Event()
    stopped = asyncio.Event()
    async def read(index):
        if index == 0:
            await started.wait()
            raise ValueError('read failed')
        started.set()
        try:
            await asyncio.sleep(30)
        finally:
            stopped.set()
    with pytest.raises(ValueError, match='read failed'):
        await ordered_map(read, [0, 1], 2)
    assert stopped.is_set()


@pytest.mark.asyncio
async def test_llm_collect_parallel_dedup_cache_and_message_order():
    from langchain_core.messages import AIMessage, ToolMessage
    cfg = settings()
    cfg.read_concurrency = 3
    gateway = MockGateway(cfg)
    active = peak = 0
    original = gateway.tool
    async def tool(*args):
        nonlocal active, peak
        active += 1; peak = max(peak, active)
        try:
            await asyncio.sleep(.005)
            return await original(*args)
        finally:
            active -= 1
    gateway.tool = tool
    names = sorted(READS)
    calls = [{'id':str(i),'name':n,'args':{} if n=='get_solution_catalog' else {'company_id':1},'type':'tool_call'}
             for i,n in enumerate(names[:-1])]
    calls.append({**calls[0],'id':'duplicate'})
    second = [{**calls[0],'id':'cached'},
              {'id':'last','name':names[-1],'args':{'company_id':1},'type':'tool_call'}]
    seen = []
    class Model:
        def bind_tools(self,*args,**kwargs): return self
        async def ainvoke(self,messages):
            seen.append(list(messages))
            return AIMessage(content='',tool_calls=calls if len(seen)==1 else second)
    reasoner = Reasoner(cfg)
    async def invoke(method,**kwargs): return await method(Model())
    reasoner.invoke = invoke
    result = await reasoner.collect({'task_id':'test','company_id':1,'request':'추천'},gateway)
    assert set(result)==READS
    assert len(gateway.calls)==7 and peak==3
    assert [m.tool_call_id for m in seen[1] if isinstance(m,ToolMessage)]==[c['id'] for c in calls]


@pytest.mark.asyncio
async def test_sequential_and_parallel_graph_results_equal():
    outputs=[]
    for concurrency in [1,3]:
        cfg=settings(); cfg.read_concurrency=concurrency
        gateway=MockGateway(cfg)
        original=gateway.tool
        async def delayed(*args):
            await asyncio.sleep(.001)
            return await original(*args)
        gateway.tool=delayed
        graph=build_graph(gateway,MockReasoner(cfg),InMemorySaver(),cfg)
        result=await graph.ainvoke({'task_id':str(uuid4()),'company_id':1,'user_id':602,
                                  'request':'예산 3억 원 과제 추천'},
                                 {'configurable':{'thread_id':str(uuid4())}})
        outputs.append({k:result[k] for k in ['company','processes','metrics','solution_candidates','evidence',
                                             'candidates','portfolio','roadmap','answer']})
    assert outputs[0]==outputs[1]


@pytest.mark.parametrize('limit',[0,9])
def test_invalid_concurrency_rejected(limit):
    with pytest.raises(ValueError,match='CONCURRENCY'):
        Settings(read_concurrency=limit)
