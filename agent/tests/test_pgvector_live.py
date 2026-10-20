"""Actual pgvector + MCP HTTP + FastAPI/checkpoint, Spring/LLM are explicit v3 fixtures."""
import json
import os
from pathlib import Path
from uuid import uuid4
from unittest.mock import patch
import httpx
import psycopg
import pytest
from agent.app.clients import Gateway
from agent.app.config import Settings
from agent.app.main import create_app
from agent.app.reasoning import MockReasoner
import sys

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'rag-mcp'))
import common
import pgvector_client as pg
DSN=os.getenv('RAG_TEST_DATABASE_URL')
pytestmark=pytest.mark.skipif(not DSN,reason='임시 pgvector DB 필요')


def synthetic_vectors(texts):
    # Only DB constraint/rollback tests; never used as a semantic-search claim.
    return [[1.0]+[0.0]*383 for _ in texts]


def records(): return common.chunks()


def test_atomic_replace_model_guard_and_filters():
    store=pg.PgVectorStore(dsn=DSN,embedder=synthetic_vectors)
    rows=records();assert store.replace(rows,common.mapping())==34
    hits=store.search('인사',doc_type='MANUAL',process_id=202,top_k=20)
    assert hits and {h['document_id'] for h in hits}=={401}
    assert store.replace(rows[:2],common.mapping())==2
    broken=pg.PgVectorStore(dsn=DSN,embedder=lambda texts:[[0]*384 for _ in texts])
    with pytest.raises(ValueError): broken.replace(rows,common.mapping())
    assert len(store.search('인사',top_k=20))==2
    with patch.object(pg,'MODEL','different-model'):
        with pytest.raises(ValueError,match='모델'):store.search('인사')
    assert store.replace(rows,common.mapping())==34


def test_real_embedding_semantic_search():
    store=pg.PgVectorStore(dsn=DSN)
    assert store.replace(records(),common.mapping())==34
    hits=store.search('코드 리뷰 보조는 기술 문서 구축과 개발자 승인이 필요한가?',doc_type='MANUAL',process_id=208,top_k=5)
    assert hits and hits[0]['document_id']==403 and '208' in hits[0]['section']
    assert all(0<=h['score']<=2 for h in hits)
    with psycopg.connect(DSN) as conn:
        assert conn.execute('SELECT min(vector_dims(embedding)),max(vector_dims(embedding)),count(*) FROM rag_document_chunks').fetchone()==(384,384,34)
        version=conn.execute('SHOW server_version').fetchone()[0]
        extension=conn.execute("SELECT extversion FROM pg_extension WHERE extname='vector'").fetchone()[0]
    report={'dataset':'v3','engine':'PostgreSQL pgvector','postgresql_version':version,'pgvector_version':extension,
            'embedding_model':common.MODEL,'embedding_revision':common.REVISION,'index_version':common.INDEX_VERSION,
            'chunks':34,'top_hits':hits}
    (ROOT/'reports/pgvector_search_v3.json').write_text(json.dumps(report,ensure_ascii=False,indent=2))


@pytest.mark.asyncio
async def test_fastapi_actual_mcp_and_pgvector_pipeline():
    base=os.getenv('TEST_SPRING_INTERNAL_URL')
    if not base:pytest.skip('테스트 전용 Spring 계약 fixture 서버 필요')
    cfg=Settings(mode='mock',internal_token='test-token',data_dir=ROOT/'AX_Navigator_AI_MVP_v3',spring_url=base,
        checkpoint_url=os.environ['AGENT_TEST_DATABASE_URL'],
        business_url=os.environ['LIVE_BUSINESS_MCP_URL'],rag_url=os.environ['LIVE_RAG_MCP_URL'])
    expected=json.loads((cfg.data_dir/'eval/demo_expected_portfolio.json').read_text())
    app=create_app(cfg,gateway=Gateway(cfg),reasoner=MockReasoner(cfg))
    key=str(uuid4());headers={'X-Internal-Token':'test-token'}
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://agent-test',headers=headers) as client:
            assert (await client.post(f'/tasks/{key}/run',json={'companyId':1,'userId':602,'requestText':'3억 원 내 최적 AX 로드맵'})).status_code==202
            job=app.state.jobs.get(key)
            if job: await job
            waiting=(await client.get(f'/tasks/{key}')).json()
            assert waiting['status']=='WAITING_APPROVAL',waiting
            assert waiting['result']['portfolio']['totalAxScore']==expected['total_ax_score']
            assert {c['solutionId'] for c in waiting['result']['portfolio']['selected']}==set(expected['selected_solution_ids'])
    # Recreate FastAPI process/graph, then resume persisted Postgres checkpoint.
    app2=create_app(cfg,gateway=Gateway(cfg),reasoner=MockReasoner(cfg))
    async with app2.router.lifespan_context(app2):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app2),base_url='http://agent-test',headers=headers) as client:
            assert (await client.post(f'/tasks/{key}/resume',json={'decision':'APPROVE','userId':601})).status_code==403
            assert (await client.post(f'/tasks/{key}/resume',json={'decision':'APPROVE','userId':602})).status_code==202
            job=app2.state.jobs.get(key)
            if job: await job
            final=(await client.get(f'/tasks/{key}')).json()
            assert final['status']=='DONE',final
            assert len(final['result']['registration']['projects'])==3
    report={'scope':'FastAPI ASGI + real Business/RAG MCP HTTP + actual pgvector + Postgres checkpoint; Spring responses and LLM reasoning are fixture mocks',
            'production_spring_tested':False,'live_llm_tested':False,'status':final['status'],'checkpoint_restart_resume':True,'result':final['result']}
    (ROOT/'reports/agent_v3_demo.json').write_text(json.dumps(report,ensure_ascii=False,indent=2))
    async with httpx.AsyncClient() as client:
        assert (await client.post(base+'/ax/roi',json={'processId':201,'solutionId':501})).status_code==403
