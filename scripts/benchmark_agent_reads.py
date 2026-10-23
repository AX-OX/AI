"""Compare ordered read phases only; no LLM, writes, task callbacks or approval.

Live requires the same MCP/DB environment as Agent. Prints hashes, never content.
"""
import argparse
import asyncio
from dataclasses import replace
import hashlib
import json
from pathlib import Path
import statistics
import sys
from time import perf_counter

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from agent.app.clients.mcp import Gateway
from agent.app.config import Settings
from agent.app.graph import build_nodes
from agent.app.mock import MockGateway
from agent.app.reasoning import MockReasoner
from agent.app.contracts import normalize_read


class ReadOnlyGateway(Gateway):
    async def event(self, task_id, type_, node='', data=None):
        self.observe(task_id,node,type_,data)


def digest(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,ensure_ascii=False,default=str).encode()).hexdigest()


async def benchmark(args):
    cfg=Settings.from_env()
    samples={1:[],args.parallel:[]}
    baseline=None
    for round_index in range(args.rounds):
        # Alternate order to reduce warm-cache/first-connection bias.
        for limit in ([1,args.parallel] if round_index%2==0 else [args.parallel,1]):
            current=replace(cfg,read_concurrency=limit)
            gateway=ReadOnlyGateway(current) if args.live else MockGateway(current)
            reasoner=MockReasoner(current)  # fixed seven reads, not an LLM benchmark
            state={'task_id':'read-benchmark','company_id':args.company_id,'request':args.request}
            started=perf_counter()
            raw=await reasoner.collect(state,gateway)
            collected=perf_counter()
            state.update({field:normalize_read(name,raw[name]) for name,field in {
                'get_company_profile':'company','get_business_processes':'processes',
                'get_operational_metrics':'metrics','get_system_inventory':'systems',
                'get_project_budget':'budget','get_solution_catalog':'solutions',
                'get_solution_candidates':'solution_candidates'}.items()})
            retrieval=await build_nodes(gateway,reasoner,current)['retrieve'](state)
            ended=perf_counter()
            fingerprint=digest({'reads':raw,'retrieval':retrieval})
            if baseline is None: baseline=fingerprint
            sample={'round':round_index+1,'collectSeconds':round(collected-started,4),
                    'retrieveSeconds':round(ended-collected,4),'totalSeconds':round(ended-started,4),
                    'sameResult':fingerprint==baseline,'sha256':fingerprint}
            samples[limit].append(sample)
    medians={str(k):{field:round(statistics.median(row[field] for row in rows),4)
                    for field in ['collectSeconds','retrieveSeconds','totalSeconds']} for k,rows in samples.items()}
    equal=all(row['sameResult'] for rows in samples.values() for row in rows)
    sequential=medians['1']['totalSeconds'];parallel=medians[str(args.parallel)]['totalSeconds']
    report={'mode':'live-mcp' if args.live else 'fixtures','scope':'7 read tools + common evidence + business searches; excludes LLM/writes',
            'rounds':args.rounds,'parallelLimit':args.parallel,'allResultsEqual':equal,
            'median':medians,'speedup':round(sequential/parallel,2) if parallel else None,'samples':samples}
    output=json.dumps(report,ensure_ascii=False,indent=2)
    print(output)
    if args.output:
        path=Path(args.output);path.parent.mkdir(parents=True,exist_ok=True);path.write_text(output+'\n')
    if not equal: raise SystemExit('Read results differ; inspect source data/index changes before rollout.')


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--live',action='store_true')
    parser.add_argument('--rounds',type=int,default=3)
    parser.add_argument('--parallel',type=int,choices=range(2,9),default=3)
    parser.add_argument('--company-id',type=int,default=1)
    parser.add_argument('--request',default='현재 업무 분석')
    parser.add_argument('--output')
    args=parser.parse_args()
    if args.rounds<1: parser.error('--rounds must be positive')
    asyncio.run(benchmark(args))
