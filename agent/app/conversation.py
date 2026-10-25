"""Read-only conversation entry point. Only Spring may turn ANALYZE into a task."""
import asyncio
import logging
import re
from typing import Literal
from uuid import UUID, uuid4

from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, ConfigDict, Field, model_validator

from .reasoning import prompt
from .contexts import context_json

log = logging.getLogger(__name__)
Intent = Literal['GREETING', 'SERVICE_QA', 'RESULT_QA', 'ANALYZE', 'CLARIFY', 'OUT_OF_SCOPE']
GREETING = '안녕하세요! AXOX는 기업의 AX 성숙도 진단, 업무 자동화 과제 추천과 도입 로드맵을 도와드려요. AX 관련 질문이나 기존 분석 결과에 대해 물어보셔도 좋아요.'
CLARIFY = 'AX 개념이나 사용 방법이 궁금하신가요, 아니면 회사 데이터를 바탕으로 새 분석을 실행할까요?'
OUT_OF_SCOPE = '저는 기업의 AX 진단, 업무 자동화 과제와 도입 로드맵에 관한 질문을 도와드려요. 해당 요청은 지원 범위에 포함되지 않아요. AX 관련 질문이나 기존 분석 결과에 대해 물어봐 주세요.'
MISSING_RESULT = '설명할 분석 결과가 아직 연결되어 있지 않아요. 작업 이력에서 해당 분석을 불러온 뒤 질문해 주세요. 새 분석을 원하시면 분석할 회사 업무와 요청 내용을 알려 주세요.'


