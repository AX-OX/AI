-- AX Navigator AI final MVP: synthetic INPUT + solution catalog + demo users only
-- PostgreSQL 16 · mirrors ax_navigator_input.sqlite
BEGIN;
INSERT INTO companies (company_id, company_name, industry, employee_count, ax_budget_krw, created_at) OVERRIDING SYSTEM VALUE VALUES
  (1, '가온비즈정밀 주식회사 (가상)', '산업용 정밀부품 B2B 제조', 200, 300000000, '2026-10-19 10:00:00');
SELECT setval(pg_get_serial_sequence('companies', 'company_id'), (SELECT MAX(company_id) FROM companies), true);

INSERT INTO departments (department_id, company_id, department_name, manager_name, manager_email, manager_phone) OVERRIDING SYSTEM VALUE VALUES
  (101, 1, '영업', NULL, NULL, NULL),
  (102, 1, '구매', NULL, NULL, NULL),
  (103, 1, '인사', NULL, NULL, NULL),
  (104, 1, '고객지원', NULL, NULL, NULL);
SELECT setval(pg_get_serial_sequence('departments', 'department_id'), (SELECT MAX(department_id) FROM departments), true);

INSERT INTO business_processes (process_id, department_id, process_name, purpose, process_steps, standardization_level, requires_approval, exception_rules) OVERRIDING SYSTEM VALUE VALUES
  (201, 101, 'CRM 영업활동 기록', '회의록 수동 전사·중복 입력', '["고객 미팅·통화 내용을 CRM 영업활동 화면에서 확인한다.","계정·담당자·방문일·요구사항·후속 일정 필수값을 정리한다.","중복 기록과 고객정보 누락 여부를 점검한 뒤 활동 내용을 저장한다.","미확정 영업 제안이나 고객에게 발송할 문구는 담당자가 검토한다."]', 0.83, FALSE, '고객 개인정보와 계약 조건 변경은 자동 확정 금지. CRM 쓰기 작업 전에 사용자 권한 확인.'),
  (202, 101, '견적서 초안 작성', '제품별 조건 복사·가격 재검토', '["고객사의 규격·수량·납기 요청을 CRM에서 조회한다.","ERP 품목 마스터·최근 견적 단가를 대조하여 견적서 초안을 만든다.","특약·할인·예외 납기 여부를 표시하고 영업팀장 결재를 요청한다.","승인된 가격·조건만 외부 고객에게 발송하고 이력을 CRM에 기록한다."]', 0.76, TRUE, '가격·할인·납기 약정과 대외 발송은 영업책임자 승인 필수. 미승인 견적 전송 금지.'),
  (203, 101, '리드 분류 및 우선순위화', '영업사원별 판단 기준 불일치', '["CRM 신규 리드의 산업·문의 제품·요구량 데이터를 수집한다.","중복·필수값 누락 리드를 분리하고 담당 영업조직을 확인한다.","요청 긴급도·예상 매출·적합성 기준으로 우선순위를 초안 산정한다.","담당자가 최종 등급을 확정하고 CRM에 근거와 후속 일정을 기록한다."]', 0.69, FALSE, 'AI의 리드 등급만으로 고객 차별 또는 거래 거절 금지. 리드 누락·중복 수동 확인.'),
  (204, 102, '공급업체 견적 비교', '양식이 다른 견적 엑셀 수기 비교', '["협력사별 견적서와 발주 요청 품목 목록을 접수한다.","품목코드·수량·단가·납기·통화 기준을 정규화해 비교표를 만든다.","ERP 계약단가 및 공급사 평가 기준과 차이를 표시한다.","단가 이탈·단독 공급·상충하는 견적은 구매담당자의 확인 후 비교 결과를 확정한다."]', 0.79, FALSE, '비교 결과에 구매자 편향 방지 기준을 적용하며 단독공급·단가 이탈은 구매담당자 검토.'),
  (205, 102, '발주서 검증·등록', '단가·납기·품목코드 수기 대조', '["결재된 구매요청서의 품목·수량·단가·납기·공급사 정보를 조회한다.","ERP 발주서의 품목코드·단가·계약조건·납기를 원천 데이터와 대조한다.","오류·누락·한도 초과 발주서를 자동 등록에서 제외한다.","구매 책임자가 승인한 발주서만 ERP에 확정 등록하고 감사 로그를 남긴다."]', 0.92, TRUE, '신규 공급사, 계약 단가 이탈, 금액 한도 초과 또는 필드 누락 발생 시 자동 등록 중단 및 구매 승인 요청.'),
  (206, 102, '납기 지연 대응', '공급사별 연락처·이력 분산', '["ERP 납기 지연 경고 및 공급사별 미납 발주를 조회한다.","약정 납기·지연 일수·재고 및 생산 영향도를 계산한다.","대체 납기 및 공급사 연락 초안을 구성하고 담당자에게 이관한다.","납기 변경 또는 고객 안내는 구매·생산 담당자의 확인 후 확정한다."]', 0.61, FALSE, '납기 변경·고객 통보·대체 공급사 결정은 구매·생산 담당자의 승인 필요.'),
  (207, 103, '입사지원서 사전 검토', '민감 개인정보·편향 위험', '["지원서의 동의 범위와 채용 공고별 필수 요건을 확인한다.","접근 허용된 지원서에서 직무 관련 경력·기술만 요약한다.","개인식별정보와 민감 특성은 마스킹하고 불확실 항목을 표시한다.","합격·불합격 결정은 채용 담당자가 수행하고 AI 추천을 단독 근거로 사용하지 않는다."]', 0.63, TRUE, '자동 합불 결정 금지. 개인정보 가명처리, 직무무관 민감정보 사용 금지, 인사 담당자 검토 필수.'),
  (208, 103, '인사 규정 질의응답', '규정 문서 검색 및 답변 반복', '["구성원의 인사규정 관련 질문을 접수한다.","접근 권한을 확인하고 승인된 최신 사규에서 관련 조항을 검색한다.","규정 버전·조항·시행일을 포함해 답변 초안을 제시한다.","개별 급여·징계·인사평가 등 민감 사안은 담당자에게 이관한다."]', 0.86, FALSE, '권한 밖 인사·급여 기록 검색 금지. 규정 충돌 시 인사 담당자에게 이관.'),
  (209, 103, '신규입사자 온보딩 안내', '부서별 안내문 분산', '["신규입사자 입사일·소속 부서와 온보딩 체크리스트를 확인한다.","계정 발급·교육 일정·장비 신청 등 부서별 안내 항목을 취합한다.","누락 또는 미완료 항목을 표시해 본인과 담당자에게 안내 초안을 제공한다.","계정 권한 부여·인사정보 변경은 인사 담당자의 승인을 통해 처리한다."]', 0.8, FALSE, '계정 발급·접근 권한 변경은 HR 승인과 내부 접근통제 절차를 거쳐야 함.'),
  (210, 104, '제품 FAQ 문의 응대', '반복 문의·지식검색 소요', '["VOC 티켓의 제품명·오류 코드·고객 질문을 확인한다.","허용된 FAQ 및 제품 매뉴얼에서 관련 절차와 예외 조항을 검색한다.","출처·안전 주의사항을 포함한 답변 초안을 작성한다.","안전사고·보증 분쟁·근거 없는 해결 방법은 상담원 또는 기술팀에 이관한다."]', 0.86, FALSE, '사고 위험, 보증분쟁, 최신 매뉴얼 근거 부족 시 AI 확답 금지 및 상담원 이관.'),
  (211, 104, '문의 티켓 분류·배정', '분류 코드 수동 입력', '["새 티켓의 제목·본문·제품·고객 요청 유형을 읽는다.","개인정보를 마스킹한 뒤 미리 정의된 분류 코드와 우선순위를 산정한다.","중복·긴급·모호한 티켓을 예외 큐에 분리한다.","담당 상담원이 예외 건을 확인하고 최종 담당 조직 및 SLA를 확정한다."]', 0.93, FALSE, '개인정보 마스킹 필수. 긴급·보안·중대 사고 티켓은 담당자 확인 후 배정.'),
  (212, 104, '기술 장애 해결 안내', '매뉴얼·고장 이력 탐색', '["고객이 전달한 증상·제품 모델·오류 코드를 확인한다.","승인된 기술 매뉴얼과 과거 장애 지식에서 재현 조건을 검색한다.","안전한 점검 절차·상담원 확인 질문·관련 출처를 안내 초안으로 구성한다.","설비 조작·안전장치 해제·교체 결정은 기술 엔지니어가 최종 승인한다."]', 0.66, TRUE, '설비 안전장치 변경·원격 제어 지시 금지. 위험 장애는 기술 엔지니어 확인 필수.');
