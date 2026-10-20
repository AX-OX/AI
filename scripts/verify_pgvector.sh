#!/bin/sh
# Disposable DB + actual MCP HTTP. Team Spring and LLM are v3 fixtures, never Maven/Java.
set -eu
ROOT_DIR=$(CDPATH= cd -- "$(dirname "$0")/.." && pwd)
cd "$ROOT_DIR"
TASK_DIR=$(mktemp -d /private/tmp/ax-v3-runtime-XXXXXX)
PG_STARTED=0
cleanup() {
  TEST_STATUS=$?
  if [ "$TEST_STATUS" -ne 0 ]; then
    mkdir -p reports/runtime
    for file in "$TASK_DIR"/*.log; do [ ! -f "$file" ] || cp "$file" reports/runtime/; done
  fi
  for pid in "${STUB_PID:-}" "${BUSINESS_PID:-}" "${RAG_PID:-}"; do
    [ -z "$pid" ] || kill "$pid" 2>/dev/null || true
  done
  if [ "$PG_STARTED" = 1 ]; then pg_ctl -D "$TASK_DIR/data" -m immediate -w stop >/dev/null 2>&1 || true; fi
  rm -rf "$TASK_DIR"
}
trap cleanup EXIT INT TERM
initdb -D "$TASK_DIR/data" --auth=trust --encoding=UTF8 --no-locale >/dev/null
pg_ctl -D "$TASK_DIR/data" -o "-k $TASK_DIR -p 55439 -h 127.0.0.1" -l "$TASK_DIR/postgres.log" -w start >/dev/null
PG_STARTED=1
createdb -h "$TASK_DIR" -p 55439 ax
createdb -h "$TASK_DIR" -p 55439 agent
for file in db/init/01_schema.sql db/init/02_seed.sql db/init/03_pgvector.sql; do
  psql -h "$TASK_DIR" -p 55439 -d ax -v ON_ERROR_STOP=1 -f "$file" >/dev/null
done
export PGHOST="$TASK_DIR" PGPORT=55439
POSTGRES_USER="$(id -un)" POSTGRES_DB=ax RAG_READER_PASSWORD=test-reader RAG_INDEXER_PASSWORD=test-indexer sh db/init/04_rag_roles.sh >/dev/null
export RAG_TEST_DATABASE_URL="postgresql:///ax?host=$TASK_DIR&port=55439"
export AGENT_TEST_DATABASE_URL="postgresql:///agent?host=$TASK_DIR&port=55439"
export RAG_DATABASE_URL="postgresql://ax_rag_reader@127.0.0.1:55439/ax"
export RAG_INDEX_DATABASE_URL="postgresql://ax_rag_indexer@127.0.0.1:55439/ax"
export CORPUS_DIR="$ROOT_DIR/AX_Navigator_AI_MVP_v3/rag"
export RAG_INDEX_VERSION=ax-v3-pgvector-v1
export HF_HOME=${HF_HOME:-/private/tmp/ax-huggingface}
export HF_HUB_OFFLINE=${HF_HUB_OFFLINE:-1}
export TRANSFORMERS_OFFLINE=${TRANSFORMERS_OFFLINE:-1}
export TOKENIZERS_PARALLELISM=false
export TEST_SPRING_INTERNAL_URL=http://127.0.0.1:18081/internal
export LIVE_BUSINESS_MCP_URL=http://127.0.0.1:19101/mcp
export LIVE_RAG_MCP_URL=http://127.0.0.1:19102/mcp
.venv/bin/python rag-mcp/index.py >"$TASK_DIR/index.log" 2>&1
AX_TEST_STUB=1 INTERNAL_TOKEN=test-token .venv/bin/uvicorn scripts.spring_contract_stub:app --host 127.0.0.1 --port 18081 >"$TASK_DIR/stub.log" 2>&1 &
STUB_PID=$!
INTERNAL_TOKEN=test-token SPRING_INTERNAL_URL="$TEST_SPRING_INTERNAL_URL" MCP_HOST=127.0.0.1 MCP_PORT=19101 .venv/bin/python business-mcp/server.py >"$TASK_DIR/business.log" 2>&1 &
BUSINESS_PID=$!
MCP_HOST=127.0.0.1 MCP_PORT=19102 .venv/bin/python rag-mcp/server.py >"$TASK_DIR/rag.log" 2>&1 &
RAG_PID=$!
.venv/bin/python - <<'PY'
import os,time,httpx
for name in ('TEST_SPRING_INTERNAL_URL','LIVE_BUSINESS_MCP_URL','LIVE_RAG_MCP_URL'):
    url=os.environ[name]+('/solutions' if name=='TEST_SPRING_INTERNAL_URL' else '')
    for _ in range(80):
        try:
            r=httpx.get(url,headers={'X-Internal-Token':'test-token'},timeout=1)
            if r.status_code in {200,400,405,406}:break
        except httpx.RequestError:pass
        time.sleep(.2)
    else:raise RuntimeError(name+' startup failed')
PY
.venv/bin/python -m pytest agent/tests tests -q
