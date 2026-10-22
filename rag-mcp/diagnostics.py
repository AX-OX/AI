"""Safe deployment diagnostics: never include driver messages or DSNs."""
import logging
import psycopg

logger = logging.getLogger(__name__)


class RagConfigurationError(ValueError):
    def __init__(self, code):
        self.code = code
        super().__init__(code)


def failure_code(exc):
    if isinstance(exc, RagConfigurationError):
        return exc.code
    state = getattr(exc, 'sqlstate', None)
    if state == '42501': return 'RAG_DB_PERMISSION_DENIED'
    if state == '42P01': return 'RAG_DB_TABLE_MISSING'
    if state == '42703': return 'RAG_DB_SCHEMA_MISMATCH'
    if state and state.startswith('28'): return 'RAG_DB_AUTH_FAILED'
    if isinstance(exc, psycopg.OperationalError): return 'RAG_DB_CONNECTION_FAILED'
    if isinstance(exc, FileNotFoundError): return 'RAG_CORPUS_MISSING'
    return 'RAG_INTERNAL_ERROR'


def report_failure(tool, exc):
    code = failure_code(exc)
    # Exception text/traceback may embed credentials; log only controlled fields.
    logger.error('RAG_TOOL_FAILED tool=%s code=%s error=%s sqlstate=%s',
                 tool, code, type(exc).__name__, getattr(exc, 'sqlstate', None) or '-')
    return code
