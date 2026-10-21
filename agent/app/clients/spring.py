"""Teammate SpringClient interface, with strict HTTP errors and explicit JSON headers."""
from datetime import datetime, timezone
import httpx
from ..models.events import EventType, TaskEvent


class SpringClient:
    def __init__(self, settings, client=None):
        self.settings = settings
        self._client = client or httpx.AsyncClient(
            base_url=settings.spring_url.rstrip('/') + '/', timeout=15,
            headers={'X-Internal-Token': settings.internal_token})

    async def request(self, method, path, body):
        response = await self._client.request(method, path.lstrip('/'), json=body,
                                             headers={'X-Internal-Token': self.settings.internal_token})
        response.raise_for_status()
        return response

    async def patch_task(self, task_id, **fields):
        return await self.request('PATCH', f'tasks/{task_id}', fields)

    async def emit(self, task_id, type_, node=None, data=None):
        event = TaskEvent(type=EventType(type_), taskId=task_id, ts=datetime.now(timezone.utc),
                          node=node, data=data or {})
        return await self.request('POST', f'tasks/{task_id}/events', event.model_dump(mode='json'))

    async def aclose(self):
        await self._client.aclose()

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        await self.aclose()
