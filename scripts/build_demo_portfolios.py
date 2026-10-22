#!/usr/bin/env python3
"""OFFLINE ONLY: precompute v3 candidate-subset portfolio fixtures, no production calculator.
Reads the reference oracle and verifies it against the package's offline compute script.
The mock loads only the JSON output; normalization always uses all company-eligible solutions.
"""
import csv
import hashlib
import itertools
import json
from decimal import Decimal
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
DATA=ROOT/'AX_Navigator_AI_MVP_v3'
sys.path.insert(0,str(DATA/'examples'))
from compute_ax import compute


def source_hashes(data=DATA):
    paths=sorted(list((data/'csv').glob('*.csv'))+list((data/'config').glob('*.json'))+[data/'eval/demo_expected_portfolio.json'])
    return {p.relative_to(data).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}


def main():
    reference=json.loads((DATA/'eval/demo_expected_portfolio.json').read_text())
    if compute(DATA)!=reference: raise ValueError('Rebuild the v3 oracle before generating mock portfolios')
    candidates=reference['per_candidate'];budget=reference['budget_limit_krw'];result={}
    smaller={}
    for item_count in (1,2,3):
        destination=result if item_count==3 else smaller.setdefault(str(item_count),{})
        for size in range(len(candidates)+1):
            for subset in itertools.combinations(candidates,size):
                if item_count<3 and size!=item_count: continue
                combinations=list(itertools.combinations(subset,item_count));valid=[]
                for combo in combinations:
                    ids={(c['processId'],c['solutionId']) for c in combo}
                    if sum(c['firstYearTcoKrw'] for c in combo)>budget:continue
                    if len({c['processId'] for c in combo})!=item_count:continue
                    if any(c['dependsOnSolutionId'] and (c['dependsOnProcessId'],c['dependsOnSolutionId']) not in ids for c in combo):continue
                    valid.append(combo)
                def score(combo):return sum((Decimal(str(c['axScore'])) for c in combo),Decimal(0))
                valid.sort(key=lambda cs:(-score(cs),-sum(c['scenarios']['base']['threeYearNetKrw'] for c in cs),sum(c['firstYearTcoKrw'] for c in cs)))
                best=list(valid[0]) if valid else []
                total=sum(c['firstYearTcoKrw'] for c in best)
                refs=lambda rows:[{'processId':c['processId'],'solutionId':c['solutionId']} for c in rows]
                greedy=sorted(subset,key=lambda c:(-c['axScore'],c['solutionId'],c['processId']))[:item_count]
                greedy_keys={(c['processId'],c['solutionId']) for c in greedy}
                violations=[]
                if sum(c['firstYearTcoKrw'] for c in greedy)>budget: violations.append('BUDGET_EXCEEDED')
                if any(c['dependsOnSolutionId'] and (c['dependsOnProcessId'],c['dependsOnSolutionId']) not in greedy_keys for c in greedy): violations.append('MISSING_DEPENDENCY')
                if len({c['processId'] for c in greedy})!=len(greedy):violations.append('DUPLICATE_PROCESS')
                destination[','.join(f"{c['processId']}:{c['solutionId']}" for c in subset)]={
                    'insufficient':not best,'budgetKrw':budget,'selected':best,
                    'totalAxScore':float(score(best)),'totalFirstYearTcoKrw':total,'remainingBudgetKrw':budget-total,
                    'runnerUp':{'candidates':refs(valid[1]),'totalAxScore':float(score(valid[1]))} if len(valid)>1 else None,
                    'greedyTop3':{'candidates':refs(greedy),'totalAxScore':float(score(greedy)),
                                  'totalFirstYearTcoKrw':sum(c['firstYearTcoKrw'] for c in greedy),'violations':violations},
                    'warnings':[], 'evaluatedCombinations':len(combinations),'validCombinations':len(valid),'excluded':reference['excluded']}
    output={'source_sha256':source_hashes(),'max_items':3,'normalization':'all_company_eligible_candidates','smaller_portfolios':smaller,
            'generated_by':'scripts/build_demo_portfolios.py (offline only)','portfolios':result}
    path=ROOT/'agent/fixtures/portfolio_subsets_v3.json'
    path.write_text(json.dumps(output,ensure_ascii=False,indent=2)+'\n')
    print(f'Generated {len(result)} precomputed candidate subsets')

if __name__=='__main__':main()
