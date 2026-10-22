"""Grounded readiness references. Spring DTO and numerical responsibility stay unchanged."""
import json
from pathlib import Path
from typing import Literal

import yaml
from pydantic import Field, create_model
from .contexts import assessment_rows
from .schemas import Assessment, AssessmentDraft, AssessmentAreaDraft


class AssessmentReferenceError(ValueError):
    def __init__(self, code, **details):
        self.code, self.details = code, details
        super().__init__(code + ': ' + json.dumps(details, ensure_ascii=False))


def load_policy(settings):
    policy = json.loads((settings.data_dir/'config/assessment_criteria_v1.json').read_text())
    rubric_path = Path(__file__).resolve().parents[1]/'config/maturity_criteria.yaml'
    rubric = yaml.safe_load(rubric_path.read_text(encoding='utf-8'))
    areas = {value['column']: value for value in rubric['areas'].values()}
    if set(areas) != set(policy['weights']) or any(areas[k]['weight'] != policy['weights'][k] for k in areas):
        raise ValueError('ASSESSMENT_POLICY_MISMATCH: 영역·가중치 기준표가 다릅니다.')
    return {**policy, 'rubric_version':rubric['version'],
            'rubrics':{k:{'label':v['label'], 'evidence_sources':v['evidence_sources'], 'rubric':v['rubric']}
                       for k,v in areas.items()}}


def evidence_catalog(state):
    rows = sorted(assessment_rows(state), key=lambda r:(r['document_id'],r['section'],r['content']))
    unique, registry = set(), {}
    for row in rows:
        key = (row['document_id'], row['section'], row['content'])
        if key in unique: continue
        unique.add(key)
        registry[f'E{len(registry)+1:03d}'] = row
    if not registry:
        raise ValueError('INSUFFICIENT_DATA: 성숙도 평가 근거가 없습니다.')
    return registry


def draft_schema(registry):
    evidence_id = Literal[tuple(registry)]
    area = create_model('GroundedAssessmentArea', __base__=AssessmentAreaDraft,
                        evidence_ids=(list[evidence_id], ...))
    return create_model('GroundedAssessment', __base__=AssessmentDraft,
                        areas=(list[area], Field(min_length=5, max_length=5)))


def resolve_draft(value, registry, criteria):
    draft = AssessmentDraft.model_validate(value.model_dump() if hasattr(value,'model_dump') else value)
    required = set(criteria['weights'])
    areas = [a.area for a in draft.areas]
    if len(areas) != len(set(areas)) or set(areas) != required:
        raise AssessmentReferenceError('ASSESSMENT_AREA_MISMATCH', received=areas, required=sorted(required))
    scores, evidence, missing = {}, [], []
    for area in draft.areas:
        unknown = sorted(set(area.evidence_ids) - registry.keys())
        if unknown:
            raise AssessmentReferenceError('ASSESSMENT_EVIDENCE_INVALID_REFERENCE', area=area.area, evidenceIds=unknown)
        if area.score is None:
            if not area.missing_reason or not area.missing_reason.strip():
                raise AssessmentReferenceError('ASSESSMENT_MISSING_REASON', area=area.area)
            missing.append(area.area)
            continue
        if not area.evidence_ids:
            raise AssessmentReferenceError('ASSESSMENT_EVIDENCE_MISSING', area=area.area)
        allowed = criteria.get('rubrics',{}).get(area.area,{}).get('evidence_sources')
        if allowed and not any(registry[key]['doc_type'] in allowed for key in area.evidence_ids):
            raise AssessmentReferenceError('ASSESSMENT_EVIDENCE_WRONG_AREA', area=area.area, evidenceIds=area.evidence_ids)
        scores[area.area] = area.score
        for key in dict.fromkeys(area.evidence_ids):
            row = registry[key]
            evidence.append({'area':area.area, 'document_id':row['document_id'],
                             'section':row['section'], 'summary':area.summary})
    return Assessment(scores=scores,evidence=evidence,insufficient_data=missing).model_dump()
