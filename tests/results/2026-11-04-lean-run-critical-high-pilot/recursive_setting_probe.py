"""An audit trigger must observe the application's original recursive_triggers setting."""
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
    spec=importlib.util.spec_from_file_location('recursive_setting_vault',workspace/'vault.py')
    vault=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(vault)
    request=dict(tenant='red',source='a',target='b',amount=10,key='k')
    rows=[('red','a',100),('red','b',0)]
    cases=[]
    for comparison in (0,1):
        for interface in ('API','CLI'):
            with tempfile.TemporaryDirectory(prefix='lean-recursive-setting-') as temporary:
                path=Path(temporary)/'probe.sqlite'
                vault.init_db(path)
                with closing(sqlite3.connect(path)) as con, con:
                    default=con.execute('PRAGMA recursive_triggers').fetchone()[0]
                    con.executemany('INSERT INTO accounts VALUES(?,?,?)',rows)
                    sql=('CREATE TRIGGER audit_guard BEFORE INSERT ON audit WHEN '
                         f'(SELECT recursive_triggers FROM pragma_recursive_triggers)={comparison} '
                         "BEGIN SELECT RAISE(ABORT,'audit storage failure'); END")
                    con.execute(sql)
                should_fail=comparison==default
                receipt=None
                error=None
                rejected=False
                if interface=='API':
                    try:receipt=vault.transfer(path,**request)
                    except sqlite3.Error as exc:
                        error=str(exc)
                        rejected='audit storage failure' in error
                else:
                    p=subprocess.run([sys.executable,'-B',str(workspace/'app.py'),str(path),
                                      json.dumps(dict(op='transfer',**request))],capture_output=True,text=True,timeout=15)
                    if p.returncode==0 and not p.stderr:receipt=json.loads(p.stdout)
                    else:
                        error=p.stderr.strip()
                        try:message=json.loads(p.stderr)
                        except ValueError:message=None
                        rejected=p.returncode==2 and not p.stdout and isinstance(message,dict) and isinstance(message.get('error'),str) and 'audit storage failure' not in error
                with closing(sqlite3.connect(path)) as con:
                    balances=con.execute('SELECT * FROM accounts ORDER BY rowid').fetchall()
                    effects=[con.execute(f'SELECT * FROM {table}').fetchall() for table in ('transfers','audit')]
                    same=con.execute("SELECT sql FROM sqlite_schema WHERE name='audit_guard'").fetchone()==(sql,)
                row=tuple(request[name] for name in ('tenant','key','source','target','amount'))
                good=(rejected and balances==rows and effects==[[],[]] if should_fail else
                      receipt==request and balances==[('red','a',90),('red','b',10)] and effects==[[row],[row]])
                cases.append(dict(interface=interface,comparison=comparison,default=default,should_fail=should_fail,
                                  error=error,passed=good and same))
    return dict(source_sha256=hashlib.sha256((workspace/'vault.py').read_bytes()).hexdigest(),
                cases=cases,failed_cases=sum(not c['passed'] for c in cases))

if __name__=='__main__':
    print(json.dumps(probe(Path(sys.argv[1]).resolve()),indent=2))
