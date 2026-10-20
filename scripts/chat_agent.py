#!/usr/bin/env python3
"""Local FastAPI runner with real OpenAI + v3 fixtures, public execution trace and automatic demo registration.
Usage: .venv/bin/python scripts/chat_agent.py [--mode llm-demo|mock] [--prompt '...']
Loads .env locally; never prints API keys. Does not use or modify a server on port 8000.
"""
import argparse
import asyncio
from dataclasses import replace
import json
import os
from pathlib import Path
import sys
import time
import warnings
from uuid import uuid4

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
# Hide only the known dependency deprecation in the normal CLI; --verbose preserves it.
if '--verbose' not in sys.argv:
    from authlib.deprecate import AuthlibDeprecationWarning
    warnings.filterwarnings('ignore',message=r'authlib\.jose module is deprecated.*',category=AuthlibDeprecationWarning)
from scripts.agent_console import TracePrinter, display_result, display_registration, read_request
from dotenv import load_dotenv
import httpx
from agent.app.config import Settings
from agent.app.main import create_app


async def poll(client,key,timeout,*,after_seq=0,stop_at_approval=True,printer=None):
    printer=printer or TracePrinter()
    seen=after_seq;deadline=time.monotonic()+timeout+30
    while time.monotonic()<deadline:
        response=await client.get(f'/tasks/{key}')
        response.raise_for_status();body=response.json()
        for event in body.get('trace',[]):
            if event['seq']>seen: printer.show(event);seen=event['seq']
        terminal={'DONE','FAILED','REJECTED'} | ({'WAITING_APPROVAL'} if stop_at_approval else set())
        if body['status'] in terminal:return body
        await asyncio.sleep(.4)
    raise TimeoutError('작업 대기 시간 초과')


async def run(args):
    load_dotenv(ROOT/'.env',override=False)
    settings=replace(Settings.from_env(),mode=args.mode,checkpoint_url='',
                     internal_token=os.getenv('INTERNAL_TOKEN') or 'local-dev-token',
                     model=args.model or os.getenv('LLM_MODEL') or 'gpt-4.1-mini',timeout=max(180,Settings.from_env().timeout))
    if settings.mode=='llm-demo' and not os.getenv('OPENAI_API_KEY'):
        print('OPENAI_API_KEY를 .env 또는 환경 변수에 설정하세요. 키를 채팅이나 코드에 넣지 마세요.',file=sys.stderr)
        return 2
    print('AX Navigator · 로컬 실행')
    print(f"LLM: {settings.model+' (실제 OpenAI)' if settings.mode=='llm-demo' else 'mock'}")
    print('데이터·검색·등록: 시연용 / PostgreSQL 서버 연결 없음')
    print('진행 단계만 표시합니다. 상세 로그는 --verbose, 여러 줄 질문은 /multi를 사용하세요.')
    app=create_app(settings)
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://local-agent',headers={'X-Internal-Token':settings.internal_token}) as client:
            while True:
                try:
                    request=args.prompt or await asyncio.to_thread(read_request)
                except EOFError:return 0
                if request is None:return 0
                if request.strip().lower() in {'exit','/exit','quit','/quit','종료'}:return 0
                if not request: continue
                key=str(uuid4())
                response=await client.post(f'/tasks/{key}/run',json={'companyId':1,'userId':602,'requestText':request})
                response.raise_for_status()
                printer=TracePrinter(verbose=args.verbose)
                print(f'\n작업 ID: {key}',flush=True)
                result=await poll(client,key,settings.timeout,printer=printer)
                if result['status']=='WAITING_APPROVAL':
                    print('\n로드맵 작성 완료 · 가상 등록을 자동 진행합니다.',flush=True)
                    response=await client.post(f'/tasks/{key}/resume',json={'decision':'APPROVE','userId':602})
                    response.raise_for_status()
                    result=await poll(client,key,settings.timeout,
                                      after_seq=max((e['seq'] for e in result.get('trace',[])),default=0),
                                      stop_at_approval=False,printer=printer)
                if args.output:
                    args.output.parent.mkdir(parents=True,exist_ok=True)
                    args.output.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
                display_result(result)
                if result['status']=='DONE':display_registration(result)
                if args.prompt:return 0 if result['status']=='DONE' else 1


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--verbose',action='store_true',help='Show all public trace events and tool arguments')
    parser.add_argument('--mode',choices=['llm-demo','mock'],default='llm-demo')
    parser.add_argument('--output',type=Path,help='Save public result and execution trace as JSON; no API keys')
    parser.add_argument('--model',help='Uses LLM_MODEL or gpt-4.1-mini when omitted')
    parser.add_argument('--prompt',help='One-shot run through automatic demo registration; omit for interactive input')
    try:sys.exit(asyncio.run(run(parser.parse_args())))
    except KeyboardInterrupt:print('\n종료했습니다.')
