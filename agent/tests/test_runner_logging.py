import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from agent.app.runner import TaskRunner
from agent.app.trace import PublicTrace
from agent.app.narrative_refs import NarrativeReferenceError


@pytest.mark.asyncio
async def test_unknown_failure_logs_location_without_exception_secrets(caplog):
    graph = SimpleNamespace(ainvoke=AsyncMock(side_effect=ValueError('postgresql://user:private-password@db/private')),
                            aupdate_state=AsyncMock())
    gateway = SimpleNamespace(status=AsyncMock(), event=AsyncMock(), public_trace=PublicTrace())
    runner = TaskRunner(graph, gateway, SimpleNamespace(mode='mock', task_timeout_seconds=None, timeout=5))

    await runner.execute('task-1', {})

    log = next(json.loads(r.getMessage()) for r in caplog.records if r.name == 'agent.app.runner')
    assert log['severity'] == 'ERROR'
    assert log['code'] == 'TASK_FAILED'
    assert log['node'] is None
    assert log['error'] == 'ValueError'
    assert log['location']['line'] > 0
    assert 'private-password' not in caplog.text
    assert 'postgresql://' not in caplog.text
    assert gateway.status.call_args.args == ('task-1', 'FAILED')


@pytest.mark.asyncio
async def test_narrative_failure_preserves_code_in_task_log(caplog):
    graph = SimpleNamespace(ainvoke=AsyncMock(side_effect=NarrativeReferenceError('NARRATIVE_REFERENCE_MISMATCH')),
                            aupdate_state=AsyncMock())
    gateway = SimpleNamespace(status=AsyncMock(), event=AsyncMock(), public_trace=PublicTrace())
    runner = TaskRunner(graph, gateway, SimpleNamespace(mode='mock', task_timeout_seconds=None, timeout=5))
    await runner.execute('task-narrative', {})
    record = next(json.loads(r.getMessage()) for r in caplog.records if r.name == 'agent.app.runner')
    assert record['code'] == 'NARRATIVE_REFERENCE_MISMATCH'
