"""MCP 세션·Spring 콜백. 업무 SQL 및 실제 ROI 계산은 이 모듈에 두지 않는다."""
import asyncio
import json
import re
import logging
from datetime import datetime, timezone
from ..trace import PublicTrace
from fastmcp import Client
from fastmcp.client.transports import StreamableHttpTransport
from .spring import SpringClient
from ..tool_errors import safe_tool_failure

logger = logging.getLogger(__name__)

READS = {'get_company_profile', 'get_business_processes', 'get_operational_metrics',
         'get_system_inventory', 'get_project_budget', 'get_solution_catalog'}
WRITES = {'save_assessment', 'save_extraction', 'create_ax_roadmap', 'create_ax_project', 'update_project_status'}
RAG_TOOLS = {'search_docs', 'get_assessment_evidence', 'get_document_chunks', 'index_document'}
# 배포 점검이 요구하는 최소 도구. 문서 업로드 도구는 업로드 기능을 쓸 때만 필요하다.
RAG_PROBE_TOOLS = {'search_docs', 'get_assessment_evidence'}


def mask(value):
    if isinstance(value, dict): return {k: mask(v) for k, v in value.items()}
    if isinstance(value, list): return [mask(v) for v in value]
    if not isinstance(value, str): return value
    value = re.sub(r'가상담당자[A-Z]', '[NAME]', value)
    value = re.sub(r'[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}', '[EMAIL]', value)
    return re.sub(r'(?<!\d)0\d{1,2}[- ]?\d{3,4}[- ]?\d{4}(?!\d)', '[PHONE]', value)


class Gateway:
    def __init__(self, settings):
        self.settings = settings
        self.events = []
        self.public_trace = PublicTrace()

    def observe(self, task_id, node, type_, data=None):
        self.public_trace.add(task_id, node, type_, mask(data or {}))

    async def event(self, task_id, type_, node='', data=None):
        self.observe(task_id, node, type_, data)
        payload = {'type': type_, 'taskId': task_id, 'ts': datetime.now(timezone.utc).isoformat(),
                   'node': node or 'collect', 'data': mask(data or {})}
        await self._spring('POST', f'/tasks/{task_id}/events', payload)

    async def status(self, task_id, status, **values):
        aliases = {'trace_url': 'traceUrl', 'error_message': 'errorMessage'}
        fields = {aliases.get(k, k): v for k, v in values.items()}
        await self._spring('PATCH', f'/tasks/{task_id}', {'status': status, **mask(fields)})

    async def index_document(self, company_id, document_id, title, pages):
        """업로드 문서를 회사 RAG 색인에 저장한다. 작업(task)이 없으므로 진행 이벤트를 보내지 않는다."""
        args = {'company_id': company_id, 'document_id': document_id, 'title': title, 'pages': pages}
        try:
            async with Client(StreamableHttpTransport(self.settings.rag_url,
                              headers={'X-Internal-Token': self.settings.internal_token})) as client:
                result = await client.call_tool('index_document', args)
            if result.is_error: raise RuntimeError('MCP 도구 오류: index_document')
            return decode_tool_result(result)
        except Exception as exc:
            code, message = safe_tool_failure(exc)
            logger.error('MCP_CALL_FAILED tool=index_document document_id=%s code=%s error=%s', document_id, code, type(exc).__name__)
            raise ValueError(message) from None

    async def document_result(self, document_id, body):
        await self._spring('PATCH', f'/documents/{document_id}', body)

    async def task_budget(self, task_id, budget_krw):
        """요청에서 추출한 예산을 작업에 저장한다. Spring 로드맵 저장이 이 값으로 재계산한다."""
        self.observe(task_id, 'collect', 'TASK_BUDGET', {'budgetKrw': budget_krw})
        await self._spring('PATCH', f'/tasks/{task_id}', {'budgetKrw': budget_krw})

    async def _spring(self, method, path, body):
        async with SpringClient(self.settings) as client:
            await client.request(method, path, body)

    async def check_rag(self):
        """Authenticated, read-only deployment probe; no embeddings or callbacks."""
        try:
            async with Client(StreamableHttpTransport(self.settings.rag_url,
                              headers={'X-Internal-Token': self.settings.internal_token})) as client:
                names = {t.name for t in await client.list_tools()}
                if not RAG_PROBE_TOOLS <= names:
                    return {'status': 'error', 'code': 'RAG_TOOL_MISSING',
                            'missingTools': sorted(RAG_PROBE_TOOLS - names)}
                result = await client.call_tool('get_assessment_evidence', {})
                if result.is_error: raise RuntimeError('RAG_INTERNAL_ERROR')
                rows = decode_tool_result(result)
                if not isinstance(rows, list): raise ValueError('Unexpected result')
                return {'status': 'ok', 'evidenceCount': len(rows)}
        except Exception as exc:
            code, message = safe_tool_failure(exc)
            logger.error('RAG_PROBE_FAILED code=%s error=%s', code, type(exc).__name__)
            return {'status': 'error', 'code': code, 'message': message}

    async def tool(self, task_id, node, name, args):
        await self.event(task_id, 'TOOL_START', node, {'tool': name, 'label': name})
        self.observe(task_id, node, 'TOOL_CALL', {'tool': name, 'arguments': args})
        try:
            url = self.settings.rag_url if name in RAG_TOOLS else self.settings.business_url
            # 같은 쓰기 재실행은 같은 키를 사용한다. Spring이 키별 중복 저장을 차단해야 한다.
            headers = {'X-Internal-Token': self.settings.internal_token}
            if name in WRITES:
                import hashlib
                digest = hashlib.sha256(json.dumps(args, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
                headers['X-Idempotency-Key'] = f'{task_id}:{name}:{digest}'
            attempts = 1 if name in WRITES else 3
            for attempt in range(attempts):
                try:
                    async with Client(StreamableHttpTransport(url, headers=headers)) as client:
                        if name == 'get_assessment_evidence':
                            names = {t.name for t in await client.list_tools()}
                            if name not in names:
                                raise ValueError('RAG_TOOL_MISSING')
                        result = await client.call_tool(name, args)
                    if result.is_error: raise RuntimeError(f'MCP 도구 오류: {name}')
                    value = decode_tool_result(result)
                    break
                except Exception:
                    if attempt == attempts - 1: raise
                    await asyncio.sleep(0.3 * 2**attempt)
            await self.event(task_id, 'TOOL_END', node, {'tool': name, 'label': name, 'ok': True})
            self.observe(task_id, node, 'TOOL_RESULT', {'tool': name, 'resultType': type(value).__name__})
            return mask(value)
        except Exception as exc:
            code, message = safe_tool_failure(exc)
            logger.error('MCP_CALL_FAILED task_id=%s node=%s tool=%s code=%s error=%s',
                         task_id, node, name, code, type(exc).__name__)
            await self.event(task_id, 'TOOL_END', node, {'tool': name, 'label': name, 'ok': False})
            raise ValueError(message) from None


def decode_tool_result(result):
    """FastMCP의 동적 Python 변환 대신 원본 JSON을 보존한다."""
    value = result.structured_content
    if value is not None:
        return value['result'] if set(value) == {'result'} else value
    texts = [c.text for c in result.content if hasattr(c, 'text')]
    return json.loads(''.join(texts))
