"""Grounded company-data extraction from uploaded documents. Numbers only when a cited chunk states them."""
from typing import Literal
from pydantic import Field, create_model
from .assessment import AssessmentReferenceError
from .schemas import ExtractionDraft, ProcessExtract, MetricExtract

CHUNK_FIELDS = {'document_id', 'title', 'section', 'page', 'content'}


def chunk_catalog(rows, document_ids):
    """Stable C001.. ids over the uploaded document chunks the task may use."""
    allowed = set(document_ids)
    rows = [r for r in rows if r.get('document_id') in allowed]
    if any(not CHUNK_FIELDS <= r.keys() for r in rows):
        raise ValueError('RAG 문서 조각 필드 부족')
    rows.sort(key=lambda r: (r['document_id'], r['page'], r.get('chunk_index', 0), r['section']))
    catalog = {f'C{i+1:03d}': row for i, row in enumerate(rows)}
    if not catalog:
        raise ValueError('INSUFFICIENT_DATA: 기업 데이터를 추출할 문서 내용이 없습니다.')
    return catalog


def draft_schema(catalog):
    source = Literal[tuple(catalog)]
    process = create_model('GroundedProcess', __base__=ProcessExtract, sourceId=(source | None, ...))
    metric = create_model('GroundedMetric', __base__=MetricExtract, sourceId=(source, ...))
    return create_model('GroundedExtraction', __base__=ExtractionDraft,
                        processes=(list[process], Field(min_length=1, max_length=200)),
                        metrics=(list[metric], Field(max_length=200)))


def _unique(keys, code):
    if len(keys) != len(set(keys)):
        raise AssessmentReferenceError(code, duplicate=sorted({k for k in keys if keys.count(k) > 1}))
    return set(keys)


def resolve_draft(value, catalog):
    """Check key references and convert sourceId to Spring's {documentId, page}. Raises for one repair round."""
    draft = ExtractionDraft.model_validate(value.model_dump() if hasattr(value, 'model_dump') else value)
    departments = _unique([d.key for d in draft.departments], 'EXTRACTION_DUPLICATE_DEPARTMENT')
    processes = _unique([p.key for p in draft.processes], 'EXTRACTION_DUPLICATE_PROCESS')
    _unique([s.key for s in draft.systems], 'EXTRACTION_DUPLICATE_SYSTEM')
    _unique([m.processKey for m in draft.metrics], 'EXTRACTION_DUPLICATE_METRIC')
    if missing := sorted({p.departmentKey for p in draft.processes} - departments):
        raise AssessmentReferenceError('EXTRACTION_UNKNOWN_DEPARTMENT', departmentKeys=missing)
    referenced = {m.processKey for m in draft.metrics} | {k for s in draft.systems for k in s.processKeys}
    if missing := sorted(referenced - processes):
        raise AssessmentReferenceError('EXTRACTION_UNKNOWN_PROCESS', processKeys=missing)
    sources = [p.sourceId for p in draft.processes if p.sourceId] + [m.sourceId for m in draft.metrics]
    if unknown := sorted(set(sources) - catalog.keys()):
        raise AssessmentReferenceError('EXTRACTION_UNKNOWN_SOURCE', sourceIds=unknown)

    def source(key):
        return {'documentId': catalog[key]['document_id'], 'page': catalog[key]['page']} if key else None

    payload = draft.model_dump()
    for row in payload['processes']:
        row['source'] = source(row.pop('sourceId'))
        if row['standardizationLevel'] is not None: row['standardizationLevel'] = round(row['standardizationLevel'], 2)
    for row in payload['metrics']:
        row['source'] = source(row.pop('sourceId'))
        row['avgMinutes'] = round(row['avgMinutes'], 2)
        if row['errorRate'] is not None: row['errorRate'] = round(row['errorRate'], 4)
        # 문서 값을 그대로 쓴 지표. 사용자가 확정 화면에서 고치면 FE가 USER_INPUT으로 바꾼다.
        row['dataSource'] = 'EXTRACTED'
    return payload