SELECT setval(pg_get_serial_sequence('business_processes', 'process_id'), (SELECT MAX(process_id) FROM business_processes), true);

INSERT INTO process_metrics (metric_id, process_id, period_start, period_end, processing_count, avg_processing_minutes, error_rate, hourly_labor_cost_krw, data_source) OVERRIDING SYSTEM VALUE VALUES
  (1001, 201, '2026-07-01', '2026-07-31', 1416, 11.04, 0.0102, 39000, 'ASSUMED'),
  (1002, 201, '2026-08-01', '2026-08-31', 1508, 11.16, 0.0113, 39000, 'ASSUMED'),
  (1003, 201, '2026-09-01', '2026-09-30', 1556, 10.9, 0.0124, 39000, 'ASSUMED'),
  (1004, 202, '2026-07-01', '2026-07-31', 229, 61.07, 0.0128, 39000, 'ASSUMED'),
  (1005, 202, '2026-08-01', '2026-08-31', 235, 60.31, 0.0139, 39000, 'ASSUMED'),
  (1006, 202, '2026-09-01', '2026-09-30', 252, 60.76, 0.0095, 39000, 'ASSUMED'),
  (1007, 203, '2026-07-01', '2026-07-31', 864, 15.21, 0.0154, 39000, 'ASSUMED'),
  (1008, 203, '2026-08-01', '2026-08-31', 903, 14.81, 0.011, 39000, 'ASSUMED'),
  (1009, 203, '2026-09-01', '2026-09-30', 906, 14.71, 0.0121, 39000, 'ASSUMED'),
  (1010, 204, '2026-07-01', '2026-07-31', 384, 40.9, 0.0125, 35000, 'ASSUMED'),
  (1011, 204, '2026-08-01', '2026-08-31', 398, 40.51, 0.0136, 35000, 'ASSUMED'),
  (1012, 204, '2026-09-01', '2026-09-30', 420, 40.9, 0.0147, 35000, 'ASSUMED'),
  (1013, 205, '2026-07-01', '2026-07-31', 873, 15.94, 0.0151, 35000, 'ASSUMED'),
  (1014, 205, '2026-08-01', '2026-08-31', 896, 15.89, 0.0162, 35000, 'ASSUMED'),
  (1015, 205, '2026-09-01', '2026-09-30', 929, 15.83, 0.0173, 35000, 'ASSUMED'),
  (1016, 206, '2026-07-01', '2026-07-31', 295, 38.21, 0.0177, 35000, 'ASSUMED'),
  (1017, 206, '2026-08-01', '2026-08-31', 297, 37.44, 0.0188, 35000, 'ASSUMED'),
  (1018, 206, '2026-09-01', '2026-09-30', 313, 38.62, 0.0199, 35000, 'ASSUMED'),
  (1019, 207, '2026-07-01', '2026-07-31', 139, 24.72, 0.0203, 32000, 'ASSUMED'),
  (1020, 207, '2026-08-01', '2026-08-31', 142, 25.09, 0.0214, 32000, 'ASSUMED'),
  (1021, 207, '2026-09-01', '2026-09-30', 149, 24.6, 0.017, 32000, 'ASSUMED'),
  (1022, 208, '2026-07-01', '2026-07-31', 305, 13.85, 0.0229, 32000, 'ASSUMED'),
  (1023, 208, '2026-08-01', '2026-08-31', 325, 14.2, 0.0185, 32000, 'ASSUMED'),
  (1024, 208, '2026-09-01', '2026-09-30', 330, 13.76, 0.0196, 32000, 'ASSUMED'),
  (1025, 209, '2026-07-01', '2026-07-31', 22, 147.8, 0.02, 32000, 'ASSUMED'),
  (1026, 209, '2026-08-01', '2026-08-31', 23, 150.49, 0.0211, 32000, 'ASSUMED'),
  (1027, 209, '2026-09-01', '2026-09-30', 23, 152.6, 0.0222, 32000, 'ASSUMED'),
  (1028, 210, '2026-07-01', '2026-07-31', 1417, 13.73, 0.0226, 28000, 'ASSUMED'),
  (1029, 210, '2026-08-01', '2026-08-31', 1479, 13.87, 0.0237, 28000, 'ASSUMED'),
  (1030, 210, '2026-09-01', '2026-09-30', 1490, 13.97, 0.0248, 28000, 'ASSUMED'),
  (1031, 211, '2026-07-01', '2026-07-31', 1798, 5.01, 0.0252, 28000, 'ASSUMED'),
  (1032, 211, '2026-08-01', '2026-08-31', 1876, 5.01, 0.0263, 28000, 'ASSUMED'),
  (1033, 211, '2026-09-01', '2026-09-30', 1927, 4.95, 0.0274, 28000, 'ASSUMED'),
  (1034, 212, '2026-07-01', '2026-07-31', 449, 35.4, 0.0278, 28000, 'ASSUMED'),
  (1035, 212, '2026-08-01', '2026-08-31', 465, 36.59, 0.0289, 28000, 'ASSUMED'),
  (1036, 212, '2026-09-01', '2026-09-30', 469, 35.53, 0.0245, 28000, 'ASSUMED');
