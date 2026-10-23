"""Select grounded catalogue entries, never independently generate process/solution IDs."""
from typing import Literal
from pydantic import Field,create_model
from .assessment import AssessmentReferenceError
from .schemas import DiscoveryDraft, CandidateDraft
from .candidates import eligible_candidates


def candidate_catalog(state):
    rows=state.get('business_evidence',[r for r in state['evidence'] if r.get('doc_type') in {'MANUAL','UPLOADED'}])
    evidence={f'B{i+1:03d}':row for i,row in enumerate(sorted(rows,key=lambda r:(r['document_id'],r['section'],r['content'])))}
    choices={}
    for candidate in eligible_candidates(state):
        pid,sid=candidate['process_id'],candidate['solution_id']
        own=[key for key,row in evidence.items() if
             (row.get('doc_type')=='UPLOADED' or row['section'].startswith(f'{pid} ')
              or row['content'].startswith(f'process_id={pid}.'))]
        if not own:
            raise ValueError(f'INSUFFICIENT_DATA: 후보 업무 문서 근거 부족 process_id={pid}')
        choices[f'S{sid}P{pid}']={'process_id':pid,'solution_id':sid,'evidence_ids':own,
                                'depends_on':candidate['depends_on']}
    if not choices or len(choices)>10:
        raise ValueError('후보 카탈로그는 근거 있는 업무 1~10개여야 합니다. 요청 범위를 나누세요.')
    return choices,evidence


def discovery_schema(choices,evidence):
    choice=Literal[tuple(choices)];reference=Literal[tuple(evidence)]
    candidate=create_model('GroundedCandidate',__base__=CandidateDraft,
                           candidate_id=(choice,...),evidence_ids=(list[reference],...))
    return create_model('GroundedDiscovery',__base__=DiscoveryDraft,
                        candidates=(list[candidate],Field(min_length=1,max_length=10)))


def resolve_candidates(value,choices,evidence):
    draft=DiscoveryDraft.model_validate(value.model_dump() if hasattr(value,'model_dump') else value)
    ids=[row.candidate_id for row in draft.candidates]
    if len(ids)!=len(set(ids)) or set(ids)!=set(choices):
        raise AssessmentReferenceError('CANDIDATE_COVERAGE_MISMATCH',
                                       missing=sorted(set(choices)-set(ids)),unknown=sorted(set(ids)-set(choices)),
                                       duplicate=len(ids)!=len(set(ids)))
    result=[]
    for row in draft.candidates:
        choice=choices[row.candidate_id]
        if not row.evidence_ids or not set(row.evidence_ids)<=set(choice['evidence_ids']):
            raise AssessmentReferenceError('CANDIDATE_EVIDENCE_INVALID_REFERENCE',candidateId=row.candidate_id)
        result.append({'process_id':choice['process_id'],'solution_id':choice['solution_id'],
                       'evidence_refs':[evidence[key] for key in dict.fromkeys(row.evidence_ids)],
                       'reason':row.reason,'document_ids':list(dict.fromkeys(evidence[key]['document_id'] for key in row.evidence_ids))})
    return result
