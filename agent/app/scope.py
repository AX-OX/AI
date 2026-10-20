"""Resolve explicitly named departments against Spring's company department inventory."""
import re


def request_scope(text, departments, processes):
    named=[]
    for department in departments:
        name=department['department_name']
        pattern=rf'(?<![가-힣A-Za-z]){re.escape(name)}\s*(?:부서|부|팀)?(?=에서|만|의|에|을|를|도|와|과|\s|[,·/]|$)'
        if re.search(pattern,text):named.append(department)
    selected=named or departments
    ids={int(d['department_id']) for d in selected}
    return {'wholeCompany':not named,'departmentIds':sorted(ids),
            'departmentNames':[d['department_name'] for d in selected],
            'processIds':[int(p['process_id']) for p in processes if int(p['department_id']) in ids]}
