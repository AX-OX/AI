"""Per-command credentials; ContextVar keeps concurrent jobs isolated."""
from contextvars import ContextVar
import re

lease_headers = ContextVar('command_lease_headers', default=None)


def command_headers():
    return dict(lease_headers.get() or {})


class RetryableWorkError(RuntimeError):
    pass


class PermanentWorkError(ValueError):
    pass


def tool_failure(exc, code, message):
    # Transport/server/rate-limit errors are retried; explicit input/config failures are not.
    permanent_codes = {'RAG_UPLOAD_EMPTY', 'RAG_CORPUS_MISSING', 'RAG_DB_URL_MISSING',
                       'RAG_DB_PERMISSION_DENIED', 'RAG_DB_AUTH_FAILED', 'RAG_DB_TABLE_MISSING',
                       'RAG_DB_SCHEMA_MISMATCH', 'RAG_INDEX_MISSING', 'RAG_INDEX_MODEL_MISMATCH',
                       'RAG_INDEX_REVISION_MISMATCH', 'RAG_INDEX_CORPUS_MISMATCH',
                       'RAG_EVIDENCE_LIMIT', 'RAG_EVIDENCE_EMPTY', 'RAG_TOOL_MISSING'}
    invalid_http = re.search(r'Spring HTTP (400|401|403|404|409|422)\b', str(exc))
    error = PermanentWorkError if code in permanent_codes or invalid_http else RetryableWorkError
    return error(message)
