"""OpenAI document/query embeddings; no local model download or offline cache."""
import math
import os
from functools import lru_cache

from openai import OpenAI
from common import MODEL, DIMENSIONS, mask


@lru_cache(maxsize=1)
def client():
    if not os.getenv('OPENAI_API_KEY'):
        raise ValueError('OpenAI 임베딩에 OPENAI_API_KEY가 필요합니다.')
    return OpenAI(timeout=45.0, max_retries=2)


def embed(texts):
    if not texts or any(not isinstance(text, str) or not text.strip() for text in texts):
        raise ValueError('비어 있지 않은 임베딩 문자열이 필요합니다.')
    if MODEL not in {'text-embedding-3-small', 'text-embedding-3-large'}:
        raise ValueError('EMBEDDING_MODEL은 text-embedding-3-small 또는 text-embedding-3-large여야 합니다.')
    vectors = []
    # At most 16 inputs: even at the API per-input limit, below its request token cap.
    for start in range(0, len(texts), 16):
        batch = [mask(text) for text in texts[start:start + 16]]
        response = client().embeddings.create(model=MODEL, input=batch,
                                              dimensions=DIMENSIONS, encoding_format='float')
        rows = sorted(response.data, key=lambda item: item.index)
        if [row.index for row in rows] != list(range(len(batch))):
            raise ValueError('OpenAI 임베딩 응답 개수 또는 인덱스 불일치')
        for row in rows:
            vector = [float(value) for value in row.embedding]
            if len(vector) != DIMENSIONS or not all(math.isfinite(v) for v in vector) or not any(vector):
                raise ValueError('OpenAI 임베딩 차원·유한성·비영 벡터 검증 실패')
            vectors.append(vector)
    return vectors
