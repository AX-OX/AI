"""Teammate TaskRunner layout with real nodes, checkpoint guards and Spring callbacks."""
import asyncio
import logging
import os
from uuid import uuid4
import httpx
from fastapi import HTTPException
from langgraph.types import Command
from .graph import task_result, approval_payload

logger = logging.getLogger(__name__)

class TaskRunner:
    def __init__(self, graph, gateway, settings):
        self.graph, self.gateway, self.settings = graph, gateway, settings
        self.jobs = {}
        self.guard = asyncio.Lock()

    @staticmethod
    def _cfg(task_id):
        return {'configurable': {'thread_id': str(task_id)}, 'recursion_limit': 40,
                'run_name': 'ax-navigator', 'metadata': {'task_id': str(task_id)}}

    async def execute(self, task_id, payload):
        graph, client = self.graph, self.gateway
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
            if not rejecting:
                await client.status(task_id, 'RUNNING', trace_url=trace_url)
            async with asyncio.timeout(self.settings.task_timeout_seconds or self.settings.timeout):
                result = await graph.ainvoke(payload, config=cfg)
            if result.get('errors'):
                raise ValueError('; '.join(result['errors']))
            if result.get('__interrupt__'):
                await client.status(task_id, 'WAITING_APPROVAL', result=task_result(result, self.settings.mode))
                # Existing FE renders natural language only from TOKEN events.
                # Send the verified complete answer once; do not expose raw LLM output.
                if result.get('answer'):
                    await client.event(task_id, 'TOKEN', 'roadmap', {'text': task_result(result, self.settings.mode)['answer']})
                await client.event(task_id, 'APPROVAL_REQUIRED', 'approval', approval_payload(result))
            elif result['status'] == 'REJECTED':
                await client.status(task_id, 'REJECTED')
            else:
                body = task_result(result, self.settings.mode)
                await client.status(task_id, 'DONE', result=body)
                await client.event(task_id, 'DONE', 'register', {'result': body})
        except asyncio.CancelledError:
            # 프로세스 종료 시 마지막 완료 노드 체크포인트는 보존한다.
            raise
        except Exception as exc:
            logger.error('Agent task failed task_id=%s error=%s', task_id, type(exc).__name__)
            failures=[e for e in client.public_trace.get(task_id) if e['type']=='NODE_ERROR']
            detail=failures[-1]['data'].get('message','') if failures else ''
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
            self.jobs.pop(task_id, None)

    async def start(self, task_id, request):
        key = str(task_id)
        if request.companyId != self.settings.company_id: raise HTTPException(403, '지원하는 회사 범위를 벗어났습니다.')
        async with self.guard:
            snapshot = await self.graph.aget_state(self._cfg(key))
            if key in self.jobs or snapshot.values: raise HTTPException(409, '이미 존재하는 작업입니다.')
            if len(self.jobs) >= 8: raise HTTPException(503, '동시 실행 한도 초과')
            initial = {'task_id': key, 'company_id': request.companyId, 'user_id': request.userId,
                       'request': request.requestText, 'messages': [], 'retry_count': 0, 'errors': [], 'status': 'QUEUED'}
            # 첫 노드 실행 전에도 중복 작업/소유권을 조회할 수 있게 저장한다.
            await self.graph.aupdate_state(self._cfg(key), initial, as_node='__start__')
            self.jobs[key] = asyncio.create_task(self.execute(key, None))
        return {'taskId': key, 'status': 'QUEUED', 'mode': self.settings.mode}

    async def resume(self, task_id, request):
        key = str(task_id)
        async with self.guard:
            snapshot = await self.graph.aget_state(self._cfg(key))
            if not snapshot.values: raise HTTPException(404, '작업이 없습니다.')
            if snapshot.values['user_id'] != request.userId: raise HTTPException(403, '작업 요청자만 재개할 수 있습니다.')
            interrupted = any(t.interrupts for t in snapshot.tasks)
            if key in self.jobs or not interrupted or snapshot.values.get('status') in {'FAILED', 'DONE', 'REJECTED'}:
                raise HTTPException(409, '승인 대기 중인 작업만 재개할 수 있습니다.')
            if len(self.jobs) >= 8: raise HTTPException(503, '동시 실행 한도 초과')
            self.jobs[key] = asyncio.create_task(self.execute(key, Command(resume=request.model_dump())))
        return {'taskId': key, 'status': 'RUNNING'}

    async def close(self):
        jobs = list(self.jobs.values())
        for job in jobs:
            job.cancel()
        await asyncio.gather(*jobs, return_exceptions=True)
