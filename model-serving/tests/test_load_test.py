import pytest

from load_test import run


def test_load_generator_is_bounded_and_rejects_external_targets():
    for url in ('http://example.com', 'http://localhost@evil.test', 'https://localhost', 'http://localhost/path'):
        with pytest.raises(ValueError):
            run(url, 'normal', 1, 1, 0)
    for requests, concurrency in ((0, 1), (1001, 1), (1, 17)):
        with pytest.raises(ValueError):
            run('http://localhost:8001', 'normal', requests, concurrency, 0)


def test_failure_demo_resets_controls_even_when_client_fails(monkeypatch):
    calls = []

    def send(base, path, body):
        calls.append((path, body))
        if path == '/predict':
            raise RuntimeError('client failed')
        return 200

    monkeypatch.setattr('load_test.send', send)
    with pytest.raises(RuntimeError):
        run('http://localhost:8001', 'failure', 1, 1, 0)
    assert calls[-1] == ('/demo/control', {'delay_ms': 0, 'error_every': 0})
