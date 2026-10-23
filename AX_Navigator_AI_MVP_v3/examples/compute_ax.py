#!/usr/bin/env python3
"""Offline reference oracle, NOT a production Agent calculator. Python 3.10+, stdlib only.
Pinned evaluation date makes the July–September 2026 sample reproducible.
Decimal ROUND_HALF_UP: score 1dp, ROI 2dp, payback 1dp, hours 2dp, KRW integer.
The objective sums the returned rounded AX scores; impact/feasibility are rounded
only for display, never before computing the AX score.
"""
import argparse
import calendar
import csv
import itertools
import json
from datetime import date
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
D = lambda v: Decimal(str(v))

def rounded(value, places=1):
    return float(value.quantize(D(1).scaleb(-places), rounding=ROUND_HALF_UP))

def money(value):
    return int(value.quantize(D(1), rounding=ROUND_HALF_UP))

def load_table(root, table):
    with (root / 'csv' / f'{table}.csv').open(encoding='utf-8-sig', newline='') as f:
        return list(csv.DictReader(f))

def truth(v):
    return str(v).lower() in ('true', '1')

def compute(root=ROOT, as_of=date(2026, 10, 1)):
    root = Path(root)
    policy = json.loads((root / 'config/ax_score_policy_v1.json').read_text())
    company = load_table(root, 'companies')[0]
    company_id = company['company_id']
    dept_ids = {d['department_id'] for d in load_table(root, 'departments') if d['company_id'] == company_id}
    processes = {p['process_id']: p for p in load_table(root, 'business_processes') if p['department_id'] in dept_ids}
    # Seed-only offline oracle: the seed has exactly one process per template type.
    # Runtime matching and calculations remain in Spring.
    solutions = []
    for template in load_table(root, 'ai_solution_catalog'):
        matching = [pid for pid,p in processes.items() if p['work_type'] == template['work_type']]
        if len(matching) != 1: raise ValueError('Offline seed oracle requires one process per template type')
        solutions.append({**template, 'target_process_id': matching[0]})
    systems = {s['system_id']: s for s in load_table(root, 'it_systems') if s['company_id'] == company_id}
    links = load_table(root, 'process_systems')
    metrics = load_table(root, 'process_metrics')
    exclusion_ids = {str(e['process_id']) for e in policy['exclusions']}
    excluded = [{'processId': int(p), 'reason': e['reason']} for e in policy['exclusions']
                if (p := str(e['process_id'])) in processes]
    eligible = [s for s in solutions if s['target_process_id'] not in exclusion_ids]
    details = {}
    grade = {'ASSUMED': 0, 'SURVEY': 1, 'MEASURED': 2}
    for s in eligible:
        pid = s['target_process_id']
        recent = sorted([m for m in metrics if m['process_id'] == pid and date.fromisoformat(m['period_end']) < as_of],
                        key=lambda m: m['period_start'], reverse=True)[:3]
        if len(recent) != 3:
            raise ValueError(f'INSUFFICIENT_DATA: process {pid} needs 3 completed months')
        periods = [date.fromisoformat(m['period_start']) for m in recent]
        for m, start in zip(recent, periods):
            if start.day != 1 or date.fromisoformat(m['period_end']).day != calendar.monthrange(start.year, start.month)[1]:
                raise ValueError('Metrics must represent full calendar months')
        if len({(p.year,p.month) for p in periods}) != 3:
            raise ValueError('Duplicate metric months')
        hours = [D(m['processing_count']) * D(m['avg_processing_minutes']) / 60 for m in recent]
        quarter = sum(hours)
        if quarter <= 0:
            raise ValueError('INSUFFICIENT_DATA: nonpositive hours')
        annual = quarter * 4
        labor = sum(h * D(m['hourly_labor_cost_krw']) for h,m in zip(hours,recent)) / quarter
        saved = annual * D(s['automation_rate_base']) * D(s['time_reduction_rate_base'])
        details[s['solution_id']] = dict(annual=annual, labor=labor, saved=saved,
            data_confidence=min((m['data_source'] for m in recent), key=grade.__getitem__),
            metric_ids=[int(m['metric_id']) for m in recent])
    maximum = max(d['saved'] for d in details.values())
    if maximum <= 0:
        raise ValueError('INSUFFICIENT_DATA: nonpositive maximum savings')
    candidates = []
    for s in eligible:
        p = processes[s['target_process_id']]
        d = details[s['solution_id']]
        api_ok = not truth(s['requires_api']) or any(truth(systems[l['system_id']]['api_available'])
                     for l in links if l['process_id'] == s['target_process_id'] and l['system_id'] in systems)
        impact = d['saved'] / maximum * 100
        feasibility = D(p['standardization_level']) * D(policy['feasibility']['standardization_multiplier']) + (D(policy['feasibility']['api_ok_points']) if api_ok else D(0))
        score = impact * D(policy['weights']['impact']) + feasibility * D(policy['weights']['feasibility'])
        annual_run = D(s['monthly_run_cost_krw']) * 12
        build = D(s['base_build_cost_krw'])
        tco = build + annual_run
        if tco <= 0:
            raise ValueError('First-year TCO must be positive')
        scenarios = {}
        for scenario in ('low','base','high'):
            saving = d['annual'] * D(s[f'automation_rate_{scenario}']) * D(s[f'time_reduction_rate_{scenario}']) * d['labor']
            scenarios[scenario] = dict(annualSavingKrw=money(saving), roiPct=rounded((saving-tco)/tco*100,2),
                paybackMonths=rounded(12*build/(saving-annual_run)) if saving>annual_run else None,
                threeYearNetKrw=money(3*saving-build-3*annual_run))
        candidates.append(dict(processId=int(p['process_id']),solutionId=int(s['solution_id']),
            dependsOnSolutionId=int(s['depends_on_solution_id']) if s['depends_on_solution_id'] else None,
            dependsOnProcessId=next(int(t['target_process_id']) for t in solutions if t['solution_id']==s['depends_on_solution_id']) if s['depends_on_solution_id'] else None,
            axScore=rounded(score,policy['rounding']),impactScore=rounded(impact),feasibilityScore=rounded(feasibility),
            savedHoursBase=rounded(d['saved'],2),apiOk=api_ok,humanReviewRequired=truth(p['requires_approval']),
            dataConfidence=d['data_confidence'],warnings=['LOW_STANDARDIZATION'] if D(p['standardization_level']) < D(s['min_standardization_level']) else [],
            firstYearTcoKrw=money(tco),scenarios=scenarios))
    candidates.sort(key=lambda c:c['solutionId'])
    budget = int(company['ax_budget_krw'])
    combinations = list(itertools.combinations(candidates, policy['portfolio']['max_items']))
    valid = []
    for combo in combinations:
        ids = {c['solutionId'] for c in combo}
        if (sum(c['firstYearTcoKrw'] for c in combo) <= budget
            and len({c['processId'] for c in combo}) == len(combo)
            and all(c['dependsOnSolutionId'] is None or c['dependsOnSolutionId'] in ids for c in combo)):
            valid.append(combo)
    def total_score(combo):
        return sum((D(c['axScore']) for c in combo),D(0))
    valid.sort(key=lambda cs:(-total_score(cs),-sum(c['scenarios']['base']['threeYearNetKrw'] for c in cs),sum(c['firstYearTcoKrw'] for c in cs)))
    if len(valid)<2:
        raise ValueError('Demo requires at least two valid portfolios')
    best, runner = valid[:2]
    greedy = sorted(candidates,key=lambda c:(-c['axScore'],c['solutionId']))[:3]
    ids = {c['solutionId'] for c in greedy}
    greedy_violations = []
    if sum(c['firstYearTcoKrw'] for c in greedy)>budget: greedy_violations.append('BUDGET_EXCEEDED')
    if any(c['dependsOnSolutionId'] and c['dependsOnSolutionId'] not in ids for c in greedy): greedy_violations.append('MISSING_DEPENDENCY')
    return dict(evaluation_as_of=as_of.isoformat(),budget_limit_krw=budget,
        selected_solution_ids=[c['solutionId'] for c in best],selected_process_ids=[c['processId'] for c in best],
        total_ax_score=float(total_score(best)),total_first_year_tco_krw=sum(c['firstYearTcoKrw'] for c in best),
        remaining_budget_krw=budget-sum(c['firstYearTcoKrw'] for c in best),
        evaluated_combinations=len(combinations),valid_combinations=len(valid),
        runner_up=dict(solution_ids=[c['solutionId'] for c in runner],total_ax_score=float(total_score(runner))),
        runner_up_score_gap=float(total_score(best)-total_score(runner)),
        greedy_top3_by_score=dict(solution_ids=[c['solutionId'] for c in greedy],total_ax_score=float(total_score(greedy)),
            total_first_year_tco_krw=sum(c['firstYearTcoKrw'] for c in greedy),violations=greedy_violations),
        excluded=excluded,per_candidate=candidates,
        calculation_details=[dict(solution_id=int(sid),annual_hours=rounded(d['annual'],4),labor_cost=rounded(d['labor'],4),
            saved_hours=rounded(d['saved'],4),metric_ids=d['metric_ids']) for sid,d in sorted(details.items())],
        normalization_max_saved_hours=rounded(maximum,4))

if __name__ == '__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root',type=Path,default=ROOT)
    parser.add_argument('--as-of',type=date.fromisoformat,default=date(2026,10,1))
    parser.add_argument('--write',action='store_true',help='Regenerate eval/demo_expected_portfolio.json')
    args=parser.parse_args()
    result=compute(args.root,args.as_of)
    output=json.dumps(result,ensure_ascii=False,indent=2)+'\n'
    if args.write: (args.root/'eval/demo_expected_portfolio.json').write_text(output,encoding='utf-8')
    else: print(output,end='')
