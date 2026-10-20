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
    for size in range(len(candidates)+1):
        for subset in itertools.combinations(candidates,size):
            combinations=list(itertools.combinations(subset,3));valid=[]
            for combo in combinations:
                ids={c['solutionId'] for c in combo}
                if sum(c['firstYearTcoKrw'] for c in combo)>budget:continue
                if len({c['processId'] for c in combo})!=3:continue
                if any(c['dependsOnSolutionId'] and c['dependsOnSolutionId'] not in ids for c in combo):continue
                valid.append(combo)
            def score(combo):return sum((Decimal(str(c['axScore'])) for c in combo),Decimal(0))
            valid.sort(key=lambda cs:(-score(cs),-sum(c['scenarios']['base']['threeYearNetKrw'] for c in cs),sum(c['firstYearTcoKrw'] for c in cs)))
            best=list(valid[0]) if valid else []
            total=sum(c['firstYearTcoKrw'] for c in best)
            result[','.join(str(c['solutionId']) for c in subset)]={
                'insufficient':not best,'budgetKrw':budget,'selected':best,
                'totalAxScore':float(score(best)),'totalFirstYearTcoKrw':total,'remainingBudgetKrw':budget-total,
                'evaluatedCombinations':len(combinations),'validCombinations':len(valid),'excluded':reference['excluded']}
    output={'source_sha256':source_hashes(),'max_items':3,'normalization':'all_company_eligible_candidates',
            'generated_by':'scripts/build_demo_portfolios.py (offline only)','portfolios':result}
    path=ROOT/'agent/fixtures/portfolio_subsets_v3.json'
    path.write_text(json.dumps(output,ensure_ascii=False,indent=2)+'\n')
    print(f'Generated {len(result)} precomputed candidate subsets')

if __name__=='__main__':main()
