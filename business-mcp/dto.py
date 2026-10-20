"""Spring storage DTO boundary. MCP tools keep their stable snake_case interface."""
AREAS = {'data_score':'data', 'infra_score':'infra', 'automation_score':'automation',
         'ai_capability_score':'aiCapability', 'governance_score':'governance'}


def camel(value):
    if isinstance(value, list):
        return [camel(v) for v in value]
    if not isinstance(value, dict):
        return value
    def key(name):
        first, *rest = name.split('_')
        return first + ''.join(part[:1].upper() + part[1:] for part in rest)
    return {key(k): camel(v) for k, v in value.items()}


def storage_result(value):
    names = {'assessmentId':'assessment_id', 'totalScore':'total_score', 'roadmapId':'roadmap_id',
             'itemIds':'item_ids', 'projectId':'project_id', 'projectStatus':'project_status'}
    return {names.get(k,k):v for k,v in value.items()}
