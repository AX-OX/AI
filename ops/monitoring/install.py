#!/usr/bin/env python3
"""Install on the existing AXOX VM as root. Never prints application secrets."""
import argparse
import datetime
import fcntl
import json
import os
from pathlib import Path
import secrets
import shutil
import subprocess
import time
import urllib.parse


SOURCE = Path(__file__).resolve().parent
APP = Path('/opt/axox-vm')
ROOT = Path('/opt/axox-monitoring')


def run(*args, capture=False):
    result = subprocess.run(args, text=True, capture_output=True)
    if result.returncode:
        # Docker errors can include interpolated env. Keep detailed errors local.
        if ROOT.exists():
            log = ROOT / 'last-error.log'
            log.write_text(result.stdout + result.stderr)
            log.chmod(0o600)
        raise RuntimeError(f'{args[0]} command failed; root-only last-error.log has details')
    return result.stdout if capture else None


def compose(*args):
    return run('docker', 'compose', '--project-directory', str(ROOT),
               '--env-file', str(APP / 'deployment.env'), '-f', str(ROOT / 'compose.yaml'),
               *args, capture=True)


def agent_command(code):
    return run('docker', 'exec', 'axox-vm-agent-1', 'python', '-c', code, capture=True)


def request(service, path, *, method='GET', body=None):
    # Run from the existing Python container, not from the public Internet.
    url = f'http://{service}{path}'
    code = ('import urllib.request; '
            f'r=urllib.request.Request({url!r}, method={method!r}); ')
    if body is not None:
        code += f'r.data={json.dumps(body).encode()!r}; r.add_header("Content-Type","application/json"); '
    code += 'print(urllib.request.urlopen(r,timeout=10).read().decode() or "{}")'
    return json.loads(run('docker', 'exec', 'axox-monitoring-alert-inbox-1', 'python', '-c', code, capture=True))


def wait_ready():
    for attempt in range(40):
        try:
            if request('grafana:3000', '/grafana/api/health')['database'] != 'ok':
                raise RuntimeError('Grafana database not ready')
            targets = request('prometheus:9090', '/api/v1/targets')['data']['activeTargets']
            agent = [target for target in targets if target['labels']['job'] == 'ax-agent']
            if len(agent) != 1 or agent[0]['health'] != 'up':
                raise RuntimeError('Agent scrape not up')
            query = urllib.parse.urlencode({'query': 'ax_agent_ready{job="ax-agent"}'})
            ready = request('prometheus:9090', '/api/v1/query?' + query)['data']['result']
            if len(ready) != 1 or ready[0]['value'][1] != '1':
                raise RuntimeError('Agent not ready')
            return
        except (RuntimeError, KeyError, ValueError):
            if attempt == 39:
                raise
            time.sleep(3)


def verify():
    wait_ready()
    health = json.loads(agent_command('import urllib.request; print(urllib.request.urlopen("http://127.0.0.1:8000/health").read().decode())'))
    if health.get('mode') != 'live':
        raise RuntimeError('Production Agent must be live')
    targets = request('prometheus:9090', '/api/v1/targets')['data']['activeTargets']
    print(json.dumps({'agent': health, 'targets': [
        {'job': t['labels']['job'], 'health': t['health']} for t in targets]}, ensure_ascii=False))
    # Credentials travel to the local Docker stdin, never through argv/logs/public URLs.
    password = (ROOT / 'secrets/grafana-password').read_text().strip()
    code = ('import sys,json,urllib.request,base64; '
            'p=sys.stdin.read().strip(); '
            'r=urllib.request.Request("http://grafana:3000/grafana/api/dashboards/uid/ax-agent-monitoring"); '
            'r.add_header("Authorization","Basic "+base64.b64encode(("axox-admin:"+p).encode()).decode()); '
            'd=json.load(urllib.request.urlopen(r,timeout=10)); '
            'print(json.dumps({"dashboard":d["dashboard"]["title"],"url":d["meta"]["url"]}))')
    result = subprocess.run(['docker', 'exec', '-i', 'axox-monitoring-alert-inbox-1', 'python', '-c', code],
                            input=password, text=True, capture_output=True)
    if result.returncode:
        raise RuntimeError('Authenticated Grafana dashboard check failed')
    print(result.stdout.strip())