SELECT setval(pg_get_serial_sequence('process_metrics', 'metric_id'), (SELECT MAX(metric_id) FROM process_metrics), true);

INSERT INTO it_systems (system_id, company_id, system_name, system_type, api_available, data_access_level, cloud_based) OVERRIDING SYSTEM VALUE VALUES
  (301, 1, '통합 ERP', 'ERP', TRUE, 'OPEN', FALSE),
  (302, 1, '고객관계관리 CRM', 'CRM', TRUE, 'OPEN', TRUE),
  (303, 1, '전자결재·그룹웨어', 'GROUPWARE', TRUE, 'OPEN', TRUE),
  (304, 1, '인사정보시스템', 'HR', FALSE, 'RESTRICTED', FALSE),
  (305, 1, 'VOC·티켓 시스템', 'CS', TRUE, 'OPEN', TRUE),
  (306, 1, '문서 관리 시스템', 'DMS', FALSE, 'RESTRICTED', FALSE);
SELECT setval(pg_get_serial_sequence('it_systems', 'system_id'), (SELECT MAX(system_id) FROM it_systems), true);

INSERT INTO process_systems (process_id, system_id, usage_purpose) VALUES
  (201, 302, 'PRIMARY'),
  (201, 306, '영업 활동 첨부 문서 검색'),
  (202, 301, 'PRIMARY'),
  (202, 302, '견적 이력 및 고객 정보 참조'),
  (202, 303, '대외 발송 전 결재'),
  (203, 302, 'PRIMARY'),
  (204, 301, 'PRIMARY'),
  (204, 303, '비교 결과 승인'),
  (205, 301, 'PRIMARY'),
  (205, 303, '발주 승인'),
  (206, 301, 'PRIMARY'),
  (207, 303, '채용 검토 결재'),
  (207, 304, 'PRIMARY'),
  (208, 304, '인사 시스템 정보 참조'),
  (208, 306, 'PRIMARY'),
  (209, 303, 'PRIMARY'),
  (209, 304, '온보딩 대상자 정보'),
  (210, 305, 'PRIMARY'),
  (210, 306, '매뉴얼 조회'),
  (211, 305, 'PRIMARY'),
  (212, 305, 'PRIMARY'),
  (212, 306, '제품·장애 매뉴얼 검색');

