"""Verify cross-tenant receipt/account preservation exposed in final review."""
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
    cases=[('old_receipt_deleted',"DELETE FROM transfers WHERE tenant='b' AND key='old';"),
           ('unrelated_balance_changed',"UPDATE accounts SET balance=0 WHERE tenant='b' AND name='source';")]
    results=[]
    for name,body in cases:
        with tempfile.TemporaryDirectory(prefix='lean-preservation-') as directory:
            db=str(Path(directory)/'probe.sqlite');module.init_db(db)
            con=sqlite3.connect(db)
            try:
                con.executemany('INSERT INTO accounts VALUES(?,?,?)',[('a','source',100),('a','target',0),('b','source',77),('b','target',0)])
                con.commit();module.transfer(db,'b','source','target',2,'old')
                con.execute("CREATE TRIGGER preservation_probe AFTER INSERT ON audit WHEN NEW.tenant='a' BEGIN "+body+' END');con.commit()
                def snapshot():
                    return {table:con.execute(f'SELECT * FROM {table} ORDER BY rowid').fetchall()
                            for table in ('accounts','transfers','audit')}
                before=snapshot();error=None;receipt=None
                try:receipt=module.transfer(db,'a','source','target',10,'new')
                except Exception as exception:error=type(exception).__name__
                after=snapshot()
                present=con.execute("SELECT COUNT(*) FROM sqlite_master WHERE type='trigger' AND name='preservation_probe'").fetchone()[0]==1
                result={'case':name,'pass':error is not None and before==after and present,'exception':error,
                        'receipt':receipt,'before':before,'after':after,'trigger_preserved':present}
                if name=='old_receipt_deleted' and error is None:
                    module.transfer(db,'b','source','target',2,'old')
                    result['old_replay_changed_data']=snapshot()!=after
                    result['after_old_replay']=snapshot()
                results.append(result)
            finally:con.close()
    return {'workspace':str(workspace),'source_sha256':hashlib.sha256((workspace/'vault.py').read_bytes()).hexdigest(),
            'issue_count':int(any(not r['pass'] for r in results)),'failed_cases':sum(not r['pass'] for r in results),'cases':results}


if __name__=='__main__':print(json.dumps(probe(Path(sys.argv[1]).resolve()),indent=2))
