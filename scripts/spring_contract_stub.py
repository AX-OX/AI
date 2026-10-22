"""TEST ONLY: v3 fixture responses for team Spring APIs, never production calculations.
Start only with AX_TEST_STUB=1. Does not connect to business DB or implement login.
"""
import os
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from fastapi import FastAPI, Request, HTTPException
from agent.app.config import Settings
from agent.app.mock import MockGateway
from agent.app.contracts import snake_keys

if os.getenv('AX_TEST_STUB')!='1':
    raise RuntimeError('Test fixture server requires AX_TEST_STUB=1')
settings=Settings(mode='mock',internal_token=os.environ['INTERNAL_TOKEN'])
gateway=MockGateway(settings)
app=FastAPI(title='TEST ONLY v3 Spring contract fixture')

@app.api_route('/internal/{path:path}',methods=['GET','POST','PATCH'])
async def contract(path:str,request:Request):
    if request.headers.get('x-internal-token')!=settings.internal_token: raise HTTPException(403)
    pieces=path.split('/')
    body=await request.json() if request.method!='GET' else {}
    name,args=None,{}
    if pieces[0]=='companies' and request.method=='GET':
        if int(pieces[1])!=1: raise HTTPException(403)
        suffix=pieces[2] if len(pieces)>2 else 'profile'
        names={'profile':'get_company_profile','processes':'get_business_processes','metrics':'get_operational_metrics',
               'systems':'get_system_inventory','budget':'get_project_budget'}
        name=names.get(suffix);args={'company_id':1}
    elif path=='solutions' and request.method=='GET': name='get_solution_catalog'
    elif path=='ax/roi': name='calculate_ax_roi';args={'process_id':body['processId'],'solution_id':body['solutionId']}
    elif path=='ax/portfolio':
        if body['companyId']!=1: raise HTTPException(403)
        name='optimize_ax_portfolio'
        args={'company_id':body['companyId'],'candidates':[{'process_id':p['processId'],'solution_id':p['solutionId']} for p in body['candidates']],'max_items':body['maxItems'],'budget_krw':body.get('budgetKrw')}
    elif path=='assessments':
        areas={'data':'data_score','infra':'infra_score','automation':'automation_score','aiCapability':'ai_capability_score','governance':'governance_score'}
        name='save_assessment';args={'task_id':body['taskId'],'scores':{areas.get(k,k):v for k,v in body['scores'].items()},'criteria_version':body['criteriaVersion'],'evidence':body['evidence']}
    elif path=='roadmaps':
        name='create_ax_roadmap';args={'task_id':body['taskId'],'company_id':body['companyId'],'assessment_id':body['assessmentId'],'roadmap_name':body['roadmapName'],'items':snake_keys(body['items'])}
    elif path=='projects': name='create_ax_project';args={'item_id':body['itemId'],'owner_department_id':body['ownerDepartmentId'],'project_name':body['projectName']}
    elif pieces[0]=='tasks' and (request.method=='PATCH' or pieces[-1]=='events'):
        return {'ok':True}
    if name is None: raise HTTPException(404)
    try: return gateway._call(body.get('taskId','v3-http-test'),name,args)
    except (StopIteration,KeyError,ValueError) as exc: raise HTTPException(422,str(exc)) from exc