INSERT INTO documents (document_id, company_id, process_id, title, doc_type, file_uri, access_level, version, created_at) OVERRIDING SYSTEM VALUE VALUES
  (401, 1, 201, '영업 업무 통합 매뉴얼', 'MANUAL', 'docs://401', 'INTERNAL', 'v2.0', '2026-10-19 10:00:00'),
  (402, 1, 205, '구매 업무 통합 매뉴얼', 'MANUAL', 'docs://402', 'INTERNAL', 'v2.0', '2026-10-19 10:00:00'),
  (403, 1, 208, '인사 업무 통합 매뉴얼', 'MANUAL', 'docs://403', 'CONFIDENTIAL', 'v2.0', '2026-10-19 10:00:00'),
  (404, 1, 210, '고객지원 업무 통합 매뉴얼', 'MANUAL', 'docs://404', 'INTERNAL', 'v2.0', '2026-10-19 10:00:00'),
  (405, 1, NULL, '통합 보안·승인 정책', 'POLICY', 'docs://405', 'INTERNAL', 'v2.0', '2026-10-19 10:00:00'),
  (406, 1, NULL, 'IT 시스템 연동 통합 명세', 'SYSTEM_SPEC', 'docs://406', 'INTERNAL', 'v2.0', '2026-10-19 10:00:00'),
  (407, 1, NULL, '부서별 AI 활용 현황 점검표', 'AI_STATUS', 'docs://407', 'INTERNAL', 'v2.0', '2026-10-19 10:00:00'),
  (408, 1, NULL, '데이터 품질·접근성 점검표', 'DATA_QUALITY', 'docs://408', 'INTERNAL', 'v2.0', '2026-10-19 10:00:00'),
  (409, 1, NULL, '기존 AX PoC 결과 보고서', 'PROJECT_REPORT', 'docs://409', 'INTERNAL', 'v2.0', '2026-10-19 10:00:00'),
  (410, 1, 210, '고객지원 제품 FAQ 기술 가이드', 'MANUAL', 'docs://410', 'INTERNAL', 'v2.0', '2026-10-19 10:00:00');
