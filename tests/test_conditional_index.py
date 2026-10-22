"""Conditional index tests. DB tests accept ONLY the named disposable local DB."""
import asyncio
from concurrent.futures import ThreadPoolExecutor
import copy
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
from unittest.mock import Mock, patch
from uuid import uuid4

import psycopg
from psycopg.conninfo import conninfo_to_dict
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'rag-mcp'))
import common
import index as indexer
import pgvector_client as pg

DSN = os.getenv('AX_RAG_TEST_DATABASE_URL')


@pytest.fixture
def context(monkeypatch):
    if not DSN:
        pytest.skip('AX_RAG_TEST_DATABASE_URL: disposable local pgvector DB required')
    params = conninfo_to_dict(DSN)
    assert params.get('dbname') == 'ax_rag_conditional_test', 'Refusing a non-test DB'
    assert params.get('host') in {'127.0.0.1', 'localhost'}, 'Refusing a remote DB'
    monkeypatch.setattr(pg, 'INDEX_VERSION', 'test-' + uuid4().hex)
    rows, docs = common.chunks(), common.mapping()
    calls = []

    def embed(texts):
        calls.append(len(texts))
        # Synthetic vectors test transactions, not semantic quality.
        return [[1.0] + [0.0] * 383 for _ in texts]

    return pg.PgVectorStore(dsn=DSN, embedder=embed), rows, docs, calls


def snapshot():
    with psycopg.connect(DSN) as conn:
        index = conn.execute('SELECT *, xmin::text FROM rag_indexes WHERE company_id=%s AND index_version=%s',
                             (pg.COMPANY_ID, pg.INDEX_VERSION)).fetchall()
        chunks = conn.execute('SELECT *, xmin::text FROM rag_document_chunks WHERE company_id=%s AND index_version=%s ORDER BY chunk_id',
                              (pg.COMPANY_ID, pg.INDEX_VERSION)).fetchall()
    return index, chunks


def test_command_reuses_conditional_store(capsys):
    store = Mock()
    store.ensure_index.return_value = {'status': 'skipped', 'chunks': 34}
    assert indexer.main(store, if_needed=True) == 34
    store.ensure_index.assert_called_once()
    store.replace.assert_not_called()
    assert json.loads(capsys.readouterr().out.splitlines()[-1]) == {'status': 'skipped', 'chunks': 34}


@pytest.mark.parametrize('writer', [False, True])
def test_cli_failure_exit_and_no_credentials_in_logs(writer):
    secret = 'local-test-password-must-not-be-logged'
    dsn = f'postgresql://local_user:{secret}@127.0.0.1:1/ax_rag_conditional_test?connect_timeout=1'
    # Isolate the missing-writer case from a developer's root .env.
    env = {'CORPUS_DIR': str(ROOT / 'AX_Navigator_AI_MVP_v3/rag'), 'RAG_DATABASE_URL': dsn,
           'RAG_INDEX_DATABASE_URL': ''}
    if writer:
        env['RAG_INDEX_DATABASE_URL'] = dsn
    result = subprocess.run([sys.executable, str(ROOT / 'rag-mcp/index.py'), '--if-needed'],
                            env=env, text=True, capture_output=True, timeout=10)
    assert result.returncode == 1
    assert 'RAG_INDEX_FAILED' in result.stderr
    assert secret not in result.stdout + result.stderr and dsn not in result.stdout + result.stderr
    if not writer:
        # Reader credentials must never be used as a fallback for the indexer.
        assert 'error=ValueError' in result.stderr


def test_initial_index(context):
    store, rows, docs, calls = context
    assert snapshot() == ([], [])
    assert store.ensure_index(rows, docs) == {'status': 'indexed', 'chunks': 34}
    index, chunks = snapshot()
    assert len(index) == 1 and len(chunks) == 34 and calls == [34]


def test_valid_index_skips_without_writes_or_model(context):
    store, rows, docs, calls = context
    store.ensure_index(rows, docs)
    before = snapshot()  # Includes xmin and indexed_at: even identical writes are detected.
    assert store.ensure_index(rows, docs)['status'] == 'skipped'
    assert calls == [34] and snapshot() == before


