"""Deployment failure cases use actual FastMCP, without cloud credentials."""
import importlib.util
from pathlib import Path
import sys
from unittest.mock import Mock, patch

import psycopg
import pytest
from fastmcp import FastMCP
from fastmcp.exceptions import ToolError
from agent.app.clients.mcp import Gateway
from agent.app.config import Settings
from agent.app.tool_errors import safe_tool_failure

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'rag-mcp'))
from diagnostics import RagConfigurationError, report_failure
import pgvector_client as pg


@pytest.mark.parametrize('field,code', [
    (None, 'RAG_INDEX_MISSING'),
    ('embedding_model', 'RAG_INDEX_MODEL_MISMATCH'),
    ('embedding_revision', 'RAG_INDEX_REVISION_MISMATCH'),
    ('corpus_hash', 'RAG_INDEX_CORPUS_MISMATCH'),
])
def test_index_mismatch_has_specific_code(field, code):
    row = {'index_version': pg.INDEX_VERSION, 'embedding_model': pg.MODEL, 'embedding_revision': pg.REVISION,
           'corpus_hash': pg.corpus_hash()}
    if field: row[field] = 'old-value'
    conn = Mock()
    conn.execute.return_value.fetchall.return_value = [row] if field else []
    with pytest.raises(RagConfigurationError, match=code):
        pg.PgVectorStore._require_index(conn)


def test_upload_index_needs_no_seed_corpus_and_seed_company_needs_seed_index():
    upload = {'index_version': pg.UPLOAD_INDEX_VERSION, 'embedding_model': pg.MODEL,
              'embedding_revision': pg.REVISION, 'corpus_hash': pg.UPLOAD_CORPUS}
    conn = Mock()
    conn.execute.return_value.fetchall.return_value = [upload]
    assert pg.PgVectorStore._require_index(conn, 2) == [pg.UPLOAD_INDEX_VERSION]
    with pytest.raises(RagConfigurationError, match='RAG_INDEX_MISSING'):
        pg.PgVectorStore._require_index(conn, pg.COMPANY_ID)
    conn.execute.return_value.fetchall.return_value = [{**upload, 'embedding_model': 'old-model'}]
    with pytest.raises(RagConfigurationError, match='RAG_INDEX_MODEL_MISMATCH'):
        pg.PgVectorStore._require_index(conn, 2)


def test_upload_chunks_split_pages_and_skip_blank_pages():
    long = '가' * 1300
    rows = pg.upload_chunks(2, 9001, '회사 소개.pdf', [
        {'page': 1, 'text': '첫 문단\n\n둘째 문단'}, {'page': 2, 'text': '   '}, {'page': 3, 'text': long}])
    assert [(r['page'], r['section']) for r in rows] == [(1, 'p.1'), (3, 'p.3'), (3, 'p.3')]
    assert rows[0]['content'] == '첫 문단\n\n둘째 문단'
    assert max(len(r['content']) for r in rows) <= pg.CHUNK_CHARS
    assert len({r['chunk_id'] for r in rows}) == 3 and [r['chunk_index'] for r in rows] == [0, 1, 2]
    assert all(r['doc_type'] == 'UPLOADED' for r in rows)
    assert pg.upload_chunks(2, 9001, 'scan.pdf', [{'page': 1, 'text': ''}]) == []


@pytest.mark.parametrize('exc,code', [
    (psycopg.errors.InsufficientPrivilege('secret-password'), 'RAG_DB_PERMISSION_DENIED'),
    (psycopg.errors.UndefinedTable('secret-password'), 'RAG_DB_TABLE_MISSING'),
    (psycopg.OperationalError('secret-password'), 'RAG_DB_CONNECTION_FAILED'),
    (FileNotFoundError('secret-password'), 'RAG_CORPUS_MISSING'),
    (RuntimeError('secret-password'), 'RAG_INTERNAL_ERROR'),
])
def test_safe_server_logging(exc, code, caplog):
    assert report_failure('get_assessment_evidence', exc) == code
    assert code in caplog.text
    assert 'secret-password' not in caplog.text


