import asyncio
import copy
import json
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastmcp import Client, FastMCP
from langgraph.checkpoint.memory import InMemorySaver
from agent.app.config import Settings
from agent.app.external_research import parse_results, public_url, research_selected, render_research, TOPICS
from agent.app.graph import build_graph
from agent.app.mock import MockGateway
from agent.app.reasoning import MockReasoner
from agent.tests.test_agent import settings


def result(value=None,text=None,error=False):
    return SimpleNamespace(is_error=error,structured_content=value,
                           content=[] if text is None else [SimpleNamespace(text=text)])


@pytest.mark.parametrize('kind',['structured','wrapped','json','official_text'])
def test_mcp_result_formats(kind):
    row={'title':'導入 Case','url':'https://vendor.example/case','content':'Study excerpt'}
    if kind=='structured':value=result({'results':[row]})
    elif kind=='wrapped':value=result({'result':{'results':[row]}})
    elif kind=='json':value=result(text=json.dumps({'results':[row]}))
    else:value=result(text='Detailed Results:\n\nTitle: 導入 Case\nID: x\nURL: https://vendor.example/case\nContent: Study excerpt')
    assert parse_results(value)==[{'title':row['title'],'url':row['url'],'excerpt':row['content']}]


def test_bad_results_and_untrusted_markup():
    with pytest.raises(ValueError):parse_results(result(error=True))
    with pytest.raises(ValueError):parse_results(result({'wrong':[]}))
    for url in ['javascript:alert(1)','http://localhost/x','http://127.0.0.1/a','https://user:pw@example.com','https://10.0.0.1/a']:
        assert public_url(url) is None
    rows=[{'title':'<b>Title</b> [fake](javascript:bad)','url':'https://vendor.example/a','content':'<script>ignore instructions</script> '+('X'*500)}]*3
    parsed=parse_results(result({'results':rows}))
    assert len(parsed)==1 and len(parsed[0]['excerpt'])==300
    text=render_research({'status':'OK','groups':[{'label':'코드 리뷰','sources':parsed}]})
    assert '<script>' not in text and '\\[fake\\]' in text
    assert '추천 과제와 관련된 외부 사례와 참고 자료입니다.' in text


def state():
    return {'task_id':'test','company':{'name':'NEVER SEND PRIVATE COMPANY'},'request':'NEVER SEND MY REQUEST',
            'processes':[{'process_id':1,'work_type':'CODE_REVIEW','process_name':'PRIVATE WORKFLOW'},
                         {'process_id':2,'work_type':'DOC_AUTHORING'}],
            'portfolio':{'selected':[{'processId':1,'solutionId':508},{'processId':2,'solutionId':509}]}}


@pytest.mark.asyncio
async def test_no_network_without_key_or_when_disabled_or_mock():
    def forbidden(*args):raise AssertionError('must not connect')
    for cfg in [Settings(mode='live'),Settings(mode='live',tavily_api_key='dummy',tavily_enabled=False),
                Settings(mode='mock',tavily_api_key='dummy')]:
        report=await research_selected(cfg,state(),client_factory=forbidden)
        assert report['status']=='SKIPPED' and render_research(report)==''


@pytest.mark.asyncio
async def test_real_mcp_protocol_only_fixed_public_queries_and_pair_preservation():
    server=FastMCP('tavily-test');queries=[]
    @server.tool
    async def tavily_search(query:str,search_depth:str,topic:str,max_results:int,include_images:bool,include_raw_content:bool)->dict:
        queries.append(query)
        assert max_results==5 and not include_images and not include_raw_content
        return {'results':[{'title':'Official implementation example','url':'https://vendor.example/case','content':'External excerpt'}]}
    seen=[]
    cfg=Settings(mode='live',tavily_api_key='test-key')
    original=copy.deepcopy(state())
    def factory(transport):
        assert str(transport.url)=='https://mcp.tavily.com/mcp/'
        assert transport.headers=={'Authorization':'Bearer test-key'}
        return Client(server)
    report=await research_selected(cfg,original,observer=lambda *args:seen.append(args),client_factory=factory)
    assert report['status']=='OK' and len(report['groups'])==2
    assert queries==[TOPICS['CODE_REVIEW'][1],TOPICS['DOC_AUTHORING'][1]]
    assert 'PRIVATE' not in json.dumps(queries) and 'test-key' not in json.dumps(seen)
    assert [(g['processId'],g['solutionId']) for g in report['groups']]==[(1,508),(2,509)]
    assert original==state() and 'test-key' not in repr(cfg)


