"""Teammate API tests, updated for internal-token auth, UUID IDs and real mock nodes."""
import time
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from agent.app.config import Settings
from agent.app.main import create_app
from agent.app.mock import MockGateway

RUN = {'companyId': 1, 'userId': 602, 'requestText': 'AX 과제 3개 선정'}


@pytest.fixture
def ctx():
    settings = Settings(mode='mock', internal_token='test-token')
    gateway = MockGateway(settings)
    with TestClient(create_app(settings, gateway=gateway), headers={'X-Internal-Token':'test-token'}) as client:
        yield client, gateway


def wait(client, key, status):
    for _ in range(100):
        response = client.get(f'/tasks/{key}')
        response.raise_for_status()
        body = response.json()
        if body['status'] == status:
            return body
        if body['status'] == 'FAILED':
            raise AssertionError(body['errors'])
        time.sleep(.02)
    raise AssertionError(f'timeout: {status}')


def start(client):
    key = str(uuid4())
    assert client.post(f'/tasks/{key}/run', json=RUN).status_code == 202
    wait(client, key, 'WAITING_APPROVAL')
    return key


def test_health(ctx):
    client, _ = ctx
    assert client.get('/health').json()['status'] == 'ok'


def test_run_returns_202_and_stops_at_approval(ctx):
    client, gateway = ctx
    key = start(client)
    assert any(e['body'].get('type') == 'APPROVAL_REQUIRED' for e in gateway.events)
    assert not wait(client, key, 'WAITING_APPROVAL')['result']['projects']


def test_duplicate_run_is_409(ctx):
    client, _ = ctx
    key = start(client)
    assert client.post(f'/tasks/{key}/run', json=RUN).status_code == 409


def test_resume_by_other_user_is_403(ctx):
    client, _ = ctx
    key = start(client)
    assert client.post(f'/tasks/{key}/resume', json={'decision':'APPROVE','userId':601}).status_code == 403


def test_resume_missing_task_is_404(ctx):
    client, _ = ctx
    assert client.post(f'/tasks/{uuid4()}/resume', json={'decision':'APPROVE','userId':602}).status_code == 404


def test_approve_finishes_done_and_cannot_resume_again(ctx):
    client, _ = ctx
    key = start(client)
    decision = {'decision':'APPROVE','userId':602}
    assert client.post(f'/tasks/{key}/resume', json=decision).status_code == 202
    assert len(wait(client, key, 'DONE')['result']['projects']) == 3
    assert client.post(f'/tasks/{key}/resume', json=decision).status_code == 409


def test_reject_sets_rejected_without_registering(ctx):
    client, gateway = ctx
    key = start(client)
    assert client.post(f'/tasks/{key}/resume', json={'decision':'REJECT','userId':602,'reason':'no'}).status_code == 202
    assert not wait(client, key, 'REJECTED')['result']['projects']
    assert not any(name.startswith('create_') for name, _ in gateway.calls)


def test_run_requires_internal_token_and_uuid(ctx):
    client, _ = ctx
    assert client.post(f'/tasks/{uuid4()}/run', json=RUN, headers={'X-Internal-Token':'wrong'}).status_code == 403
    assert client.post('/tasks/invalid-id/run', json=RUN).status_code == 422
