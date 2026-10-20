-- DEMO ONLY: requester (ai_tasks.user_id=602) explicitly approves their own generated plan. No role check.
-- Production approval must be checked in Spring before calling business-mcp write tools.
BEGIN;
UPDATE ai_tasks SET status='DONE', updated_at='2026-10-19 14:00:00', completed_at='2026-10-19 14:00:00' WHERE task_id='66580f0c-445d-5d0d-a5a4-45ef6c3f5d56' AND status='WAITING_APPROVAL';
INSERT INTO ax_roadmaps (roadmap_id, company_id, task_id, assessment_id, roadmap_name, budget_limit_krw, total_allocated_krw, approval_status, approved_by, approved_at, rejection_reason, created_at) OVERRIDING SYSTEM VALUE VALUES
  (801, 1, '66580f0c-445d-5d0d-a5a4-45ef6c3f5d56', 701, '2027 제조기업 AX 전환 우선 도입 로드맵', 300000000, 284000000, 'APPROVED', 602, '2026-10-19 14:00:00', NULL, '2026-10-19 14:00:00');
INSERT INTO roadmap_items (item_id, roadmap_id, process_id, solution_id, item_name, priority_order, phase, start_month, duration_months, allocated_budget_krw, expected_annual_saving_krw, roi_pct, payback_months, rationale, evidence) OVERRIDING SYSTEM VALUE VALUES
  (901, 801, 201, 501, 'CRM 영업활동 자동기록 Agent', 1, 'SHORT', 1, 3, 98000000, 71316408, -27.23, 18.01, '합성 운영 지표와 고정 카탈로그 가정에 근거한 3년 순편익 우선순위', '[{"document_id":401,"section":"업무 범위","summary":"가상 회사 문서 근거"},{"document_id":405,"section":"업무 범위","summary":"가상 회사 문서 근거"}]'),
  (902, 801, 210, 509, '제품 문의 RAG 상담 Agent', 2, 'MID', 4, 3, 92000004, 63721544, -30.74, 19.26, '합성 운영 지표와 고정 카탈로그 가정에 근거한 3년 순편익 우선순위', '[{"document_id":404,"section":"업무 범위","summary":"가상 회사 문서 근거"},{"document_id":405,"section":"업무 범위","summary":"가상 회사 문서 근거"}]'),
  (903, 801, 205, 505, '발주서 자동 검증·등록', 3, 'LONG', 7, 3, 93999996, 56702629, -39.68, 23.0, '합성 운영 지표와 고정 카탈로그 가정에 근거한 3년 순편익 우선순위', '[{"document_id":402,"section":"업무 범위","summary":"가상 회사 문서 근거"},{"document_id":405,"section":"업무 범위","summary":"가상 회사 문서 근거"}]');
INSERT INTO ax_projects (project_id, item_id, owner_department_id, project_name, project_status, start_date, end_date, created_at, updated_at) OVERRIDING SYSTEM VALUE VALUES
  (10001, 901, 101, 'CRM 영업활동 자동기록 Agent', 'REGISTERED', '2027-01-01', '2027-03-31', '2026-10-19 14:00:00', '2026-10-19 14:00:00'),
  (10002, 902, 104, '제품 문의 RAG 상담 Agent', 'REGISTERED', '2027-04-01', '2027-06-30', '2026-10-19 14:00:00', '2026-10-19 14:00:00'),
  (10003, 903, 102, '발주서 자동 검증·등록', 'REGISTERED', '2027-07-01', '2027-09-30', '2026-10-19 14:00:00', '2026-10-19 14:00:00');
SELECT setval(pg_get_serial_sequence('ax_roadmaps', 'roadmap_id'), (SELECT MAX(roadmap_id) FROM ax_roadmaps), true);
SELECT setval(pg_get_serial_sequence('roadmap_items', 'item_id'), (SELECT MAX(item_id) FROM roadmap_items), true);
SELECT setval(pg_get_serial_sequence('ax_projects', 'project_id'), (SELECT MAX(project_id) FROM ax_projects), true);
COMMIT;
