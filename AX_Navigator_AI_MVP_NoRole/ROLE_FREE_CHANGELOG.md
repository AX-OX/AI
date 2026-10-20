# Role-free 승인·검색 구조 변경 안내

- `users.role` 컬럼 및 ADMIN/MEMBER 구분 제거. 사용자 601/602는 역할 없는 가상 계정으로 유지.
- `ai_tasks.user_id`: 과제 생성 요청자. `ax_roadmaps.approved_by`: 실제 승인 사용자 ID. **동일해야 함**.
- 데모에는 `ai_tasks.user_id = 602`, `ax_roadmaps.approved_by = 602`를 저장.
- Spring이 로그인 사용자의 `user_id`와 작업 요청자를 비교해 승인/거절 수행. 작업 소유자가 아닌 경우 거절.
- `WAITING_APPROVAL` 상태에서만 승인 처리. `APPROVED` 이후에만 Business MCP를 통한 DB 로드맵/프로젝트 생성 허용.
- `documents.access_level`은 민감도 분류 메타데이터로 **유지**하되 ADMIN/MEMBER 기반 검색 권한 검증 제거.
- Chroma `allowed_roles` 속성 삭제. 소속 기업 `company_id` 검색 범위 및 개인식별정보 마스킹을 적용.
- 구매/영업/인사/안전 등 원래 업무 자체의 사람 검토 규칙은 유지 (플랫폼 역할과 무관).
- 기존 Chroma 컬렉션에 적재했다면 이전 `allowed_roles` metadata를 삭제하거나 컬렉션을 새 데이터로 재생성해야 함.
- PostgreSQL을 이미 초기화했다면 `sql/02_migrate_remove_user_roles.sql`을 적용하고, 새로 만든 DB에는 00 → 01만 적용.

**주의:** 역할을 없애는 것이 인증이나 기업 간 데이터 격리까지 없앤다는 뜻은 아님. 실제 운영용 서버는 사용자 인증, 기업 소속 검증, 요청자 동일성 검증을 구현해야 함.
