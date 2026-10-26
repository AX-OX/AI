FROM python:3.11-slim-bookworm

WORKDIR /app
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONPATH=/app \
    AGENT_MODE=live \
    PORT=8000 \
    BUSINESS_MCP_URL=http://127.0.0.1:9101/mcp \
    RAG_MCP_URL=http://127.0.0.1:9102/mcp \
    SPRING_INTERNAL_URL=https://axox-853402721456.asia-northeast1.run.app/internal \
    DATASET_DIR=/app/AX_Navigator_AI_MVP_v3 \
    AX_POLICY_FILE=/app/AX_Navigator_AI_MVP_v3/config/ax_score_policy_v1.json \
    CORPUS_DIR=/app/AX_Navigator_AI_MVP_v3/rag \
    TOKENIZERS_PARALLELISM=false \
    OMP_NUM_THREADS=1 \
    MKL_NUM_THREADS=1

COPY agent/requirements.lock.txt agent/requirements.lock.txt
COPY business-mcp/requirements.txt business-mcp/requirements.txt
COPY rag-mcp/requirements.txt rag-mcp/requirements.txt
RUN pip install --no-cache-dir -r agent/requirements.lock.txt \
        -r business-mcp/requirements.txt -r rag-mcp/requirements.txt \
    && pip check

ENV EMBEDDING_MODEL=text-embedding-3-small \
    EMBEDDING_REVISION=openai-dim384-v1 \
    RAG_INDEX_VERSION=ax-v3-openai-small-384-v1

COPY agent/app agent/app
COPY agent/prompts agent/prompts
COPY agent/config agent/config
COPY agent/fixtures agent/fixtures
COPY business-mcp/*.py business-mcp/
COPY rag-mcp/*.py rag-mcp/
COPY AX_Navigator_AI_MVP_v3 AX_Navigator_AI_MVP_v3
COPY scripts/run_cloudrun.py scripts/run_cloudrun.py
COPY ops/monitoring /opt/axox-monitoring-package
COPY model-serving/monitoring/grafana/dashboards/ax-agent.json /opt/axox-monitoring-package/ax-agent.json
COPY model-serving/app/ops.py /opt/axox-monitoring-package/alert_inbox.py
RUN useradd --create-home --uid 10001 axagent
USER axagent

EXPOSE 8000
ENTRYPOINT ["python", "scripts/run_cloudrun.py"]
