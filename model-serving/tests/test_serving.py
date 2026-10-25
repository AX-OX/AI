from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from prometheus_client.parser import text_string_to_metric_families

from app.main import create_app
from app.train import train


@pytest.fixture
def artifact(tmp_path):
    path = tmp_path / "iris.joblib"
    trained = train(path)
    assert trained["test_accuracy"] >= 0.9
    return path


def metric(client, name, labels=None):
    for family in text_string_to_metric_families(client.get("/metrics").text):
        for sample in family.samples:
            if sample.name == name and (labels is None or sample.labels == labels):
                return sample.value
    raise AssertionError(f"Missing metric: {name} {labels}")


def test_serves_saved_model_and_records_metrics(artifact):
    with TestClient(create_app(artifact)) as client:
        assert client.get("/health").json() == {"status": "ok", "model_version": "iris-rf-v1"}
        assert metric(client, "model_ready") == 1
        for features, expected in [
            ([5.1, 3.5, 1.4, 0.2], "setosa"),
            ([7.0, 3.2, 4.7, 1.4], "versicolor"),
            ([6.3, 3.3, 6.0, 2.5], "virginica"),
        ]:
            response = client.post("/predict", json={"features": features})
            assert response.status_code == 200
            body = response.json()
            assert body["class_name"] == expected
            assert body["model_version"] == "iris-rf-v1"
            assert sum(body["probabilities"].values()) == pytest.approx(1)
        assert metric(client, "model_prediction_requests_total", {"status": "200"}) == 3
        assert metric(client, "model_prediction_duration_seconds_count") == 3
        assert metric(client, "model_test_accuracy") >= 0.9


@pytest.mark.parametrize("features", [
    [], [1, 2, 3], [1, 2, 3, 4, 5], [-1, 2, 3, 4], [0, 2, 3, 4],
    [101, 2, 3, 4], ["5.1", 2, 3, 4], [True, 2, 3, 4], [None, 2, 3, 4],
])
def test_invalid_inputs_are_counted(artifact, features):
    with TestClient(create_app(artifact)) as client:
        assert client.post("/predict", json={"features": features}).status_code == 422
        assert metric(client, "model_prediction_requests_total", {"status": "422"}) == 1
        assert metric(client, "model_prediction_requests_total", {"status": "200"}) == 0
        assert metric(client, "model_prediction_duration_seconds_count") == 1


def test_inference_failure_is_counted(artifact):
    app = create_app(artifact)
    with TestClient(app, raise_server_exceptions=False) as client:
        with patch.object(app.state.artifact["model"], "predict_proba", side_effect=RuntimeError("failure")):
            assert client.post("/predict", json={"features": [5.1, 3.5, 1.4, 0.2]}).status_code == 500
        assert metric(client, "model_prediction_requests_total", {"status": "500"}) == 1


@pytest.mark.parametrize("number", ["1e400", "NaN", "Infinity", "-Infinity"])
def test_nonfinite_input_returns_422(artifact, number):
    with TestClient(create_app(artifact)) as client:
        response = client.post(
            "/predict", content='{"features":[' + number + ',2,3,4]}',
            headers={"Content-Type": "application/json"},
        )
        assert response.status_code == 422
        assert metric(client, "model_prediction_requests_total", {"status": "422"}) == 1


def test_missing_model_fails_startup(tmp_path):
    with pytest.raises(FileNotFoundError), TestClient(create_app(tmp_path / "missing.joblib")):
        pass


def test_unready_model_returns_503(artifact):
    app = create_app(artifact)
    with TestClient(app) as client:
        app.state.artifact = None
        assert client.get("/health").status_code == 503
        assert client.post("/predict", json={"features": [5.1, 3.5, 1.4, 0.2]}).status_code == 503
        assert metric(client, "model_prediction_requests_total", {"status": "503"}) == 1
