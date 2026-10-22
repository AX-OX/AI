"""Controlled public error messages for MCP failures; no raw transport errors."""
import re

MESSAGES = {
    'RAG_DB_URL_MISSING': '배포 환경에 RAG_DATABASE_URL이 없습니다.',
    'RAG_DB_PERMISSION_DENIED': 'RAG DB 계정의 테이블 조회 권한이 부족합니다.',
    'RAG_DB_TABLE_MISSING': 'RAG DB 테이블이 없습니다. 연결 DB와 스키마를 확인하세요.',
    'RAG_DB_SCHEMA_MISMATCH': 'RAG DB 스키마와 배포 코드가 다릅니다.',
    'RAG_DB_AUTH_FAILED': 'RAG DB 인증에 실패했습니다.',
    'RAG_DB_CONNECTION_FAILED': 'RAG DB 연결 실패: Cloud SQL 연결·계정·네트워크를 확인하세요.',
    'RAG_CORPUS_MISSING': '배포 이미지에 RAG 문서 파일이 없습니다.',
    'RAG_INDEX_MISSING': '배포 DB에 활성 RAG 색인이 없습니다. 동일 설정의 색인 Job을 실행하세요.',
    'RAG_INDEX_MODEL_MISMATCH': 'RAG 색인의 임베딩 모델이 배포 설정과 다릅니다.',
    'RAG_INDEX_REVISION_MISMATCH': 'RAG 색인의 임베딩 revision이 배포 설정과 다릅니다.',
    'RAG_INDEX_CORPUS_MISMATCH': '배포 이미지 문서와 DB 색인의 문서 해시가 다릅니다.',
    'RAG_EVIDENCE_LIMIT': '성숙도 근거가 200개를 초과합니다. 범위를 나누세요.',
    'RAG_EVIDENCE_EMPTY': '활성 색인에 성숙도 근거 문서가 없습니다.',
    'RAG_INTERNAL_ERROR': 'RAG 내부 오류입니다. RAG_TOOL_FAILED 로그를 확인하세요.',
    'RAG_TOOL_MISSING': '연결된 RAG 서버에 필수 도구가 없습니다. RAG 배포 버전·URL을 확인하세요.',
    'MCP_CALL_FAILED': 'MCP 호출 실패. 서버 버전·연결·인증 상태를 확인하세요.',
}


def safe_tool_failure(exc):
    # Only exact allowlisted codes can cross the server/public boundary.
    codes = re.findall(r'\bRAG_[A-Z_]+\b', str(exc))
    code = next((c for c in codes if c in MESSAGES), 'MCP_CALL_FAILED')
    return code, f'{code}: {MESSAGES[code]}'