@pytest.mark.parametrize('change', ['corpus', 'revision', 'model', 'index_version'])
def test_changed_input_reindexes(context, monkeypatch, change):
    store, rows, docs, calls = context
    store.ensure_index(rows, docs)
    if change == 'corpus':
        rows = copy.deepcopy(rows)
        rows[0]['document'] += '\n변경된 테스트 문서'
        monkeypatch.setattr(pg, 'corpus_hash', lambda: 'changed-test-corpus')
    elif change == 'revision':
        monkeypatch.setattr(pg, 'REVISION', 'changed-test-revision')
    elif change == 'model':
        monkeypatch.setattr(pg, 'MODEL', 'changed-test-model')
        rows = copy.deepcopy(rows)
        for row in rows:
            row['metadata']['embedding_model'] = pg.MODEL
    else:
        monkeypatch.setattr(pg, 'INDEX_VERSION', 'test-' + uuid4().hex)
    assert store.ensure_index(rows, docs)['status'] == 'indexed'
    assert store.ensure_index(rows, docs)['status'] == 'skipped'
    assert calls == [34, 34]


def test_document_version_change(context, monkeypatch):
    store, rows, docs, calls = context
    store.ensure_index(rows, docs)
    changed_rows, changed_docs = copy.deepcopy(rows), copy.deepcopy(docs)
    changed_docs['401']['version'] = 'test-v4'
    for row in changed_rows:
        if row['metadata']['document_id'] == 401:
            row['metadata']['version'] = 'test-v4'
    try:
        with psycopg.connect(DSN) as conn:
            conn.execute("UPDATE documents SET version='test-v4' WHERE document_id=401")
        monkeypatch.setattr(pg, 'corpus_hash', lambda: 'document-test-v4')
        assert store.ensure_index(changed_rows, changed_docs)['status'] == 'indexed'
        assert calls == [34, 34]
    finally:
        with psycopg.connect(DSN) as conn:
            conn.execute('UPDATE documents SET version=%s WHERE document_id=401', (docs['401']['version'],))


@pytest.mark.parametrize('damage', ['count', 'missing', 'body', 'metadata', 'mapping', 'zero_vector'])
def test_damaged_data_is_repaired(context, damage):
    store, rows, docs, calls = context
    store.ensure_index(rows, docs)
    scope = (pg.COMPANY_ID, pg.INDEX_VERSION)
    with psycopg.connect(DSN) as conn:
        if damage == 'count':
            conn.execute('UPDATE rag_indexes SET chunk_count=1 WHERE company_id=%s AND index_version=%s', scope)
        elif damage == 'missing':
            conn.execute('DELETE FROM rag_document_chunks WHERE company_id=%s AND index_version=%s AND chunk_id=%s', (*scope, rows[0]['id']))
        else:
            assignments = {'body': "content='damaged'", 'metadata': "metadata='{}'::jsonb",
                           'mapping': 'related_process_ids=ARRAY[999]::bigint[]',
                           'zero_vector': 'embedding=%s::vector'}
            args = ([json.dumps([0.0] * 384)] if damage == 'zero_vector' else []) + [*scope, rows[0]['id']]
            conn.execute('UPDATE rag_document_chunks SET ' + assignments[damage] + ' WHERE company_id=%s AND index_version=%s AND chunk_id=%s', args)
    assert store.ensure_index(rows, docs)['status'] == 'indexed'
    assert store.ensure_index(rows, docs)['status'] == 'skipped'
    assert calls == [34, 34]


def test_source_mismatch_aborts_even_when_index_exists(context):
    store, rows, docs, calls = context
    store.ensure_index(rows, docs)
    before = snapshot()
    docs = copy.deepcopy(docs)
    docs['401']['version'] = 'not-the-db-version'
    with pytest.raises(ValueError, match='원본 문서'):
        store.ensure_index(rows, docs)
    assert snapshot() == before and calls == [34]


@pytest.mark.parametrize('failure', ['model', 'database_write', 'verification', 'connect'])
def test_failures_preserve_previous_index(context, monkeypatch, failure):
    store, rows, docs, _ = context
    store.ensure_index(rows, docs)
    before = snapshot()
    monkeypatch.setattr(pg, 'corpus_hash', lambda: 'force-replacement')
    if failure == 'model':
        store.embedder = Mock(side_effect=RuntimeError('test model failure'))
    elif failure == 'database_write':
        original = store._replace
        def failing_write(conn, rows, docs):
            original(conn, rows, docs)
            conn.execute('SELECT 1/0')  # Abort the real test transaction after RAG writes.
        monkeypatch.setattr(store, '_replace', failing_write)
    elif failure == 'verification':
        monkeypatch.setattr(store, '_index_matches', lambda *args: False)
    if failure == 'connect':
        with patch.object(pg.psycopg, 'connect', side_effect=psycopg.OperationalError('test connection failure')):
            with pytest.raises(psycopg.OperationalError):
                store.ensure_index(rows, docs)
    else:
        with pytest.raises((RuntimeError, ValueError, psycopg.Error)):
            store.ensure_index(rows, docs)
    assert snapshot() == before


