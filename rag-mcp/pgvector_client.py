"""pgvector 정확 cosine 검색. 업무 테이블은 조회하지 않으며 문서 소속 검증에만 JOIN한다."""
import json
import math
import os
import psycopg
from psycopg.rows import dict_row
from common import MODEL, INDEX_VERSION, COMPANY_ID, REVISION, DIMENSIONS, corpus_hash
from embeddings import embed
from diagnostics import RagConfigurationError

def vector_literal(values):
    values = [float(v) for v in values]
    if len(values) != DIMENSIONS or not all(math.isfinite(v) for v in values) or sum(v*v for v in values) == 0:
        raise ValueError('임베딩은 384차원의 유한한 비영벡터여야 합니다.')
    return '[' + ','.join(repr(v) for v in values) + ']'


class PgVectorStore:
    def __init__(self, *, dsn=None, embedder=None, write=False):
        self.dsn = dsn or os.getenv('RAG_INDEX_DATABASE_URL' if write else 'RAG_DATABASE_URL')
        if not self.dsn: raise RagConfigurationError('RAG_DB_URL_MISSING')
        self.embedder = embedder or embed

    def replace(self, rows, docs):
        with psycopg.connect(self.dsn, row_factory=dict_row) as conn:
            self._lock(conn)
            self._replace(conn, rows, docs)
        return len(rows)

    @staticmethod
    def _lock(conn):
        conn.execute('SELECT pg_advisory_xact_lock(hashtext(%s))', (f'rag:{COMPANY_ID}:{INDEX_VERSION}',))

    @staticmethod
    def _validate_documents(conn, rows, docs):
        if not rows or len({r['id'] for r in rows}) != len(rows): raise ValueError('빈 청크 또는 중복 청크 ID')
        found_docs = {}
        for row in rows:
            meta = row['metadata']
            if meta['company_id'] != COMPANY_ID: raise ValueError('색인 회사 범위 불일치')
            document_id = meta['document_id']
            if document_id not in found_docs:
                found_docs[document_id] = conn.execute(
                    'SELECT document_id,company_id,process_id,title,doc_type,access_level,version FROM documents WHERE document_id=%s AND company_id=%s',
                    (document_id, COMPANY_ID)).fetchone()
            found = found_docs[document_id]
            doc = docs[str(document_id)]
            if not found or any(found[k] != doc[k] for k in found):
                raise ValueError(f'원본 문서 metadata·회사 불일치: document_id={document_id}')
            if any(meta[k] != doc[k] for k in ('company_id','process_id','title','doc_type','access_level','version')) or meta['embedding_model'] != MODEL:
                raise ValueError('청크 metadata·모델 불일치')

    @staticmethod
    def _index_matches(conn, rows, docs):
        index = conn.execute('SELECT * FROM rag_indexes WHERE company_id=%s AND index_version=%s',
                             (COMPANY_ID, INDEX_VERSION)).fetchone()
        if not index or (index['embedding_model'], index['embedding_revision'], index['corpus_hash'], index['chunk_count']) != (MODEL, REVISION, corpus_hash(), len(rows)):
            return False
        stored = conn.execute('''SELECT chunk_id,document_id,title,doc_type,section,page,chunk_index,
                                        related_process_ids,content,metadata,embedding::text AS embedding
                                 FROM rag_document_chunks WHERE company_id=%s AND index_version=%s''',
                              (COMPANY_ID, INDEX_VERSION)).fetchall()
        expected = {row['id']: row for row in rows}
        if len(stored) != len(rows) or {r['chunk_id'] for r in stored} != set(expected):
            return False
        for chunk in stored:
            row = expected[chunk['chunk_id']]
            meta = row['metadata']
            if any(chunk[k] != meta[k] for k in ('document_id','title','doc_type','section','page','chunk_index')):
                return False
            if chunk['content'] != row['document'] or chunk['metadata'] != meta or chunk['related_process_ids'] != docs[str(meta['document_id'])]['related_process_ids']:
                return False
            try:
                vector_literal(json.loads(chunk['embedding']))
            except (ValueError, TypeError):
                return False
        return True

    def ensure_index(self, rows, docs):
        """Check, optionally replace, and verify under one transaction/lock."""
        with psycopg.connect(self.dsn, row_factory=dict_row) as conn:
            self._lock(conn)
            # Also check source ownership when skipping; no model load or DML on a match.
            print('RAG_INDEX phase=source_validation', flush=True)
            self._validate_documents(conn, rows, docs)
            print('RAG_INDEX phase=stored_index_validation', flush=True)
            if self._index_matches(conn, rows, docs):
                return {'status': 'skipped', 'chunks': len(rows)}
            self._replace(conn, rows, docs)
            print('RAG_INDEX phase=verification', flush=True)
            if not self._index_matches(conn, rows, docs):
                raise ValueError('색인 적재 후 검증 실패; 트랜잭션 롤백')
        return {'status': 'indexed', 'chunks': len(rows)}

    def _replace(self, conn, rows, docs):
        # Validate before loading the model, and before any DELETE/INSERT.
        self._validate_documents(conn, rows, docs)
        print('RAG_INDEX phase=embedding', flush=True)
        vectors = self.embedder([r['document'] for r in rows])
        if len(vectors) != len(rows): raise ValueError('임베딩 건수 불일치')
        literals = [vector_literal(v) for v in vectors]
        self._validate_documents(conn, rows, docs)
        print('RAG_INDEX phase=writing', flush=True)
        conn.execute('DELETE FROM rag_document_chunks WHERE company_id=%s AND index_version=%s', (COMPANY_ID, INDEX_VERSION))
        conn.execute('''INSERT INTO rag_indexes(company_id,index_version,embedding_model,embedding_revision,corpus_hash,chunk_count)
                            VALUES (%s,%s,%s,%s,%s,%s) ON CONFLICT(company_id,index_version) DO UPDATE SET
                            embedding_model=excluded.embedding_model, embedding_revision=excluded.embedding_revision,
                            corpus_hash=excluded.corpus_hash,chunk_count=excluded.chunk_count,indexed_at=now()''',
                     (COMPANY_ID, INDEX_VERSION, MODEL, REVISION, corpus_hash(), len(rows)))
        for row, vector in zip(rows, literals, strict=True):
            meta = dict(row['metadata'])
            doc = docs[str(meta['document_id'])]
            meta['embedding_model'] = MODEL
            conn.execute('''INSERT INTO rag_document_chunks(company_id,index_version,chunk_id,document_id,title,doc_type,section,page,chunk_index,related_process_ids,content,metadata,embedding)
                                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb,%s::vector)''',
                         (COMPANY_ID,INDEX_VERSION,row['id'],meta['document_id'],meta['title'],meta['doc_type'],meta['section'],meta['page'],meta['chunk_index'],doc['related_process_ids'],row['document'],json.dumps(meta,ensure_ascii=False),vector))

    @staticmethod
    def _require_index(conn):
        index = conn.execute('SELECT * FROM rag_indexes WHERE company_id=%s AND index_version=%s', (COMPANY_ID, INDEX_VERSION)).fetchone()
        if not index:
            raise RagConfigurationError('RAG_INDEX_MISSING')
        for field, expected, code in (
            ('embedding_model', MODEL, 'RAG_INDEX_MODEL_MISMATCH'),
            ('embedding_revision', REVISION, 'RAG_INDEX_REVISION_MISMATCH'),
            ('corpus_hash', corpus_hash(), 'RAG_INDEX_CORPUS_MISMATCH'),
        ):
            if index[field] != expected:
                raise RagConfigurationError(code)

    def assessment_evidence(self):
        """Read all readiness sections in the active company/index; no embedding call.

        Never silently truncate required sections. Large corpora need a separately
        paginated assessment contract rather than a partial readiness diagnosis.
        """
        with psycopg.connect(self.dsn, row_factory=dict_row) as conn:
            self._require_index(conn)
            rows = conn.execute('''SELECT c.chunk_id,c.document_id,c.title,c.doc_type,c.section,c.page,c.content
                                   FROM rag_document_chunks c JOIN documents d
                                     ON d.document_id=c.document_id AND d.company_id=c.company_id
                                   WHERE c.company_id=%s AND c.index_version=%s
                                     AND c.doc_type=ANY(%s)
                                   ORDER BY c.document_id,c.chunk_index,c.chunk_id LIMIT 201''',
                                (COMPANY_ID,INDEX_VERSION,['SYSTEM_SPEC','POLICY','AI_STATUS','DATA_QUALITY','PROJECT_REPORT'])).fetchall()
            if len(rows) > 200:
                raise RagConfigurationError('RAG_EVIDENCE_LIMIT')
            if not rows:
                raise RagConfigurationError('RAG_EVIDENCE_EMPTY')
            return rows

    def search(self, query, doc_type=None, process_id=None, top_k=5):
        if not query.strip() or not 1 <= top_k <= 20: raise ValueError('검색어와 top_k 1~20이 필요합니다.')
        with psycopg.connect(self.dsn, row_factory=dict_row) as conn:
            self._require_index(conn)
            vector = vector_literal(self.embedder([query])[0])
            return conn.execute('''SELECT c.document_id,c.title,c.doc_type,c.section,c.page,c.content,
                                          (c.embedding <=> %s::vector)::float8 AS score
                                   FROM rag_document_chunks c JOIN documents d ON d.document_id=c.document_id AND d.company_id=c.company_id
                                   WHERE c.company_id=%s AND c.index_version=%s
                                     AND (%s::text IS NULL OR c.doc_type=%s)
                                     AND (%s::bigint IS NULL OR %s=ANY(c.related_process_ids) OR cardinality(c.related_process_ids)=0)
                                   ORDER BY c.embedding <=> %s::vector,c.chunk_id LIMIT %s''',
                                (vector,COMPANY_ID,INDEX_VERSION,doc_type,doc_type,process_id,process_id,vector,top_k)).fetchall()