@pytest.mark.asyncio
@pytest.mark.parametrize('code', ['RAG_INDEX_MISSING', 'RAG_DB_PERMISSION_DENIED',
                                 'RAG_INDEX_CORPUS_MISMATCH'])
async def test_real_mcp_error_reaches_agent_and_probe(code, caplog):
    server = FastMCP('deployment-test')
    @server.tool
    def get_assessment_evidence() -> list[dict]:
        raise ToolError(code + ': private-password-must-not-leak')
    @server.tool
    def search_docs(query: str) -> list[dict]:
        return []
    gateway = Gateway(Settings(mode='live', internal_token='test'))
    async def no_callback(*args, **kwargs): pass
    gateway._spring = no_callback
    with patch('agent.app.clients.mcp.StreamableHttpTransport', return_value=server):
        probe = await gateway.check_rag()
        assert probe['code'] == code
        with pytest.raises(ValueError, match=code) as caught:
            await gateway.tool('task', 'retrieve', 'get_assessment_evidence', {})
    assert 'private-password' not in str(caught.value)
    assert code in caplog.text


@pytest.mark.asyncio
async def test_old_rag_server_detected():
    server = FastMCP('old-rag')
    gateway = Gateway(Settings(mode='live', internal_token='test'))
    async def no_callback(*args, **kwargs): pass
    gateway._spring = no_callback
    with patch('agent.app.clients.mcp.StreamableHttpTransport', return_value=server):
        assert (await gateway.check_rag())['code'] == 'RAG_TOOL_MISSING'
        with pytest.raises(ValueError, match='RAG_TOOL_MISSING'):
            await gateway.tool('task', 'retrieve', 'get_assessment_evidence', {})


def test_unknown_exception_never_exposes_text():
    code, message = safe_tool_failure(RuntimeError('postgresql://user:password@private/db'))
    assert code == 'MCP_CALL_FAILED'
    assert 'password' not in message and 'private' not in message

@pytest.mark.asyncio
@pytest.mark.parametrize('exc,code', [
    (RagConfigurationError('RAG_INDEX_MISSING'), 'RAG_INDEX_MISSING'),
    (psycopg.errors.InsufficientPrivilege('postgresql://user:private-secret@db'),
     'RAG_DB_PERMISSION_DENIED'),
])
async def test_actual_rag_handler_to_agent_error_boundary(exc, code):
    spec = importlib.util.spec_from_file_location('rag_failure_test', ROOT / 'rag-mcp/server.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    store = Mock()
    store.assessment_evidence.side_effect = exc
    gateway = Gateway(Settings(mode='live', internal_token='test'))
    async def no_callback(*args, **kwargs): pass
    gateway._spring = no_callback
    with patch.object(module, 'PgVectorStore', return_value=store), \
         patch('agent.app.clients.mcp.StreamableHttpTransport', return_value=module.mcp):
        assert (await gateway.check_rag())['code'] == code
        with pytest.raises(ValueError, match=code) as caught:
            await gateway.tool('task', 'retrieve', 'get_assessment_evidence', {})
        assert 'private-secret' not in str(caught.value)


def test_diagnostic_endpoint_requires_internal_auth(monkeypatch):
    from fastapi.testclient import TestClient
    from langgraph.checkpoint.memory import InMemorySaver
    from agent.app.main import create_app
    from agent.app.reasoning import MockReasoner
    from unittest.mock import AsyncMock
    monkeypatch.setenv('OPENAI_API_KEY', 'not-a-real-key')
    settings = Settings(mode='live', model='test', internal_token='test-token')
    gateway = Gateway(settings)
    gateway.check_rag = AsyncMock(return_value={'status': 'ok', 'evidenceCount': 19})
    app = create_app(settings, gateway=gateway, reasoner=MockReasoner(), checkpointer=InMemorySaver())
    with TestClient(app) as client:
        assert client.get('/diagnostics/rag').status_code == 403
        gateway.check_rag.assert_not_called()
        response = client.get('/diagnostics/rag', headers={'X-Internal-Token': 'test-token'})
        assert response.json() == {'status': 'ok', 'evidenceCount': 19}
