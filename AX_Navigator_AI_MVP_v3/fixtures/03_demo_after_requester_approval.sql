-- Explicit requester approval demonstration; never auto-run in production.
BEGIN;
INSERT INTO ax_roadmaps (roadmap_id, company_id, task_id, assessment_id, roadmap_name, budget_limit_krw, total_allocated_krw, approval_status, approved_by, approved_at, rejection_reason, created_at) OVERRIDING SYSTEM VALUE VALUES
(801, 1, 'a3000000-0000-4000-8000-000000000001', 701, '가상 개발 업무 AX 도입 로드맵', 300000000, 295000000, 'APPROVED', 602, '2026-10-20 10:00:00', NULL, '2026-10-20 09:00:00');
INSERT INTO roadmap_items (item_id, roadmap_id, process_id, solution_id, item_name, priority_order, phase, start_month, duration_months, allocated_budget_krw, ax_score, impact_score, feasibility_score, expected_annual_saving_krw, roi_pct, payback_months, three_year_net_value_krw, rationale, evidence) OVERRIDING SYSTEM VALUE VALUES
(901, 801, 207, 507, '장애 티켓 분류·배정 보조', 1, 'SHORT', 1, 3, 125000000, 97.6, 100.0, 94.0, 125084198, 0.07, 12.0, 214252595, 'AX점수 합 최대 조합으로 선정. 도구 계산 수치를 그대로 보존한다.', '[{"document_id":403,"section":"207 장애 티켓 분류·배정","summary":"반복 장애의 초기 분류·담당 팀 배정 초안을 만들어 대응 대기시간을 줄인다."}]'::jsonb),
(902, 801, 209, 509, '승인형 기술·API 문서 구축', 2, 'SHORT', 1, 3, 55000000, 77.0, 68.5, 89.8, 94317115, 71.49, 6.3, 203951346, 'AX점수 합 최대 조합으로 선정. 도구 계산 수치를 그대로 보존한다. 업무 완료 전 사람 최종 검토·승인 단계를 둔다.', '[{"document_id":403,"section":"209 기술·API 문서 작성","summary":"코드와 명세로 기술·API 문서 초안을 만들고 사람이 검토한 버전을 지식 기반으로 관리한다."}]'::jsonb),
(903, 801, 208, 508, '기술 문서 기반 코드 리뷰 보조', 3, 'MID', 4, 3, 115000000, 90.4, 88.0, 94.0, 121109569, 5.31, 11.3, 212328706, 'AX점수 합 최대 조합으로 선정. 도구 계산 수치를 그대로 보존한다. 선행 솔루션 509 승인·게시 완료 후 시작한다. 업무 완료 전 사람 최종 검토·승인 단계를 둔다.', '[{"document_id":403,"section":"208 코드 리뷰 보조","summary":"승인된 기술 문서를 근거로 코드 변경의 검토 초안을 제공한다."}]'::jsonb);
INSERT INTO ax_projects (project_id, item_id, owner_department_id, project_name, project_status, start_date, end_date, created_at, updated_at) OVERRIDING SYSTEM VALUE VALUES
(10001, 901, 103, '장애 티켓 분류·배정 보조', 'REGISTERED', NULL, NULL, '2026-10-20 09:00:00', '2026-10-20 10:00:00'),
(10002, 902, 103, '승인형 기술·API 문서 구축', 'REGISTERED', NULL, NULL, '2026-10-20 09:00:00', '2026-10-20 10:00:00'),
(10003, 903, 103, '기술 문서 기반 코드 리뷰 보조', 'REGISTERED', NULL, NULL, '2026-10-20 09:00:00', '2026-10-20 10:00:00');
UPDATE ai_tasks SET status='DONE', updated_at='2026-10-20 10:00:00', completed_at='2026-10-20 10:00:00' WHERE task_id='a3000000-0000-4000-8000-000000000001' AND user_id=602;
SELECT setval(pg_get_serial_sequence('ax_roadmaps', 'roadmap_id'), COALESCE((SELECT MAX(roadmap_id) FROM ax_roadmaps), 1), EXISTS(SELECT 1 FROM ax_roadmaps));
SELECT setval(pg_get_serial_sequence('roadmap_items', 'item_id'), COALESCE((SELECT MAX(item_id) FROM roadmap_items), 1), EXISTS(SELECT 1 FROM roadmap_items));
SELECT setval(pg_get_serial_sequence('ax_projects', 'project_id'), COALESCE((SELECT MAX(project_id) FROM ax_projects), 1), EXISTS(SELECT 1 FROM ax_projects));
COMMIT;
