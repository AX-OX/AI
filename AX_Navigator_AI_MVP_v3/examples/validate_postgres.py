#!/usr/bin/env python3
"""Destructive integration validation: DATABASE_URL MUST target a fresh disposable DB.
Creates synthetic demo tables and two test roles; uses real pinned 384-d embeddings.
Requires a setup superuser, psycopg and sentence-transformers. No production fallback.
"""
import json
import os
import sqlite3
from decimal import Decimal
from pathlib import Path
from tempfile import TemporaryDirectory
import shutil
import psycopg
from psycopg.conninfo import conninfo_to_dict,make_conninfo
from psycopg.rows import dict_row
from compute_ax import compute
from validate_final import data_artifact_hashes
from pgvector_ingest import PgVectorIndex,ROOT,load_corpus,vector_literal,corpus_hash


def main():
    dsn=os.environ['DATABASE_URL']
    expected=compute()
    output={}
    def execute_file(conn,path):
        # Files contain explicit BEGIN/COMMIT. Setup connection runs autocommit.
        conn.execute((ROOT/path).read_text(),prepare=False)
    with psycopg.connect(dsn,autocommit=True,row_factory=dict_row) as setup:
        assert setup.execute("SELECT count(*) n FROM pg_tables WHERE schemaname='public'").fetchone()['n']==0,'Fresh disposable DB required'
        execute_file(setup,'sql/00_schema_postgres16.sql')
        execute_file(setup,'sql/01_seed_input_postgres.sql')
        execute_file(setup,'sql/03_pgvector.sql')
        execute_file(setup,'fixtures/02_demo_waiting_approval.sql')
        task=setup.execute('SELECT user_id,status,result FROM ai_tasks').fetchone()
        assert task['user_id']==602 and task['status']=='WAITING_APPROVAL'
        assert task['result']['candidates']==expected['per_candidate']
        assert setup.execute('SELECT count(*) n FROM ax_roadmaps').fetchone()['n']==0
        execute_file(setup,'fixtures/03_demo_after_requester_approval.sql')
        assert setup.execute('SELECT status FROM ai_tasks').fetchone()['status']=='DONE'
        tables=setup.execute("SELECT count(*) n FROM pg_tables WHERE schemaname='public'").fetchone()['n']
        fks=setup.execute("SELECT count(*) n FROM pg_constraint WHERE contype='f' AND connamespace='public'::regnamespace").fetchone()['n']
        assert tables==16 and fks==27
        # Compare REAL PostgreSQL execution of fixture SQL against the independently loaded SQLite preview.
        with sqlite3.connect(ROOT/'ax_navigator_demo_approved.sqlite') as preview:
            preview.row_factory=sqlite3.Row
            items=[dict(r) for r in preview.execute('SELECT * FROM roadmap_items ORDER BY item_id')]
        actual=setup.execute('SELECT * FROM roadmap_items ORDER BY item_id').fetchall()
        for pg,sq in zip(actual,items,strict=True):
            for key in pg:
                if key=='evidence': assert pg[key]==json.loads(sq[key])
                elif isinstance(pg[key],Decimal): assert pg[key]==Decimal(str(sq[key])),key
                else: assert pg[key]==sq[key],key
        assert {r['solution_id'] for r in actual}==set(expected['selected_solution_ids'])
        for table,col in [('ai_solution_catalog','solution_id'),('roadmap_items','item_id'),('ax_projects','project_id')]:
            nextval=setup.execute("SELECT nextval(pg_get_serial_sequence(%s,%s)) n",(table,col)).fetchone()['n']
            maximum=setup.execute(f'SELECT max({col}) n FROM {table}').fetchone()['n']
            assert nextval>maximum
        setup.execute('CREATE ROLE ax_v3_test_reader LOGIN')
        setup.execute('CREATE ROLE ax_v3_test_indexer LOGIN')
        setup.execute('GRANT USAGE ON SCHEMA public TO ax_v3_test_reader,ax_v3_test_indexer')
        setup.execute('GRANT SELECT ON rag_indexes,rag_document_chunks TO ax_v3_test_reader,ax_v3_test_indexer')
        setup.execute('GRANT SELECT(document_id,company_id,process_id,title,doc_type,access_level,version) ON documents TO ax_v3_test_reader,ax_v3_test_indexer')
        setup.execute('GRANT INSERT,UPDATE,DELETE ON rag_indexes,rag_document_chunks TO ax_v3_test_indexer')
        parameters=conninfo_to_dict(dsn)
        writer_dsn=make_conninfo(**{**parameters,'user':'ax_v3_test_indexer'})
        reader_dsn=make_conninfo(**{**parameters,'user':'ax_v3_test_reader'})
        store=PgVectorIndex(dsn=writer_dsn,write=True)
        count=store.replace()
        assert count==len(load_corpus()[0])
        vectors=store.embed(['코드 리뷰 보조의 선행 과제와 승인 절차'])
        # Reuse the same loaded model, not random or stub embeddings, in search and re-ingest.
        search=PgVectorIndex(dsn=reader_dsn,embedder=store.embed)
        rows=search.search('코드 리뷰 보조의 선행 과제와 승인 절차',doc_type='MANUAL',process_id=208,top_k=10)
        assert rows and all(r['document_id']==403 and r['doc_type']=='MANUAL' for r in rows)
        assert [r['score'] for r in rows]==sorted(r['score'] for r in rows)
        hr=search.search('사내 규정 문의',process_id=201,top_k=50)
        assert hr and all(r['document_id'] not in (402,403) for r in hr)
        assert any(r['document_id'] in (404,405,406,407,408) for r in hr),'Common documents must remain searchable'
        rerun=store.replace()
        stats=setup.execute('''SELECT (SELECT chunk_count FROM rag_indexes WHERE company_id=1 AND index_version=%s) registry,
            count(*) actual,min(vector_dims(embedding)) dimensions_min,max(vector_dims(embedding)) dimensions_max FROM rag_document_chunks WHERE company_id=1 AND index_version=%s''',(store.version,store.version)).fetchone()
        assert stats==dict(registry=count,actual=count,dimensions_min=384,dimensions_max=384) and rerun==count
        def must_raise(call,exception=ValueError):
            try: call()
            except exception: return True
            raise AssertionError('Expected failure did not occur')
        assert must_raise(lambda:vector_literal([0]*384))
        assert must_raise(lambda:vector_literal([float('nan')]*384))
        assert must_raise(lambda:vector_literal([1]*383))
        assert must_raise(lambda:PgVectorIndex(dsn=reader_dsn,embedder=store.embed,index_version='missing').search('근거'))
        for field in ('embedding_model','embedding_revision','corpus_hash'):
            original=setup.execute(f'SELECT {field} FROM rag_indexes WHERE company_id=1 AND index_version=%s',(store.version,)).fetchone()[field]
            setup.execute(f'UPDATE rag_indexes SET {field}=%s WHERE company_id=1 AND index_version=%s',('invalid-for-test',store.version))
            assert must_raise(lambda:search.search('근거'))
            setup.execute(f'UPDATE rag_indexes SET {field}=%s WHERE company_id=1 AND index_version=%s',(original,store.version))
        with TemporaryDirectory() as temp:
            changed=Path(temp)
            shutil.copytree(ROOT/'rag',changed/'rag')
            with (changed/'rag/pgvector_import.jsonl').open('a') as f: f.write('\n')
            assert must_raise(lambda:PgVectorIndex(root=changed,dsn=reader_dsn,embedder=store.embed).search('근거'))
        # Force failure AFTER delete/upsert, verifying transactional rollback preserves the previous index.
        setup.execute("CREATE FUNCTION fail_v3_chunk() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN RAISE EXCEPTION 'intentional rollback check'; END $$")
        setup.execute('CREATE TRIGGER fail_v3_chunk BEFORE INSERT ON rag_document_chunks FOR EACH ROW EXECUTE FUNCTION fail_v3_chunk()')
        assert must_raise(store.replace,psycopg.errors.RaiseException)
        setup.execute('DROP TRIGGER fail_v3_chunk ON rag_document_chunks')
        setup.execute('DROP FUNCTION fail_v3_chunk()')
        assert setup.execute('SELECT count(*) n FROM rag_document_chunks').fetchone()['n']==count
        assert search.search('코드 리뷰',doc_type='MANUAL',process_id=208)
        for role_dsn in (reader_dsn,writer_dsn):
            def forbidden():
                with psycopg.connect(role_dsn) as conn: conn.execute('UPDATE companies SET employee_count=201 WHERE company_id=1')
            assert must_raise(forbidden,psycopg.errors.InsufficientPrivilege)
        def reader_write():
            with psycopg.connect(reader_dsn) as conn: conn.execute('DELETE FROM rag_document_chunks')
        assert must_raise(reader_write,psycopg.errors.InsufficientPrivilege)
        # Second company's document and index exercise actual SQL company filtering.
        setup.execute("INSERT INTO companies(company_id,company_name,industry,employee_count,ax_budget_krw) OVERRIDING SYSTEM VALUE VALUES(2,'가상 분리 테스트 기업','TEST',1,0)")
        setup.execute("INSERT INTO documents(document_id,company_id,title,doc_type,file_uri,access_level,version) OVERRIDING SYSTEM VALUE VALUES(499,2,'가상 분리 테스트 문서','MANUAL','docs://499','INTERNAL','v3')")
        setup.execute('INSERT INTO rag_indexes(company_id,index_version,embedding_model,embedding_revision,corpus_hash,chunk_count) VALUES(2,%s,%s,%s,%s,1)',(store.version,store.model,store.revision,corpus_hash(ROOT)))
        setup.execute('''INSERT INTO rag_document_chunks(company_id,index_version,chunk_id,document_id,title,doc_type,section,page,chunk_index,related_process_ids,content,metadata,embedding)
            SELECT 2,index_version,'company-2-chunk',499,'가상 분리 테스트 문서',doc_type,section,page,chunk_index,ARRAY[]::bigint[],content,metadata,embedding FROM rag_document_chunks WHERE company_id=1 LIMIT 1''')
        assert all(r['document_id']!=499 for r in search.search('코드 리뷰',top_k=50))
        second=PgVectorIndex(dsn=reader_dsn,embedder=store.embed,company_id=2)
        assert [r['document_id'] for r in second.search('근거',top_k=50)]==[499]
        setup.execute('DELETE FROM rag_document_chunks WHERE company_id=2')
        setup.execute('DELETE FROM rag_indexes WHERE company_id=2')
        setup.execute('DELETE FROM documents WHERE document_id=499')
        setup.execute('DELETE FROM companies WHERE company_id=2')
        version=setup.execute('SHOW server_version').fetchone()['server_version']
        extension=setup.execute("SELECT extversion FROM pg_extension WHERE extname='vector'").fetchone()['extversion']
        counts={r['tablename']:setup.execute('SELECT count(*) n FROM '+r['tablename']).fetchone()['n'] for r in setup.execute("SELECT tablename FROM pg_tables WHERE schemaname='public'").fetchall()}
        output=dict(status='passed',data_artifact_sha256=data_artifact_hashes(ROOT),postgresql_version=version,pgvector_version=extension,postgresql_16_tested=version.startswith('16.'),
            note='PostgreSQL 16 is not installed locally; actual SQL/pgvector execution verified on PostgreSQL 17. Target-16 execution remains unverified.' if not version.startswith('16.') else 'Target PostgreSQL 16 verified.',
            database_scope='fresh disposable local database only; deployment database untouched',tables=tables,foreign_keys=fks,row_counts=counts,
            waiting_approval_snapshot=True,fixture_sql_vs_sqlite_and_eval=True,identity_sequences=True,
            actual_embedding_model=store.model,actual_embedding_revision=store.revision,actual_embedding_dimensions=384,
            indexed_chunks=count,repeat_ingest_no_duplicates=True,company_filter=True,doc_type_filter=True,process_filter_and_common_documents=True,
            cosine_distance_ascending=True,model_revision_and_corpus_mismatch_rejected=True,invalid_vectors_rejected=True,
            failed_ingest_rollback_preserves_index=True,reader_cannot_write=True,indexer_cannot_write_business_data=True,
            sample_search=[dict(document_id=r['document_id'],section=r['section'],cosine_distance=r['score']) for r in rows])
    (ROOT/'eval/postgres_validation.json').write_text(json.dumps(output,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps(output,ensure_ascii=False,indent=2))

if __name__=='__main__': main()
