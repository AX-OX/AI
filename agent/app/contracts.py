"""Adapt Spring read DTOs to the Agent's internal schema, without calculating metrics."""
import re


def snake_keys(value):
    if isinstance(value, list):
        return [snake_keys(v) for v in value]
    if not isinstance(value, dict):
        return value
    result = {}
    for key, item in value.items():
        name = re.sub(r'(?<!^)(?=[A-Z])', '_', key).lower()
        converted = snake_keys(item)
        if name in result and result[name] != converted:
            raise ValueError(f'Spring 응답 필드 충돌: {name}')
        result[name] = converted
    return result


def normalize_read(name, value):
    """Support both current Spring camelCase DTOs and existing snake_case fixtures."""
    value = snake_keys(value)
    if name == 'get_operational_metrics' and isinstance(value, list):
        rows = []
        for process in value:
            if 'months' not in process:
                rows.append(process)
                continue
            context = {k: v for k, v in process.items() if k != 'months'}
            # Preserve missing-month information even when no monthly records exist.
            rows.extend([{**context, **month} for month in process['months']] or [context])
        return rows
    if name == 'get_system_inventory' and isinstance(value, list):
        return {
            'systems': [{k: v for k, v in system.items() if k != 'processes'} for system in value],
            'process_systems': [
                {'system_id': system['system_id'], **link}
                for system in value for link in system.get('processes', [])
            ],
        }
    return value
