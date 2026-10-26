"""Installer recovery tests; never run Docker or touch a real VM."""
import importlib.util
import json
from pathlib import Path

import pytest


spec = importlib.util.spec_from_file_location('monitoring_install', Path(__file__).with_name('install.py'))
installer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(installer)

CADDY = '{$SITE_ADDRESS} {\n    @internal path /internal /internal/*\n    respond @internal 404\n    reverse_proxy backend:8080 {\n        flush_interval -1\n    }\n}\n'


@pytest.fixture
def vm(tmp_path, monkeypatch):
    app, root = tmp_path / 'app', tmp_path / 'monitoring'
    (app / 'runtime').mkdir(parents=True)
    (app / 'Caddyfile').write_text(CADDY)
    (app / 'runtime/agent.env').write_text('INTERNAL_TOKEN=existing-application-secret\n')
    (app / 'deployment.env').write_text('SITE_ADDRESS=axox.example.test\nAI_IMAGE=existing-image\n')
    monkeypatch.setattr(installer, 'APP', app)
    monkeypatch.setattr(installer, 'ROOT', root)
    monkeypatch.setattr(installer.os, 'chown', lambda *args: None)
    commands = []

    def fake_run(*args, capture=False):
        commands.append(args)
        if args[:2] == ('docker', 'inspect'):
            return json.dumps([{'Config': {'Env': ['AGENT_MODE=live', 'METRICS_TOKEN=existing-metrics-secret']}}])
        return ''

    monkeypatch.setattr(installer, 'run', fake_run)
    monkeypatch.setattr(installer, 'compose', lambda *args: commands.append(('compose', *args)))
    monkeypatch.setattr(installer, 'wait_ready', lambda: None)
    monkeypatch.setattr(installer, 'verify', lambda: None)
    return app, root, commands


def test_reinstall_preserves_credentials_and_does_not_restart_agent(vm):
    app, root, commands = vm
    installer.install()
    password = (root / 'secrets/grafana-password').read_text()
    installer.install()
    assert (root / 'secrets/grafana-password').read_text() == password
    assert (root / 'secrets/metrics-token').read_text() == 'existing-metrics-secret\n'
    assert (app / 'Caddyfile').read_text().count('# BEGIN AXOX MONITORING') == 1
    assert 'respond @internal 404' in (app / 'Caddyfile').read_text()
    assert not any('agent' == arg for command in commands for arg in command)
    assert (root / 'grafana-access.txt').stat().st_mode & 0o777 == 0o600


def test_first_install_failure_restores_routing_and_stops_only_monitoring(vm, monkeypatch):
    app, root, commands = vm
    monkeypatch.setattr(installer, 'wait_ready', lambda: (_ for _ in ()).throw(RuntimeError('not ready')))
    with pytest.raises(RuntimeError, match='not ready'):
        installer.install()
    assert (app / 'Caddyfile').read_text() == CADDY
    assert ('compose', 'stop') in commands
    assert not any('down' in command for command in commands)


def test_upgrade_failure_restores_previous_monitoring_settings(vm, monkeypatch):
    app, root, commands = vm
    installer.install()
    old_rules = (root / 'alerts.yml').read_text() + '\n# prior rules\n'
    (root / 'alerts.yml').write_text(old_rules)
    monkeypatch.setattr(installer, 'wait_ready', lambda: (_ for _ in ()).throw(RuntimeError('not ready')))
    with pytest.raises(RuntimeError, match='not ready'):
        installer.install()
    assert (root / 'alerts.yml').read_text() == old_rules
    assert '# BEGIN AXOX MONITORING' in (app / 'Caddyfile').read_text()
    assert ('compose', 'stop') not in commands


def test_active_execution_prevents_first_token_restart(vm, monkeypatch):
    app, root, commands = vm
    monkeypatch.setattr(installer, 'run', lambda *args, **kwargs: json.dumps([
        {'Config': {'Env': ['AGENT_MODE=live', 'INTERNAL_TOKEN=existing']}}]))
    monkeypatch.setattr(installer, 'agent_command', lambda code: '1\n')
    with pytest.raises(RuntimeError, match='active executions'):
        installer.install()
    assert (app / 'Caddyfile').read_text() == CADDY
    assert (app / 'runtime/agent.env').read_text() == 'INTERNAL_TOKEN=existing-application-secret\n'
    assert not commands


def test_reinstall_removes_appledouble_from_provisioning_without_losing_it(vm):
    app, root, commands = vm
    installer.install()
    metadata = root / 'grafana/provisioning/dashboards/._production.yml'
    metadata.write_bytes(b'\x00AppleDouble metadata')
    installer.install()
    assert not metadata.exists()
    saved = list((root / 'backups').glob('*/packaging-metadata/provisioning/dashboards/._production.yml'))
    assert len(saved) == 1
    assert saved[0].read_bytes() == b'\x00AppleDouble metadata'
