import os
import asyncio
from contextlib import asynccontextmanager
from pathlib import Path
from time import perf_counter, time
from typing import Annotated

import joblib
from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from prometheus_client import (
    CONTENT_TYPE_LATEST,
    CollectorRegistry,
    Counter,
    Gauge,
    Histogram,
    Info,
    ProcessCollector,
    PlatformCollector,
    generate_latest,
)
from pydantic import BaseModel, Field

Measurement = Annotated[float, Field(gt=0, le=100, allow_inf_nan=False, strict=True)]


class PredictionRequest(BaseModel):
    # Iris measurements in cm: sepal length, sepal width, petal length, petal width.
    features: Annotated[list[Measurement], Field(min_length=4, max_length=4)]


class PredictionResponse(BaseModel):
    model_version: str
    class_id: int
    class_name: str
    probabilities: dict[str, float]


class DemoControl(BaseModel):
    delay_ms: int = Field(default=0, ge=0, le=2000)
    error_every: int = Field(default=0, ge=0, le=100)


def create_app(model_path: Path | None = None) -> FastAPI:
    registry = CollectorRegistry()
    ProcessCollector(registry=registry)
    PlatformCollector(registry=registry)
    info = Info('model', 'Loaded model identity', registry=registry)
    loaded_at = Gauge('model_loaded_timestamp_seconds', 'Model load time in Unix seconds', registry=registry)
    ready = Gauge("model_ready", "Whether the trained model is loaded", registry=registry)
    requests = Counter(
        "model_prediction_requests_total", "Prediction HTTP requests", ["status"], registry=registry
    )
    for status in ("200", "422", "500", "503"):
        requests.labels(status=status)
    latency = Histogram(
        "model_prediction_duration_seconds", "Prediction HTTP request duration",
        buckets=(0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5), registry=registry,
    )
    accuracy = Gauge(
        "model_test_accuracy", "Fixed holdout accuracy at build time, not live accuracy",
        registry=registry,
    )

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        # Only load the artifact produced by app.train during the image build.
        path = model_path or Path(os.getenv("MODEL_PATH", "artifacts/iris.joblib"))
        app.state.artifact = joblib.load(path)
        app.state.loaded_at = time()
        app.state.demo_control = DemoControl()
        app.state.demo_requests = 0
        artifact = app.state.artifact
        info.info({'name': 'Iris RandomForest', 'version': artifact['version'],
                   'dataset': 'sklearn_builtin_iris', 'trained_at': artifact['trained_at']})
        loaded_at.set(app.state.loaded_at)
        accuracy.set(app.state.artifact["test_accuracy"])
        ready.set(1)
        try:
            yield
        finally:
            ready.set(0)
            app.state.artifact = None

    app = FastAPI(title="Simple Iris Model Serving", lifespan=lifespan)

    @app.exception_handler(RequestValidationError)
    async def invalid_request(request: Request, error: RequestValidationError):
        # Do not echo non-finite input values: JSON cannot serialize NaN/Infinity.
        return JSONResponse(status_code=422, content={"detail": [
            {key: item[key] for key in ("loc", "msg", "type")}
            for item in error.errors()
        ]})

    @app.middleware("http")
    async def record_prediction(request: Request, call_next):
        if request.method != "POST" or request.url.path != "/predict":
            return await call_next(request)
        started = perf_counter()
        status = "500"
        try:
            response = await call_next(request)
            status = str(response.status_code)
            return response
        finally:
            requests.labels(status=status).inc()
            latency.observe(perf_counter() - started)

    @app.get("/health")
    def health():
        artifact = getattr(app.state, "artifact", None)
        if artifact is None:
            raise HTTPException(status_code=503, detail="Model is not ready")
        return {"status": "ok", "model_version": artifact["version"]}

    @app.get("/metrics", include_in_schema=False)
    def metrics():
        return Response(generate_latest(registry), media_type=CONTENT_TYPE_LATEST)

    @app.get('/model')
    def model_info():
        artifact = app.state.artifact
        return {'name': 'Iris RandomForest', 'version': artifact['version'],
                'dataset': 'sklearn_builtin_iris', 'features': ['sepal_length_cm', 'sepal_width_cm', 'petal_length_cm', 'petal_width_cm'],
                'classes': artifact['classes'], 'trained_at': artifact['trained_at'],
                'loaded_at_unix': app.state.loaded_at, 'training_samples': artifact['training_samples'],
                'test_samples': artifact['test_samples'], 'holdout_accuracy': artifact['test_accuracy'],
                'demo_controls_enabled': os.getenv('ENABLE_DEMO_CONTROLS') == 'true'}

    @app.post('/demo/control')
    def demo_control(control: DemoControl):
        if os.getenv('ENABLE_DEMO_CONTROLS') != 'true':
            raise HTTPException(404, 'Demo controls disabled')
        app.state.demo_control = control
        app.state.demo_requests = 0
        return control

    @app.post("/predict", response_model=PredictionResponse)
    async def predict(body: PredictionRequest):
        artifact = getattr(app.state, "artifact", None)
        if artifact is None:
            raise HTTPException(status_code=503, detail="Model is not ready")
        control = app.state.demo_control
        app.state.demo_requests += 1
        should_fail = control.error_every and app.state.demo_requests % control.error_every == 0
        if control.delay_ms:
            await asyncio.sleep(control.delay_ms / 1000)
        if should_fail:
            raise HTTPException(503, 'Simulated demo failure')
        probabilities = (await asyncio.to_thread(artifact["model"].predict_proba, [body.features]))[0]
        class_id = int(probabilities.argmax())
        return PredictionResponse(
            model_version=artifact["version"],
            class_id=class_id,
            class_name=artifact["classes"][class_id],
            probabilities=dict(zip(artifact["classes"], probabilities.tolist())),
        )

    return app


app = create_app()
