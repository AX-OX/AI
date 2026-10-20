> 과거 입력 제안 보존 문서입니다. 현재 실행 기준은 `AX_NAVIGATOR_CONTEXT.md`와 v3 정책이며 이 문서의 이전 점수식을 사용하지 않습니다.

AX Navigator AI — 정량적 평가 기준 개선안
McKinsey·BCG·Microsoft 프레임워크 기반 | 2일 MVP
핵심 방향

기존 기업 전체 AX 성숙도 평가 → 업무별 AI 도입 적합성 및 투자 우선순위 평가로 변경
제조·영업·구매·인사 등 다양한 부서에 공통 적용
실제 컨설팅 기관의 평가 원칙을 참고하되, 계산식은 MVP 수준으로 단순화
정량 평가 3개 + ROI 계산 1개 + 위험 검증 1개로 구성
기존 LangGraph·MCP·Spring Boot 구조 최대한 유지
1. 평가 기준 선정 근거
① Microsoft — AI 도입 후보의 사업적 가치와 실행 가능성 평가
근거 자료: Microsoft — Business plan for AI agents

AI 도입 후보를 Business Impact, Technical Feasibility, User Desirability의 세 가지 영역으로 평가
각 영역을 1~5점 척도로 평가하여 AI 도입 우선순위 결정
비즈니스 효과가 높더라도 기술적 구현이 어렵거나 사용자의 수용성이 낮으면 우선순위를 조정
핵심 KPI를 설정하고 PoC 결과에 따라 투자 지속 여부 결정
→ 프로젝트 적용

업무별 비즈니스 효과, AI 적용 가능성, 도입 준비도를 정량 평가
각 평가 항목을 0~100점으로 환산
최종 평가 점수로 업무별 AI 도입 우선순위 산출
Microsoft의 세 가지 평가 영역은 공식 기준이며, 아래에서 제안하는 가중치와 세부 계산식은 AX Navigator 자체 설계임. Microsoft Learn
② BCG — AI 도입의 실질적인 생산성 개선 효과 중시
근거 자료: BCG — The CIO's Role in AI Transformation and Productivity

AI 도입 후보 선정 시 기존 업무 비용뿐 아니라 예상 생산성 개선 효과를 함께 고려
비용 규모가 큰 업무보다 실제 효율성 개선 가능성이 높은 업무가 우선될 수 있음
AI 전환은 기술 도입뿐 아니라 업무 프로세스 재설계와 조직 변화가 중요
10/20/70 원칙 강조: 알고리즘 10%, 기술·데이터 20%, 사람·프로세스 70%
→ 프로젝트 적용

연간 업무 투입 시간과 AI 적용 후 예상 절감 시간 계산
업무량과 생산성 개선 가능성을 결합해 기대 효과 평가
단순 기술 도입 가능 여부보다 실제 업무 개선 효과 중시
※ BCG의 10/20/70은 전환 노력의 배분을 설명하는 원칙이며, AX 점수 가중치가 아님. BCG Global
③ McKinsey — 업무 재설계 및 성과 KPI 중심
근거 자료: McKinsey — The State of AI: How Organizations Are Rewiring to Capture Value (2025)

AI 성과를 높이기 위해 기존 업무 프로세스를 재설계하는 것이 중요
AI 도입 성과를 판단할 수 있는 구체적인 KPI 설정과 추적 강조
AI 도입 자체가 아니라 실제 비용·생산성·업무 성과 개선 여부 측정
조직 전체에 확대하기 전 개별 업무의 성과를 검증하는 접근 필요
→ 프로젝트 적용

업무별 처리량·처리 시간·오류율을 핵심 KPI로 활용
AI 도입 전 기준값(Baseline)을 계산
AI 도입 후 예상 성과를 산출하고 도입 전후 비교
측정 데이터가 없으면 가정 기반 추정치임을 명시
McKinsey의 연구 결과와 KPI 활용 원칙을 참고한 것이며, 아래 점수 공식은 McKinsey가 직접 제시한 공식이 아님. McKinsey & Company

2. AX Navigator 정량 평가 함수 — 최종 제안
기존 데이터를 그대로 활용할 수 있도록 3개 평가 점수와 ROI 함수만 구현하는 것을 추천함.
① Business Impact Score — 기대 효과 (50%)
평가 목적