SELECT setval(pg_get_serial_sequence('documents', 'document_id'), (SELECT MAX(document_id) FROM documents), true);

INSERT INTO ai_solution_catalog (solution_id, solution_type, solution_name, description, base_build_cost_krw, monthly_run_cost_krw, automation_rate_low, automation_rate_base, automation_rate_high, time_reduction_rate_low, time_reduction_rate_base, time_reduction_rate_high, min_standardization_level, requires_api, data_source) OVERRIDING SYSTEM VALUE VALUES
  (501, 'AI_AGENT', 'CRM 영업활동 자동기록 Agent', 'LLM Agent + CRM API; 합성 기준값, 기존 후보 ID AX-S01', 80000000, 1500000, 0.51, 0.75, 0.82, 0.59, 0.74, 0.81, 0.65, TRUE, 'ASSUMED'),
  (502, 'RAG', '제안·견적 초안 생성 Copilot', 'RAG + LLM; 합성 기준값, 기존 후보 ID AX-S02', 56000000, 1000000, 0.42, 0.62, 0.69, 0.48, 0.6, 0.66, 0.65, FALSE, 'ASSUMED'),
  (503, 'PREDICTION', '리드 우선순위 예측', 'ML Classification; 합성 기준값, 기존 후보 ID AX-S03', 95000000, 1833333, 0.34, 0.5, 0.56, 0.24, 0.3, 0.33, 0.55, TRUE, 'ASSUMED'),
  (504, 'AI_AGENT', '공급업체 견적 비교 Agent', 'OCR + RAG + Agent; 합성 기준값, 기존 후보 ID AX-P01', 75000000, 1166667, 0.45, 0.66, 0.72, 0.56, 0.7, 0.77, 0.65, TRUE, 'ASSUMED'),
  (505, 'RPA', '발주서 자동 검증·등록', 'Rules + RPA + ERP API; 합성 기준값, 기존 후보 ID AX-P02', 78000000, 1333333, 0.55, 0.81, 0.89, 0.56, 0.7, 0.77, 0.65, TRUE, 'ASSUMED'),
  (506, 'AI_AGENT', '채용 서류 요약·검토 보조', 'LLM + HITL; 합성 기준값, 기존 후보 ID AX-H01', 42000000, 1083333, 0.29, 0.42, 0.46, 0.28, 0.35, 0.39, 0.55, FALSE, 'ASSUMED'),
  (507, 'RAG', '사내 인사규정 Q&A Agent', 'RAG + 권한검색; 합성 기준값, 기존 후보 ID AX-H02', 30000000, 666667, 0.5, 0.74, 0.81, 0.56, 0.7, 0.77, 0.65, FALSE, 'ASSUMED'),
  (508, 'RAG', '온보딩 안내 Agent', 'RAG + Workflow; 합성 기준값, 기존 후보 ID AX-H03', 35000000, 750000, 0.52, 0.77, 0.84, 0.48, 0.6, 0.66, 0.65, FALSE, 'ASSUMED'),
  (509, 'RAG', '제품 문의 RAG 상담 Agent', 'RAG + 상담시스템 API; 합성 기준값, 기존 후보 ID AX-C01', 75000000, 1416667, 0.53, 0.78, 0.86, 0.58, 0.72, 0.79, 0.65, TRUE, 'ASSUMED'),
  (510, 'CLASSIFICATION', '티켓 자동 분류·배정', 'Text Classification + API; 합성 기준값, 기존 후보 ID AX-C02', 55000000, 1166667, 0.61, 0.9, 1.0, 0.6, 0.75, 0.83, 0.65, TRUE, 'ASSUMED'),
  (511, 'AI_AGENT', '기술 문제 해결 Copilot', 'GraphRAG + Agent; 합성 기준값, 기존 후보 ID AX-C03', 100000000, 1916667, 0.31, 0.45, 0.5, 0.36, 0.45, 0.5, 0.55, TRUE, 'ASSUMED');
SELECT setval(pg_get_serial_sequence('ai_solution_catalog', 'solution_id'), (SELECT MAX(solution_id) FROM ai_solution_catalog), true);

INSERT INTO users (user_id, company_id, email, password_hash, user_name, created_at) OVERRIDING SYSTEM VALUE VALUES
  (601, 1, 'analyst1@gaon.example', '$2y$10$q7ou7PRvm2rMsTLKS5N3reQy/4bhPJSjF7/yRToO823GWRFykXw8G', '가상 AX 분석 담당자', '2026-10-19 10:00:00'),
  (602, 1, 'analyst2@gaon.example', '$2y$10$q7ou7PRvm2rMsTLKS5N3reQy/4bhPJSjF7/yRToO823GWRFykXw8G', '가상 전략 담당자', '2026-10-19 10:00:00');
SELECT setval(pg_get_serial_sequence('users', 'user_id'), (SELECT MAX(user_id) FROM users), true);

COMMIT;