def test_concurrent_runs_only_embed_once(context, monkeypatch):
    store, rows, docs, calls = context
    entered, release = threading.Event(), threading.Event()
    original = store.embedder
    original_lock = store._lock
    attempts = []
    second_lock_attempt = threading.Event()
    def observed_lock(conn):
        attempts.append(1)
        if len(attempts) == 2:
            second_lock_attempt.set()
        original_lock(conn)
    monkeypatch.setattr(store, '_lock', observed_lock)
    def slow_embed(texts):
        entered.set()
        assert release.wait(10)
        return original(texts)
    store.embedder = slow_embed
    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(store.ensure_index, rows, docs)
        assert entered.wait(10)
        second = pool.submit(store.ensure_index, rows, docs)
        try:
            assert second_lock_attempt.wait(10)
            assert not second.done()
        finally:
            release.set()
        statuses = {first.result(timeout=20)['status'], second.result(timeout=20)['status']}
    assert statuses == {'indexed', 'skipped'} and calls == [34]
    assert len(snapshot()[1]) == 34


def test_other_index_version_is_unchanged(context, monkeypatch):
    store, rows, docs, _ = context
    store.ensure_index(rows, docs)
    before = snapshot()
    with monkeypatch.context() as scope:
        scope.setattr(pg, 'INDEX_VERSION', 'test-' + uuid4().hex)
        store.ensure_index(rows, docs)
    assert snapshot() == before


def test_search_docs_after_indexing(context):
    store, rows, docs, _ = context
    store.ensure_index(rows, docs)
    spec = importlib.util.spec_from_file_location('conditional_rag_server', ROOT / 'rag-mcp/server.py')
    server = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(server)
    from fastmcp import Client
    from agent.app.clients.mcp import decode_tool_result
    async def search():
        with patch.object(server, 'PgVectorStore', return_value=store):
            async with Client(server.mcp) as client:
                result = await client.call_tool('search_docs', {'query':'인사 업무', 'doc_type':'MANUAL', 'process_id':202})
        return decode_tool_result(result)
    hits = asyncio.run(search())
    assert hits and {hit['document_id'] for hit in hits} == {401}


@pytest.mark.skipif(os.getenv('AX_TEST_OPENAI_EMBEDDINGS') != '1', reason='Actual OpenAI API requires explicit opt-in')
def test_real_model_semantic_search(context):
    _, rows, docs, _ = context
    store = pg.PgVectorStore(dsn=DSN)
    assert store.ensure_index(rows, docs)['status'] == 'indexed'
    hits = store.search('코드 리뷰 보조에 기술 문서와 개발자 승인이 필요한가?', doc_type='MANUAL', process_id=208)
    assert hits and all(h['document_id'] == 403 for h in hits)
    assert any(h['section'].startswith('208 ') for h in hits[:3])
    assert store.ensure_index(rows, docs)['status'] == 'skipped'


def test_readiness_lookup_is_complete_and_never_embeds(context):
    store,rows,docs,calls=context
    store.ensure_index(rows,docs)
    before=len(calls)
    store.embedder=lambda _: (_ for _ in ()).throw(AssertionError('Readiness lookup must not embed'))
    evidence=store.assessment_evidence()
    assert len(evidence)==19 and len(calls)==before
    assert {(r['document_id'],r['section']) for r in evidence} >= {
        (404,'개인정보 처리'),(405,'업무 연결'),(407,'표준화 점검'),(408,'가상 사전 실험')}
    assert all(r['doc_type']!='MANUAL' for r in evidence)


def test_readiness_lookup_rejects_mismatched_index(context,monkeypatch):
    store,rows,docs,_=context
    store.ensure_index(rows,docs)
    monkeypatch.setattr(pg,'REVISION','wrong-test-config')
    with pytest.raises(ValueError,match='모델'):store.assessment_evidence()
