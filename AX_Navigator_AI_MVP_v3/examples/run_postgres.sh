#!/usr/bin/env bash
set -euo pipefail
# DATABASE_URL: fresh, disposable DB with an extension-install-capable setup account.
# --with-demo applies explicit synthetic requester-approval fixtures. Never use on production.
if [[ -n "${1:-}" && "${1:-}" != "--with-demo" ]]; then
  echo 'Usage: run_postgres.sh [--with-demo]' >&2
  exit 2
fi
: "${DATABASE_URL:?Set DATABASE_URL to a fresh PostgreSQL 16 database}"
package_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
psql "$DATABASE_URL" -X -v ON_ERROR_STOP=1 -f "$package_root/sql/00_schema_postgres16.sql"
psql "$DATABASE_URL" -X -v ON_ERROR_STOP=1 -f "$package_root/sql/01_seed_input_postgres.sql"
psql "$DATABASE_URL" -X -v ON_ERROR_STOP=1 -f "$package_root/sql/03_pgvector.sql"
if [[ "${1:-}" == "--with-demo" ]]; then
  psql "$DATABASE_URL" -X -v ON_ERROR_STOP=1 -f "$package_root/fixtures/02_demo_waiting_approval.sql"
  psql "$DATABASE_URL" -X -v ON_ERROR_STOP=1 -f "$package_root/fixtures/03_demo_after_requester_approval.sql"
fi
# Account provisioning/GRANT is deployment-specific. See README before ingesting.
echo 'SQL applied. Configure RAG_INDEX_DATABASE_URL then run examples/pgvector_ingest.py.'
