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
    HF_HOME=/opt/model-cache \
    TOKENIZERS_PARALLELISM=false \
    OMP_NUM_THREADS=1 \
    MKL_NUM_THREADS=1

COPY agent/requirements.lock.txt agent/requirements.lock.txt
COPY business-mcp/requirements.txt business-mcp/requirements.txt
COPY rag-mcp/requirements.txt rag-mcp/requirements.txt
# Avoid the much larger CUDA distribution on Cloud Run's CPU instances.
RUN pip install --no-cache-dir --index-url https://download.pytorch.org/whl/cpu torch==2.14.1 \
    && pip install --no-cache-dir -r agent/requirements.lock.txt \
        -r business-mcp/requirements.txt -r rag-mcp/requirements.txt \
    && pip check

ARG EMBEDDING_MODEL=sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2
ARG EMBEDDING_REVISION=e8f8c211226b894fcb81acc59f3b34ba3efd5f42
ENV EMBEDDING_MODEL=${EMBEDDING_MODEL} EMBEDDING_REVISION=${EMBEDDING_REVISION}
# Bake the pinned public model into the image. No DB connection or indexing here.
RUN python -c 'import os; from sentence_transformers import SentenceTransformer; SentenceTransformer(os.environ["EMBEDDING_MODEL"], revision=os.environ["EMBEDDING_REVISION"], device="cpu")' \
    && chmod -R a+rX /opt/model-cache
ENV HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1

COPY agent/app agent/app
COPY agent/prompts agent/prompts
COPY agent/fixtures agent/fixtures
COPY business-mcp/*.py business-mcp/
COPY rag-mcp/*.py rag-mcp/
COPY AX_Navigator_AI_MVP_v3 AX_Navigator_AI_MVP_v3
COPY scripts/run_cloudrun.py scripts/run_cloudrun.py
RUN useradd --create-home --uid 10001 axagent
USER axagent

EXPOSE 8000
ENTRYPOINT ["python", "scripts/run_cloudrun.py"]
