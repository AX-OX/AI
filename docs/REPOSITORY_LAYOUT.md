# GitHub 업로드 범위

기존 팀원이 작성한 `agent/` 경로를 유지하며 실제 노드·실행기·MCP 클라이언트를 추가한다. FE·BE 코드를 이 저장소에 복사하지 않는다.

| 업로드 대상 | 이유 |
|---|---|
| `agent/` | 팀원 구조의 FastAPI·LangGraph·Harness와 실제 구현·의존성 잠금·테스트 |
| `business-mcp/`, `rag-mcp/` | Agent가 사용하는 실제 도구·Spring DTO 변환·벡터 검색 |
| `AX_Navigator_AI_MVP_v3/` | CSV·정책·정답·문서·mock SQLite 등 실행 입력 |
| `db/` | 현재 PostgreSQL 스키마·시드·pgvector·계정·ERD |
| `scripts/`, `tests/` | 로컬 채팅·fixture 재생성·검증 |
| `docs/`, 공통 기준 MD | 실행 방법·계약·데이터 생성 요구사항 |
| `.github/`, `.gitignore`, `.env.example`, `compose.yaml`, `pytest.ini`, README | 협업·실행 설정 |

## 업로드하지 않는 파일

| 위치 | 내용 |
|---|---|
| `.env`, `.env.*` | 실제 키·비밀번호. `.env.example`은 예외로 업로드 |
| `.venv/`, 캐시·빌드 폴더 | 설치·실행 중 생성되는 파일 |
| `.local/reports/` | 실행 로그·검증 JSON. 테스트·CLI에서 생성 가능 |
| `.local/archive/AX_Navigator_AI_MVP_NoRole/` | 이전 데이터 패키지 |
| `.local/archive/backend-evaluation/`, `config/` | 현재 서비스에 사용하지 않는 이전 Spring·정책 참고 코드 |
| `.local/archive/`의 ZIP·SQL·PNG·이전 문서·migration·문서 매핑 | 중복 산출물·과거 설계 기록 |

파일을 영구 삭제하지 않고 보관했다. `.local/archive/manifest.json`에 원래 경로·보관 경로·SHA-256이 있어 이동 전후 동일 파일인지 확인할 수 있다. 기존 파일을 복원하려면 해당 보관 파일을 원래 경로로 옮기면 된다.

이전 업로드 브랜치에는 과거 파일이 이미 커밋되어 있다. 이번 정리를 커밋하면 그 파일들은 현재 브랜치의 업로드 트리에서 제거되지만 이전 Git 이력에는 남는다. `.gitignore`만 추가해서 기존 이력을 지우거나 강제 푸시하지 않는다.

## 준비 상태 확인

```sh
git status --short
git diff --check
git check-ignore .env .local .venv
```

이번 정리는 업로드 준비이며 커밋·푸시는 별도다. 현재 브랜치는 `codex/team-agent-alignment`다. 팀원 저장소에 합칠 때는 기존 `agent/`에 이 폴더의 `agent/` 내용을 반영하고, 나머지 런타임 폴더도 같은 루트에 추가한다.
