#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
# Requires PostgreSQL 16 and environment variable DATABASE_URL (e.g., postgresql://.../ax).
: "${DATABASE_URL:?Set DATABASE_URL for test PostgreSQL database.}"
psql "$DATABASE_URL" -v ON_ERROR_STOP=1 -f sql/00_schema_postgres16.sql
psql "$DATABASE_URL" -v ON_ERROR_STOP=1 -f sql/01_seed_input_postgres.sql
echo 'Input seeded. Optional, demo-only: fixtures/02_demo_waiting_approval.sql then fixtures/03_demo_after_requester_approval.sql'
