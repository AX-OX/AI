"""pip install chromadb sentence-transformers; run from package root.
Requires a locally available sentence-transformers embedding model with Korean support.
No embeddings are included in the dataset.
"""
import json
from pathlib import Path
import chromadb
from chromadb.utils.embedding_functions import SentenceTransformerEmbeddingFunction
rows=[json.loads(line) for line in Path('rag/chroma_import.jsonl').read_text(encoding='utf8').splitlines() if line.strip()]
client=chromadb.PersistentClient(path='chroma_db')
# Download/model config is user's responsibility; verify model suitability and privacy first.
embedding=SentenceTransformerEmbeddingFunction(model_name='sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2')
col=client.get_or_create_collection(name='ax_navigator_docs_mvp',embedding_function=embedding)
for i in range(0,len(rows),32):
    batch=rows[i:i+32]
    col.upsert(ids=[r['id'] for r in batch],documents=[r['document'] for r in batch],metadatas=[r['metadata'] for r in batch])
print('Chroma documents:',col.count())
# In RAG MCP, scope searches to authenticated company_id; role-based filters are unused.
# Sensitive document labels remain metadata and response PII must be masked.
