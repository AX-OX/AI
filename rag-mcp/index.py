"""v3 section chunks -> transactional pgvector index replacement."""
from common import mapping, chunks
from pgvector_client import PgVectorStore


def main(store=None):
    docs=mapping()
    count=(store or PgVectorStore(write=True)).replace(chunks(),docs)
    print(f'Indexed {count} chunks in PostgreSQL pgvector.')
    return count


if __name__=='__main__': main()