class Message(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    role: Literal['user', 'assistant']
    content: str = Field(min_length=1, max_length=4000)


class TaskContext(BaseModel):
    model_config = ConfigDict(extra='forbid')
    taskId: UUID
    status: Literal['QUEUED', 'RUNNING', 'WAITING_CONFIRMATION', 'WAITING_APPROVAL', 'DONE', 'FAILED', 'REJECTED']
    result: dict | None
    requestText: str | None = Field(default=None, max_length=8000)


class ChatRequest(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    message: str = Field(min_length=1, max_length=4000)
    history: list[Message] = Field(default_factory=list, max_length=12)
    task: TaskContext | None = None

    @model_validator(mode='after')
    def bounded_context(self):
        if sum(len(m.content) for m in self.history) > 16000:
            raise ValueError('Conversation history exceeds 16000 characters')
        if self.task and len(self.task.model_dump_json()) > 80000:
            raise ValueError('Analysis context exceeds 80000 characters')
        return self


class RouteDecision(BaseModel):
    model_config = ConfigDict(extra='forbid')
    intent: Intent
    analysisRequest: str | None = Field(description='ANALYZE일 때만, 명시적인 실행 요청과 대화에서 확정한 조건을 합친 요청. 그 외 null.')
    clarification: str | None = Field(description='CLARIFY일 때 사용자에게 할 구체적인 확인 질문. 그 외 null.')

    @model_validator(mode='after')
    def valid_execution(self):
        if self.intent == 'ANALYZE':
            if not self.analysisRequest or not 1 <= len(self.analysisRequest.strip()) <= 4000:
                raise ValueError('ANALYZE requires a bounded analysis request')
        elif self.analysisRequest is not None:
            raise ValueError('Only ANALYZE may carry an analysis request')
        if self.clarification is not None and not 1 <= len(self.clarification.strip()) <= 2000:
            raise ValueError('Invalid clarification')
        return self


class Answer(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    message: str = Field(min_length=1, max_length=6000)


class ChatReply(BaseModel):
    intent: Intent
    message: str
    analysisRequest: str | None = None


def simple_greeting(text):
    # Exact utterances only: "안녕, 회사 분석해줘" must still reach the router.
    normalized = re.sub(r'[\s!?.~。！？]+', '', text.casefold())
    return normalized in {'안녕', '안녕하세요', '안녕하십니까', '반가워', '반갑습니다',
                          '고마워', '감사합니다', '고맙습니다', 'hi', 'hello', 'thanks', 'thankyou'}


class Conversation:
    def __init__(self, reasoner, *, mock=False):
        self.reasoner = reasoner
        self.mock = mock
        self.slots = asyncio.Semaphore(4)

    async def reply(self, request: ChatRequest) -> ChatReply:
        if simple_greeting(request.message):
            return self._reply('GREETING', GREETING)
        # Includes queue time; an unavailable model must never fall back to execution.
        async with asyncio.timeout(24):
            async with self.slots:
                request_id = str(uuid4())
                route = self.mock_route(request) if self.mock else await self.route(request, request_id)
                if route.intent == 'ANALYZE':
                    return self._reply('ANALYZE', '요청하신 조건으로 새 분석을 시작할게요.', route.analysisRequest.strip())
                if route.intent == 'GREETING':
                    return self._reply('GREETING', GREETING)
                if route.intent == 'OUT_OF_SCOPE':
                    return self._reply('OUT_OF_SCOPE', OUT_OF_SCOPE)
                if route.intent == 'CLARIFY':
                    return self._reply('CLARIFY', route.clarification or CLARIFY)
                if route.intent == 'RESULT_QA' and not request.task:
                    return self._reply('CLARIFY', MISSING_RESULT)
                if self.mock:
                    message = self.mock_answer(request, route.intent)
                else:
                    message = await self.answer(request, route.intent, request_id)
                return self._reply(route.intent, message)

    @staticmethod
    def _reply(intent, message, analysis_request=None):
        # No user messages, company results, tokens or credentials in routing logs.
        log.info('chat_route intent=%s starts_analysis=%s', intent, intent == 'ANALYZE')
        return ChatReply(intent=intent, message=message, analysisRequest=analysis_request)

    async def route(self, request, request_id):
        context = {'message': request.message, 'history': [m.model_dump() for m in request.history],
                   'hasAnalysis': request.task is not None,
                   'analysisStatus': request.task.status if request.task else None,
                   'previousAnalysisRequest': request.task.requestText if request.task else None}
        messages = [SystemMessage(content=prompt('chat_route')),
                    HumanMessage(content=context_json(context, stage='chat_route', limit=42000))]

        async def generate(model):
            return await model.with_structured_output(RouteDecision, method='function_calling', strict=True).ainvoke(messages)

        result = await self.reasoner.invoke(generate, task_id=request_id, stage='chat_route')
        return RouteDecision.model_validate(result)

    async def answer(self, request, intent, request_id):
        context = {'intent': intent, 'message': request.message,
                   'history': [m.model_dump() for m in request.history],
                   'analysis': request.task.model_dump(mode='json') if request.task else None}
        messages = [SystemMessage(content=prompt('chat_answer')),
                    HumanMessage(content=context_json(context, stage='chat_answer', limit=120000))]

        async def generate(model):
            return await model.with_structured_output(Answer, method='function_calling', strict=True).ainvoke(messages)

        result = await self.reasoner.invoke(generate, task_id=request_id, stage='chat_answer')
        return Answer.model_validate(result).message

    @staticmethod
    def mock_route(request):
        """Deterministic offline demo only. Live mode always uses the semantic router."""
        text = request.message
        if re.search(r'날씨|저녁|맛집|주식|로또|시스템\s*프롬프트', text):
            intent = 'OUT_OF_SCOPE'
        elif re.search(r'하지\s*말|방법|뭐야|무엇|어떻게|하면.*(비용|달라)|할\s*수\s*있', text):
            intent = 'SERVICE_QA'
        elif re.search(r'분석해|진단해|선정해|만들어|추천해|분석.*실행|진단.*해\s*줘|선정하고|진단하고', text):
            intent = 'ANALYZE'
        elif re.search(r'아까|기존|결과|이\s*과제|두\s*번째|1순위|왜.*추천|ROI.*높', text):
            intent = 'RESULT_QA'
        elif re.search(r'AX|ROI|성숙도|자동화|로드맵|사용|할\s*수|PDF', text, re.I):
            intent = 'SERVICE_QA'
        else:
            intent = 'CLARIFY'
        return RouteDecision(intent=intent, analysisRequest=text if intent == 'ANALYZE' else None,
                             clarification=CLARIFY if intent == 'CLARIFY' else None)

    @staticmethod
    def mock_answer(request, intent):
        if intent == 'RESULT_QA':
            if not request.task.result:
                return f'연결된 분석의 현재 상태는 {request.task.status}예요. 아직 설명할 분석 결과가 준비되지 않았어요. 새 분석은 실행하지 않았어요.'
            answer = request.task.result.get('answer')
            return ('연결된 기존 분석 결과를 바탕으로 설명드릴게요.\n\n' + str(answer)[:4500]) if answer else '기존 분석 결과가 연결되어 있어요. 어떤 과제나 지표를 설명해 드릴까요? 새 분석은 실행하지 않았어요.'
        if 'ROI' in request.message.upper():
            return 'ROI는 투자 비용에 비해 얻는 순편익의 비율이에요. 예상 절감액과 도입·운영 비용, 산정 기간을 함께 확인해야 해요. 회사별 수치는 기존 분석 결과가 있어야 설명할 수 있어요.'
        return 'AXOX는 기업 데이터를 바탕으로 AX 성숙도를 진단하고 자동화 과제와 도입 로드맵을 추천해요. 개념이나 사용 방법은 바로 질문하셔도 되고, 새 분석은 “우리 회사 AX 과제를 분석해 줘”처럼 요청해 주세요.'
