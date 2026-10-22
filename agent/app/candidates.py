"""Candidate identity and Spring-owned eligibility; no matching or scoring formulas."""
from .schemas import SolutionCandidate


def pair(row):
    if 'process_id' in row:
        return int(row['process_id']), int(row['solution_id'])
    return int(row['processId']), int(row['solutionId'])


def pair_id(row):
    pid, sid = pair(row)
    return f'{pid}:{sid}'


def roi_dependency(row):
    pid, sid = row['dependsOnProcessId'], row['dependsOnSolutionId']
    if (pid is None) != (sid is None):
        raise ValueError('Spring 선행 후보 쌍의 일부 필드가 없습니다.')
    return None if pid is None else (pid, sid)


def normalize_candidates(rows, processes, solutions):
    if not isinstance(rows, list): raise ValueError('Spring solution_candidates 응답은 배열이어야 합니다.')
    pids = {int(p['process_id']) for p in processes}
    sids = {int(s['solution_id']) for s in solutions}
    result, seen = [], set()
    for raw in rows:
        row = SolutionCandidate.model_validate(raw).model_dump()
        key = pair(row)
        if key in seen or key[0] not in pids or key[1] not in sids:
            raise ValueError('Spring 후보 쌍 중복 또는 회사·템플릿 범위 불일치')
        seen.add(key); result.append(row)
    return result


def eligible_candidates(state):
    scoped = set((state.get('scope') or {}).get('processIds', [int(p['process_id']) for p in state['processes']]))
    return [r for r in state['solution_candidates'] if r['process_id'] in scoped
            and r['excluded_reason'] is None and r['metrics_sufficient']]


def exclusions(state):
    # API contains excluded pairs; portfolio excluded is company-wide, one per process.
    return [{'processId': pid, 'reason': reason} for pid, reason in sorted({
        (r['process_id'], r['excluded_reason']) for r in state['solution_candidates']
        if r['excluded_reason'] is not None})]


def grounded_rows(candidate, state):
    if candidate.get('evidence_refs'):
        return candidate['evidence_refs']
    pid = candidate['process_id']
    docs = set(candidate['document_ids'])
    return [r for r in state['business_evidence'] if r['document_id'] in docs and
            (r.get('doc_type') == 'UPLOADED' or r['section'].startswith(f'{pid} ')
             or r['content'].startswith(f'process_id={pid}.'))]
