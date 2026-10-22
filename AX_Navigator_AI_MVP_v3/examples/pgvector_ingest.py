#!/usr/bin/env python3
"""Actual pgvector indexing and reference search for the portable v3 corpus.
Dependencies: requirements-pgvector.txt. Connection credentials are environment-only.
No business table writes. Does not install extensions or provision accounts.
"""
import hashlib
import json
import math
import os
import re
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
MODEL='text-embedding-3-small'
REVISION='openai-dim384-v1'
DIMENSIONS=384
REQUIRED={'document_id','title','doc_type','process_id','section','page','chunk_index','version','embedding_model','company_id','access_level'}

def corpus_hash(root):
    digest=hashlib.sha256()
    for name in ('pgvector_import.jsonl','doc_mapping.json'):
        digest.update(name.encode()+b'\0')
        digest.update((Path(root)/'rag'/name).read_bytes())
    return digest.hexdigest()

def load_corpus(root=ROOT):
    root=Path(root)
    raw=json.loads((root/'rag/doc_mapping.json').read_text())['documents']
    docs={d['document_id']:d for d in raw}
    if len(docs)!=len(raw): raise ValueError('Duplicate document ID')
    chunks=[json.loads(line) for line in (root/'rag/pgvector_import.jsonl').read_text().splitlines() if line.strip()]
    if not chunks or len({r['id'] for r in chunks})!=len(chunks): raise ValueError('Empty corpus or duplicate chunk ID')
    model=os.getenv('EMBEDDING_MODEL',MODEL)
    for row in chunks:
        meta=row['metadata']
        if not REQUIRED<=meta.keys() or not row['document'].strip(): raise ValueError('Missing metadata or empty content')
        d=docs[meta['document_id']]
        for field in ('company_id','title','doc_type','process_id','access_level','version'):
            if meta[field]!=d[field]: raise ValueError(f'Document metadata mismatch: {field}')
        if not isinstance(meta['page'],int) or not isinstance(meta['chunk_index'],int): raise ValueError('Invalid page/chunk index')
        if meta['embedding_model']!=model: raise ValueError('Corpus embedding_model differs from encoder')
        if not isinstance(d['related_process_ids'],list) or any(not isinstance(p,int) for p in d['related_process_ids']): raise ValueError('Invalid related_process_ids')
    return chunks,docs

def vector_literal(values):
    values=[float(v) for v in values]
    if len(values)!=DIMENSIONS or not all(math.isfinite(v) for v in values) or sum(v*v for v in values)==0:
        raise ValueError('Expected 384-dimensional finite nonzero embedding')
    return '['+','.join(repr(v) for v in values)+']'

