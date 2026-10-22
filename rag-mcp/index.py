"""v3 section chunks -> transactional pgvector index replacement."""
from common import mapping, chunks
from pgvector_client import PgVectorStore
from diagnostics import failure_code
import argparse
import json
import sys


def main(store=None, *, if_needed=False):
    docs=mapping()
    store = store or PgVectorStore(write=True)
    if if_needed:
        print('RAG_INDEX_CHECK company/version scoped; validating source and stored chunks.', flush=True)
        result = store.ensure_index(chunks(), docs)
        print(json.dumps(result, ensure_ascii=False), flush=True)
        return result['chunks']
    count=store.replace(chunks(),docs)
    print(f'Indexed {count} chunks in PostgreSQL pgvector.')
    return count


if __name__=='__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--if-needed', action='store_true', help='Skip a valid index; otherwise replace and verify atomically.')
    args = parser.parse_args()
    try:
        main(if_needed=args.if_needed)
    except Exception as exc:
        # Driver/model exceptions may contain credentials or connection strings.
        # Emit only safe categories, never the exception text, headers, or DSNs.
        print(f'RAG_INDEX_FAILED code={failure_code(exc)} error={type(exc).__name__} sqlstate={getattr(exc, "sqlstate", None) or "-"}; check DB access, source metadata, model and corpus settings.',
              file=sys.stderr, flush=True)
        sys.exit(1)
