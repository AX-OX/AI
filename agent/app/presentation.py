"""Display DTOs for the existing FE. Values come from tools, never from new formulas."""
import math

AREAS = {'data_score': 'data', 'infra_score': 'infra', 'automation_score': 'automation',
         'ai_capability_score': 'aiCapability', 'governance_score': 'governance'}


def evidence_dto(evidence):
    return [{**row, 'documentId': row.get('documentId', row.get('document_id'))}
            for row in evidence]


def names_for(state, process_id, solution_id):
    process = next((p for p in state.get('processes', []) if int(p['process_id']) == process_id), {})
    solution = next((s for s in state.get('solutions', []) if int(s['solution_id']) == solution_id), {})
    department = next((d for d in state.get('company', {}).get('departments', [])
                       if int(d['department_id']) == int(process.get('department_id', -1))), {})
    return {'processName': process.get('process_name', ''),
            'departmentName': department.get('department_name', process.get('department_name', '')),
            'solutionName': solution.get('solution_name', ''), 'solutionType': solution.get('solution_type', '')}


def candidates_dto(state):
    selected = {c['solutionId'] for c in (state.get('portfolio') or {}).get('selected', [])}
    proposals = {(c['process_id'], c['solution_id']): c for c in state.get('candidates', [])}
    def evidence(candidate):
        proposal = proposals.get((candidate['processId'], candidate['solutionId']), {})
        document_ids = set(proposal.get('document_ids', []))
        rows = [r for r in state.get('evidence', []) if r['document_id'] in document_ids]
        rows.sort(key=lambda r: not r['section'].startswith(str(candidate['processId']) + ' '))
        return evidence_dto([{'document_id': r['document_id'], 'title': r.get('title'),
                              'section': r['section'], 'summary': r['content'][:400]} for r in rows[:3]])
    return [{**c, **names_for(state, c['processId'], c['solutionId']),
             'firstYearCostKrw': c['firstYearTcoKrw'], 'priority': c['axScore'],
             'selected': c['solutionId'] in selected, 'evidence': evidence(c)} for c in state.get('roi', [])]


def maturity_dto(assessment):
    # The current FE calls totalScore.toFixed(). Do not fabricate a missing Spring total.
    if not assessment:
        return None
    total = assessment.get('total_score')
    if isinstance(total, bool) or not isinstance(total, (int, float)) or not math.isfinite(total):
        return None
    return {'assessmentId': assessment['assessment_id'], 'totalScore': total,
            'criteriaVersion': assessment['criteria_version'],
            'scores': {AREAS[k]: v for k, v in assessment['scores'].items()},
            'insufficientData': assessment.get('insufficient_data', []),
            'evidence': [{**row, 'area': AREAS[row['area']]}
                         for row in evidence_dto(assessment['evidence'])]}


def projects_dto(state):
    return [{'projectId': p['project_id'], 'itemId': p['item_id'], 'projectName': p['project_name'],
             'ownerDepartmentId': p['owner_department_id'], 'projectStatus': p['project_status']}
            for p in (state.get('registration') or {}).get('projects', [])]