def test_alert():
    """Exercise firing/resolved delivery without failing a real service."""
    now = datetime.datetime.now(datetime.timezone.utc)
    stamp = lambda value: value.isoformat().replace('+00:00', 'Z')
    alert = {'labels': {'alertname': 'MonitoringDeliveryCheck', 'job': 'monitoring-selftest',
                        'severity': 'info', 'check_id': now.strftime('%Y%m%d%H%M%S')},
             'annotations': {'summary': 'Synthetic monitoring delivery check; no service failure'},
             'startsAt': stamp(now), 'endsAt': stamp(now + datetime.timedelta(minutes=5))}
    request('alertmanager:9093', '/api/v2/alerts', method='POST', body=[alert])
    try:
        for _ in range(20):
            notifications = request('alert-inbox:8000', '/alerts')
            if any(item['status'] == 'firing' and any(
                    a['labels'].get('check_id') == alert['labels']['check_id'] for a in item['alerts'])
                   for item in notifications):
                break
            time.sleep(2)
        else:
            raise RuntimeError('Firing alert was not persisted')
    finally:
        alert['endsAt'] = stamp(datetime.datetime.now(datetime.timezone.utc))
        request('alertmanager:9093', '/api/v2/alerts', method='POST', body=[alert])
    for _ in range(40):
        notifications = request('alert-inbox:8000', '/alerts')
        if any(item['status'] == 'resolved' and any(
                a['labels'].get('check_id') == alert['labels']['check_id'] for a in item['alerts'])
               for item in notifications):
            print('Synthetic alert firing and resolution both persisted successfully')
            return
        time.sleep(2)
    raise RuntimeError('Resolved alert was not persisted')


