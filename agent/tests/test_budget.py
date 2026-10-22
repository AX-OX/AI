"""Optional budget: extracted from the request, stored on the Spring task, passed to the portfolio."""
from uuid import uuid4

import pytest
from langgraph.checkpoint.memory import InMemorySaver
from agent.app.budget import request_budget
from agent.app.graph import build_graph
from agent.app.mock import MockGateway
from agent.app.reasoning import MockReasoner
from agent.tests.test_agent import settings


@pytest.mark.parametrize('text,expected', [
    ('AI 도입 효과가 높은 과제 3개를 선정하고, 예산 3억 원 내에서 최적의 AX 투자 로드맵을 만들어 줘.', 300_000_000),
    ('3억 원 내 3개 추천', 300_000_000),
    ('예산 1.5억으로 추천', 150_000_000),
    ('2억 5천만 원 이내', 250_000_000),
    ('3억 5000만 원 이내', 350_000_000),
    ('예산은 5,000만 원', 50_000_000),
    ('300,000,000원 한도에서', 300_000_000),
    ('우리 회사의 AX 성숙도를 진단하고 근거 문서를 보여 줘.', None),
    ('개발팀에서 자동화 효과가 가장 큰 업무는 뭐야?', None),
    ('인건비가 시간당 3만 원인 업무 중 추천', None),
])
def test_request_budget(text, expected):
    assert request_budget(text) == expected


async def run(request):
    cfg = settings()
    gateway = MockGateway(cfg)
    graph = build_graph(gateway, MockReasoner(cfg), InMemorySaver(), cfg)
    task_id = str(uuid4())
    state = await graph.ainvoke({'task_id': task_id, 'company_id': 1, 'user_id': 602, 'request': request, 'retry_count': 0},
                                {'configurable': {'thread_id': task_id}})
    return gateway, state, task_id


@pytest.mark.asyncio
async def test_budget_is_saved_on_task_and_sent_to_portfolio():
    gateway, state, task_id = await run('예산 3억 원 내에서 과제 3개 추천')
    assert {'method': 'PATCH', 'path': f'/tasks/{task_id}', 'body': {'budgetKrw': 300_000_000}} in gateway.events
    portfolio_args = next(args for name, args in gateway.calls if name == 'optimize_ax_portfolio')
    assert portfolio_args['budget_krw'] == 300_000_000
    assert state['portfolio']['remainingBudgetKrw'] == 300_000_000 - state['portfolio']['totalFirstYearTcoKrw']
    assert '잔여 예산' in state['answer']


@pytest.mark.asyncio
async def test_request_without_budget_has_no_budget_constraint():
    gateway, state, task_id = await run('과제 3개 추천')
    assert not any(e['body'].get('budgetKrw') for e in gateway.events if e['method'] == 'PATCH')
    portfolio_args = next(args for name, args in gateway.calls if name == 'optimize_ax_portfolio')
    assert portfolio_args['budget_krw'] is None
    assert state['portfolio']['budgetKrw'] is None and state['roadmap']['budgetKrw'] is None
    assert '예산 제약 없이' in state['answer']


@pytest.mark.asyncio
async def test_spring_budget_values_must_match_request():
    cfg = settings()

    class Leaky(MockGateway):
        def _call(self, task_id, name, args):
            value = super()._call(task_id, name, args)
            if name == 'optimize_ax_portfolio': value['budgetKrw'] = 300_000_000
            return value
    graph = build_graph(Leaky(cfg), MockReasoner(cfg), InMemorySaver(), cfg)
    with pytest.raises(ValueError, match='예산 없는 요청'):
        await graph.ainvoke({'task_id': str(uuid4()), 'company_id': 1, 'user_id': 602, 'request': '추천', 'retry_count': 0},
                            {'configurable': {'thread_id': str(uuid4())}})
