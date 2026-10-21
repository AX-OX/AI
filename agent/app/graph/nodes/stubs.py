"""Node 스텁. MCP·데이터 연결 전까지 그래프 흐름을 검증하기 위한 자리표시자.

각 Node는 실제 구현이 나오면 별도 파일로 옮겨 builder의 기본 매핑을 교체한다.
스텁은 업무 데이터를 만들지 않는다 (빈 값만 채운다).
"""

from ...models.state import AXState


# 🔴 실제 구현에는 business-mcp 조회 도구(MCP 연결 + 업무 데이터)가 필요
async def collect(state: AXState) -> dict:
    return {}


# 🔴 rag-mcp search_docs + 색인된 문서 필요
async def retrieve(state: AXState) -> dict:
    return {}


# 🔴 문서 근거 + LLM 필요
async def assess(state: AXState) -> dict:
    return {}


# 🔴 솔루션 카탈로그·업무 데이터 필요
async def discover(state: AXState) -> dict:
    return {}


# 🔴 Spring ROI·포트폴리오 계산(MCP 경유) 필요
async def evaluate(state: AXState) -> dict:
    return {}


# 🔴 앞 단계 결과 전체 필요
async def roadmap(state: AXState) -> dict:
    return {}


# 🔴 MCP 쓰기 도구(create_ax_roadmap, create_ax_project) 필요
async def register(state: AXState) -> dict:
    return {}
