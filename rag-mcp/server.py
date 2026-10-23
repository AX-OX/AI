"""pgvector RAG MCP: 회사별 검색·원문·업로드 문서 색인, 이메일·전화번호 마스킹."""
import asyncio
import os
from fastmcp import FastMCP
from fastmcp.exceptions import ToolError
import common
from common import mapping, mask, COMPANY_ID
from pgvector_client import PgVectorStore
from diagnostics import report_failure

mcp = FastMCP('rag')

@mcp.tool
async def get_assessment_evidence(company_id: int | None = None) -> list[dict]:
    """회사의 성숙도 공통 문서 5종과 업로드 문서(UPLOADED) 전체 섹션을 조회한다. company_id를 생략하면 시드 회사다. 유사도 top_k나 임베딩 API 없이 정책·시스템·AI 현황·데이터 품질·프로젝트 보고서를 확보한다."""
    try:
        rows = await asyncio.to_thread(lambda: PgVectorStore().assessment_evidence(company_id or COMPANY_ID))
        return [{**r, 'content':mask(r['content'])} for r in rows]
    except Exception as exc:
        code = report_failure('get_assessment_evidence', exc)
        raise ToolError(f'{code}: 성숙도 근거 조회 실패. 배포 DB·색인 설정을 확인하세요.') from None

@mcp.tool
async def search_docs(query: str, doc_type: str | None = None, process_id: int | None = None, top_k: int = 5,
                      company_id: int | None = None) -> list[dict]:
    """문장과 선택적인 문서 유형·업무 ID로 회사 범위의 pgvector 근거 검색. company_id를 생략하면 시드 회사다. score는 cosine 거리로 낮을수록 가깝다."""
    if not query.strip() or not 1 <= top_k <= 20: raise ToolError('검색어가 필요하며 top_k는 1~20이어야 합니다.')
    try:
        rows = await asyncio.to_thread(lambda: PgVectorStore().search(query, doc_type, process_id, top_k, company_id or COMPANY_ID))
        return [{**r,'content':mask(r['content'])} for r in rows]
    except Exception as exc:
        code = report_failure('search_docs', exc)
        raise ToolError(f'{code}: pgvector 검색 실패. DB와 색인·모델 설정을 확인하세요.') from None

@mcp.tool
async def get_document_chunks(company_id: int, document_ids: list[int]) -> list[dict]:
    """회사 업로드 문서의 전체 조각을 페이지 순서로 조회한다. 기업 데이터 추출에만 쓴다. 임베딩 API를 호출하지 않는다."""
    if not document_ids or len(document_ids) > 20: raise ToolError('document_ids는 1~20개여야 합니다.')
    try:
        rows = await asyncio.to_thread(lambda: PgVectorStore().document_chunks(company_id, document_ids))
        return [{**r, 'content': mask(r['content'])} for r in rows]
    except Exception as exc:
        code = report_failure('get_document_chunks', exc)
        raise ToolError(f'{code}: 업로드 문서 조회 실패. 색인 상태를 확인하세요.') from None

@mcp.tool(annotations={'destructiveHint': True})
async def index_document(company_id: int, document_id: int, title: str, pages: list[dict]) -> dict:
    """업로드 PDF의 페이지 텍스트 [{page, text}]를 조각내 임베딩하고 회사 업로드 색인에 저장한다. 같은 문서는 교체한다. RAG_INDEX_DATABASE_URL 쓰기 계정이 필요하다."""
    if not pages or len(pages) > 100: raise ToolError('pages는 1~100개여야 합니다.')
    try:
        return await asyncio.to_thread(lambda: PgVectorStore(write=True).index_document(company_id, document_id, title, pages))
    except Exception as exc:
        code = report_failure('index_document', exc)
        raise ToolError(f'{code}: 업로드 문서 색인 실패.') from None

@mcp.resource('docs://{document_id}')
def get_document(document_id: str) -> str:
    """검색 결과의 document_id로 같은 회사의 Markdown 원문을 읽는다."""
    if not document_id.isdecimal(): raise ValueError('유효하지 않은 문서 ID')
    doc = mapping().get(document_id)
    if not doc or doc.get('company_id') != COMPANY_ID: raise ValueError('문서가 없거나 접근할 수 없습니다.')
    return mask((common.CORPUS / 'docs' / f'{int(document_id)}.md').read_text(encoding='utf-8'))

if __name__ == '__main__': mcp.run(transport='http', host=os.getenv('MCP_HOST', '0.0.0.0'), port=int(os.getenv('MCP_PORT', '9102')), path='/mcp')
