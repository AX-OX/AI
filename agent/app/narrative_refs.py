"""Bind final descriptions to selected pairs; the model never generates DB IDs."""
from collections import Counter
from typing import Literal
from pydantic import Field, create_model
from .schemas import ContractModel, Narrative
from .assessment import AssessmentReferenceError
from .candidates import pair


class NarrativeReferenceError(AssessmentReferenceError):
    pass


class RecommendationDraft(ContractModel):
    recommendation_id: str
    reason: str = Field(min_length=1)
    document_ids: list[int] = Field(min_length=1)


class NarrativeDraft(ContractModel):
    summary: str = Field(min_length=1)
    recommendations: list[RecommendationDraft] = Field(min_length=1, max_length=3)


def reference_catalog(state):
    selected={pair(row):row for row in state['portfolio']['selected']}
    items=state['roadmap']['items']
    keys=[pair(item) for item in items]
    if not 1<=len(keys)<=3 or len(keys)!=len(set(keys)) or set(keys)!=set(selected):
        raise NarrativeReferenceError('NARRATIVE_SELECTION_INVALID')
    catalog={}
    for i,item in enumerate(items,1):
        docs=list(dict.fromkeys(e['document_id'] for e in item['evidence']))
        if not docs: raise NarrativeReferenceError('NARRATIVE_SOURCE_MISSING',processId=item['process_id'])
        catalog[f'R{i}']={'process_id':item['process_id'],'solution_id':item['solution_id'],
                          'item_name':item['item_name'],'document_ids':docs}
    return catalog


def draft_schema(catalog):
    reference=Literal[tuple(catalog)]
    docs=Literal[tuple(sorted({d for c in catalog.values() for d in c['document_ids']}))]
    recommendation=create_model('SelectedRecommendation',__base__=RecommendationDraft,
                                recommendation_id=(reference,...),
                                document_ids=(list[docs],Field(min_length=1)))
    return create_model('GroundedNarrative',__base__=NarrativeDraft,
                        recommendations=(list[recommendation],Field(min_length=len(catalog),max_length=len(catalog))))


def resolve_narrative(raw,catalog):
    draft=NarrativeDraft.model_validate(raw.model_dump() if hasattr(raw,'model_dump') else raw)
    received=[r.recommendation_id for r in draft.recommendations]
    counts=Counter(received)
    # Unknown values might contain arbitrary model text: only reference-shaped IDs are logged.
    safe=lambda ref: ref if ref.startswith('R') and ref[1:].isdigit() and len(ref)<=5 else '<invalid-ref>'
    if len(received)!=len(catalog) or set(received)!=set(catalog) or any(n>1 for n in counts.values()):
        raise NarrativeReferenceError('NARRATIVE_REFERENCE_MISMATCH',
            expected=[{'reference':key,'processId':c['process_id'],'solutionId':c['solution_id']} for key,c in catalog.items()],
            received=[safe(r) for r in received],missing=sorted(set(catalog)-set(received)),
            unknown=[safe(r) for r in sorted(set(received)-set(catalog))],
            duplicates=[safe(r) for r,n in counts.items() if n>1])
    notes={r.recommendation_id:r for r in draft.recommendations}
    recommendations=[]
    for ref,choice in catalog.items():
        note=notes[ref]
        if not set(note.document_ids)<=set(choice['document_ids']):
            raise NarrativeReferenceError('NARRATIVE_EVIDENCE_MISMATCH',reference=ref,
                expectedDocumentIds=choice['document_ids'],receivedDocumentIds=note.document_ids)
        recommendations.append({'process_id':choice['process_id'],'solution_id':choice['solution_id'],
                                'reason':note.reason,'document_ids':list(dict.fromkeys(note.document_ids))})
    return Narrative(summary=draft.summary,recommendations=recommendations).model_dump()
