-- Synthetic inputs only. Fresh database, not a migration.
BEGIN;
INSERT INTO companies (company_id, company_name, industry, employee_count, ax_budget_krw, created_at) OVERRIDING SYSTEM VALUE VALUES
(1, '가온비즈정밀 주식회사 (가상)', 'B2B 정밀부품 제조', 200, 300000000, '2026-10-20 09:00:00');
INSERT INTO departments (department_id, company_id, department_name, manager_name, manager_email, manager_phone) OVERRIDING SYSTEM VALUE VALUES
(101, 1, '인사', '가상담당자A', 'demo.101@gaon.example', '010-0000-0001'),
(102, 1, '기획', '가상담당자B', 'demo.102@gaon.example', '010-0000-0002'),
(103, 1, '개발', '가상담당자C', 'demo.103@gaon.example', '010-0000-0003');
INSERT INTO business_processes (process_id, department_id, process_name, purpose, process_steps, standardization_level, requires_approval, exception_rules, work_type) OVERRIDING SYSTEM VALUE VALUES
(201, 101, '사내 규정 문의 응답', '최신 인사 규정의 조항을 찾아 반복 문의에 근거와 함께 응답한다.', '["문의 접수","개인정보 제거","최신 규정 검색","근거 조항 확인","답변 초안 전달"]'::jsonb, 0.88, FALSE, '개인별 급여·징계·법률 해석 문의는 인사 담당자에게 이관한다.', 'KNOWLEDGE_QA'),
(202, 101, '신규 입사자 온보딩 안내', '입사 준비물과 필수 교육 일정을 일관되게 안내한다.', '["입사 일정 확인","직무별 체크리스트 조회","안내문 초안 작성","입사자 확인","미완료 항목 알림"]'::jsonb, 0.8, FALSE, '계정 권한 발급과 근로계약 확정은 담당자가 별도 처리한다.', 'GUIDANCE'),
(203, 101, '인사평가 등급 산정', '인사위원회가 근거 자료를 검토하여 직원의 최종 평가 등급을 결정한다.', '["평가 자료 취합","근거 누락 확인","인사위원회 검토","위원회 최종 등급 결정","결과 통지"]'::jsonb, 0.75, TRUE, '사람의 최종 평가 등급 결정은 AI 자동 실행 대상에서 제외한다. 자료 정리와 최종 판단을 구분한다.', 'DECISION_SUPPORT'),
(204, 102, '주간 업무 보고 취합', '부서 보고의 누락과 중복을 줄이고 표준 보고서를 작성한다.', '["보고 요청","부서별 보고 수집","누락·중복 확인","주간 보고 초안 작성","기획 담당자 검토·승인"]'::jsonb, 0.85, TRUE, '대외 공개 수치와 경영진 의사결정은 사람이 확인한다.', 'REPORT_AGGREGATION'),
(205, 102, '시장·경쟁사 동향 리포트 작성', '출처가 있는 시장 동향 초안을 작성하고 사실을 검증한다.', '["허용 자료 수집","출처·날짜 확인","주제별 요약","리포트 초안 작성","기획 담당자 사실 검토·승인"]'::jsonb, 0.7, TRUE, '미확인 수치와 출처 없는 주장은 제외한다. 현재 연결 시스템에 API가 없어 수동 수집이 필요하다.', 'RESEARCH_REPORT'),
(206, 102, '회의록 작성·액션 아이템 정리', '회의 내용을 요약하고 담당자와 기한을 명확히 정리한다.', '["녹취 동의 확인","회의 자료 수집","발언·결정 사항 요약","담당자·기한 정리","회의 주관자 검토·승인"]'::jsonb, 0.9, TRUE, '동의 없는 녹취와 민감 인사 정보는 처리하지 않는다. 담당자·기한은 주관자가 확정한다.', 'MEETING_SUMMARY'),
(207, 103, '장애 티켓 분류·배정', '반복 장애의 초기 분류·담당 팀 배정 초안을 만들어 대응 대기시간을 줄인다.', '["장애 티켓 접수","비밀값 제거","유형·긴급도 초안 분류","담당 팀 배정","예외 티켓 이관"]'::jsonb, 0.9, FALSE, '보안사고·최고 심각도 장애·낮은 분류 확신은 온콜 담당자에게 즉시 이관한다. 운영 시스템 복구 명령은 실행하지 않는다.', 'TICKET_TRIAGE'),
(208, 103, '코드 리뷰 보조', '승인된 기술 문서를 근거로 코드 변경의 검토 초안을 제공한다.', '["변경 요청 수집","승인된 기술·API 문서 검색","정적 검사 결과 확인","리뷰 의견 초안 작성","개발자 최종 검토·승인"]'::jsonb, 0.9, TRUE, '코드 병합과 배포는 개발자가 결정한다. 선행 과제 509의 문서 구축 완료 후 적용한다.', 'CODE_REVIEW'),
(209, 103, '기술·API 문서 작성', '코드와 명세로 기술·API 문서 초안을 만들고 사람이 검토한 버전을 지식 기반으로 관리한다.', '["변경 명세 수집","기존 문서·코드 대조","API 문서 초안 작성","개발자 검토·승인","버전 게시"]'::jsonb, 0.83, TRUE, '시크릿·고객 데이터는 문서에 넣지 않는다. 승인 전 문서는 리뷰 보조 지식 기반에 게시하지 않는다.', 'DOC_AUTHORING');
INSERT INTO process_metrics (metric_id, process_id, period_start, period_end, processing_count, avg_processing_minutes, error_rate, hourly_labor_cost_krw, data_source) OVERRIDING SYSTEM VALUE VALUES
(1, 201, '2026-07-01', '2026-07-31', 582, 17.64, 0.0250, 34650, 'ASSUMED'),
(2, 201, '2026-08-01', '2026-08-31', 618, 18.36, 0.0250, 35350, 'ASSUMED'),
(3, 201, '2026-09-01', '2026-09-30', 600, 18.00, 0.0250, 35000, 'ASSUMED'),
(4, 202, '2026-07-01', '2026-07-31', 5, 1764.00, 0.0250, 34650, 'ASSUMED'),
(5, 202, '2026-08-01', '2026-08-31', 5, 1836.00, 0.0250, 35350, 'ASSUMED'),
(6, 202, '2026-09-01', '2026-09-30', 5, 1800.00, 0.0250, 35000, 'ASSUMED'),
(7, 203, '2026-07-01', '2026-07-31', 78, 88.20, 0.0250, 39600, 'ASSUMED'),
(8, 203, '2026-08-01', '2026-08-31', 82, 91.80, 0.0250, 40400, 'ASSUMED'),
(9, 203, '2026-09-01', '2026-09-30', 80, 90.00, 0.0250, 40000, 'ASSUMED'),
(10, 204, '2026-07-01', '2026-07-31', 776, 21.56, 0.0250, 44550, 'ASSUMED'),
(11, 204, '2026-08-01', '2026-08-31', 824, 22.44, 0.0250, 45450, 'ASSUMED'),
(12, 204, '2026-09-01', '2026-09-30', 800, 22.00, 0.0250, 45000, 'ASSUMED'),
(13, 205, '2026-07-01', '2026-07-31', 78, 232.75, 0.0250, 44550, 'ASSUMED'),
(14, 205, '2026-08-01', '2026-08-31', 82, 242.25, 0.0250, 45450, 'ASSUMED'),
(15, 205, '2026-09-01', '2026-09-30', 80, 237.50, 0.0250, 45000, 'ASSUMED'),
(16, 206, '2026-07-01', '2026-07-31', 970, 14.70, 0.0250, 44550, 'ASSUMED'),
(17, 206, '2026-08-01', '2026-08-31', 1030, 15.30, 0.0250, 45450, 'ASSUMED'),
(18, 206, '2026-09-01', '2026-09-30', 1000, 15.00, 0.0250, 45000, 'ASSUMED'),
(19, 207, '2026-07-01', '2026-07-31', 970, 21.87, 0.0250, 49500, 'ASSUMED'),
(20, 207, '2026-08-01', '2026-08-31', 1030, 22.77, 0.0250, 50500, 'ASSUMED'),
(21, 207, '2026-09-01', '2026-09-30', 1000, 22.32, 0.0250, 50000, 'ASSUMED'),
(22, 208, '2026-07-01', '2026-07-31', 291, 78.99, 0.0250, 54450, 'ASSUMED'),
(23, 208, '2026-08-01', '2026-08-31', 309, 82.21, 0.0250, 55550, 'ASSUMED'),
(24, 208, '2026-09-01', '2026-09-30', 300, 80.60, 0.0250, 55000, 'ASSUMED'),
(25, 209, '2026-07-01', '2026-07-31', 194, 83.30, 0.0250, 54450, 'ASSUMED'),
(26, 209, '2026-08-01', '2026-08-31', 206, 86.70, 0.0250, 55550, 'ASSUMED'),
(27, 209, '2026-09-01', '2026-09-30', 200, 85.00, 0.0250, 55000, 'ASSUMED');
INSERT INTO it_systems (system_id, company_id, system_name, system_type, api_available, data_access_level, cloud_based) OVERRIDING SYSTEM VALUE VALUES
(301, 1, '인사정보 HRIS', 'HR', FALSE, 'RESTRICTED', FALSE),
(302, 1, '그룹웨어', 'GROUPWARE', TRUE, 'RESTRICTED', TRUE),
(303, 1, '이슈 트래커', 'ETC', TRUE, 'RESTRICTED', TRUE),
(304, 1, '코드 저장소', 'ETC', TRUE, 'RESTRICTED', FALSE),
(305, 1, '사내 위키', 'ETC', FALSE, 'RESTRICTED', FALSE),
(306, 1, '제조 ERP', 'ERP', FALSE, 'RESTRICTED', FALSE);
INSERT INTO process_systems (process_id, system_id, usage_purpose) VALUES
(201, 301, '사내 규정 문의 응답의 허용 자료 조회'),
(201, 305, '사내 규정 문의 응답의 허용 자료 조회'),
(202, 301, '신규 입사자 온보딩 안내의 허용 자료 조회'),
(202, 302, '신규 입사자 온보딩 안내의 허용 자료 조회'),
(203, 301, '인사평가 등급 산정의 허용 자료 조회'),
(204, 302, '주간 업무 보고 취합의 허용 자료 조회'),
(204, 306, '주간 업무 보고 취합의 허용 자료 조회'),
(205, 305, '시장·경쟁사 동향 리포트 작성의 허용 자료 조회'),
(205, 306, '시장·경쟁사 동향 리포트 작성의 허용 자료 조회'),
(206, 302, '회의록 작성·액션 아이템 정리의 허용 자료 조회'),
(206, 305, '회의록 작성·액션 아이템 정리의 허용 자료 조회'),
(207, 303, '장애 티켓 분류·배정의 허용 자료 조회'),
(207, 305, '장애 티켓 분류·배정의 허용 자료 조회'),
(208, 304, '코드 리뷰 보조의 허용 자료 조회'),
(208, 305, '코드 리뷰 보조의 허용 자료 조회'),
(209, 304, '기술·API 문서 작성의 허용 자료 조회'),
(209, 305, '기술·API 문서 작성의 허용 자료 조회');
INSERT INTO documents (document_id, company_id, process_id, title, doc_type, file_uri, access_level, version, status, created_at) OVERRIDING SYSTEM VALUE VALUES
(401, 1, 201, '인사 업무 매뉴얼', 'MANUAL', 'docs://401', 'CONFIDENTIAL', 'v3', 'INDEXED', '2026-10-20 09:00:00'),
(402, 1, 204, '기획 업무 매뉴얼', 'MANUAL', 'docs://402', 'INTERNAL', 'v3', 'INDEXED', '2026-10-20 09:00:00'),
(403, 1, 207, '개발 업무 매뉴얼', 'MANUAL', 'docs://403', 'INTERNAL', 'v3', 'INDEXED', '2026-10-20 09:00:00'),
(404, 1, NULL, '보안·데이터 처리 정책', 'POLICY', 'docs://404', 'INTERNAL', 'v3', 'INDEXED', '2026-10-20 09:00:00'),
(405, 1, NULL, 'IT 시스템 명세', 'SYSTEM_SPEC', 'docs://405', 'INTERNAL', 'v3', 'INDEXED', '2026-10-20 09:00:00'),
(406, 1, NULL, 'AI 활용 현황', 'AI_STATUS', 'docs://406', 'INTERNAL', 'v3', 'INDEXED', '2026-10-20 09:00:00'),
(407, 1, NULL, '데이터 품질 점검표', 'DATA_QUALITY', 'docs://407', 'INTERNAL', 'v3', 'INDEXED', '2026-10-20 09:00:00'),
(408, 1, NULL, '과거 프로젝트 보고서', 'PROJECT_REPORT', 'docs://408', 'INTERNAL', 'v3', 'INDEXED', '2026-10-20 09:00:00');
INSERT INTO ai_solution_catalog (solution_id, work_type, depends_on_solution_id, solution_type, solution_name, description, base_build_cost_krw, monthly_run_cost_krw, automation_rate_low, automation_rate_base, automation_rate_high, time_reduction_rate_low, time_reduction_rate_base, time_reduction_rate_high, min_standardization_level, requires_api, data_source) OVERRIDING SYSTEM VALUE VALUES
(501, 'KNOWLEDGE_QA', NULL, 'RAG', '규정 근거 검색 도우미', '가상 합성 시연용 가정. 효과는 실제 측정이 아닌 업무 시간 환산 잠재치이며 도입 후 재측정한다.', 36000000, 750000, 0.65, 0.8, 0.9, 0.6, 0.75, 0.85, 0.65, FALSE, 'ASSUMED'),
(502, 'GUIDANCE', NULL, 'AI_AGENT', '온보딩 안내 도우미', '가상 합성 시연용 가정. 효과는 실제 측정이 아닌 업무 시간 환산 잠재치이며 도입 후 재측정한다.', 38000000, 1000000, 0.6, 0.75, 0.85, 0.52, 0.67, 0.77, 0.65, TRUE, 'ASSUMED'),
(503, 'DECISION_SUPPORT', NULL, 'PREDICTION', '평가 등급 예측 검토용 후보 (제외)', '가상 합성 시연용 가정. 효과는 실제 측정이 아닌 업무 시간 환산 잠재치이며 도입 후 재측정한다.', 20000000, 500000, 0.55, 0.7, 0.8, 0.45, 0.6, 0.7, 0.65, TRUE, 'ASSUMED'),
(504, 'REPORT_AGGREGATION', NULL, 'RPA', '주간 보고 취합 자동화', '가상 합성 시연용 가정. 효과는 실제 측정이 아닌 업무 시간 환산 잠재치이며 도입 후 재측정한다.', 102000000, 1500000, 0.7, 0.85, 0.95, 0.55, 0.7, 0.8, 0.65, TRUE, 'ASSUMED'),
(505, 'RESEARCH_REPORT', NULL, 'AI_AGENT', '시장 동향 리포트 초안', '가상 합성 시연용 가정. 효과는 실제 측정이 아닌 업무 시간 환산 잠재치이며 도입 후 재측정한다.', 72000000, 1500000, 0.65, 0.8, 0.9, 0.48, 0.63, 0.73, 0.75, TRUE, 'ASSUMED'),
(506, 'MEETING_SUMMARY', NULL, 'AI_AGENT', '회의록·액션 정리 보조', '가상 합성 시연용 가정. 효과는 실제 측정이 아닌 업무 시간 환산 잠재치이며 도입 후 재측정한다.', 68000000, 1000000, 0.65, 0.8, 0.9, 0.48, 0.63, 0.73, 0.65, TRUE, 'ASSUMED'),
(507, 'TICKET_TRIAGE', NULL, 'CLASSIFICATION', '장애 티켓 분류·배정 보조', '가상 합성 시연용 가정. 효과는 실제 측정이 아닌 업무 시간 환산 잠재치이며 도입 후 재측정한다.', 107000000, 1500000, 0.65, 0.8, 0.9, 0.55, 0.7, 0.8, 0.65, TRUE, 'ASSUMED'),
(509, 'DOC_AUTHORING', NULL, 'AI_AGENT', '승인형 기술·API 문서 구축', '가상 합성 시연용 가정. 효과는 실제 측정이 아닌 업무 시간 환산 잠재치이며 도입 후 재측정한다.', 43000000, 1000000, 0.65, 0.8, 0.9, 0.48, 0.63, 0.73, 0.65, TRUE, 'ASSUMED'),
(508, 'CODE_REVIEW', 509, 'RAG', '기술 문서 기반 코드 리뷰 보조', '가상 합성 시연용 가정. 효과는 실제 측정이 아닌 업무 시간 환산 잠재치이며 도입 후 재측정한다.', 97000000, 1500000, 0.55, 0.7, 0.8, 0.5, 0.65, 0.75, 0.65, TRUE, 'ASSUMED');
INSERT INTO users (user_id, company_id, email, password_hash, user_name, created_at) OVERRIDING SYSTEM VALUE VALUES
(601, 1, 'analyst1@gaon.example', '$2y$10$q7ou7PRvm2rMsTLKS5N3reQy/4bhPJSjF7/yRToO823GWRFykXw8G', '가상 AX 분석 담당자', '2026-10-19 10:00:00'),
(602, 1, 'analyst2@gaon.example', '$2y$10$q7ou7PRvm2rMsTLKS5N3reQy/4bhPJSjF7/yRToO823GWRFykXw8G', '가상 전략 담당자', '2026-10-19 10:00:00');
SELECT setval(pg_get_serial_sequence('companies', 'company_id'), COALESCE((SELECT MAX(company_id) FROM companies), 1), EXISTS(SELECT 1 FROM companies));
SELECT setval(pg_get_serial_sequence('departments', 'department_id'), COALESCE((SELECT MAX(department_id) FROM departments), 1), EXISTS(SELECT 1 FROM departments));
SELECT setval(pg_get_serial_sequence('business_processes', 'process_id'), COALESCE((SELECT MAX(process_id) FROM business_processes), 1), EXISTS(SELECT 1 FROM business_processes));
SELECT setval(pg_get_serial_sequence('process_metrics', 'metric_id'), COALESCE((SELECT MAX(metric_id) FROM process_metrics), 1), EXISTS(SELECT 1 FROM process_metrics));
SELECT setval(pg_get_serial_sequence('it_systems', 'system_id'), COALESCE((SELECT MAX(system_id) FROM it_systems), 1), EXISTS(SELECT 1 FROM it_systems));
SELECT setval(pg_get_serial_sequence('documents', 'document_id'), COALESCE((SELECT MAX(document_id) FROM documents), 1), EXISTS(SELECT 1 FROM documents));
SELECT setval(pg_get_serial_sequence('ai_solution_catalog', 'solution_id'), COALESCE((SELECT MAX(solution_id) FROM ai_solution_catalog), 1), EXISTS(SELECT 1 FROM ai_solution_catalog));
SELECT setval(pg_get_serial_sequence('users', 'user_id'), COALESCE((SELECT MAX(user_id) FROM users), 1), EXISTS(SELECT 1 FROM users));
COMMIT;
