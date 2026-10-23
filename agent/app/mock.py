"""Offline contract mock: returns v3 oracle responses; contains no scoring/optimization formula."""
import copy
import hashlib
from pathlib import Path
import csv
import json
import sqlite3
from .clients import Gateway, mask


class MockGateway(Gateway):
    def __init__(self, settings):
        super().__init__(settings)
        self.tables = {}
        for path in (settings.data_dir/'csv').glob('*.csv'):
            with path.open(encoding='utf-8-sig') as file:
                self.tables[path.stem] = list(csv.DictReader(file))
        self.expected = json.loads((settings.data_dir/'eval/demo_expected_portfolio.json').read_text())
        self.docs = {d['document_id']:d for d in json.loads((settings.data_dir/'rag/doc_mapping.json').read_text())['documents']}
        self.chunks = [json.loads(line) for line in (settings.data_dir/'rag/pgvector_import.jsonl').read_text().splitlines() if line.strip()]
        fixture_path=Path(__file__).resolve().parents[1]/'fixtures/portfolio_subsets_v3.json'
        self.portfolio_fixtures=json.loads(fixture_path.read_text())
        for relative,digest in self.portfolio_fixtures['source_sha256'].items():
            if hashlib.sha256((settings.data_dir/relative).read_bytes()).hexdigest()!=digest:
                raise ValueError('v3 mock 정답이 오래되었습니다. scripts/build_demo_portfolios.py로 재생성하세요.')
        self.calls, self.saved = [], {}
        # 업로드 문서 조각: company_id -> [chunk]. index_document 도구가 채운다 (v3 시드 회사 1 문서와 분리).
        self.uploads = {}

    async def _spring(self, method, path, body):
        self.events.append({'method':method,'path':path,'body':copy.deepcopy(body)})

    async def index_document(self, company_id, document_id, title, pages):
        args = {'company_id': company_id, 'document_id': document_id, 'title': title, 'pages': pages}
        self.calls.append(('index_document', copy.deepcopy(args)))
        result = self._call('', 'index_document', args)
        if not result['chunks']: raise ValueError('RAG_UPLOAD_EMPTY: PDF에서 텍스트를 추출하지 못했습니다.')
        return result

    async def tool(self, task_id, node, name, args):
        self.calls.append((name,copy.deepcopy(args)))
        await self.event(task_id,'TOOL_START',node,{'tool':name,'label':name})
        self.observe(task_id,node,'TOOL_CALL',{'tool':name,'arguments':args,'backend':'v3-fixture'})
        result = copy.deepcopy(self._call(task_id,name,args))
        self.observe(task_id,node,'TOOL_RESULT',{'tool':name,'resultType':type(result).__name__})
        await self.event(task_id,'TOOL_END',node,{'tool':name,'label':name,'ok':True})
        return mask(result)

    def solution_candidates(self):
        """Offline contract fixture matching only. Runtime matching belongs to Spring."""
        processes=sorted(self.tables['business_processes'],key=lambda p:int(p['process_id']))
        templates={int(s['solution_id']):s for s in self.tables['ai_solution_catalog']}
        excluded={int(e['processId']):e['reason'] for e in self.expected['excluded']}
        result=[]
        for sid,template in sorted(templates.items()):
            for process in processes:
                pid=int(process['process_id'])
                if not process.get('work_type') or process['work_type']=='OTHER' or process['work_type']!=template['work_type']: continue
                dependency=None
                if dep:=template.get('depends_on_solution_id'):
                    required=templates.get(int(dep))
                    prerequisite=next((p for p in processes if required and p['department_id']==process['department_id']
                                       and p.get('work_type')==required['work_type'] and int(p['process_id']) not in excluded),None)
                    if prerequisite is None: continue
                    dependency={'process_id':int(prerequisite['process_id']),'solution_id':int(dep)}
                result.append({'process_id':pid,'solution_id':sid,'work_type':process['work_type'],'depends_on':dependency,
                               'excluded_reason':excluded.get(pid),
                               'metrics_sufficient':len([m for m in self.tables['process_metrics'] if int(m['process_id'])==pid])>=3})
        changed=True
        while changed:
            keys={(c['process_id'],c['solution_id']) for c in result}
            retained=[c for c in result if not c['depends_on'] or (c['depends_on']['process_id'],c['depends_on']['solution_id']) in keys]
            changed=len(retained)!=len(result); result=retained
        return result

    def _call(self, task_id, name, args):
        if name=='get_company_profile': return {**self.tables['companies'][0],'departments':self.tables['departments']}
        if name=='get_business_processes': return self.tables['business_processes']
        if name=='get_operational_metrics': return self.tables['process_metrics']
        if name=='get_system_inventory': return {'systems':self.tables['it_systems'],'process_systems':self.tables['process_systems']}
        if name=='get_project_budget': return {'ax_budget_krw':int(self.tables['companies'][0]['ax_budget_krw'])}
        if name=='get_solution_catalog': return self.tables['ai_solution_catalog']
        if name=='get_solution_candidates': return self.solution_candidates()
        if name=='index_document':
            rows=[{'document_id':args['document_id'],'title':args['title'],'doc_type':'UPLOADED','section':f"p.{p['page']}",
                   'page':p['page'],'chunk_index':i,'content':p['text']} for i,p in enumerate(args['pages']) if p['text'].strip()]
            company=self.uploads.setdefault(args['company_id'],[])
            company[:]=[r for r in company if r['document_id']!=args['document_id']]+rows
            return {'document_id':args['document_id'],'chunks':len(rows)}
        if name=='get_document_chunks':
            return [dict(r) for r in self.uploads.get(args['company_id'],[]) if r['document_id'] in args['document_ids']]
        if name=='save_extraction':
            return {'draft_id':7001}
        if args.get('company_id') in self.uploads and name in {'get_assessment_evidence','search_docs'}:
            rows=[dict(r) for r in self.uploads[args['company_id']] if not args.get('doc_type') or r['doc_type']==args['doc_type']]
            return rows if name=='get_assessment_evidence' else rows[:args.get('top_k',5)]
        if name=='get_assessment_evidence':
            return [{**r['metadata'],'content':r['document']} for r in self.chunks
                    if r['metadata']['doc_type'] in {'SYSTEM_SPEC','POLICY','AI_STATUS','DATA_QUALITY','PROJECT_REPORT'}]
        if name=='search_docs':
            rows = [r for r in self.chunks if (not args.get('doc_type') or r['metadata']['doc_type']==args['doc_type'])
                    and (not args.get('process_id') or not self.docs[r['metadata']['document_id']]['related_process_ids']
                         or args['process_id'] in self.docs[r['metadata']['document_id']]['related_process_ids'])]
            query = args['query']
            # Lexical, deterministic fixture selection only; NOT semantic retrieval evaluation.
            rows.sort(key=lambda r:-(100*int(query in r['metadata']['section'])+sum(word in r['document']+' '+r['metadata']['section'] for word in query.split())))
            return [{**r['metadata'],'content':r['document'],'score':None} for r in rows[:args.get('top_k',5)]]
        if name=='calculate_ax_roi':
            return next(copy.deepcopy(c) for c in self.expected['per_candidate'] if (c['processId'],c['solutionId'])==(args['process_id'],args['solution_id']))
        if name=='optimize_ax_portfolio':
            if args['company_id']!=int(self.tables['companies'][0]['company_id']): raise ValueError('회사 범위 오류')
            ids=[]
            catalog={(c['processId'],c['solutionId']) for c in self.expected['per_candidate']}
            for c in args['candidates']:
                if (c['process_id'],c['solution_id']) not in catalog: raise ValueError('mock 후보 업무·솔루션 연결 불일치')
                ids.append((c['process_id'],c['solution_id']))
            if len(set(ids))!=len(ids): raise ValueError('중복된 mock 후보')
            key=','.join(f'{pid}:{sid}' for pid,sid in sorted(ids))
            fixtures=self.portfolio_fixtures['portfolios'] if args['max_items']==3 else self.portfolio_fixtures['smaller_portfolios'].get(str(args['max_items']),{})
            if key not in fixtures:
                raise ValueError('mock에 기록되지 않은 후보 수·조합입니다.')
            # Lookup only: every subset result was generated offline, no optimization at runtime.
            result=copy.deepcopy(fixtures[key])
            budget=args.get('budget_krw')
            if budget is None:
                # 예산 없는 요청: Spring은 예산 값을 null로 준다. 조합은 3억 기준 fixture를 그대로 쓴다(계약 검증용).
                result['budgetKrw']=result['remainingBudgetKrw']=None
            elif budget!=result['budgetKrw']:
                raise ValueError('mock 포트폴리오는 예산 3억 원 fixture만 제공합니다.')
            return result
        key = task_id+name+json.dumps(args,sort_keys=True)
        if key not in self.saved:
            if name=='save_assessment':
                with sqlite3.connect(f'file:{self.settings.data_dir}/ax_navigator_demo_approved.sqlite?mode=ro',uri=True) as db:
                    db.row_factory=sqlite3.Row
                    reference=dict(db.execute('SELECT * FROM ax_assessments WHERE assessment_id=701').fetchone())
                self.saved[key]={'assessment_id':reference['assessment_id']}
                if all(args['scores'].get(k)==reference[k] for k in ('data_score','infra_score','automation_score','ai_capability_score','governance_score')):
                    self.saved[key]['total_score']=reference['total_score']
            elif name=='create_ax_roadmap': self.saved[key]={'roadmap_id':801,'item_ids':list(range(901,901+len(args['items'])))}
            elif name=='create_ax_project': self.saved[key]={'project_id':10001+args['item_id']-901}
            else: raise ValueError(f'알 수 없는 mock 도구: {name}')
        return self.saved[key]
