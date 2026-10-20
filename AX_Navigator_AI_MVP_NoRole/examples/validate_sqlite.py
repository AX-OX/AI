import sqlite3, json
from pathlib import Path
for file in ['ax_navigator_input.sqlite','ax_navigator_demo_approved.sqlite']:
    cx=sqlite3.connect(Path(__file__).resolve().parents[1]/file)
    cx.execute('PRAGMA foreign_keys=ON')
    tables=[r[0] for r in cx.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")]
    assert len(tables)==14, tables
    assert not cx.execute('PRAGMA foreign_key_check').fetchall()
    assert 'role' not in [r[1] for r in cx.execute('PRAGMA table_info(users)')]
    for table in ['companies','departments','business_processes','process_metrics','documents','ai_solution_catalog','users','ai_tasks','ax_projects']:
        print(file,table,cx.execute(f'SELECT COUNT(*) FROM {table}').fetchone()[0])
    cx.close()
print('OK')