AI 도입에 따른 생산성 개선 효과 측정
McKinsey의 업무 성과 KPI 측정 및 BCG의 생산성 개선 중심 접근 반영
정량 지표

월간 업무 처리 건수
건당 평균 처리 시간
예상 자동화율
예상 처리 시간 절감률
계산식
annual_hours = monthly_count * avg_minutes / 60 * 12saved_hours = (    annual_hours    * automation_rate    * time_reduction_rate)impact_score = min(100, saved_hours / 2000 * 100)
연간 절감 가능 시간이 2,000시간 이상이면 100점
1,000시간이면 50점
500시간이면 25점
※ 2,000시간은 프로젝트에서 임의로 설정하는 정규화 기준으로, 컨설팅 기관이 제시한 표준이 아님.
② Technical Feasibility Score — 기술적 실현 가능성 (35%)
평가 목적

업무에 AI를 적용할 수 있는 기술적 환경 평가
Microsoft의 기술 적합성·운영 가능성 평가 기준 반영
정량 지표

업무 표준화 수준
기존 시스템 연동 가능 여부
계산식
feasibility_score = (    standardization_level * 60    + api_available * 40)
standardization_level: 0~1
api_available: 가능 1, 불가능 0
예시

표준화 수준 0.8
API 연동 가능
0.8 × 60 + 1 × 40 = 88점※ 기존 시스템과의 연동이 API 외의 방식으로도 가능할 수 있으므로, MVP에서는 API 유무를 단순 대리 지표로 사용함.
③ Data Confidence Score — 데이터 신뢰도 (15%)
평가 목적

분석에 사용한 데이터의 신뢰성 평가
Microsoft의 데이터 가용성 검토 및 McKinsey의 KPI 기반 성과 측정 원칙 반영
정량 지표

데이터 출처 유형
계산식
confidence_scores = {    "MEASURED": 100,    "SURVEY": 60,    "ASSUMED": 20}confidence_score = confidence_scores[data_source]데이터 유형점수의미MEASURED100실제 측정 데이터SURVEY60담당자 설문 기반ASSUMED20가정 데이터

데이터의 출처에 따라 분석 결과의 신뢰 수준 구분
가정 데이터만 존재하면 낮은 신뢰도 표시
실제 데이터가 없더라도 분석은 가능하지만 추정치임을 명시
※ 이 점수는 데이터 품질 자체가 아니라 근거의 신뢰 수준을 나타냄. 점수 100이라고 해서 데이터가 정확하다는 의미는 아님.

3. 최종 AX Opportunity Score 계산
세 가지 평가 결과를 가중합하여 업무별 AI 도입 우선순위 점수 산출
ax_score = (    impact_score * 0.50    + feasibility_score * 0.35    + confidence_score * 0.15)평가 항목가중치근거Business Impact50%McKinsey, BCGTechnical Feasibility35%MicrosoftData Confidence15%Microsoft, McKinsey의 데이터·KPI 검증 원칙 참고합계100%
가중치는 프로젝트에서 설정한 초기 가설이며, 공식 컨설팅 평가 가중치가 아님.
평가 예시
업무ImpactFeasibilityConfidence최종 점수고객 문의 분류908510089.75견적 비교80906080.50영업 보고서 작성658010075.50사내 규정 문의55956069.75
위 점수는 계산 방식의 예시이며 실측 결과가 아님.
→ 점수가 높은 업무를 우선 검토하되, 신뢰도가 낮은 업무는 PoC 검증을 선행하도록 안내.

4. ROI 계산 — 기존 함수 유지
평가 목적

AX 전환에 따른 경제적 타당성 검증
BCG의 생산성 개선 효과 중심 투자 판단 반영
Microsoft의 KPI 기반 투자 의사결정 원칙 반영
계산식
annual_saving = saved_hours * hourly_labor_costfirst_year_cost = (    build_cost    + monthly_run_cost * 12)roi = (    (annual_saving - first_year_cost)    / first_year_cost) * 100
구축비와 운영비는 기존 ai_solution_catalog 활용
자동화율 및 시간 절감률도 기존 카탈로그 활용
보수·기준·낙관 3개 시나리오 유지
연간 절감액은 인건비 환산 가치이며 실제 현금 절감액과 구분
ROI는 AX Opportunity Score와 별도로 표시.

