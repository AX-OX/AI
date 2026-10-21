"""Readable CLI presentation; full API trace remains available via --verbose/--output."""
import json
import unicodedata

NODE_LABELS={
    'collect':'1/8 회사 데이터 수집', 'retrieve':'2/8 근거 문서 검색',
    'assess':'3/8 성숙도 평가', 'discover':'4/8 AX 후보 생성',
    'evaluate':'5/8 점수·예산·선행 과제 검증', 'roadmap':'6/8 로드맵·응답 작성',
    'approval':'7/8 자동 진행', 'register':'8/8 가상 프로젝트 등록',
}
TOOL_LABELS={'get_company_profile':'기업 정보','get_business_processes':'업무 목록',
             'get_operational_metrics':'업무 지표','get_system_inventory':'IT 시스템',
             'get_project_budget':'예산','get_solution_catalog':'솔루션 목록'}
QUIT_WORDS={'/exit','exit','/quit','quit','종료'}


def width(text):
    return sum(0 if unicodedata.combining(c) else 2 if unicodedata.east_asian_width(c) in 'WF' else 1 for c in str(text))


def cell(text,size):
    value=str(text)
    if width(value)>size:
        while value and width(value+'…')>size:value=value[:-1]
        value+='…'
    return value+' '*max(0,size-width(value))


def paragraph(text,limit=94):
    lines=[]
    for source in str(text).splitlines():
        if not source.strip():lines.append('');continue
        current='  ' if source.startswith('  ') else ''
        continuation='  ' if source.startswith(('-', '  ')) else ''
        for word in source.split():
            separator=' ' if current.strip() else ''
            if width(current+separator+word)>limit and current.strip():
                lines.append(current);current=continuation;separator=''
            if width(current+word)>limit:
                for char in word:
                    if width(current+char)>limit:lines.append(current);current=continuation
                    current+=char
            else:current+=separator+word
        lines.append(current)
    return '\n'.join(lines)


class TracePrinter:
    def __init__(self,verbose=False):
        self.verbose=verbose
        self.tool_counts={}

    def show(self,event):
        node,kind,data=event['node'],event['type'],event['data']
        if self.verbose:
            print(f"  [{node or 'task'}] {kind} {json.dumps(data,ensure_ascii=False)}",flush=True)
            return
        if kind=='NODE_START':
            self.tool_counts[node]=0
            print(f"\n[{NODE_LABELS.get(node,node)}] 진행 중",flush=True)
        elif kind=='TOOL_CALL':self.tool_counts[node]=self.tool_counts.get(node,0)+1
        elif kind=='NODE_END':
            count=self.tool_counts.get(node,0)
            print(f"  완료{f' · 도구 {count}회 호출' if count else ''}",flush=True)
        elif kind=='LLM_RESPONSE' and data.get('toolCalls'):
            names=[TOOL_LABELS.get(t,t) for t in data['toolCalls']]
            print('  LLM 도구 선택: '+', '.join(names),flush=True)
        elif kind=='LLM_REQUEST' and data.get('attempt',1)>1:
            print(f"  LLM 재시도 {data['attempt']}회차",flush=True)
        elif kind=='REQUEST_SCOPE':
            names=', '.join(data.get('departmentNames',[]))
            print(f"  분석 범위: {names} · 업무 {len(data.get('processIds',[]))}개",flush=True)
        elif kind=='CANDIDATES_PROPOSED':print(f"  후보 {len(data.get('candidates',[]))}개 제안",flush=True)
        elif kind=='APPROVAL_REQUIRED':print('\n[7/8 자동 진행] 가상 등록 준비',flush=True)
        elif kind in {'LLM_ERROR','NODE_ERROR','TOOL_REJECTED'}:
            detail=data.get('message') or data.get('reason') or f"{data.get('errorType','오류')} / HTTP {data.get('httpStatus','-')}"
            print('  오류: '+paragraph(detail),flush=True)


def display_result(body):
    print('\n'+'='*78)
    if body['status']=='FAILED':
        print('작업 실패')
        for error in body.get('errors',[]):print(paragraph(error))
        print('문제가 난 단계와 오류 사유를 확인하세요. 상세 기록: --verbose')
        return
    result=body['result'];portfolio=result.get('portfolio') or {};roadmap=result.get('roadmap') or {}
    names=', '.join((result.get('scope') or {}).get('departmentNames',[]))
    print(f"분석 결과{f' · {names}' if names else ''}")
    print(f"AX점수 합 {portfolio.get('totalAxScore','-')} | 총비용 {portfolio.get('totalFirstYearTcoKrw',0):,}원 | 잔여 예산 {portfolio.get('remainingBudgetKrw',0):,}원")
    print('-'*78)
    sizes=(4,30,8,16,10)
    header=('순서','과제','AX점수','초년도 비용','사람 검토')
    print(' '.join(cell(v,n) for v,n in zip(header,sizes)))
    for item in roadmap.get('items',[]):
        values=(item['priorityOrder'],item['itemName'],item['axScore'],f"{item['allocatedBudgetKrw']:,}원",'필요' if item['humanReviewRequired'] else '예외 이관')
        print(' '.join(cell(v,n) for v,n in zip(values,sizes)))
    print('\nAgent 응답')
    answer=result.get('answer') or '(응답 없음)'
    if body['status']=='DONE':
        answer=answer.replace('요청자 승인 후 로드맵·프로젝트를 등록합니다.', '로드맵·프로젝트 가상 등록까지 완료했습니다.')
    print(paragraph(answer))
    print('\n현재 결과는 가정 데이터 기반이며, 자동 등록은 실제 DB 저장이 아닌 가상 등록입니다.')
    print('='*78)


def display_registration(body):
    print('\n'+'-'*60)
    if body['status']=='DONE':
        registration=body['result'].get('registration') or {}
        projects=registration.get('projects',[])
        print(f"가상 등록 완료 · 로드맵 {registration.get('roadmap_id','-')} · 프로젝트 {len(projects)}개")
        print('가상 프로젝트 ID: '+', '.join(str(p['project_id']) for p in projects))
        print('실제 DB에는 저장되지 않았습니다.')
    elif body['status']=='REJECTED':print('등록을 거절했습니다. 로드맵·프로젝트를 생성하지 않았습니다.')
    else:
        print('최종 상태: '+body['status'])
        for error in body.get('errors',[]):print(paragraph(error))
    print('-'*60)


def read_request():
    text=input('\n질문 (exit 종료 / /multi 여러 줄 입력)> ').strip()
    if text.lower() in QUIT_WORDS:return None
    if text=='/multi':
        print('질문을 붙여 넣은 뒤 마지막 줄에 /send를 입력하세요. /exit로 종료합니다.')
        lines=[]
        while True:
            line=input()
            if line.strip().lower() in QUIT_WORDS:return None
            if line.strip()=='/send':return '\n'.join(lines).strip()
            lines.append(line)
    return text

