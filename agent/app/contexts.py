"""Purpose-specific, complete JSON contexts. Never slice serialized JSON or citations."""
import json
from .clients import mask

# UPLOADED: 고객사가 올린 PDF. 유형 분류가 없으므로 모든 성숙도 영역의 근거 후보가 된다.
ASSESSMENT_TYPES = frozenset({'SYSTEM_SPEC', 'POLICY', 'AI_STATUS', 'DATA_QUALITY', 'PROJECT_REPORT', 'UPLOADED'})


def pick(row, fields):
    return {k: row[k] for k in fields if k in row}


def evidence_rows(rows):
    return [pick(r, ('evidence_id', 'document_id', 'title', 'doc_type', 'section', 'content')) for r in rows]


def assessment_rows(state):
    if 'assessment_evidence' in state:
        return state['assessment_evidence']
    return [r for r in state['evidence'] if r.get('doc_type') in ASSESSMENT_TYPES]


def assessment_context(state, criteria):
    return {
        'criteria': criteria,
        'evidence': evidence_rows(assessment_rows(state)),
        'processes': [pick(p, ('process_id', 'process_name', 'standardization_level', 'requires_approval'))
                      for p in state['processes']],
        'systems': state['systems'],
        'metrics': [pick(m, ('process_id', 'period_start', 'period_end', 'processing_count',
                            'avg_processing_minutes', 'error_rate', 'data_source')) for m in state['metrics']],
    }


def discovery_context(state, mode):
    process_fields = ('process_id', 'department_id', 'process_name', 'purpose', 'standardization_level',
                      'requires_approval', 'exception_rules')
    solution_fields = ('solution_id', 'target_process_id', 'depends_on_solution_id', 'solution_name',
                       'solution_type', 'description', 'min_standardization_level', 'requires_api')
    return {
        'request': state['request'], 'evaluation_policy': state.get('evaluation_policy', {}),
        'evidence': evidence_rows(state['evidence']),
        'processes': [pick(p, process_fields) for p in state['processes']],
        'solutions': [pick(s, solution_fields) for s in state['solutions']],
        'scope': state.get('scope'), 'execution_mode': mode,
        'previous_portfolio': state.get('portfolio'), 'previous': state.get('candidates', []),
        'retry': state.get('retry_count', 0),
    }


def response_context(state):
    selected = {c['processId'] for c in state['portfolio']['selected']}
    documents = {e['document_id'] for item in state['roadmap']['items'] for e in item['evidence']}
    roadmap = {**state['roadmap'], 'items': [
        {k: v for k, v in item.items() if k != 'evidence'} for item in state['roadmap']['items']]}
    return {
        'request': state['request'], 'portfolio': state['portfolio'], 'roadmap': roadmap,
        'selected_processes': [pick(p, ('process_id', 'process_name', 'purpose', 'requires_approval', 'exception_rules'))
                               for p in state['processes'] if int(p['process_id']) in selected],
        'evidence': evidence_rows([r for r in state['evidence'] if r['document_id'] in documents]),
    }


def context_json(data, *, stage, limit):
    text = json.dumps(mask(data), ensure_ascii=False, default=str, separators=(',', ':'))
    if len(text) > limit:
        raise ValueError(f'{stage.upper()}_CONTEXT_LIMIT: {len(text)} characters exceeds {limit}; '
                         'reduce source sections before evaluation, never truncate required evidence.')
    return text
