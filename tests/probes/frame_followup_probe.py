"""Uniform checks for contract findings discovered in the first Critical review.

These are additional diagnostics; the initially frozen twelve cases are retained.
"""
from collections import Counter
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
    cases=[
        ('identical_account_replacement',True,None,"INSERT OR REPLACE INTO accounts(rowid,tenant,name,balance) VALUES(3,'two','private',456);"),
        ('identical_receipt_replacement',True,None,"INSERT OR REPLACE INTO transfers(rowid,tenant,key,source,target,amount) VALUES(1,'two','old','private','spare',7);"),
        ('identical_audit_replacement',True,None,"INSERT OR REPLACE INTO audit(rowid,tenant,key,source,target,amount) VALUES(1,'two','old','private','spare',7);"),
        ('replacement_rowid_swap',True,None,"INSERT OR REPLACE INTO accounts(rowid,tenant,name,balance) VALUES(4,'two','private',456); INSERT OR REPLACE INTO accounts(rowid,tenant,name,balance) VALUES(3,'two','spare',789);"),
        ('unique_account_victim',False,'CREATE UNIQUE INDEX existing_balance_index ON accounts(balance)',"INSERT OR REPLACE INTO accounts VALUES('one','scratch',456); DELETE FROM accounts WHERE tenant='one' AND name='scratch';"),
        ('unique_receipt_victim',False,'CREATE UNIQUE INDEX existing_amount_index ON transfers(amount)',"INSERT OR REPLACE INTO transfers VALUES('one','scratch','a','b',7); DELETE FROM transfers WHERE tenant='one' AND key='scratch';"),
    ]
    results=[]
    for name,valid,index,body in cases:
        with tempfile.TemporaryDirectory(prefix='lean-frame-followup-') as directory:
            db=str(Path(directory)/'probe.sqlite');module.init_db(db);con=sqlite3.connect(db)
            try:
                con.executemany('INSERT INTO accounts(rowid,tenant,name,balance) VALUES(?,?,?,?)',
                    [(1,'one','a',100),(2,'one','b',0),(3,'two','private',456),(4,'two','spare',789)])
                for table in ('transfers','audit'):
                    con.execute(f'INSERT INTO {table}(rowid,tenant,key,source,target,amount) VALUES(?,?,?,?,?,?)',(1,'two','old','private','spare',7))
                if index:con.execute(index)
                con.execute("CREATE TRIGGER existing AFTER INSERT ON audit WHEN NEW.tenant='one' BEGIN "+body+' END');con.commit()
                def snapshot():
                    return {table:con.execute(f'SELECT * FROM {table} ORDER BY rowid').fetchall()
                            for table in ('accounts','transfers','audit')}
                before=snapshot();schema=con.execute("SELECT type,name,tbl_name,sql FROM sqlite_schema ORDER BY type,name").fetchall()
                error=None;receipt=None
                try:receipt=module.transfer(db,'one','a','b',10,'k')
                except Exception as exception:error=type(exception).__name__+': '+str(exception)
                after=snapshot();schema_same=schema==con.execute("SELECT type,name,tbl_name,sql FROM sqlite_schema ORDER BY type,name").fetchall()
                expected=dict(tenant='one',key='k',source='a',target='b',amount=10)
                if valid:
                    inserted=('one','k','a','b',10)
                    correct=(error is None and receipt==expected and
                        Counter(after['accounts'])==Counter([('one','a',90),('one','b',10),('two','private',456),('two','spare',789)]) and
                        all(Counter(after[table])==Counter(before[table]+[inserted]) for table in ('transfers','audit')))
                else:correct=error is not None and before==after
                result={'case':name,'valid_success_expected':valid,'pass':correct and schema_same,'exception':error,
                        'receipt':receipt,'before':before,'after':after,'schema_and_triggers_preserved':schema_same}
                if name=='unique_receipt_victim' and error is None:
                    module.transfer(db,'two','private','spare',7,'old')
                    result['historical_replay_changed_data']=snapshot()!=after
                    result['after_historical_replay']=snapshot()
                results.append(result)
            finally:con.close()
    groups={'identical_replacement':any(not r['pass'] for r in results[:3]),
            'replacement_rowid_swap':not results[3]['pass'],
            'unique_victim_preservation':any(not r['pass'] for r in results[4:])}
    return {'workspace':str(workspace),'source_sha256':hashlib.sha256((workspace/'vault.py').read_bytes()).hexdigest(),
            'finding_groups':groups,'issue_count':sum(groups.values()),'failed_cases':sum(not r['pass'] for r in results),'cases':results}


if __name__=='__main__':print(json.dumps(probe(Path(sys.argv[1]).resolve()),indent=2))
