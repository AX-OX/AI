"""Uploaded PDF -> page texts -> company RAG index -> Spring callback. The PDF itself is never stored."""
import asyncio
import io
import logging
from pypdf import PdfReader
from .tool_errors import safe_tool_failure

logger = logging.getLogger(__name__)
MAX_BYTES = 20 * 1024 * 1024
MAX_PAGES = 100


class IngestError(ValueError):
    pass


def pdf_pages(data):
    """[{page, text}] for every page (1부터). 텍스트가 없는 페이지는 빈 문자열로 둔다."""
    try:
        reader = PdfReader(io.BytesIO(data))
        if reader.is_encrypted: raise IngestError('암호가 걸린 PDF는 읽을 수 없습니다.')
        if len(reader.pages) > MAX_PAGES: raise IngestError(f'PDF는 최대 {MAX_PAGES}페이지까지 색인합니다.')
        return [{'page': i + 1, 'text': (page.extract_text() or '').strip()} for i, page in enumerate(reader.pages)]
    except IngestError:
        raise
    except Exception as exc:
        raise IngestError('PDF를 읽을 수 없습니다. 손상되었거나 지원하지 않는 형식입니다.') from exc


class Ingestor:
    """Spring의 색인 요청을 202로 받고 백그라운드에서 처리한다. 결과는 PATCH /internal/documents/{id}로 돌려준다."""
    def __init__(self, gateway, limit=4):
        self.gateway, self.limit, self.jobs = gateway, limit, {}

    def start(self, document_id, company_id, title, data):
        if document_id in self.jobs: return False
        if len(self.jobs) >= self.limit: raise OverflowError('동시 색인 한도 초과')
        self.jobs[document_id] = asyncio.create_task(self.run(document_id, company_id, title, data))
        return True

    async def run(self, document_id, company_id, title, data):
        try:
            pages = await asyncio.to_thread(pdf_pages, data)
            await self.gateway.index_document(company_id, document_id, title, pages)
            body = {'status': 'INDEXED', 'pageCount': len(pages), 'pages': pages}
        except Exception as exc:
            message = str(exc) if isinstance(exc, IngestError) else safe_tool_failure(exc)[1]
            logger.error('INGEST_FAILED document_id=%s error=%s', document_id, type(exc).__name__)
            body = {'status': 'FAILED', 'errorMessage': message}
        try:
            await self.gateway.document_result(document_id, body)
        except Exception:
            logger.exception('Ingest callback failed document_id=%s', document_id)
        finally:
            self.jobs.pop(document_id, None)

    async def close(self):
        jobs = list(self.jobs.values())
        for job in jobs: job.cancel()
        await asyncio.gather(*jobs, return_exceptions=True)
