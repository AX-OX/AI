"""v3 corpus contract. No external process map or legacy JSONL dependency."""
import hashlib
import json
import os
import re
from pathlib import Path

CORPUS = Path(os.getenv('CORPUS_DIR', str(Path(__file__).resolve().parents[1]/'AX_Navigator_AI_MVP_v3/rag')))
INDEX_VERSION = os.getenv('RAG_INDEX_VERSION','ax-v3-pgvector-v1')
REVISION = os.getenv('EMBEDDING_REVISION','e8f8c211226b894fcb81acc59f3b34ba3efd5f42')
MODEL = os.getenv('EMBEDDING_MODEL','sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2')
COMPANY_ID = int(os.getenv('RAG_COMPANY_ID','1'))
REQUIRED = {'document_id','title','doc_type','process_id','section','page','chunk_index','version','embedding_model','company_id','access_level'}


def chunks():
    rows=[json.loads(line) for line in (CORPUS/'pgvector_import.jsonl').read_text(encoding='utf-8').splitlines() if line.strip()]
    if not rows or len({r['id'] for r in rows})!=len(rows): raise ValueError('빈 청크 또는 중복 청크 ID')
    return rows


def mapping():
    raw=json.loads((CORPUS/'doc_mapping.json').read_text(encoding='utf-8'))['documents']
    docs={str(d['document_id']):d for d in raw}
    if len(raw)!=len(docs): raise ValueError('중복 문서 ID')
    for doc in docs.values():
        related=doc.get('related_process_ids')
        if doc['company_id']!=COMPANY_ID or not isinstance(related,list) or any(type(p) is not int for p in related):
            raise ValueError('문서 회사·업무 연결 정보 오류')
    for row in chunks():
        meta=row['metadata']
        if not REQUIRED <= meta.keys() or not row['document'].strip(): raise ValueError('청크 metadata 또는 본문 부족')
        doc=docs[str(meta['document_id'])]
        if any(meta[k]!=doc[k] for k in ('company_id','title','doc_type','process_id','access_level','version')):
            raise ValueError('문서 metadata 불일치')
        if meta['embedding_model']!=MODEL: raise ValueError('청크 임베딩 모델 불일치')
        if type(meta['page']) is not int or type(meta['chunk_index']) is not int: raise ValueError('페이지·청크 번호 오류')
    return docs


def mask(text):
    text=re.sub(r'[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}','[EMAIL]',text)
    text=re.sub(r'가상담당자[A-Z]','[NAME]',text)
    return re.sub(r'(?<!\d)0\d{1,2}[- ]?\d{3,4}[- ]?\d{4}(?!\d)','[PHONE]',text)


def corpus_hash():
    digest=hashlib.sha256()
    for name in ('pgvector_import.jsonl','doc_mapping.json'):
        digest.update(name.encode()+b'\0')
        digest.update((CORPUS/name).read_bytes())
    return digest.hexdigest()