5. 위험 평가 — 복잡한 점수 대신 간단한 조건문
근거: Microsoft는 AI 도입 시 보안·운영 위험과 안전장치의 충분성을 검토하고, 보호 조치가 불명확하면 도입을 보류하도록 권고함. Microsoft Learn
프로젝트 적용

시스템 데이터 접근 불가 → DATA_ACCESS_BLOCKED
업무 예외 규칙 존재 → REVIEW_REQUIRED
기타 → ELIGIBLE
if data_access_level == "NONE":    status = "DATA_ACCESS_BLOCKED"elif exception_rules:    status = "REVIEW_REQUIRED"else:    status = "ELIGIBLE"
DATA_ACCESS_BLOCKED: 접근 문제 해결 전 도입 보류
REVIEW_REQUIRED: 사람의 검토 필요
ELIGIBLE: 초기 검토 통과
ELIGIBLE은 법적·보안적 안전성이 검증되었다는 뜻은 아님. MVP에서 확인 가능한 조건만 통과했다는 의미임.

6. 기존 프로젝트 적용 범위
기존 아키텍처 최대한 유지
구성 요소변경 사항LangGraph기존 그래프 유지MCP Server기존 도구 유지Spring Boot평가 점수 계산 함수 변경PostgreSQL기존 업무 지표 활용Chroma RAG평가 근거 문서 검색 유지ROI Calculator기존 계산식 유지Portfolio Optimizer새로운 점수를 우선순위에 반영HITL기존 승인 프로세스 유지Frontend업무별 점수·ROI·근거 표시
현재 Spring Boot의 ROI 계산과 feasibility_score 계산이 정의되어 있으므로, 이를 재활용하면 구현 범위를 줄일 수 있어. 다만 최종 평가 점수를 포트폴리오에 적용하려면 기존 계산 계약은 수정해야 함.  AX_NAVIGATOR_CONTEXT
2일 개발 범위
Day 1 — 평가 로직 및 Agent 연동

3개 평가 함수 구현
기존 업무 데이터 연결
MCP를 통한 계산 결과 조회
RAG 기반 추천 근거 생성
업무별 평가 결과 반환
Day 2 — 로드맵 및 시연

최종 점수 기반 업무 순위 산출
기존 ROI 계산 및 포트폴리오 최적화 연결
상위 3개 업무 선정
사용자 승인 및 프로젝트 등록
프론트엔드 결과 표시
테스트 및 시연


7. 최종 프로젝트 정의
AX Navigator AI
글로벌 AX 평가 프레임워크 기반 AI 전환 투자 의사결정 Agent
평가 방법

McKinsey·BCG의 생산성 및 업무 성과 개선 원칙을 반영한 Business Impact 평가
Microsoft의 기술적 타당성 평가를 반영한 Technical Feasibility 평가
데이터 출처를 기반으로 분석 신뢰도를 구분하는 Data Confidence 평가
기존 ROI 모델을 활용한 경제성 분석
위험 조건 검증을 통한 도입 보류 및 검토 필요 과제 식별
최종 산출물

업무별 AX Opportunity Score(0~100)
업무별 예상 절감 시간
예상 구축비·운영비·ROI
평가 근거 및 데이터 신뢰도
AI 도입 우선순위 TOP 3
예산 내 AX 전환 로드맵
핵심 차별점

AI가 임의로 성숙도 점수를 생성하지 않음.
기존 업무 데이터와 명시적인 계산식을 활용함.
글로벌 컨설팅 기관과 Microsoft의 평가 원칙을 참고함.
LLM은 업무 해석·솔루션 추천·근거 설명에 집중함.
정량적 점수 산출은 Spring Boot에서 수행함.
최종적으로 2일 MVP에서는 정량 함수 3개, 기존 ROI 함수 1개, 위험 조건문 1개만 구현하면 돼. 여기에 기존 LangGraph와 MCP를 연결하는 방식이 가장 현실적이야.
이 설계에서는 실제 PoC로 검증하지 않은 시간 절감률과 ROI는 어디까지나 예상치라는 점을 명확히 표시해야 해.