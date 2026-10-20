#!/bin/sh
set -eu
: "${RAG_READER_PASSWORD:?Set RAG_READER_PASSWORD}"
: "${RAG_INDEXER_PASSWORD:?Set RAG_INDEXER_PASSWORD}"
# Runs only when PostgreSQL initializes a fresh volume, after tables exist.
psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" \
  --set=db_name="$POSTGRES_DB" --set=reader_password="$RAG_READER_PASSWORD" \
  --set=indexer_password="$RAG_INDEXER_PASSWORD" <<'SQL'
CREATE ROLE ax_rag_reader LOGIN NOINHERIT PASSWORD :'reader_password';
CREATE ROLE ax_rag_indexer LOGIN NOINHERIT PASSWORD :'indexer_password';
GRANT CONNECT ON DATABASE :"db_name" TO ax_rag_reader, ax_rag_indexer;
GRANT USAGE ON SCHEMA public TO ax_rag_reader, ax_rag_indexer;
GRANT SELECT ON rag_indexes, rag_document_chunks TO ax_rag_reader, ax_rag_indexer;
GRANT SELECT(document_id,company_id,process_id,title,doc_type,access_level,version)
  ON documents TO ax_rag_reader, ax_rag_indexer;
GRANT INSERT,UPDATE,DELETE ON rag_indexes,rag_document_chunks TO ax_rag_indexer;
SQL
