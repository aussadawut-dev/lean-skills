"""Check that a row-level RAISE(IGNORE) cannot disable a trigger for later rows."""
from contextlib import closing
import hashlib
import importlib.util
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile

def probe(workspace):
    sys.path.insert(0,str(workspace))
    spec=importlib.util.spec_from_file_location('ignore_scope_vault',workspace/'vault.py')
    vault=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(vault)
    request=dict(tenant='one',source='a',target='b',amount=10,key='k')
    rows=[('one','a',100),('one','b',0),('two','x',777),('two','y',888)]
    tables=('accounts','transfers','audit')
    cases=[]
    for should_fail in (True,False):
        for interface in ('API','CLI'):
            with tempfile.TemporaryDirectory(prefix='lean-ignore-scope-') as directory:
                db=Path(directory)/'probe.sqlite'
                vault.init_db(db)
                with closing(sqlite3.connect(db)) as con, con:
                    con.executemany('INSERT INTO accounts VALUES(?,?,?)',rows)
                    otherwise="RAISE(ABORT, 'must fail on y')" if should_fail else 'NULL'
                    con.execute("CREATE TRIGGER checked BEFORE UPDATE ON accounts WHEN NEW.tenant='two' BEGIN "
                                "SELECT CASE WHEN NEW.name='x' THEN RAISE(IGNORE) ELSE "+otherwise+" END; END")
                    con.execute("CREATE TRIGGER nested AFTER INSERT ON audit BEGIN "
                                "UPDATE accounts SET balance=balance WHERE tenant='two'; END")
                    schema=con.execute('SELECT name,sql FROM sqlite_schema ORDER BY name').fetchall()
                receipt=None;error=None;rejected=False
                if interface=='API':
                    try:receipt=vault.transfer(db,**request)
                    except sqlite3.Error as exc:
                        error=str(exc);rejected='must fail on y' in error
                else:
                    p=subprocess.run([sys.executable,'-B',str(workspace/'app.py'),str(db),
                                      json.dumps(dict(op='transfer',**request))],capture_output=True,text=True,timeout=15)
                    if p.returncode==0 and not p.stderr:receipt=json.loads(p.stdout)
                    else:
                        error=p.stderr.strip()
                        rejected=p.returncode==2 and not p.stdout and 'must fail on y' not in error and 'Traceback' not in error
                with closing(sqlite3.connect(db)) as con:
                    observed=[con.execute(f'SELECT * FROM {table} ORDER BY rowid').fetchall() for table in tables]
                    preserved=con.execute('SELECT name,sql FROM sqlite_schema ORDER BY name').fetchall()==schema
                if should_fail:passed=rejected and observed==[rows,[],[]]
                else:
                    expected=[('one','a',90),('one','b',10),*rows[2:]]
                    row=tuple(request[name] for name in ('tenant','key','source','target','amount'))
                    passed=receipt==request and observed==[expected,[row],[row]]
                cases.append(dict(interface=interface,should_fail=should_fail,error=error,passed=passed and preserved))
    return dict(source_sha256=hashlib.sha256((workspace/'vault.py').read_bytes()).hexdigest(),
                cases=cases,failed_cases=sum(not c['passed'] for c in cases))

if __name__=='__main__':
    print(json.dumps(probe(Path(sys.argv[1]).resolve()),indent=2))
