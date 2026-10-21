"""Run the three existing servers together; no DB initialization or indexing."""
import os
from pathlib import Path
import signal
import subprocess
import sys
import time
from urllib.error import HTTPError, URLError
from urllib.request import ProxyHandler, Request, build_opener

ROOT = Path(__file__).resolve().parents[1]


def check_processes(children):
    for name, process in children:
        if process.poll() is not None:
            raise RuntimeError(f'{name} exited (code={process.returncode})')


def main():
    children = []
    stopping = False

    def stop(signum, frame):
        nonlocal stopping
        stopping = True

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    env = dict(os.environ)
    env.setdefault('BUSINESS_MCP_URL', 'http://127.0.0.1:9101/mcp')
    env.setdefault('RAG_MCP_URL', 'http://127.0.0.1:9102/mcp')
    opener = build_opener(ProxyHandler({}))
    try:
        port = int(env.get('PORT', '8000'))
        if not 1 <= port <= 65535 or port in {9101, 9102}:
            raise ValueError('PORT must be 1..65535 and different from 9101/9102')
        for name, mcp_port in [('business-mcp', 9101), ('rag-mcp', 9102)]:
            process = subprocess.Popen([sys.executable, str(ROOT / name / 'server.py')], cwd=ROOT,
                                       env={**env, 'MCP_HOST': '127.0.0.1', 'MCP_PORT': str(mcp_port)})
            children.append((name, process))
        # Existing MCP endpoint returns 406 for JSON-only GET when ready.
        # No new health endpoints or DB/model access are needed for this probe.
        for mcp_port in (9101, 9102):
            deadline = time.monotonic() + 90
            while not stopping:
                check_processes(children)
                request = Request(f'http://127.0.0.1:{mcp_port}/mcp', headers={'Accept': 'application/json'})
                try:
                    with opener.open(request, timeout=0.5) as response:
                        ready = response.status == 200
                except HTTPError as exc:
                    ready = exc.code == 406
                    exc.close()
                except (URLError, TimeoutError, ConnectionError):
                    ready = False
                if ready:
                    break
                if time.monotonic() >= deadline:
                    raise RuntimeError(f'MCP port {mcp_port} startup timed out')
                time.sleep(0.1)
            if stopping:
                return 0
        command = [sys.executable, '-m', 'uvicorn', 'agent.app.main:app', '--host', '0.0.0.0',
                   '--port', str(port), '--workers', '1', '--http', 'h11', '--timeout-graceful-shutdown', '4']
        children.append(('agent', subprocess.Popen(command, cwd=ROOT, env=env)))
        while not stopping:
            check_processes(children)
            time.sleep(0.1)
        return 0
    except Exception as exc:
        print(f'Service failed: {exc}', file=sys.stderr, flush=True)
        return 1
    finally:
        # Cloud Run gives 10 seconds after SIGTERM; share a 7-second budget.
        for _, process in reversed(children):
            if process.poll() is None:
                process.terminate()
        deadline = time.monotonic() + 7
        for _, process in children:
            try:
                process.wait(timeout=max(0.01, deadline - time.monotonic()))
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()


if __name__ == '__main__':
    sys.exit(main())
