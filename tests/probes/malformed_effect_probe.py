"""Posthoc public regression: a foreign malformed TEXT no-op must remain valid."""
from pathlib import Path
import hashlib,json,sqlite3,subprocess,sys,tempfile
from contextlib import closing

workspace=Path(sys.argv[1]).resolve()
sys.path.insert(0,str(workspace))
import vault
cases=[]
for mode in ('DELETE','WAL'):
 for interface in ('API','CLI'):
  with tempfile.TemporaryDirectory(prefix='lean-counter-probe-') as tmp:
   path=str(Path(tmp)/'vault.sqlite')
   vault.init_db(path)
   with closing(sqlite3.connect(path)) as con,con:
    con.execute('PRAGMA journal_mode='+mode)
    con.executemany('INSERT INTO accounts VALUES(?,?,?)',[('one','a',100),('one','b',0)])
    con.execute("INSERT INTO accounts VALUES ('other','secret',CAST(x'80ff' AS TEXT))")
    sql="CREATE TRIGGER foreign_noop AFTER INSERT ON audit BEGIN UPDATE accounts SET balance=balance WHERE tenant='other'; END"
    con.execute(sql)
   # Native SQLite accepts the no-op over a malformed TEXT value.
   with closing(sqlite3.connect(path)) as con:
    con.execute('BEGIN')
    con.execute("UPDATE accounts SET balance=90 WHERE tenant='one' AND name='a'")
    con.execute("UPDATE accounts SET balance=10 WHERE tenant='one' AND name='b'")
    con.execute("INSERT INTO audit VALUES ('one','control','a','b',10)")
    con.rollback()
   want=dict(tenant='one',source='a',target='b',amount=10,key='counter')
   exception=None;receipt=None
   if interface=='API':
    try:receipt=vault.transfer(path,**want)
    except Exception as error:exception=type(error).__name__+': '+str(error)
   else:
    p=subprocess.run([sys.executable,'-B',str(workspace/'app.py'),path,json.dumps(dict(op='transfer',**want))],capture_output=True,text=True,timeout=20)
    if p.returncode==0 and not p.stderr:
     try:receipt=json.loads(p.stdout)
     except ValueError:pass
    else:exception=f'CLI exit {p.returncode}: {p.stderr}'
   with closing(sqlite3.connect(path)) as con:
    balances=con.execute("SELECT tenant,name,balance FROM accounts WHERE tenant='one' ORDER BY name").fetchall()
    history=[con.execute('SELECT tenant,key,source,target,amount FROM '+table).fetchall() for table in ('transfers','audit')]
    foreign_unchanged=con.execute("SELECT typeof(balance),hex(balance) FROM accounts WHERE tenant='other'").fetchone()==('text','80FF')
    schema_preserved=con.execute("SELECT sql FROM sqlite_schema WHERE name='foreign_noop'").fetchone()==(sql,)
   correct=(receipt==want and balances==[('one','a',90),('one','b',10)]
            and history==[[('one','counter','a','b',10)]]*2 and schema_preserved and foreign_unchanged)
   cases.append(dict(mode=mode,interface=interface,pass_=correct,error=exception,receipt=receipt,balances=balances,history=history,schema_preserved=schema_preserved))
print(json.dumps(dict(source_sha256=hashlib.sha256((workspace/'vault.py').read_bytes()).hexdigest(),native_control='PASS',cases=cases,failed_cases=sum(not c['pass_'] for c in cases)),indent=2))
