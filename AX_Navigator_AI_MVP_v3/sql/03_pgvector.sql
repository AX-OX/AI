CREATE EXTENSION IF NOT EXISTS vector;
CREATE TABLE IF NOT EXISTS rag_indexes (
    company_id BIGINT NOT NULL REFERENCES companies(company_id),
    index_version TEXT NOT NULL,
    embedding_model TEXT NOT NULL,
    embedding_revision TEXT NOT NULL,
    corpus_hash TEXT NOT NULL,
    chunk_count INTEGER NOT NULL CHECK (chunk_count > 0),
    indexed_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (company_id, index_version)
);
CREATE TABLE IF NOT EXISTS rag_document_chunks (
    company_id BIGINT NOT NULL,
    index_version TEXT NOT NULL,
    chunk_id TEXT NOT NULL,
    document_id BIGINT NOT NULL REFERENCES documents(document_id),
    title TEXT NOT NULL,
    doc_type TEXT NOT NULL,
    section TEXT NOT NULL,
    page INTEGER NOT NULL,
    chunk_index INTEGER NOT NULL,
    related_process_ids BIGINT[] NOT NULL,
    content TEXT NOT NULL,
    metadata JSONB NOT NULL,
    embedding vector(384) NOT NULL,
    PRIMARY KEY (company_id, index_version, chunk_id),
    FOREIGN KEY (company_id, index_version) REFERENCES rag_indexes(company_id, index_version)
);
-- MVP는 정확 cosine 검색을 사용한다. 대규모화 전 ANN과 필터 recall을 별도 검증한다.
CREATE INDEX IF NOT EXISTS rag_chunks_scope ON rag_document_chunks(company_id, index_version, document_id);
