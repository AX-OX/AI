"""v3 orchestration. Spring owns scores and optimization; this module validates contracts."""
import json
from decimal import Decimal
from langgraph.types import interrupt
from ...schemas import AXState, Assessment, RoiResult
from ...scope import request_scope
from ...budget import request_budget
from ...contexts import ASSESSMENT_TYPES
from ...assessment import load_policy, AssessmentReferenceError
from ...contracts import normalize_read
from ...candidates import pair, pair_id, roi_dependency, normalize_candidates, eligible_candidates, exclusions, grounded_rows
from ...presentation import candidates_dto, evidence_dto, maturity_dto, names_for, projects_dto


def truth(value):
    return value is True or str(value).lower() in {'true', '1'}


def display_roadmap(roadmap, state=None):
    if not roadmap:
        return None
    names = {'process_id':'processId','solution_id':'solutionId','item_name':'itemName',
             'priority_order':'priorityOrder','start_month':'startMonth','duration_months':'durationMonths',
             'allocated_budget_krw':'allocatedBudgetKrw','ax_score':'axScore','impact_score':'impactScore',
             'feasibility_score':'feasibilityScore','expected_annual_saving_krw':'expectedAnnualSavingKrw',
             'roi_pct':'roiPct','payback_months':'paybackMonths','three_year_net_value_krw':'threeYearNetKrw'}
    reviews = roadmap['humanReviewByCandidate']
    return {k:v for k,v in roadmap.items() if k not in {'items','humanReviewByCandidate'}} | {
        'budgetLimitKrw': roadmap['budgetKrw'],
        'approvalStatus': {'APPROVE':'APPROVED','REJECT':'REJECTED'}.get(
            ((state or {}).get('approval') or {}).get('decision'), 'PENDING'),
        'items': [{**{names.get(k,k):v for k,v in item.items()},
                   **names_for(state or {}, item['process_id'], item['solution_id']),
                   'threeYearNetValueKrw': item['three_year_net_value_krw'],
                   'evidence': evidence_dto(item['evidence']),
                   'humanReviewRequired': reviews[pair_id(item)]} for item in roadmap['items']]}


def task_result(state, mode):
    answer = state.get('answer')
    if answer and state.get('status') == 'DONE':
        answer = answer.replace('요청자 승인 후 로드맵·프로젝트를 등록합니다.',
                                '로드맵·프로젝트 등록을 완료했습니다.' if mode == 'live' else '로드맵·프로젝트 가상 등록을 완료했습니다.')
    return {'scope': state.get('scope'), 'assessment': state.get('maturity'),
            'maturity': maturity_dto(state.get('maturity')), 'candidates': candidates_dto(state),
            'portfolio': state.get('portfolio'), 'excluded': state.get('excluded', []),
            'roadmap': display_roadmap(state.get('roadmap'), state), 'evaluationPolicy': state.get('evaluation_policy'),
            'insufficientData': state.get('insufficient_data', []), 'registration': state.get('registration'),
            'projects': projects_dto(state), 'answer': answer, 'mode': mode,
            'extraction': {'draftId': state['extraction']['draft_id']} if state.get('extraction') else None,
            'priorityBasis': 'AX_SCORE',
            'notice': '가정 데이터 기반. 절감액은 인력 시간 환산 가치이며 확정 현금 절감이 아닙니다.'}


def approval_payload(state):
    roadmap = display_roadmap(state['roadmap'], state)
    return {'roadmap': roadmap, 'items': roadmap['items'], 'totalAllocatedKrw': roadmap['totalAllocatedKrw'],
            'budgetKrw': roadmap['budgetKrw'], 'totalAxScore': state['portfolio']['totalAxScore'],
            'excluded': state['excluded'], 'assessment': state['maturity']}


