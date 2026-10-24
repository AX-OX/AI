"""Spring 내부 API 호출 및 MCP 오류 변환."""
import os
from typing import Any

import httpx
from fastmcp.exceptions import ToolError


async def call(method: str, path: str, *, params: dict | None = None, body: Any = None) -> Any:
    token = os.getenv('INTERNAL_TOKEN')
    if not token:
        raise ToolError('INTERNAL_TOKEN이 설정되지 않았습니다.')
    base_url = os.getenv('SPRING_INTERNAL_URL', 'http://backend:8080/internal').rstrip('/')
    headers = {'X-Internal-Token': token}
    # Agent가 부여한 키를 Spring에 전달. Spring의 키별 원자적 중복 방지가 필요하다.
    from fastmcp.server.dependencies import get_http_headers
    request_headers = get_http_headers()
    for name in ('x-command-id', 'x-command-lease'):
        if request_headers.get(name):
            headers[name] = request_headers[name]
    if request_headers.get('x-idempotency-key'):
        headers['X-Idempotency-Key'] = request_headers['x-idempotency-key']
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            response = await client.request(method, base_url + path, params=params, json=body,
                                            headers=headers)
        if response.is_error:
            try:
                detail = response.json()
            except ValueError:
                detail = {'message': 'Spring 내부 API 오류'}
            raise ToolError(f'Spring HTTP {response.status_code}: {detail}')
        if not response.content:
            return {'ok': True}
        try:
            return response.json()
        except ValueError as exc:
            raise ToolError('Spring 내부 API가 유효하지 않은 JSON을 반환했습니다.') from exc
    except httpx.RequestError as exc:
        raise ToolError(f'Spring 내부 API 연결 실패: {type(exc).__name__}. 서비스 상태를 확인하세요.') from exc
