"""Teammate TaskRunner layout with real nodes, checkpoint guards and Spring callbacks."""
import asyncio
import json
import logging
import os
import re
import traceback
from uuid import uuid4
from time import perf_counter
import httpx
from fastapi import HTTPException
from langgraph.types import Command
from .graph import task_result, approval_payload
from .tool_errors import MESSAGES
from .narrative_refs import NarrativeReferenceError

logger = logging.getLogger(__name__)

def pending_kind(snapshot):
    """현재 멈춘 interrupt 종류. 기업 데이터 확정 대기면 CONFIRMATION, 로드맵 승인 대기면 APPROVAL."""
    for task in snapshot.tasks:
        for item in task.interrupts:
            return 'CONFIRMATION' if isinstance(item.value, dict) and item.value.get('kind') == 'CONFIRMATION' else 'APPROVAL'
    return None


def interrupt_kind(result):
    items = result.get('__interrupt__') or []
    value = items[0].value if items else None
    return 'CONFIRMATION' if isinstance(value, dict) and value.get('kind') == 'CONFIRMATION' else 'APPROVAL'


class TaskRunner:
    def __init__(self, graph, gateway, settings):
        self.graph, self.gateway, self.settings = graph, gateway, settings
        self.jobs = {}
        self.guard = asyncio.Lock()

    @staticmethod
    def _cfg(task_id):
        return {'configurable': {'thread_id': str(task_id)}, 'recursion_limit': 40,
                'run_name': 'ax-navigator', 'metadata': {'task_id': str(task_id)}}

    async def execute(self, task_id, payload, *, durable=False, publish_only=None):
        graph, client = self.graph, self.gateway
        metrics = getattr(client, 'metrics', None)
        started, outcome = perf_counter(), 'FAILED'
        if metrics:
            metrics.active.inc()
        cfg = self._cfg(task_id)
        cfg['run_id'] = uuid4()
        cfg['metadata']['mode'] = self.settings.mode
        trace_url = None
        if os.getenv('LANGSMITH_TRACING', '').lower() == 'true' and os.getenv('LANGSMITH_API_KEY'):
            try:
                from langsmith import Client as TraceClient
                trace_url = TraceClient().get_run_url(run_id=cfg['run_id'], project_name=os.getenv('LANGSMITH_PROJECT', 'ax-navigator'))
            except Exception:
                logger.warning('LangSmith URL unavailable task_id=%s', task_id)
        try:
            rejecting = isinstance(payload, Command) and isinstance(payload.resume, dict) and payload.resume.get('decision') == 'REJECT'
            if not rejecting and publish_only is None:
                await client.status(task_id, 'RUNNING', trace_url=trace_url)
            if publish_only is not None:
                result = publish_only
            else:
                async with asyncio.timeout(self.settings.task_timeout_seconds or self.settings.timeout):
                    kwargs = {'durability': 'sync'} if durable else {}
                    result = await graph.ainvoke(payload, config=cfg, **kwargs)
            if result.get('errors'):
                raise ValueError('; '.join(result['errors']))
            if result.get('__interrupt__') and interrupt_kind(result) == 'CONFIRMATION':
                outcome = 'WAITING_CONFIRMATION'
                # Spring은 draft가 저장된 작업만 WAITING_CONFIRMATION으로 바꾼다. 상태 전환은 이벤트로 한다.
                await client.event(task_id, 'CONFIRMATION_REQUIRED', 'confirmation', {'draftId': result['extraction']['draft_id']})
            elif result.get('__interrupt__'):
                outcome = 'WAITING_APPROVAL'
                await client.status(task_id, 'WAITING_APPROVAL', result=task_result(result, self.settings.mode))
                # Existing FE renders natural language only from TOKEN events.
                # Send the verified complete answer once; do not expose raw LLM output.
                if result.get('answer'):
                    await client.event(task_id, 'TOKEN', 'roadmap', {'text': task_result(result, self.settings.mode)['answer']})
                await client.event(task_id, 'APPROVAL_REQUIRED', 'approval', approval_payload(result))
            elif result['status'] == 'REJECTED':
                outcome = 'REJECTED'
                await client.status(task_id, 'REJECTED')
            else:
                body = task_result(result, self.settings.mode)
                await client.status(task_id, 'DONE', result=body)
                await client.event(task_id, 'DONE', 'register', {'result': body})
                outcome = 'DONE'
        except asyncio.CancelledError:
            outcome = 'CANCELLED'
            # 프로세스 종료 시 마지막 완료 노드 체크포인트는 보존한다.
            raise
        except Exception as exc:
            outcome = 'FAILED'
            if durable:
                raise
            failures=[e for e in client.public_trace.get(task_id) if e['type']=='NODE_ERROR']
            detail=failures[-1]['data'].get('message','') if failures else ''
            # Cloud Logging은 JSON severity를 인식한다. 원문 예외·프롬프트·자격증명은 남기지 않는다.
            codes = re.findall(r'\b[A-Z][A-Z_]+\b', detail)
            code = next((c for c in codes if c in MESSAGES or c == 'INSUFFICIENT_DATA'), 'TASK_FAILED')
            if isinstance(exc, NarrativeReferenceError): code = exc.code
            if isinstance(exc, TimeoutError): code = 'TASK_TIMEOUT'
            if isinstance(exc, httpx.HTTPStatusError): code = 'SPRING_HTTP_ERROR'
            record = {'severity': 'ERROR', 'message': 'Agent task failed', 'task_id': task_id,
                      'node': failures[-1]['node'] if failures else None,
                      'code': code, 'error': type(exc).__name__}
            frames = traceback.extract_tb(exc.__traceback__)
            if frames:
                frame = frames[-1]
                record['location'] = {'file': os.path.basename(frame.filename),
                                      'function': frame.name, 'line': frame.lineno}
            logger.error(json.dumps(record, ensure_ascii=False))
            if isinstance(exc, httpx.HTTPStatusError):
                detail = f'Spring HTTP {exc.response.status_code}: {exc.request.method} {exc.request.url.path}'
            message = f'작업 실패: {type(exc).__name__}. {detail or "내부 로그와 연동 상태를 확인하세요."}'
            try:
                await graph.aupdate_state(cfg, {'status': 'FAILED', 'errors': [message]})
                await client.status(task_id, 'FAILED', error_message=message)
                await client.event(task_id, 'FAILED', data={'message': message})
            except Exception:
                logger.exception('Failure callback failed task_id=%s', task_id)
        finally:
            if metrics:
                metrics.active.dec()
                metrics.executions.labels(outcome).inc()
                metrics.execution_time.observe(perf_counter() - started)
            self.jobs.pop(task_id, None)

    async def start(self, task_id, request):
        key = str(task_id)
        async with self.guard:
            snapshot = await self.graph.aget_state(self._cfg(key))
            if key in self.jobs or snapshot.values: raise HTTPException(409, '이미 존재하는 작업입니다.')
            if len(self.jobs) >= 8: raise HTTPException(503, '동시 실행 한도 초과')
            initial = {'task_id': key, 'company_id': request.companyId, 'user_id': request.userId,
                       'request': request.requestText, 'messages': [], 'retry_count': 0, 'errors': [], 'status': 'QUEUED',
                       'company_data_confirmed': request.companyDataConfirmed, 'document_ids': request.documentIds}
            # 첫 노드 실행 전에도 중복 작업/소유권을 조회할 수 있게 저장한다.
            await self.graph.aupdate_state(self._cfg(key), initial, as_node='__start__')
            self.jobs[key] = asyncio.create_task(self.execute(key, None))
        return {'taskId': key, 'status': 'QUEUED', 'mode': self.settings.mode}

    async def resume(self, task_id, request):
        return await self._continue(task_id, request.userId, 'APPROVAL', request.model_dump())

    async def confirm(self, task_id, request):
        return await self._continue(task_id, request.userId, 'CONFIRMATION', {'kind': 'CONFIRMATION', 'userId': request.userId})

    async def _continue(self, task_id, user_id, kind, value):
        key = str(task_id)
        async with self.guard:
            snapshot = await self.graph.aget_state(self._cfg(key))
            if not snapshot.values: raise HTTPException(404, '작업이 없습니다.')
            if snapshot.values['user_id'] != user_id: raise HTTPException(403, '작업 요청자만 재개할 수 있습니다.')
            # Spring can resume immediately after observing WAITING while the
            # previous turn is still sending its final notification. Finish that
            # turn before starting a new one; never cancel it or skip the interrupt.
            previous = self.jobs.get(key)
            if previous and pending_kind(snapshot) == kind:
                await asyncio.wait({previous}, timeout=5)
                snapshot = await self.graph.aget_state(self._cfg(key))
            waiting = '기업 데이터 확정' if kind == 'CONFIRMATION' else '승인'
            if key in self.jobs or pending_kind(snapshot) != kind or snapshot.values.get('status') in {'FAILED', 'DONE', 'REJECTED'}:
                raise HTTPException(409, f'{waiting} 대기 중인 작업만 재개할 수 있습니다.')
            if len(self.jobs) >= 8: raise HTTPException(503, '동시 실행 한도 초과')
            self.jobs[key] = asyncio.create_task(self.execute(key, Command(resume=value)))
        return {'taskId': key, 'status': 'RUNNING'}

    async def close(self):
        jobs = list(self.jobs.values())
        for job in jobs:
            job.cancel()
        await asyncio.gather(*jobs, return_exceptions=True)