def build_nodes(gateway, reasoner, settings):
    policy = json.loads(settings.policy_file.read_text(encoding='utf-8'))
    maturity_policy = load_policy(settings)

    async def tool(state, node, name, **args):
        return await gateway.tool(state['task_id'], node, name, args)

    async def extract(state):
        document_ids = state.get('document_ids') or []
        if not document_ids:
            raise ValueError('INSUFFICIENT_DATA: 기업 데이터를 추출할 색인 완료 문서가 없습니다. PDF를 먼저 업로드하세요.')
        chunks = await tool(state,'extract','get_document_chunks',company_id=state['company_id'],document_ids=document_ids)
        if not isinstance(chunks,list): raise ValueError('문서 조각 응답은 배열이어야 합니다.')
        payload = await reasoner.extract(state, chunks)
        saved = await tool(state,'extract','save_extraction',task_id=state['task_id'],document_ids=document_ids,payload=payload)
        if type(saved.get('draft_id')) is not int or saved['draft_id'] <= 0: raise ValueError('Spring draft_id 응답 필요')
        return {'extraction':{'draft_id':saved['draft_id'],'payload':payload},'status':'RUNNING'}

    def confirmation(state):
        # Spring이 사용자 확정 데이터를 저장한 뒤 confirm으로 재개한다. 확정 내용은 collect가 Spring에서 다시 읽는다.
        decision = interrupt({'kind':'CONFIRMATION','taskId':state['task_id'],'draftId':state['extraction']['draft_id']})
        if decision.get('kind')!='CONFIRMATION' or decision.get('userId')!=state['user_id']:
            raise ValueError('요청자의 기업 데이터 확정만 재개할 수 있습니다.')
        return {'company_data_confirmed':True}

    async def collect(state):
        raw = {name: normalize_read(name, value) for name, value in (await reasoner.collect(state, gateway)).items()}
        fields = {'get_company_profile':'company','get_business_processes':'processes',
                  'get_operational_metrics':'metrics','get_system_inventory':'systems',
                  'get_project_budget':'budget','get_solution_catalog':'solutions','get_solution_candidates':'solution_candidates'}
        result = {fields[k]:raw[k] for k in fields}
        if not isinstance(result['processes'],list) or not result['processes']:
            raise ValueError('INSUFFICIENT_DATA: Spring processes 응답 필요')
        # 새 회사는 지표가 일부 없거나 대상 솔루션이 없을 수 있다. 지표 없는 업무는 Spring 계산에서 빠진다.
        for field in ('metrics','solutions'):
            if not isinstance(result[field],list): raise ValueError(f'Spring {field} 응답은 배열이어야 합니다.')
        if int(result['company']['company_id']) != state['company_id']: raise ValueError('회사 응답 불일치')
        result['solution_candidates'] = normalize_candidates(result['solution_candidates'], result['processes'], result['solutions'])
        scope=request_scope(state['request'],result['company']['departments'],result['processes'])
        gateway.observe(state['task_id'],'collect','REQUEST_SCOPE',scope)
        # 예산은 회사 고정값이 아니라 요청에 적힌 선택값이다. 없으면 예산 제약 없이 계산한다.
        budget_krw=request_budget(state['request'])
        gateway.observe(state['task_id'],'collect','REQUEST_BUDGET',{'budgetKrw':budget_krw})
        if budget_krw is not None: await gateway.task_budget(state['task_id'],budget_krw)
        return {**result,'status':'RUNNING','evaluation_policy':policy,'scope':scope,'budget_krw':budget_krw}

    async def retrieve(state):
        common = await tool(state,'retrieve','get_assessment_evidence',company_id=state['company_id'])
        if not isinstance(common,list): raise ValueError('성숙도 근거 응답은 배열이어야 합니다.')
        evidence = list(common)
        document_type = 'UPLOADED' if state['company_id'] != settings.company_id else 'MANUAL'
        scope = state.get('scope') or {}
        scoped = set(scope.get('processIds', [int(p['process_id']) for p in state['processes']]))
        # Retrieve only requested business processes. Readiness remains company-wide.
        for process in state['processes']:
            pid = int(process['process_id'])
            if pid not in scoped: continue
            rows = await tool(state,'retrieve','search_docs',query=f"{pid} {process['process_name']} 목적 절차 승인 예외 규칙",
                              company_id=state['company_id'],doc_type=document_type,process_id=pid,top_k=5)
            if not isinstance(rows,list): raise ValueError('업무 검색 응답은 배열이어야 합니다.')
            # In the v3 corpus a document covers several processes; prefer the
            # exact process section instead of borrowing a neighbouring workflow.
            own = [r for r in rows if r.get('section','').startswith(f'{pid} ')
                   or r.get('content','').startswith(f'process_id={pid}.')]
            evidence.extend(own or rows)
        seen, unique = set(), []
        for row in evidence:
            if not {'document_id','section','content'} <= row.keys(): raise ValueError('RAG 근거 필드 부족')
            key = (row['document_id'],row['section'],row['content'])
            if key not in seen: seen.add(key); unique.append(row)
        if not unique: raise ValueError('INSUFFICIENT_DATA: 문서 근거가 없습니다.')
        # Keep each process's own section ahead of generic chunks when limiting context.
        prefixes = tuple(str(p['process_id']) + ' ' for p in state['processes'])
        unique.sort(key=lambda row: not row['section'].startswith(prefixes))
        gateway.observe(state['task_id'],'retrieve','RETRIEVAL_COUNTS',
                        {'raw':len(evidence),'unique':len(unique),'retained':len(unique)})
        return {'evidence':unique,
                'assessment_evidence':[r for r in unique if r.get('doc_type') in ASSESSMENT_TYPES],
                'business_evidence':[r for r in unique if r.get('doc_type') in {'MANUAL','UPLOADED'}]}

    async def assess(state):
        assessment = Assessment.model_validate(await reasoner.assess(state,maturity_policy))
        required = set(maturity_policy['weights'])
        if assessment.insufficient_data or set(assessment.scores) != required:
            raise ValueError('INSUFFICIENT_DATA: 성숙도 영역 근거가 부족합니다. 없는 점수를 만들지 않습니다.')
        valid = {(r['document_id'],r['section']) for r in state.get('assessment_evidence',state['evidence'])}
        for area in required:
            evidence = [e for e in assessment.evidence if e.area == area]
            if not evidence:
                raise AssessmentReferenceError('ASSESSMENT_EVIDENCE_MISSING', area=area)
            invalid=[{'documentId':e.document_id,'section':e.section} for e in evidence if (e.document_id,e.section) not in valid]
            if invalid:
                raise AssessmentReferenceError('ASSESSMENT_EVIDENCE_INVALID_REFERENCE', area=area, references=invalid)
        payload = assessment.model_dump()
        saved = await tool(state,'assess','save_assessment',task_id=state['task_id'],scores=payload['scores'],
                           criteria_version=maturity_policy['criteria_version'],evidence=payload['evidence'])
        if not isinstance(saved.get('assessment_id'),int) or saved['assessment_id'] <= 0:
            raise ValueError('Spring assessment_id 응답 필요')
        maturity = {**payload,'criteria_version':maturity_policy['criteria_version'],'assessment_id':saved['assessment_id']}
        # A weighted total is never computed by the Agent. Spring may return it after saving.
        if saved.get('total_score') is not None: maturity['total_score'] = saved['total_score']
        return {'maturity':maturity,'insufficient_data':[]}

    async def discover(state):
        choices = eligible_candidates(state)
        excluded = exclusions(state)
        if not choices:
            gateway.observe(state['task_id'],'discover','NO_ELIGIBLE_CANDIDATES',
                            {'scope':state['scope'],'candidateCount':len(state['solution_candidates'])})
            return {'candidates':[],'excluded':excluded,'status':'DONE','answer':assessment_answer(state)}
        if len(choices)>10: raise ValueError('후보는 최대 10개입니다. 요청 범위를 나누세요.')
        allowed = {pair(c):c for c in choices}
        for candidate in choices:
            dep = candidate['depends_on']
            if dep and pair(dep) not in allowed:
                raise ValueError('Spring 선행 후보 쌍이 요청 범위의 유효 후보에 없습니다.')
        proposed = await reasoner.discover(state)
        valid_docs = {r['document_id'] for r in state['business_evidence']}
        valid_refs = {(r['document_id'],r['section'],r['content']) for r in state['business_evidence']}
        seen = set()
        for candidate in proposed:
            key = pair(candidate)
            if key not in allowed:
                raise ValueError(f'Spring 후보 쌍에 없는 후보: process_id={key[0]}, solution_id={key[1]}')
            if key in seen: raise ValueError('중복된 후보 쌍')
            if not candidate['document_ids'] or not set(candidate['document_ids']) <= valid_docs:
                raise ValueError(f'후보 문서 근거가 부족합니다: process_id={key[0]}')
            rows = grounded_rows(candidate,state)
            if not rows or any((r['document_id'],r['section'],r['content']) not in valid_refs for r in rows):
                raise ValueError('후보의 문서 조각 근거가 유효하지 않습니다.')
            seen.add(key)
        if seen != set(allowed): raise ValueError('Spring 유효 후보 쌍이 누락됐습니다.')
        return {'candidates':proposed,'excluded':excluded,
                'retry_count':state.get('retry_count',0) + int(bool((state.get('portfolio') or {}).get('insufficient')))}

    def validate_roi(raw, candidate, state):
        value = RoiResult.model_validate(raw).model_dump()
        if (value['processId'],value['solutionId']) != (candidate['process_id'],candidate['solution_id']):
            raise ValueError('ROI 응답의 후보 ID 불일치')
        process = next(p for p in state['processes'] if int(p['process_id'])==value['processId'])
        match = next(c for c in state['solution_candidates'] if pair(c)==pair(candidate))
        expected_dep = pair(match['depends_on']) if match['depends_on'] else None
        if roi_dependency(value) != expected_dep or value['humanReviewRequired'] != truth(process['requires_approval']):
            raise ValueError('Spring 선행 후보 쌍·사람 검토 조건 불일치')
        return value

    async def evaluate(state):
        roi = [validate_roi(await tool(state,'evaluate','calculate_ax_roi',process_id=c['process_id'],solution_id=c['solution_id']),c,state)
               for c in state['candidates']]
        portfolio = await tool(state,'evaluate','optimize_ax_portfolio',company_id=state['company_id'],
                               candidates=[{'process_id':c['process_id'],'solution_id':c['solution_id']} for c in state['candidates']],max_items=min(3,len(state['candidates'])),
                               budget_krw=state.get('budget_krw'))
        if not isinstance(portfolio.get('insufficient'),bool): raise ValueError('portfolio.insufficient 필수')
        if portfolio['insufficient']:
            if state.get('retry_count',0)>=2: raise ValueError('예산·선행 조건 안에서 근거 있는 과제 3개를 찾지 못했습니다.')
            return {'roi':roi,'portfolio':portfolio}
        selected = portfolio.get('selected')
        if not isinstance(selected,list) or len(selected)!=min(3,len(state['candidates'])): raise ValueError('포트폴리오 선정 과제 수 불일치')
        lookup = {pair(r):r for r in roi}
        if any(pair(c) not in lookup or validate_roi(c,{'process_id':c['processId'],'solution_id':c['solutionId']},state)!=lookup[pair(c)] for c in selected):
            raise ValueError('선정 결과와 후보 계산값이 다릅니다.')
        ids = {pair(c) for c in selected}
        if len({c['processId'] for c in selected}) != len(selected): raise ValueError('중복 업무 선정')
        if any(roi_dependency(c) and roi_dependency(c) not in ids for c in selected): raise ValueError('선행 과제가 빠졌습니다.')
        if portfolio.get('excluded') != state['excluded']: raise ValueError('Spring 정책 제외 목록 불일치')
        # Consistency checks only; scoring formulas and optimization remain entirely in Spring.
        total = sum(c['firstYearTcoKrw'] for c in selected)
        budget = state.get('budget_krw')
        if portfolio.get('totalFirstYearTcoKrw')!=total: raise ValueError('Spring 비용 합계 불일치')
        if budget is None:
            if portfolio.get('budgetKrw') is not None or portfolio.get('remainingBudgetKrw') is not None:
                raise ValueError('예산 없는 요청에 Spring 예산 값이 있습니다.')
        elif total>budget or portfolio.get('budgetKrw')!=budget or portfolio.get('remainingBudgetKrw')!=budget-total:
            raise ValueError('Spring 예산 합계 불일치 또는 예산 초과')
        score_sum = sum((Decimal(str(c['axScore'])) for c in selected),Decimal(0))
        if Decimal(str(portfolio.get('totalAxScore'))) != score_sum: raise ValueError('Spring AX점수 합계 불일치')
        return {'roi':roi,'portfolio':portfolio,'opportunities':roi}

    async def roadmap(state):
        pending = list(state['portfolio']['selected'])
        reasons = {pair(c):c for c in state['candidates']}
        processes = {int(p['process_id']):p for p in state['processes']}
        items, scheduled, reviews = [],{},{}
        while pending:
            ready = [c for c in pending if roi_dependency(c) is None or roi_dependency(c) in scheduled]
            if not ready: raise ValueError('선행 과제 순환 또는 누락')
            c = sorted(ready,key=lambda c:(-c['axScore'],c['solutionId'],c['processId']))[0]
            pending.remove(c)
            base = c['scenarios']['base']
            candidate = reasons[pair(c)]
            evidence = [{'document_id':r['document_id'],'section':r['section'],'summary':r['content'][:400]}
                        for r in grounded_rows(candidate,state)][:3]
            dep = roi_dependency(c)
            start = scheduled[dep]+3 if dep else 1
            scheduled[pair(c)] = start
            reviews[pair_id(c)] = c['humanReviewRequired']
            rationale = 'AX점수 기준 선정. '+candidate['reason']
            if c['humanReviewRequired']: rationale += ' 업무 완료 전 사람 최종 검토·승인이 필요합니다.'
            if dep: rationale += f" 선행 업무 {processes[dep[0]]['process_name']} 완료 후 시작합니다."
            items.append({'process_id':c['processId'],'solution_id':c['solutionId'],'item_name':processes[c['processId']]['process_name'],
                'priority_order':len(items)+1,'phase':'SHORT' if start<=3 else 'MID','start_month':start,'duration_months':3,
                'allocated_budget_krw':c['firstYearTcoKrw'],'ax_score':c['axScore'],'impact_score':c['impactScore'],
                'feasibility_score':c['feasibilityScore'],'expected_annual_saving_krw':base['annualSavingKrw'],
                'roi_pct':base['roiPct'],'payback_months':base['paybackMonths'],'three_year_net_value_krw':base['threeYearNetKrw'],
                'rationale':rationale,'evidence':evidence})
        roadmap = {'roadmapName':'AX 도입 로드맵 초안','items':items,'humanReviewByCandidate':reviews,
                'totalAllocatedKrw':state['portfolio']['totalFirstYearTcoKrw'],'budgetKrw':state['portfolio']['budgetKrw'],
                'totalAxScore':state['portfolio']['totalAxScore'],
                'effectBasis':'가정 데이터 기반 인력 시간 환산 가치. 현금 절감·실측 성과 아님.',
                'scheduleBasis':'3개월 단위 MVP 일정 초안. 실제 일정과 PoC 성공 기준은 담당자 검토 필요.',
                'pocSuccessCriteria':['표본 업무 전후 처리 시간을 측정하고 사람 검토 시간을 포함한다.',
                                      '담당자가 품질·오류율 기준과 자동화 중단 조건을 확정한다.']}
        narrative = await reasoner.respond({**state,'roadmap':roadmap})
        return {'roadmap':roadmap,'answer':render_answer(state,roadmap,narrative)}

    def approval(state):
        decision = interrupt({'taskId':state['task_id'],**approval_payload(state)})
        if decision.get('userId')!=state['user_id']: raise ValueError('요청자만 승인할 수 있습니다.')
        if decision.get('decision') not in {'APPROVE','REJECT'}: raise ValueError('잘못된 승인 결정')
        return {'approval':decision,'status':'RUNNING' if decision['decision']=='APPROVE' else 'REJECTED'}

    async def register(state):
        if state.get('approval',{}).get('decision')!='APPROVE': raise ValueError('승인이 필요합니다.')
        saved = await tool(state,'register','create_ax_roadmap',task_id=state['task_id'],company_id=state['company_id'],
            assessment_id=state['maturity']['assessment_id'],roadmap_name=state['roadmap']['roadmapName'],items=state['roadmap']['items'])
        ids = saved['item_ids']
        if len(ids)!=len(state['roadmap']['items']) or len(set(ids))!=len(ids): raise ValueError('로드맵 항목 ID 응답 불일치')
        processes = {int(p['process_id']):p for p in state['processes']}
        projects = []
        for item_id, item in zip(ids, state['roadmap']['items']):
            args = {'item_id': item_id, 'owner_department_id': int(processes[item['process_id']]['department_id']),
                    'project_name': item['item_name']}
            project = await tool(state,'register','create_ax_project', **args)
            if type(project.get('project_id')) is not int or project['project_id'] <= 0:
                raise ValueError('Spring project_id 응답 필요')
            projects.append({**args, **project, 'project_status': project.get('project_status', 'REGISTERED')})
        return {'registration':{'roadmap_id':saved['roadmap_id'],'projects':projects},'status':'DONE'}

    def assessment_answer(state):
        maturity = state['maturity']
        labels = {k:v['label'] for k,v in maturity_policy['rubrics'].items()}
        lines = ['AX 성숙도 진단을 완료했습니다.']
        if maturity.get('total_score') is not None: lines.append(f"총점 {maturity['total_score']}점 (기준 {maturity['criteria_version']}).")
        lines.extend(f"- {labels.get(area,area)}: {score}점" for area,score in maturity['scores'].items())
        missing = any(not c['metrics_sufficient'] and c['excluded_reason'] is None for c in state['solution_candidates'])
        note = '지표가 부족합니다. 월 건수·처리 시간·인건비 지표를 입력하면 과제를 추천할 수 있습니다.' if missing else '요청 범위에 추천 가능한 업무 유형·솔루션 후보가 없어 로드맵을 제공하지 않습니다.'
        lines.extend(['',note])
        return '\n'.join(lines)

    def render_answer(state, roadmap, raw):
        from ...schemas import Narrative
        narrative=Narrative.model_validate(raw)
        selected={pair(c):c for c in state['portfolio']['selected']}
        if len(narrative.recommendations)!=len(selected) or {(r.process_id,r.solution_id) for r in narrative.recommendations}!=set(selected):
            raise ValueError('응답 설명의 선정 솔루션 ID 불일치')
        valid_docs={r['document_id'] for r in state['evidence']}
        notes={(r.process_id,r.solution_id):r for r in narrative.recommendations}
        lines=[narrative.summary,'']
        if len(selected)<3: lines.append(f'추천 가능한 과제가 {len(selected)}개뿐이므로 해당 과제로 구성했습니다.')
        for item in roadmap['items']:
            note=notes[pair(item)]
            if not set(note.document_ids)<=valid_docs: raise ValueError('응답 설명의 문서 근거 불일치')
            lines.append(f"- {item['item_name']}: AX점수 {item['ax_score']}, 초년도 비용 {item['allocated_budget_krw']:,}원. {note.reason} (문서 {', '.join(map(str,note.document_ids))})")
            process=next(p for p in state['processes'] if int(p['process_id'])==item['process_id'])
            if process.get('exception_rules'): lines.append('  예외·제한: '+process['exception_rules'])
            if truth(process['requires_approval']): lines.append('  사람 최종 검토·승인 필요.')
        remaining=state['portfolio']['remainingBudgetKrw']
        budget_note=f", 잔여 예산 {remaining:,}원." if remaining is not None else ". 요청에 예산이 없어 예산 제약 없이 선정했습니다."
        lines.extend(['',f"총 AX점수 {state['portfolio']['totalAxScore']}, 총비용 {state['portfolio']['totalFirstYearTcoKrw']:,}원"+budget_note,
                      '가정 데이터 기반 인력 시간 환산 가치입니다. 실제 성과나 확정 현금 절감을 보장하지 않습니다.',
                      '요청자 승인 후 로드맵·프로젝트를 등록합니다.'])
        return '\n'.join(lines)

    async def observed_node(name,node,state):
        gateway.observe(state['task_id'],name,'NODE_START')
        try:
            value=await node(state)
            gateway.observe(state['task_id'],name,'NODE_END',{'updatedFields':list(value)})
            return value
        except Exception as exc:
            gateway.observe(state['task_id'],name,'NODE_ERROR',{'errorType':type(exc).__name__,'message':str(exc)[:400] if isinstance(exc,(ValueError,AssessmentReferenceError)) else '응답 형식 또는 서비스 호출 오류'})
            raise

    nodes = {}
    for name,node in [('extract',extract),('confirmation',confirmation),('collect',collect),('retrieve',retrieve),('assess',assess),('discover',discover),('evaluate',evaluate),('roadmap',roadmap),('approval',approval),('register',register)]:
        if name in {'approval','confirmation'}:
            nodes[name] = node
        else:
            async def traced(state, _name=name, _node=node):
                return await observed_node(_name,_node,state)
            nodes[name] = traced
    return nodes
