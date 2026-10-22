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
    row = {'embedding_model': pg.MODEL, 'embedding_revision': pg.REVISION,
           'corpus_hash': pg.corpus_hash()}
    if field: row[field] = 'old-value'
    conn = Mock()
    conn.execute.return_value.fetchone.return_value = row if field else None
    with pytest.raises(RagConfigurationError, match=code):
        pg.PgVectorStore._require_index(conn)


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