class PgVectorIndex:
    def __init__(self,root=ROOT,*,dsn=None,write=False,embedder=None,company_id=None,index_version=None):
        self.root=Path(root)
        self.company_id=company_id if company_id is not None else int(os.getenv('RAG_COMPANY_ID','1'))
        self.version=index_version or os.getenv('RAG_INDEX_VERSION','ax-v3-openai-small-384-v1')
        self.model=os.getenv('EMBEDDING_MODEL',MODEL)
        self.revision=os.getenv('EMBEDDING_REVISION',REVISION)
        self.dsn=dsn or os.getenv('RAG_INDEX_DATABASE_URL' if write else 'RAG_DATABASE_URL')
        if not self.dsn: raise ValueError('Set RAG_INDEX_DATABASE_URL for ingest or RAG_DATABASE_URL for search')
        self._embedder=embedder

    def embed(self,texts):
        if self._embedder: return self._embedder(texts)
        # Same provider and dimensions as rag-mcp; batches preserve input order.
        from openai import OpenAI
        vectors=[]
        with OpenAI(timeout=45, max_retries=2) as client:
            for start in range(0,len(texts),16):
                batch=[re.sub(r"(?<!\d)0\d{1,2}[- ]?\d{3,4}[- ]?\d{4}(?!\d)", "[PHONE]",
                              re.sub(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}", "[EMAIL]", text))
                       for text in texts[start:start+16]]
                response=client.embeddings.create(model=self.model,input=batch,dimensions=DIMENSIONS,encoding_format='float')
                rows=sorted(response.data,key=lambda item:item.index)
                if [r.index for r in rows]!=list(range(len(batch))): raise ValueError('Embedding response indices mismatch')
                for row in rows:
                    vector_literal(row.embedding)
                    vectors.append(row.embedding)
        return vectors

    def replace(self):
        import psycopg
        from psycopg.rows import dict_row
        chunks,docs=load_corpus(self.root)
        if any(r['metadata']['company_id']!=self.company_id for r in chunks): raise ValueError('Corpus company mismatch')
        vectors=self.embed([r['document'] for r in chunks])
        if len(vectors)!=len(chunks): raise ValueError('Embedding count mismatch')
        literals=[vector_literal(v) for v in vectors]
        with psycopg.connect(self.dsn,row_factory=dict_row) as conn:
            conn.execute('SELECT pg_advisory_xact_lock(hashtext(%s))',(f'rag:{self.company_id}:{self.version}',))
            for doc in docs.values():
                found=conn.execute('SELECT document_id,company_id,process_id,title,doc_type,access_level,version FROM documents WHERE document_id=%s AND company_id=%s',(doc['document_id'],self.company_id)).fetchone()
                if not found or any(found[k]!=doc[k] for k in found): raise ValueError('Database document metadata/company mismatch')
                # Ownership of related process IDs is validated without granting other business table reads:
                # validate_final.py verifies process membership against the input CSV/SQL contract.
            conn.execute('DELETE FROM rag_document_chunks WHERE company_id=%s AND index_version=%s',(self.company_id,self.version))
            conn.execute('''INSERT INTO rag_indexes(company_id,index_version,embedding_model,embedding_revision,corpus_hash,chunk_count)
                VALUES (%s,%s,%s,%s,%s,%s) ON CONFLICT(company_id,index_version) DO UPDATE SET
                embedding_model=excluded.embedding_model,embedding_revision=excluded.embedding_revision,
                corpus_hash=excluded.corpus_hash,chunk_count=excluded.chunk_count,indexed_at=now()''',
                (self.company_id,self.version,self.model,self.revision,corpus_hash(self.root),len(chunks)))
            for row,vector in zip(chunks,literals):
                m=row['metadata']
                conn.execute('''INSERT INTO rag_document_chunks(company_id,index_version,chunk_id,document_id,title,doc_type,section,page,chunk_index,related_process_ids,content,metadata,embedding)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb,%s::vector)''',
                    (self.company_id,self.version,row['id'],m['document_id'],m['title'],m['doc_type'],m['section'],m['page'],m['chunk_index'],docs[m['document_id']]['related_process_ids'],row['document'],json.dumps(m,ensure_ascii=False),vector))
        return len(chunks)

    def search(self,query,doc_type=None,process_id=None,top_k=5):
        import psycopg
        from psycopg.rows import dict_row
        if not query.strip() or not 1<=top_k<=50: raise ValueError('Query required; top_k must be 1..50')
        with psycopg.connect(self.dsn,row_factory=dict_row) as conn:
            index=conn.execute('SELECT embedding_model,embedding_revision,corpus_hash FROM rag_indexes WHERE company_id=%s AND index_version=%s',(self.company_id,self.version)).fetchone()
            if not index or (index['embedding_model'],index['embedding_revision'],index['corpus_hash'])!=(self.model,self.revision,corpus_hash(self.root)):
                raise ValueError('Index missing or model/revision/corpus mismatch; reindex required')
            vector=vector_literal(self.embed([query])[0])
            return conn.execute('''SELECT c.document_id,c.title,c.doc_type,c.section,c.page,c.content,
                    (c.embedding <=> %s::vector)::float8 AS score
                FROM rag_document_chunks c JOIN documents d ON d.document_id=c.document_id AND d.company_id=c.company_id
                WHERE c.company_id=%s AND c.index_version=%s AND (%s::text IS NULL OR c.doc_type=%s)
                    AND (%s::bigint IS NULL OR %s=ANY(c.related_process_ids) OR cardinality(c.related_process_ids)=0)
                ORDER BY c.embedding <=> %s::vector,c.chunk_id LIMIT %s''',
                (vector,self.company_id,self.version,doc_type,doc_type,process_id,process_id,vector,top_k)).fetchall()

if __name__=='__main__':
    print(json.dumps(dict(indexed_chunks=PgVectorIndex(write=True).replace(),store='PostgreSQL pgvector')))
