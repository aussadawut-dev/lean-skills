"""Post-discovery coordinator check: silent SQLite writes must not commit.

This is a supplemental issue category discovered in independent review, not a
retroactive change to the frozen nine-category critical grader.
"""
import importlib
import json
from pathlib import Path
import sqlite3
import sys
import tempfile

sys.path.insert(0, str(Path(sys.argv[1]).resolve()))
vault = importlib.import_module('vault')


def snapshot(path):
    with sqlite3.connect(path) as con:
        result = {table: con.execute('SELECT * FROM '+table+' ORDER BY rowid').fetchall()
                  for table in ('accounts', 'transfers', 'audit')}
        result['triggers'] = con.execute("SELECT name, sql FROM sqlite_master WHERE type='trigger' ORDER BY name").fetchall()
        return result


triggers = {
    'debit': "BEFORE UPDATE OF balance ON accounts WHEN OLD.name='a'",
    'credit': "BEFORE UPDATE OF balance ON accounts WHEN OLD.name='b'",
    'receipt': 'BEFORE INSERT ON transfers',
    'audit': 'BEFORE INSERT ON audit',
}
checks = []
for name, trigger in triggers.items():
    with tempfile.TemporaryDirectory(prefix='lean-write-effects-') as scratch:
        path = Path(scratch)/'db.sqlite'
        vault.init_db(path)
        with sqlite3.connect(path) as con:
            con.executemany('INSERT INTO accounts VALUES (?,?,?)', [('one','a',100),('one','b',0)])
            con.execute('CREATE TRIGGER suppress_write '+trigger+' BEGIN SELECT RAISE(IGNORE); END')
        before = snapshot(path)
        error = None
        returned = None
        try:
            returned = vault.transfer(path,'one','a','b',10,'k')
        except Exception as exc:
            error = type(exc).__name__+': '+str(exc)
        after = snapshot(path)
        checks.append({'probe':name, 'status':'PASS' if error and before==after else 'FAIL',
                       'error':error, 'returned':returned, 'before':before, 'after':after})
print(json.dumps({'category':'unchecked SQLite write effects', 'checks':checks,
                  'issue_count':int(any(check['status']!='PASS' for check in checks))},indent=2))
