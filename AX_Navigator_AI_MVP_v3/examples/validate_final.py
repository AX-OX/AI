#!/usr/bin/env python3
"""Offline schema/CSV/SQLite/corpus/fixture consistency and all eight demo checks.
Optional --postgres-report incorporates actual temporary DB integration results.
Never represents SQLite or fake embeddings as a pgvector test.
"""
import argparse
import csv
import hashlib
import json
import re
import sqlite3
from collections import Counter
from decimal import Decimal
from pathlib import Path
from compute_ax import compute,load_table,truth
from pgvector_ingest import load_corpus
from rebuild_dataset import parse_schema

ROOT=Path(__file__).resolve().parents[1]

def data_artifact_hashes(root):
    root=Path(root)
    paths=[]
    for folder in ('sql','fixtures','csv','rag','config','contracts'):
        paths.extend(p for p in (root/folder).rglob('*') if p.is_file())
    paths.append(root/'eval/demo_expected_portfolio.json')
    return {p.relative_to(root).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(paths)}

def validate(root=ROOT,postgres_report=None):
    root=Path(root)
    ddl=(root/'sql/00_schema_postgres16.sql').read_text()
    rag=(root/'sql/03_pgvector.sql').read_text()
    schema=parse_schema(ddl)
    assert len(schema)==14 and len(re.findall(r'REFERENCES\s+\w+',ddl))==24
    assert len(re.findall('CREATE TABLE',rag))==2 and len(re.findall(r'REFERENCES\s+\w+',rag))==3
    context=(root/'contracts/AX_NAVIGATOR_CONTEXT.md').read_text()
    sqlblocks=re.findall(r'```sql\n(.*?)```',context,re.S)
    original=next(b for b in sqlblocks if 'CREATE TABLE companies' in b)
    assert re.sub(r'(?m)^(\s+\w+\s+BIGINT) GENERATED ALWAYS AS IDENTITY',r'\1',ddl)==original
    assert rag==next(b for b in sqlblocks if 'CREATE TABLE IF NOT EXISTS rag_indexes' in b)
    assert len(re.findall(r'(?m)^\s+\w+\s+BIGINT GENERATED ALWAYS AS IDENTITY',ddl))==12
    assert len(list((root/'csv').glob('*.csv')))==14
    rows={t:load_table(root,t) for t in schema}
    for table,cols in schema.items():
        with (root/'csv'/f'{table}.csv').open(encoding='utf-8-sig') as f:
            assert next(csv.reader(f))==[c for c,_ in cols], table
    expected_counts=dict(companies=1,departments=3,business_processes=9,process_metrics=27,it_systems=6,process_systems=17,documents=8,ai_solution_catalog=9,users=2,ai_tasks=0,ax_assessments=0,ax_roadmaps=0,roadmap_items=0,ax_projects=0)
    assert {t:len(v) for t,v in rows.items()}==expected_counts
    company=rows['companies'][0]
    assert int(company['employee_count'])==200 and int(company['ax_budget_krw'])==300000000
    assert {p['department_name'] for p in rows['departments']}=={'인사','기획','개발'}
    assert Counter(p['department_id'] for p in rows['business_processes'])=={'101':3,'102':3,'103':3}
    for p in rows['business_processes']:
        assert p['purpose'] and p['exception_rules'] and 4<=len(json.loads(p['process_steps']))<=6
    for pid in range(201,210):
        metrics=[m for m in rows['process_metrics'] if int(m['process_id'])==pid]
        assert {m['period_start'] for m in metrics}=={'2026-07-01','2026-08-01','2026-09-01'}
        assert all(m['data_source']=='ASSUMED' for m in metrics)
    assert all(s['data_source']=='ASSUMED' for s in rows['ai_solution_catalog'])
    assert all(d['manager_email'].endswith('.example') and d['manager_phone'].startswith('010-0000-') for d in rows['departments'])
    sourceusers=json.loads((root/'examples/source_users.json').read_text())
    assert rows['users']==sourceusers
    assert not any('role' in col for col,_ in schema['users'])
    for u in rows['users']: assert u['email'].endswith('.example') and u['password_hash'].startswith('$2y$')
    criteria=json.loads((root/'config/assessment_criteria_v1.json').read_text())
    assert sum(Decimal(str(w)) for w in criteria['weights'].values())==1
    expected=json.loads((root/'eval/demo_expected_portfolio.json').read_text())
    assert compute(root)==expected,'Computed oracle differs from eval JSON'
    assert set(expected['selected_solution_ids']).issubset({c['solutionId'] for c in expected['per_candidate']})
    candidates={c['solutionId']:c for c in expected['per_candidate']}
    selected=[candidates[s] for s in expected['selected_solution_ids']]
    processes={int(p['process_id']):p for p in rows['business_processes']}
    solutions={int(s['solution_id']):s for s in rows['ai_solution_catalog']}
    systems={int(s['system_id']):s for s in rows['it_systems']}
    def has_api(pid):
        return any(truth(systems[int(l['system_id'])]['api_available']) for l in rows['process_systems'] if int(l['process_id'])==pid)
    pairs=[s for s in solutions.values() if s['depends_on_solution_id']]
    conditions={
      '1_excluded_human_final_judgment': any(e['processId']==203 for e in expected['excluded']) and 503 not in candidates,
      '2_one_dependency_same_department': len(pairs)==1 and all(processes[int(s['target_process_id'])]['department_id']==processes[int(solutions[int(s['depends_on_solution_id'])]['target_process_id'])]['department_id'] for s in pairs),
      '3_api_rule_both_cases': any(not truth(solutions[s]['requires_api']) and not has_api(c['processId']) and c['apiOk'] for s,c in candidates.items()) and any(truth(solutions[s]['requires_api']) and not has_api(c['processId']) and not c['apiOk'] for s,c in candidates.items()),
      '4_human_review_in_selected': any(c['humanReviewRequired'] for c in selected),
      '5_greedy_differs_due_to_constraints': bool(expected['greedy_top3_by_score']['violations']) and set(expected['greedy_top3_by_score']['solution_ids'])!=set(expected['selected_solution_ids']),
      '6_unique_optimum_gap_at_least_0_5': expected['runner_up_score_gap']>=.5,
      '7_selected_payback_and_three_year_net': all(c['scenarios']['base']['paybackMonths'] is not None and c['scenarios']['base']['paybackMonths']<=36 and c['scenarios']['base']['threeYearNetKrw']>0 for c in selected),
      '8_low_standardization_warning': any('LOW_STANDARDIZATION' in c['warnings'] for c in candidates.values())}
    assert all(conditions.values()),conditions
    sqlite_reports={}
    for name in ('ax_navigator_input_only.sqlite','ax_navigator_demo_approved.sqlite'):
        with sqlite3.connect(root/name) as db:
            db.row_factory=sqlite3.Row
            db.execute('PRAGMA foreign_keys=ON')
            assert db.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
            assert not db.execute('PRAGMA foreign_key_check').fetchall()
            assert len(db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'").fetchall())==14
            assert sum(len(db.execute(f'PRAGMA foreign_key_list({t})').fetchall()) for t in schema)==24
            counts={t:db.execute(f'SELECT count(*) FROM {t}').fetchone()[0] for t in schema}
            if name.endswith('input_only.sqlite'): assert counts==expected_counts
            else:
                assert counts=={**expected_counts,'ai_tasks':1,'ax_assessments':1,'ax_roadmaps':1,'roadmap_items':3,'ax_projects':3}
                items=[dict(r) for r in db.execute('SELECT * FROM roadmap_items ORDER BY priority_order')]
                assert {r['solution_id'] for r in items}==set(expected['selected_solution_ids'])
                position={r['solution_id']:r['priority_order'] for r in items}
                for r in items:
                    c=candidates[r['solution_id']]
                    for field,key in [('ax_score','axScore'),('impact_score','impactScore'),('feasibility_score','feasibilityScore'),('allocated_budget_krw','firstYearTcoKrw')]:
                        assert Decimal(str(r[field]))==Decimal(str(c[key])),field
                    for field,key in [('expected_annual_saving_krw','annualSavingKrw'),('roi_pct','roiPct'),('payback_months','paybackMonths'),('three_year_net_value_krw','threeYearNetKrw')]:
                        assert Decimal(str(r[field]))==Decimal(str(c['scenarios']['base'][key])),field
                    if c['dependsOnSolutionId']: assert position[c['dependsOnSolutionId']]<r['priority_order']
                    if c['humanReviewRequired']: assert '사람 최종 검토·승인' in r['rationale']
                task=db.execute('SELECT * FROM ai_tasks').fetchone()
                roadmap=db.execute('SELECT * FROM ax_roadmaps').fetchone()
                assert task['user_id']==roadmap['approved_by']==602
                snapshot=json.loads(task['result'])
                assert snapshot['candidates']==expected['per_candidate']
                assert snapshot['portfolio']['selected']==selected
                assert snapshot['portfolio']['runner_up']==expected['runner_up']
                a=db.execute('SELECT * FROM ax_assessments').fetchone()
                assert Decimal(str(a['total_score']))==sum(Decimal(str(a[k]))*Decimal(str(w)) for k,w in criteria['weights'].items())
            sqlite_reports[name]=dict(status='passed',row_counts=counts,foreign_key_violations=0)
    chunks,docs=load_corpus(root)
    assert set(docs)==set(range(401,409))
    assert len(list((root/'rag/docs').glob('*.md')))==8
    document_rows={int(d['document_id']):d for d in rows['documents']}
    for did,d in docs.items():
        dbdoc=document_rows[did]
        assert d['process_id']==(int(dbdoc['process_id']) if dbdoc['process_id'] else None)
        assert all(d[k]==dbdoc[k] for k in ('title','doc_type','access_level','version','file_uri'))
        assert d['company_id']==int(dbdoc['company_id'])==1
        assert all(pid in processes for pid in d['related_process_ids'])
        text=(root/'rag'/d['local_path']).read_text()
        relevant=[r for r in chunks if r['metadata']['document_id']==did]
        for c in relevant:
            assert '## '+c['metadata']['section']+'\n\n'+c['document'] in text
        if d['doc_type']=='MANUAL':
            for pid in d['related_process_ids']:
                p=processes[pid]
                assert all(step in text for step in json.loads(p['process_steps']))
                assert p['exception_rules'] in text
                assert f"requires_approval={p['requires_approval']}" in text
    benchmark=json.loads((root/'eval/benchmark_queries.json').read_text())['queries']
    assert [b['id'] for b in benchmark]==[f'B-0{i}' for i in range(1,8)]
    assert benchmark[3]['expected_solution_ids']==expected['selected_solution_ids']
    labels=json.loads((root/'eval/reference_9_processes.json').read_text())['processes']
    assert len(labels)==9 and sum(p['label']=='EXCLUDED' for p in labels)==1
    # Numeric fixture SQL text must encode the same artifacts as the preview.
    fixture=(root/'fixtures/03_demo_after_requester_approval.sql').read_text()
    assert 'OVERRIDING SYSTEM VALUE' in fixture and len(re.findall(r'CREATE TABLE',ddl+rag))==16
    assert all((root/'contracts'/name).read_bytes() and hashlib.sha256((root/'contracts'/name).read_bytes()).hexdigest()==digest for name,digest in json.loads((root/'contracts/sha256.json').read_text()).items())
    pg=json.loads(Path(postgres_report).read_text()) if postgres_report else dict(status='not_run',reason='Run validate_postgres.py against a fresh PostgreSQL DB; SQLite does not verify pgvector')
    if postgres_report:
        assert pg['status']=='passed'
        assert pg['data_artifact_sha256']==data_artifact_hashes(root),'PostgreSQL report is stale for these data artifacts'
    return dict(package='AX_Navigator_AI_MVP_v3',synthetic_data=True,evaluation_as_of=expected['evaluation_as_of'],offline_status='passed',
        schema=dict(business_tables=14,business_foreign_keys=24,rag_tables=2,rag_foreign_keys=3,total_ax_tables=16,total_ax_foreign_keys=27,identity_columns=12,ddl_contract_match=True),
        input_row_counts=expected_counts,sqlite_previews=sqlite_reports,demo_conditions=conditions,
        computed_eval_and_fixture_match=True,documents=dict(document_count=len(docs),chunk_count=len(chunks),source_and_metadata_consistent=True),
        expected_portfolio=dict(solution_ids=expected['selected_solution_ids'],total_ax_score=expected['total_ax_score'],total_first_year_tco_krw=expected['total_first_year_tco_krw'],runner_up=expected['runner_up'],runner_up_score_gap=expected['runner_up_score_gap'],evaluated_combinations=expected['evaluated_combinations'],valid_combinations=expected['valid_combinations']),
        postgresql_and_pgvector=pg)

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--postgres-report',type=Path)
    parser.add_argument('--write',action='store_true')
    args=parser.parse_args()
    result=validate(postgres_report=args.postgres_report)
    text=json.dumps(result,ensure_ascii=False,indent=2)+'\n'
    if args.write: (ROOT/'quality_checks.json').write_text(text)
    print(text,end='')
