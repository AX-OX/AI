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

    async def _spring(self, method, path, body):
        self.events.append({'method':method,'path':path,'body':copy.deepcopy(body)})

    async def tool(self, task_id, node, name, args):
        self.calls.append((name,copy.deepcopy(args)))
        await self.event(task_id,'TOOL_START',node,{'tool':name,'label':name})
        self.observe(task_id,node,'TOOL_CALL',{'tool':name,'arguments':args,'backend':'v3-fixture'})
        result = copy.deepcopy(self._call(task_id,name,args))
        self.observe(task_id,node,'TOOL_RESULT',{'tool':name,'resultType':type(result).__name__})
        await self.event(task_id,'TOOL_END',node,{'tool':name,'label':name,'ok':True})
        return mask(result)

    def _call(self, task_id, name, args):
        if name=='get_company_profile': return {**self.tables['companies'][0],'departments':self.tables['departments']}
        if name=='get_business_processes': return self.tables['business_processes']
        if name=='get_operational_metrics': return self.tables['process_metrics']
        if name=='get_system_inventory': return {'systems':self.tables['it_systems'],'process_systems':self.tables['process_systems']}
        if name=='get_project_budget': return {'ax_budget_krw':int(self.tables['companies'][0]['ax_budget_krw'])}
        if name=='get_solution_catalog': return self.tables['ai_solution_catalog']
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
                ids.append(c['solution_id'])
            if len(set(ids))!=len(ids): raise ValueError('중복된 mock 후보')
            key=','.join(map(str,sorted(ids)))
            if args['max_items']!=self.portfolio_fixtures['max_items'] or key not in self.portfolio_fixtures['portfolios']:
                raise ValueError('mock에 기록되지 않은 후보 수·조합입니다.')
            # Lookup only: every subset result was generated offline, no optimization at runtime.
            return copy.deepcopy(self.portfolio_fixtures['portfolios'][key])
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
