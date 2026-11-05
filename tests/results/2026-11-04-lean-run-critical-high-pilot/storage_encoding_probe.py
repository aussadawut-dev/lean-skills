"""Verify a valid transfer and preserved unrelated rows in each SQLite TEXT encoding."""
import hashlib
import importlib.util
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
from contextlib import closing

def probe(workspace):
    sys.path.insert(0, str(workspace))
    spec = importlib.util.spec_from_file_location('encoding_vault', workspace/'vault.py')
    vault = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(vault)
    rows = [('one','α',100),('one','β',0),('two','private',777)]
    request = dict(tenant='one',source='α',target='β',amount=10,key='κ')
    cases = []
    for encoding in ('UTF-8','UTF-16le','UTF-16be'):
        for interface in ('API','CLI'):
            with tempfile.TemporaryDirectory(prefix='lean-encoding-') as temporary:
                path=Path(temporary)/'db.sqlite'
                with closing(sqlite3.connect(path)) as con:
                    con.execute('PRAGMA encoding='+json.dumps(encoding))
                    con.execute('CREATE TABLE encoding_seed(x)')
                    con.execute('DROP TABLE encoding_seed')
                vault.init_db(path)
                with closing(sqlite3.connect(path)) as con, con:
                    actual=con.execute('PRAGMA encoding').fetchone()[0]
                    assert actual.lower()==encoding.lower(), (actual, encoding)
                    con.executemany('INSERT INTO accounts VALUES(?,?,?)',rows)
                    con.execute("CREATE TRIGGER benign AFTER INSERT ON audit BEGIN SELECT 1; END")
                error = None
                try:
                    if interface=='API':
                        receipt=vault.transfer(path,**request)
                    else:
                        p=subprocess.run([sys.executable,'-B',str(workspace/'app.py'),str(path),
                                          json.dumps(dict(op='transfer',**request))],
                                         capture_output=True,text=True,timeout=15)
                        receipt=json.loads(p.stdout) if p.returncode==0 and not p.stderr else None
                        if receipt is None:error=f'CLI exit {p.returncode}: {p.stderr.strip()}'
                except Exception as exc:
                    receipt=None
                    error=type(exc).__name__+': '+str(exc)
                with closing(sqlite3.connect(path)) as con:
                    accounts=con.execute('SELECT tenant,name,balance FROM accounts ORDER BY rowid').fetchall()
                    counts=[con.execute(f'SELECT COUNT(*) FROM {table}').fetchone()[0] for table in ('transfers','audit')]
                    trigger=con.execute("SELECT sql FROM sqlite_schema WHERE name='benign'").fetchone()
                expected=[('one','α',90),('one','β',10),rows[-1]]
                cases.append(dict(encoding=encoding,actual=actual,interface=interface,error=error,
                                  passed=actual.lower()==encoding.lower() and receipt==request
                                         and accounts==expected and counts==[1,1]
                                         and trigger==('CREATE TRIGGER benign AFTER INSERT ON audit BEGIN SELECT 1; END',)))
    return dict(source_sha256=hashlib.sha256((workspace/'vault.py').read_bytes()).hexdigest(),
                cases=cases,failed_cases=sum(not c['passed'] for c in cases))

if __name__=='__main__':
    print(json.dumps(probe(Path(sys.argv[1]).resolve()),indent=2))
