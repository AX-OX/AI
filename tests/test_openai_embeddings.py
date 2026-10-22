"""Embedding protocol validation without external API calls."""
import json
from pathlib import Path
import sys
from unittest.mock import Mock

import httpx
from openai import OpenAI
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'rag-mcp'))
import common
import embeddings


def api(monkeypatch, respond):
    sdk = OpenAI(api_key='test-only', max_retries=0,
                 http_client=httpx.Client(transport=httpx.MockTransport(respond)))
    monkeypatch.setattr(embeddings, 'client', lambda: sdk)
    return sdk


def test_request_dimensions_mask_batch_order(monkeypatch):
    requests = []
    def respond(request):
        body = json.loads(request.content)
        requests.append(body)
        assert body['model'] == 'text-embedding-3-small'
        assert body['dimensions'] == 384 and body['encoding_format'] == 'float'
        assert all('a@example.com' not in text and '010-1234-5678' not in text for text in body['input'])
        rows = [{'index': i, 'embedding': [float(i + 1)] + [0.] * 383, 'object': 'embedding'}
                for i in reversed(range(len(body['input'])))]
        return httpx.Response(200, json={'object': 'list', 'model': body['model'], 'data': rows,
                                       'usage': {'prompt_tokens': 1, 'total_tokens': 1}})
    with api(monkeypatch, respond):
        vectors = embeddings.embed(['a@example.com 010-1234-5678'] * 17)
    assert [len(r['input']) for r in requests] == [16, 1]
    assert len(vectors) == 17 and vectors[0][0] == 1 and vectors[15][0] == 16
    assert requests[0]['input'][0] == '[EMAIL] [PHONE]'


@pytest.mark.parametrize('rows', [[], [{'index': 0, 'embedding': [1.]*383}],
                                      [{'index': 0, 'embedding': [0.]*384}],
                                      [{'index': 1, 'embedding': [1.]*384}],
                                      [{'index': 0, 'embedding': [float('nan')]*384}]])
def test_malformed_response_rejected(monkeypatch, rows):
    from types import SimpleNamespace
    sdk = Mock()
    sdk.embeddings.create.return_value.data = [SimpleNamespace(**r) for r in rows]
    monkeypatch.setattr(embeddings, 'client', lambda: sdk)
    with pytest.raises(ValueError): embeddings.embed(['업무 문서'])


@pytest.mark.parametrize('texts', [[], [''], ['  '], [None]])
def test_empty_inputs_never_call_api(monkeypatch, texts):
    factory = Mock()
    monkeypatch.setattr(embeddings, 'client', factory)
    with pytest.raises(ValueError): embeddings.embed(texts)
    factory.assert_not_called()


def test_api_error_propagates(monkeypatch):
    with api(monkeypatch, lambda req: httpx.Response(401, json={'error': {'message':'test unauthorized','type':'invalid_request_error'}})):
        from openai import AuthenticationError
        with pytest.raises(AuthenticationError): embeddings.embed(['업무 문서'])


def test_corpus_and_service_use_same_openai_model():
    rows = common.chunks()
    assert common.MODEL == 'text-embedding-3-small'
    assert common.INDEX_VERSION == 'ax-v3-openai-small-384-v1'
    assert len(rows) == 34
    assert {r['metadata']['embedding_model'] for r in rows} == {common.MODEL}
    assert common.mapping()
