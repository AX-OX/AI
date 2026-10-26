from fastapi.testclient import TestClient

from app.ops import create_app


def test_alert_notifications_persist_firing_and_resolved(tmp_path):
    path = tmp_path / 'alerts.sqlite'
    with TestClient(create_app(path)) as client:
        for status in ('firing', 'resolved'):
            payload = {'status': status, 'alerts': [{'status': status, 'labels': {'alertname': 'ServingTargetDown'}, 'startsAt': '2026-10-26T00:00:00Z'}]}
            assert client.post('/webhook', json=payload).status_code == 202
        assert client.get('/alerts').json()[0]['status'] == 'resolved'
        assert client.post('/webhook', json={'status': 'wrong', 'alerts': []}).status_code == 422
    with TestClient(create_app(path)) as client:
        assert len(client.get('/alerts').json()) == 2


def test_inbox_keeps_a_bounded_history(tmp_path):
    with TestClient(create_app(tmp_path / 'alerts.sqlite')) as client:
        for _ in range(205):
            client.post('/webhook', json={'status': 'firing', 'alerts': []})
        items = client.get('/alerts').json()
        assert len(items) == 100
        assert items[0]['id'] == 205
