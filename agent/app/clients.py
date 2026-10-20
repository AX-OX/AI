"""MCP 세션·Spring 콜백. 업무 SQL 및 실제 ROI 계산은 이 모듈에 두지 않는다."""
import asyncio
import json
import re
from datetime import datetime, timezone
import httpx
from .trace import PublicTrace
from fastmcp import Client
from fastmcp.client.transports import StreamableHttpTransport

READS = {'get_company_profile', 'get_business_processes', 'get_operational_metrics',
         'get_system_inventory', 'get_project_budget', 'get_solution_catalog'}
WRITES = {'save_assessment', 'create_ax_roadmap', 'create_ax_project', 'update_project_status'}


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
                   'node': node, 'data': mask(data or {})}
        await self._spring('POST', f'/tasks/{task_id}/events', payload)

    async def status(self, task_id, status, **values):
        await self._spring('PATCH', f'/tasks/{task_id}', {'status': status, **mask(values)})

    async def _spring(self, method, path, body):
        async with httpx.AsyncClient(timeout=15) as client:
            response = await client.request(method, self.settings.spring_url.rstrip('/') + path,
                json=body, headers={'X-Internal-Token': self.settings.internal_token})
            response.raise_for_status()

    async def tool(self, task_id, node, name, args):
        await self.event(task_id, 'TOOL_START', node, {'tool': name, 'label': name})
        self.observe(task_id, node, 'TOOL_CALL', {'tool': name, 'arguments': args})
        try:
            url = self.settings.rag_url if name == 'search_docs' else self.settings.business_url
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
        except Exception:
            await self.event(task_id, 'TOOL_END', node, {'tool': name, 'label': name, 'ok': False})
            raise


def decode_tool_result(result):
    """FastMCP의 동적 Python 변환 대신 원본 JSON을 보존한다."""
    value = result.structured_content
    if value is not None:
        return value['result'] if set(value) == {'result'} else value
    texts = [c.text for c in result.content if hasattr(c, 'text')]
    return json.loads(''.join(texts))
