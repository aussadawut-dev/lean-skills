"""A conflict-ignored trigger must not invalidate an otherwise valid transfer."""
import hashlib
import importlib.util
import json
from pathlib import Path
import sqlite3
import sys
import tempfile


def probe(workspace):
    spec=importlib.util.spec_from_file_location('candidate',workspace/'vault.py')
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    with tempfile.TemporaryDirectory(prefix='lean-noop-probe-') as directory:
        db=str(Path(directory)/'probe.sqlite');module.init_db(db);con=sqlite3.connect(db)
        try:
            con.executemany('INSERT INTO accounts VALUES(?,?,?)',[('a','source',100),('a','target',0)])
            con.execute('CREATE TRIGGER harmless_ensure AFTER INSERT ON audit BEGIN INSERT OR IGNORE INTO accounts(tenant,name,balance) VALUES(NEW.tenant,NEW.target,0); END');con.commit()
            error=None;receipt=None
            try:receipt=module.transfer(db,'a','source','target',10,'new')
            except Exception as exception:error=type(exception).__name__
            state={table:con.execute(f'SELECT * FROM {table} ORDER BY rowid').fetchall() for table in ('accounts','transfers','audit')}
            expected=('a','new','source','target',10)
            present=con.execute("SELECT COUNT(*) FROM sqlite_master WHERE type='trigger' AND name='harmless_ensure'").fetchone()[0]==1
            passed=(error is None and receipt==dict(tenant='a',key='new',source='source',target='target',amount=10)
                    and state['accounts']==[('a','source',90),('a','target',10)]
                    and state['transfers']==[expected] and state['audit']==[expected] and present)
        finally:con.close()
    return {'workspace':str(workspace),'source_sha256':hashlib.sha256((workspace/'vault.py').read_bytes()).hexdigest(),
            'issue_count':int(not passed),'failed_cases':int(not passed),'case':'conflict_ignored_noop_insert',
            'pass':passed,'exception':error,'receipt':receipt,'state':state,'trigger_preserved':present}


if __name__=='__main__':print(json.dumps(probe(Path(sys.argv[1]).resolve()),indent=2))
