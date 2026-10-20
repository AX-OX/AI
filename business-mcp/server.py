"""Business MCP. 데이터 접근과 계산은 Spring 내부 API에 위임한다."""
import os
from typing import Any
from fastmcp import FastMCP
from fastmcp.exceptions import ToolError
from spring_client import call
from dto import AREAS, camel, storage_result

mcp = FastMCP('business')

@mcp.tool
async def get_company_profile(company_id: int) -> Any:
    """작업 컨텍스트의 회사 ID로 회사 정보와 부서 ID 목록을 조회한다."""
    return await call('GET', f'/companies/{company_id}')

@mcp.tool
async def get_business_processes(company_id: int, department_id: int | None = None) -> Any:
    """회사 ID와 선택적 부서 ID로 업무 절차, 표준화 수준 및 승인 조건을 조회한다."""
    return await call('GET', f'/companies/{company_id}/processes', params={'departmentId': department_id} if department_id is not None else None)

@mcp.tool
async def get_operational_metrics(company_id: int, department_id: int | None = None) -> Any:
    """회사와 선택적 부서의 최근 3개월 업무 지표를 조회한다. 시간은 분, 인건비는 원이다."""
    return await call('GET', f'/companies/{company_id}/metrics', params={'departmentId': department_id} if department_id is not None else None)

@mcp.tool
async def get_system_inventory(company_id: int) -> Any:
    """회사 ID로 IT 시스템, API 제공 여부와 업무 연결 정보를 조회한다."""
    return await call('GET', f'/companies/{company_id}/systems')

@mcp.tool
async def get_project_budget(company_id: int) -> Any:
    """회사 ID로 연간 AX 예산을 원 단위로 조회한다."""
    return await call('GET', f'/companies/{company_id}/budget')

@mcp.tool
async def get_solution_catalog() -> Any:
    """솔루션 ID, target_process_id, depends_on_solution_id, 비용(원), 자동화율(0~1) 및 적용 조건을 조회한다."""
    return await call('GET', '/solutions')

@mcp.tool
async def calculate_ax_roi(process_id: int, solution_id: int) -> Any:
    """업무·솔루션 ID로 Spring의 AX점수(Impact 60%, Feasibility 40%)·사람 검토 여부·경고와 ROI·회수 기간·3년 순편익 세 시나리오를 받는다. 신뢰도는 표시만 한다. 수치는 가정이며 PoC 검증이 필요하다."""
    return await call('POST', '/ax/roi', body={'processId': process_id, 'solutionId': solution_id})

@mcp.tool
async def optimize_ax_portfolio(company_id: int, candidates: list[dict[str, int]], max_items: int = 3) -> Any:
    """회사 ID와 process_id, solution_id 후보로 예산·중복 업무·정책 제외·선행 과제 제약 안에서 AX점수 합 최대 max_items개 조합을 Spring에 요청한다."""
    if not 1 <= max_items <= 10 or len(candidates) > 10:
        raise ToolError('max_items는 1~10, 후보는 최대 10개여야 합니다.')
    if any(set(c) != {'process_id', 'solution_id'} for c in candidates):
        raise ToolError('각 후보에 process_id와 solution_id가 필요합니다.')
    return await call('POST', '/ax/portfolio', body={'companyId': company_id, 'candidates': [{'processId': c['process_id'], 'solutionId': c['solution_id']} for c in candidates], 'maxItems': max_items})

@mcp.tool
async def save_assessment(task_id: str, scores: dict[str, Any], criteria_version: str, evidence: list[dict[str, Any]]) -> Any:
    """작업 ID, 0~100 영역 점수, 기준 버전과 문서 근거를 Spring에 저장한다."""
    evidence = [{**row, 'area': AREAS.get(row.get('area'), row.get('area'))} for row in evidence]
    result = await call('POST', '/assessments', body={'taskId': task_id,
        'scores': {AREAS.get(k,k):v for k,v in scores.items()},
        'criteriaVersion': criteria_version, 'evidence': camel(evidence)})
    return storage_result(result)

@mcp.tool(annotations={'destructiveHint': True})
async def create_ax_roadmap(task_id: str, company_id: int, assessment_id: int | None, roadmap_name: str, items: list[dict[str, Any]]) -> Any:
    """요청자 승인 후 작업 ID, 회사, 평가 ID와 로드맵 항목으로 로드맵을 생성한다. 금액은 원이다."""
    result = await call('POST', '/roadmaps', body={'taskId': task_id, 'companyId': company_id, 'assessmentId': assessment_id, 'roadmapName': roadmap_name, 'items': camel(items)})
    return storage_result(result)

@mcp.tool(annotations={'destructiveHint': True})
async def create_ax_project(item_id: int, owner_department_id: int, project_name: str) -> Any:
    """요청자 승인 후 생성된 로드맵 항목 ID와 담당 부서 ID로 프로젝트를 등록한다."""
    return storage_result(await call('POST', '/projects', body={'itemId': item_id, 'ownerDepartmentId': owner_department_id, 'projectName': project_name}))

@mcp.tool(annotations={'destructiveHint': True})
async def update_project_status(project_id: int, status: str) -> Any:
    """요청자 승인 후 프로젝트 상태를 REGISTERED, IN_PROGRESS, ON_HOLD, COMPLETED 중 하나로 바꾼다."""
    if status not in {'REGISTERED', 'IN_PROGRESS', 'ON_HOLD', 'COMPLETED'}:
        raise ToolError('유효한 상태: REGISTERED, IN_PROGRESS, ON_HOLD, COMPLETED')
    return await call('PATCH', f'/projects/{project_id}/status', body={'status': status})

if __name__ == '__main__':
    mcp.run(transport='http', host=os.getenv('MCP_HOST', '0.0.0.0'), port=int(os.getenv('MCP_PORT', '9101')), path='/mcp')
