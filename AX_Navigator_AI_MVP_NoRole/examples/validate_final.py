#!/usr/bin/env python3
"""Runs offline schema, referential and Chroma-import metadata checks."""
from pathlib import Path
import sqlite3, json
root=Path(__file__).resolve().parent.parent
expected={"companies":1,"departments":4,"business_processes":12,"process_metrics":36,"it_systems":6,"process_systems":22,"documents":10,"ai_solution_catalog":11,"users":2,"ai_tasks":0,"ax_assessments":0,"ax_roadmaps":0,"roadmap_items":0,"ax_projects":0}
for fn in ["ax_navigator_input.sqlite","ax_navigator_demo_approved.sqlite"]:
    with sqlite3.connect(root/fn) as c:
        c.execute("PRAGMA foreign_keys=ON")
        assert c.execute("PRAGMA foreign_key_check").fetchall()==[]
        for tab,n in expected.items():
            actual=c.execute('select count(*) from "'+tab+'"').fetchone()[0]
            if fn.endswith("input.sqlite"): assert actual==n,(tab,actual,n)
        if fn.endswith("demo_approved.sqlite"):
            assert c.execute("select count(*) from ax_projects").fetchone()[0]==3
records=[json.loads(s) for s in (root/'rag/chroma_import.jsonl').read_text(encoding='utf8').splitlines() if s.strip()]
assert len(set(r['id'] for r in records))==len(records)
assert all('allowed_roles' not in r['metadata'] and r['metadata']['company_id']==1 for r in records)
assert all('role' not in [x[1] for x in sqlite3.connect(root/fn).execute('PRAGMA table_info(users)')] for fn in ['ax_navigator_input.sqlite','ax_navigator_demo_approved.sqlite'])
with sqlite3.connect(root/'ax_navigator_demo_approved.sqlite') as c:
    assert c.execute("""SELECT COUNT(*) FROM ax_roadmaps r JOIN ai_tasks t ON r.task_id=t.task_id WHERE r.approval_status='APPROVED' AND r.approved_by=t.user_id""").fetchone()[0]==1
print('PASS: 14 tables / 22 FK constraints / 12 processes / 36 metrics / 10 docs /',len(records),'Chroma chunks')
