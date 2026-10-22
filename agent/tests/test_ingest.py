"""POST /documents/{id}/ingest: PDF pages -> company RAG index -> Spring PATCH /documents/{id}."""
import asyncio
from uuid import uuid4

import httpx
import pytest
from agent.app.ingest import pdf_pages
from agent.app.main import create_app
from agent.app.mock import MockGateway
from agent.tests.test_agent import settings, wait_job


def text_pdf(*pages):
    """Minimal PDF with one Helvetica text line per page (ASCII only)."""
    objects = ['<< /Type /Catalog /Pages 2 0 R >>', None, '<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>']
    kids = []
    for text in pages:
        stream = f'BT /F1 12 Tf 72 720 Td ({text}) Tj ET'.encode() if text else b''
        objects.append(f'<< /Length {len(stream)} >>\nstream\n'.encode() + stream + b'\nendstream')
        objects.append(f'<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 3 0 R >> >> /Contents {len(objects)} 0 R >>')
        kids.append(f'{len(objects)} 0 R')
    objects[1] = f'<< /Type /Pages /Kids [{" ".join(kids)}] /Count {len(kids)} >>'
    out, offsets = bytearray(b'%PDF-1.4\n'), []
    for i, body in enumerate(objects, 1):
        offsets.append(len(out))
        out += f'{i} 0 obj\n'.encode() + (body if isinstance(body, bytes) else body.encode()) + b'\nendobj\n'
    xref = len(out)
    out += f'xref\n0 {len(objects)+1}\n0000000000 65535 f \n'.encode() + b''.join(f'{o:010d} 00000 n \n'.encode() for o in offsets)
    out += f'trailer\n<< /Size {len(objects)+1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n'.encode()
    return bytes(out)


def test_pdf_pages_keeps_every_page_number():
    assert pdf_pages(text_pdf('HR answers 120 policy questions a month', '')) == [
        {'page': 1, 'text': 'HR answers 120 policy questions a month'}, {'page': 2, 'text': ''}]


async def post(client, document_id, data, content_type='application/pdf', company=2):
    return await client.post(f'/documents/{document_id}/ingest',
                             data={'companyId': str(company), 'fileName': '회사 소개.pdf', 'contentType': content_type},
                             files={'file': ('document.pdf', data, 'application/pdf')})


async def wait_ingest(app, document_id):
    job = app.state.ingestor.jobs.get(document_id)
    if job: await asyncio.wait_for(job, 10)


def callback(gateway, document_id):
    return next(e['body'] for e in gateway.events if e['method'] == 'PATCH' and e['path'] == f'/documents/{document_id}')


@pytest.mark.asyncio
async def test_ingest_indexes_pages_then_extraction_uses_them():
    cfg = settings()
    gateway = MockGateway(cfg)
    app = create_app(cfg, gateway=gateway)
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
            assert (await post(client, 9001, text_pdf('HR policy questions'))).status_code == 403
            client.headers['X-Internal-Token'] = 'test-token'
            assert (await post(client, 9001, text_pdf('HR answers policy questions', 'Groupware handles approvals'))).status_code == 202
            await wait_ingest(app, 9001)
            body = callback(gateway, 9001)
            assert body == {'status': 'INDEXED', 'pageCount': 2, 'pages': [
                {'page': 1, 'text': 'HR answers policy questions'}, {'page': 2, 'text': 'Groupware handles approvals'}]}
            assert [r['section'] for r in gateway.uploads[2]] == ['p.1', 'p.2']
            assert next(args for name, args in gateway.calls if name == 'index_document')['title'] == '회사 소개.pdf'

            key = str(uuid4())
            run = {'companyId': 2, 'userId': 700, 'requestText': '진단', 'companyDataConfirmed': False, 'documentIds': [9001]}
            assert (await client.post(f'/tasks/{key}/run', json=run)).status_code == 202
            await wait_job(app, key)
            assert (await client.get(f'/tasks/{key}')).json()['status'] == 'WAITING_CONFIRMATION'
            payload = next(args for name, args in gateway.calls if name == 'save_extraction')['payload']
            assert payload['processes'][0]['source'] == {'documentId': 9001, 'page': 1}


@pytest.mark.asyncio
@pytest.mark.parametrize('data,message', [
    (b'%PDF-1.4 broken', 'PDF를 읽을 수 없습니다'),
    (text_pdf(''), 'RAG_UPLOAD_EMPTY'),
])
async def test_unreadable_or_textless_pdf_reports_failed(data, message):
    cfg = settings()
    gateway = MockGateway(cfg)
    app = create_app(cfg, gateway=gateway)
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test',
                                     headers={'X-Internal-Token': 'test-token'}) as client:
            assert (await post(client, 9002, data)).status_code == 202
            await wait_ingest(app, 9002)
            body = callback(gateway, 9002)
            assert body['status'] == 'FAILED' and message in body['errorMessage']
            assert 'pages' not in body


@pytest.mark.asyncio
async def test_ingest_rejects_non_pdf_and_empty_file():
    cfg = settings()
    gateway = MockGateway(cfg)
    app = create_app(cfg, gateway=gateway)
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test',
                                     headers={'X-Internal-Token': 'test-token'}) as client:
            assert (await post(client, 9003, text_pdf('x'), content_type='text/plain')).status_code == 400
            assert (await post(client, 9003, b'')).status_code == 400
            assert not gateway.events
