"""Exercise the real local Agent application with offline fixtures only."""
import json
from time import monotonic, sleep
from urllib.request import Request, urlopen
from urllib.error import URLError
from uuid import uuid4

BASE = 'http://127.0.0.1:8002'


def call(path, body=None):
    request = Request(BASE + path, data=json.dumps(body).encode() if body is not None else None,
                      headers={'Content-Type': 'application/json', 'X-Internal-Token': 'local-agent-demo-only'})
    with urlopen(request, timeout=10) as response:
        return json.load(response)


def wait(key, expected):
    deadline = monotonic() + 30
    while monotonic() < deadline:
        state = call(f'/tasks/{key}')
        if state['status'] == expected:
            return
        if state['status'] == 'FAILED':
            raise RuntimeError('Agent failed; inspect its local logs')
        sleep(.2)
    raise TimeoutError(f'Agent did not reach {expected}')


if __name__ == '__main__':
    deadline = monotonic() + 30
    while True:
        try:
            mode = call('/health')['mode']
            break
        except (URLError, ConnectionError, TimeoutError):
            if monotonic() >= deadline:
                raise RuntimeError('Local Agent is not ready') from None
            sleep(.5)
    if mode != 'mock':
        raise RuntimeError('This fixture demo is permitted only in mock mode')
    key = str(uuid4())
    call(f'/tasks/{key}/run', {'companyId': 1, 'userId': 602, 'requestText': 'AX 과제 3개 선정'})
    wait(key, 'WAITING_APPROVAL')
    call(f'/tasks/{key}/resume', {'decision': 'APPROVE', 'userId': 602})
    wait(key, 'DONE')
    print('AX Agent: WAITING_APPROVAL → DONE. Fixture tools executed; no live LLM/DB writes.')