def install():
    ROOT.mkdir(mode=0o700, exist_ok=True)
    ROOT.chmod(0o700)
    timestamp = datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    backup = ROOT / 'backups' / timestamp
    backup.mkdir(parents=True, mode=0o700)
    for name in ('Caddyfile',):
        shutil.copy2(APP / name, backup / name)
    shutil.copy2(APP / 'runtime/agent.env', backup / 'agent.env')
    existing = (ROOT / 'compose.yaml').exists()
    if existing:
        for name in ('compose.yaml', 'prometheus.yml', 'alerts.yml', 'alertmanager.yml'):
            shutil.copy2(ROOT / name, backup / name)
        shutil.copytree(ROOT / 'grafana', backup / 'grafana')
        shutil.copy2(ROOT / 'alert_inbox.py', backup / 'alert_inbox.py')

    env = json.loads(run('docker', 'inspect', 'axox-vm-agent-1', capture=True))[0]['Config']['Env']
    env = dict(value.split('=', 1) for value in env)
    if env.get('AGENT_MODE', 'live') != 'live':
        raise RuntimeError('Refusing to monitor a non-live production Agent')
    runtime = APP / 'runtime/agent.env'
    original_runtime = runtime.read_text()
    token = env.get('METRICS_TOKEN')
    restart_agent = not token
    if restart_agent:
        active = agent_command(
            'import os,urllib.request; '
            'r=urllib.request.Request("http://127.0.0.1:8000/metrics",headers={"Authorization":"Bearer "+os.environ["INTERNAL_TOKEN"]}); '
            's=urllib.request.urlopen(r,timeout=5).read().decode(); '
            'print(next(line.split()[1] for line in s.splitlines() if line.startswith("ax_agent_active_executions ")))')
        if float(active.strip()) != 0:
            raise RuntimeError('Agent has active executions; retry once idle')
        token = secrets.token_urlsafe(48)

    secret_dir = ROOT / 'secrets'
    secret_dir.mkdir(mode=0o700, exist_ok=True)
    secret_dir.chmod(0o700)
    token_file = secret_dir / 'metrics-token'
    if not token_file.exists() or token_file.read_text().strip() != token:
        if token_file.exists():
            token_file.chmod(0o600)
        token_file.write_text(token + '\n')
    os.chown(token_file, 65534, 65534)
    token_file.chmod(0o400)
    password_file = secret_dir / 'grafana-password'
    if not password_file.exists():
        password_file.write_text(secrets.token_urlsafe(32) + '\n')
    os.chown(password_file, 472, 0)
    password_file.chmod(0o400)

    for name in ('compose.yaml', 'prometheus.yml', 'alerts.yml', 'alertmanager.yml'):
        shutil.copy2(SOURCE / name, ROOT / name)
        (ROOT / name).chmod(0o644)
    shutil.copytree(SOURCE / 'grafana', ROOT / 'grafana', dirs_exist_ok=True,
                    ignore=shutil.ignore_patterns('._*', '.DS_Store', '__pycache__'))
    # macOS tar can carry AppleDouble files; Grafana parses every *.yml file.
    # Preserve any prior packaging metadata outside the provisioned directory.
    for metadata in (ROOT / 'grafana').rglob('._*'):
        if metadata.is_file():
            saved = backup / 'packaging-metadata' / metadata.relative_to(ROOT / 'grafana')
            saved.parent.mkdir(parents=True, exist_ok=True)
            metadata.rename(saved)
    dashboard = SOURCE / 'ax-agent.json'
    inbox = SOURCE / 'alert_inbox.py'
    if not dashboard.exists():
        dashboard = SOURCE.parents[1] / 'model-serving/monitoring/grafana/dashboards/ax-agent.json'
        inbox = SOURCE.parents[1] / 'model-serving/app/ops.py'
    target = ROOT / 'grafana/dashboards'
    target.mkdir(exist_ok=True)
    document = json.loads(dashboard.read_text())
    document['title'] = 'AX Agent · GCP Production'
    document['tags'] = ['axox', 'production', 'gcp']
    document['refresh'] = '2m'
    document['timepicker'] = {'refresh_intervals': ['30s', '1m', '2m', '5m', '15m', '1h']}
    document['links'] = []
    for panel in document['panels']:
        if panel['type'] == 'text':
            panel['gridPos'].update(x=6, w=18)
            panel['options']['content'] = (
                '**GCP production / mode=live**: 실제 운영 LLM·MCP/pgvector 경로를 사용하는 Agent의 지표입니다. '
                '문서 내용·질문·사용자 식별자는 수집하지 않습니다. 토큰은 제공자가 보고한 값이며, '
                '호출이 없으면 관련 패널은 No data로 표시될 수 있습니다. CPU/RSS는 Agent 프로세스 기준입니다. '
                'Active alerts는 현재 발생 중인 운영 경보 수입니다. 알림 발생·해제 이력은 내부 수신함에 저장됩니다.')
    document['panels'].append({
        'id': 16, 'type': 'stat', 'title': 'Active alerts',
        'gridPos': {'x': 0, 'y': 38, 'w': 6, 'h': 5},
        'datasource': {'type': 'prometheus', 'uid': 'model-prometheus'},
        'targets': [{'refId': 'A', 'expr': 'sum(ALERTS{alertstate="firing"}) or vector(0)', 'instant': True}],
        'fieldConfig': {'defaults': {'unit': 'short', 'thresholds': {'mode': 'absolute', 'steps': [
            {'color': 'green', 'value': None}, {'color': 'red', 'value': 1}]}}, 'overrides': []},
        'options': {'reduceOptions': {'calcs': ['lastNotNull'], 'fields': '', 'values': False},
                    'colorMode': 'value', 'graphMode': 'none'},
    })
    (target / 'ax-agent.json').write_text(json.dumps(document, ensure_ascii=False, indent=2) + '\n')
    shutil.copy2(inbox, ROOT / 'alert_inbox.py')
    alerts = ROOT / 'state/alerts'
    alerts.mkdir(parents=True, exist_ok=True)
    os.chown(alerts, 10001, 10001)
    alerts.chmod(0o700)

    # Fail before touching production routing or restarting the Agent.
    compose('config', '--quiet')
    compose('pull', 'prometheus', 'grafana', 'alertmanager')
    run('docker', 'run', '--rm', '--entrypoint', 'promtool',
        '-v', f'{ROOT / "prometheus.yml"}:/etc/prometheus/prometheus.yml:ro',
        '-v', f'{ROOT / "alerts.yml"}:/etc/prometheus/alerts.yml:ro',
        '-v', f'{token_file}:/run/secrets/metrics-token:ro', 'prom/prometheus:v3.15.1',
        'check', 'config', '/etc/prometheus/prometheus.yml')
    run('docker', 'run', '--rm', '--entrypoint', 'amtool',
        '-v', f'{ROOT / "alertmanager.yml"}:/etc/alertmanager/alertmanager.yml:ro',
        'prom/alertmanager:v0.34.1', 'check-config', '/etc/alertmanager/alertmanager.yml')

    route = ('    # BEGIN AXOX MONITORING\n'
             '    @grafana path /grafana /grafana/*\n'
             '    handle @grafana {\n'
             '        reverse_proxy axox-grafana:3000\n'
             '    }\n'
             '    # END AXOX MONITORING\n')
    caddy = APP / 'Caddyfile'
    original_caddy = caddy.read_text()
    if '# BEGIN AXOX MONITORING' not in original_caddy:
        marker = '    reverse_proxy backend:8080'
        if original_caddy.count(marker) != 1:
            raise RuntimeError('Unexpected Caddyfile; cannot insert Grafana route safely')
        # Caddy sorts handle before reverse_proxy, preserving the full subpath.
        caddy.write_text(original_caddy.replace(marker, route + marker))
    credentials = ROOT / 'grafana-access.txt'
    site = dict(line.split('=', 1) for line in (APP / 'deployment.env').read_text().splitlines()
                if line and not line.startswith('#'))['SITE_ADDRESS']
    credentials.write_text(f'URL: https://{site}/grafana/\nUsername: axox-admin\nPassword: {password_file.read_text().strip()}\n')
    credentials.chmod(0o600)
    try:
        run('docker', 'exec', 'axox-vm-gateway-1', 'caddy', 'validate', '--config', '/etc/caddy/Caddyfile', '--adapter', 'caddyfile')
        if restart_agent:
            # Retain every existing secret exactly; add one narrow metrics credential.
            runtime.write_text(original_runtime.rstrip('\n') + '\nMETRICS_TOKEN=' + token + '\n')
            runtime.chmod(0o600)
            run('docker', 'compose', '--project-directory', str(APP), '--env-file', str(APP / 'deployment.env'),
                'up', '-d', '--no-deps', '--wait', '--wait-timeout', '240', 'agent')
        compose('up', '-d', '--remove-orphans')
        wait_ready()
        run('docker', 'exec', 'axox-vm-gateway-1', 'caddy', 'reload', '--config', '/etc/caddy/Caddyfile', '--adapter', 'caddyfile')
        verify()
    except Exception:
        caddy.write_text(original_caddy)
        run('docker', 'exec', 'axox-vm-gateway-1', 'caddy', 'reload', '--config', '/etc/caddy/Caddyfile', '--adapter', 'caddyfile')
        if restart_agent:
            runtime.write_text(original_runtime)
            runtime.chmod(0o600)
            run('docker', 'compose', '--project-directory', str(APP), '--env-file', str(APP / 'deployment.env'),
                'up', '-d', '--no-deps', '--wait', '--wait-timeout', '240', 'agent')
        if existing:
            for name in ('compose.yaml', 'prometheus.yml', 'alerts.yml', 'alertmanager.yml', 'alert_inbox.py'):
                shutil.copy2(backup / name, ROOT / name)
            shutil.copytree(backup / 'grafana', ROOT / 'grafana', dirs_exist_ok=True)
            compose('up', '-d')
        else:
            compose('stop')
        raise
    print(f'Monitoring installed. Credentials: {credentials} (root-only). Backup: {backup}')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--verify', action='store_true')
    parser.add_argument('--test-alert', action='store_true')
    args = parser.parse_args()
    if os.geteuid() != 0:
        raise SystemExit('Run with sudo on the AXOX VM')
    # Same lock as update-service.sh; avoid racing application deployments.
    with open('/run/lock/axox-vm-deploy.lock', 'w') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        if args.test_alert:
            test_alert()
        elif args.verify:
            verify()
        else:
            install()