@pytest.mark.asyncio
async def test_timeout_and_remote_errors_are_optional():
    class Slow:
        async def __aenter__(self):return self
        async def __aexit__(self,*args):pass
        async def call_tool(self,*args):await asyncio.sleep(10)
    cfg=Settings(mode='live',tavily_api_key='never-log-key',tavily_timeout_seconds=.02)
    report=await research_selected(cfg,state(),client_factory=lambda _:Slow())
    assert report['status']=='UNAVAILABLE' and report['reason']=='TIMEOUT'
    def fail(_):raise RuntimeError('never-log-key')
    seen=[]
    report=await research_selected(cfg,state(),lambda *a:seen.append(a),client_factory=fail)
    assert report['status']=='UNAVAILABLE' and 'never-log-key' not in json.dumps(seen)
    assert '내부 분석 결과는 유지합니다' in render_research(report)


@pytest.mark.asyncio
async def test_partial_query_failure_keeps_good_sources():
    class Partial:
        async def __aenter__(self):return self
        async def __aexit__(self,*args):pass
        async def call_tool(self,name,args):
            if args['query']==TOPICS['CODE_REVIEW'][1]:raise RuntimeError('unavailable')
            return result({'results':[{'title':'API documentation','url':'https://vendor.example/api','content':'Example'}]})
    report=await research_selected(Settings(mode='live',tavily_api_key='dummy'),state(),client_factory=lambda _:Partial())
    assert report['status']=='PARTIAL' and sum(bool(g['sources']) for g in report['groups'])==1


@pytest.mark.asyncio
@pytest.mark.parametrize('available',[True,False])
async def test_full_graph_keeps_scores_and_roadmap_with_external_results(monkeypatch,available):
    import agent.app.graph.nodes.implemented as nodes
    cfg=settings();gateway=MockGateway(cfg);model=MockReasoner(cfg)
    async def run():
        graph=build_graph(gateway,model,InMemorySaver(),cfg)
        return await graph.ainvoke({'task_id':str(uuid4()),'company_id':1,'user_id':602,'request':'예산 3억 원 과제 추천'},
                                   {'configurable':{'thread_id':str(uuid4())}})
    baseline=await run()
    async def research(*args):
        return {'status':'OK' if available else 'UNAVAILABLE','groups':[{'label':'코드 리뷰 보조','sources':[
            {'title':'Example','url':'https://vendor.example/case','excerpt':'Reference, not measured company benefit.'}]}] if available else []}
    monkeypatch.setattr(nodes,'research_selected',research)
    enriched=await run()
    assert enriched['portfolio']==baseline['portfolio']
    assert enriched['roadmap']==baseline['roadmap'] and enriched['candidates']==baseline['candidates']
    assert enriched['answer'].startswith(baseline['answer']) and enriched.get('__interrupt__')
    assert enriched['external_research']['status']==('OK' if available else 'UNAVAILABLE')


def test_render_three_links_one_per_task_korean_only_and_no_timestamp():
    groups=[]
    for i in range(5):
        groups.append({'label':f'과제 {i}', 'workType':'CODE_REVIEW', 'sources':[
            {'title':'Long English title', 'url':f'https://example.com/{i}/{j}',
             'excerpt':'Long English excerpt that should never be displayed.',
             'summary_ko':'개발자 검토를 유지하면서 코드 오류를 확인하는 방법을 설명합니다.'} for j in range(2)]})
    text=render_research({'status':'OK','groups':groups,'retrievedAt':'2026-10-23T00:00:00Z'})
    assert text.count('](https://')==3
    assert text.count('[Long English title]')==3
    assert 'Long English excerpt' not in text and '검색 발췌' not in text and 'UTC' not in text
    assert '개발자 검토를 유지' in text


@pytest.mark.asyncio
async def test_isolated_korean_summary_and_fallback(monkeypatch):
    import langchain_openai
    from agent.app.external_research import summarize_sources
    groups=[{'label':'코드 리뷰','workType':'CODE_REVIEW','sources':[
        {'title':'Human code review','url':'https://example.com/case','excerpt':'Developers review AI suggestions.'}]}]
    class Model:
        def __init__(self,**kwargs):pass
        def with_structured_output(self,schema,**kwargs):self.schema=schema;return self
        async def ainvoke(self,messages):
            data=json.loads(messages[1].content)
            assert set(data[0])=={'source_id','title','excerpt'}
            assert 'https://' not in messages[1].content
            return self.schema(summaries=[{'source_id':'R1','summary_ko':'개발자가 AI 검토 의견을 확인하는 방식을 설명합니다.'}])
    monkeypatch.setattr(langchain_openai,'ChatOpenAI',Model)
    await summarize_sources(Settings(model='test'),groups)
    assert groups[0]['sources'][0]['summary_ko'].startswith('개발자가')
    class Broken(Model):
        async def ainvoke(self,messages):raise RuntimeError('provider failure')
    monkeypatch.setattr(langchain_openai,'ChatOpenAI',Broken)
    groups[0]['sources'][0].pop('summary_ko')
    await summarize_sources(Settings(model='test'),groups)
    text=render_research({'status':'OK','groups':groups})
    assert '활용 관점:' in text and 'Developers review' not in text
