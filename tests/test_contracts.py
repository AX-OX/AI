import asyncio
import importlib.util
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
import httpx
from fastmcp.exceptions import ToolError

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'rag-mcp'))
sys.path.insert(0,str(ROOT/'business-mcp'))

def load(name,path):
    spec=importlib.util.spec_from_file_location(name,path)
    mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(mod);return mod

rag=load('rag_contracts',ROOT/'rag-mcp/server.py')
common=sys.modules['common'];common.CORPUS=ROOT/'AX_Navigator_AI_MVP_v3/rag'
business=load('business_contracts',ROOT/'business-mcp/server.py')
indexer=load('index_contracts',ROOT/'rag-mcp/index.py')

def fn(value): return getattr(value,'fn',value)

class ContractTests(unittest.TestCase):
    def test_corpus_mapping(self):
        docs=common.mapping()
        rows=[json.loads(x) for x in (common.CORPUS/'pgvector_import.jsonl').read_text().splitlines()]
        self.assertEqual((len(docs),len(rows)),(8,34))
        self.assertEqual(len({r['id'] for r in rows}),34)
        self.assertEqual(docs['401']['related_process_ids'],[201,202,203])
        self.assertEqual(docs['403']['related_process_ids'],[207,208,209])
        self.assertEqual(docs['404']['related_process_ids'],[])
        self.assertTrue(all('allowed_roles' not in r['metadata'] for r in rows))
    def test_indexer_uses_atomic_store(self):
        class Store:
            def replace(self,rows,docs):
                self.rows=rows;return len(rows)
        store=Store();self.assertEqual(indexer.main(store),34)
    def test_resource_scope_and_mask(self):
        self.assertIn('인사',fn(rag.get_document)('401'))
        with self.assertRaises(ValueError):fn(rag.get_document)('../401')
        self.assertEqual(common.mask('a@example.com 010-1234-5678'),'[EMAIL] [PHONE]')
    def test_business_routes(self):
        calls=[]
        async def fake(method,path,**kwargs):calls.append((method,path,kwargs));return {}
        with patch.object(business,'call',fake):
            asyncio.run(fn(business.calculate_ax_roi)(201,501))
            asyncio.run(fn(business.optimize_ax_portfolio)(1,[{'process_id':201,'solution_id':501}]))
        self.assertEqual(calls[0],('POST','/ax/roi',{'body':{'processId':201,'solutionId':501}}))
        self.assertEqual(calls[1][2]['body']['candidates'],[{'processId':201,'solutionId':501}])
    def test_bad_candidate(self):
        with self.assertRaises(ToolError):asyncio.run(fn(business.optimize_ax_portfolio)(1,[{'bad':1}]))
    def test_spring_headers_and_error(self):
        client=sys.modules['spring_client'];requests=[]
        original=httpx.AsyncClient
        def responder(req):requests.append(req);return httpx.Response(404,json={'code':'NOT_FOUND','hint':{'validIds':[1]}})
        def factory(**kwargs):return original(transport=httpx.MockTransport(responder),**kwargs)
        with patch.dict('os.environ',{'INTERNAL_TOKEN':'test-token'}),patch.object(client.httpx,'AsyncClient',factory):
            with self.assertRaisesRegex(ToolError,'validIds'):asyncio.run(client.call('GET','/solutions'))
        self.assertEqual(requests[0].headers['x-internal-token'],'test-token')

if __name__=='__main__':unittest.main()
