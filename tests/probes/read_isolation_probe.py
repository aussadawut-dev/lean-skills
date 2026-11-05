"""A different tenant's malformed TEXT must not be materialized by this transfer."""
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
    with tempfile.TemporaryDirectory(prefix='lean-read-isolation-') as directory:
        db=str(Path(directory)/'probe.sqlite');module.init_db(db);con=sqlite3.connect(db);con.text_factory=bytes
        try:
            con.executemany('INSERT INTO accounts VALUES(?,?,?)',[('alpha','a',100),('alpha','b',0)])
            con.execute("INSERT INTO accounts VALUES('beta',CAST(X'626574612d707269766174652d736563726574ff' AS TEXT),999)");con.commit()
            before=con.execute('SELECT * FROM accounts ORDER BY rowid').fetchall();error=None;receipt=None
            try:receipt=module.transfer(db,'alpha','a','b',10,'k')
            except Exception as exception:error=type(exception).__name__+': '+str(exception)
            accounts=con.execute('SELECT * FROM accounts ORDER BY rowid').fetchall()
            transfers=con.execute('SELECT * FROM transfers').fetchall();audit=con.execute('SELECT * FROM audit').fetchall()
            expected=(b'alpha',b'k',b'a',b'b',10)
            passed=(error is None and receipt==dict(tenant='alpha',key='k',source='a',target='b',amount=10)
                    and accounts==[(b'alpha',b'a',90),(b'alpha',b'b',10),before[2]]
                    and transfers==[expected] and audit==[expected])
        finally:con.close()
    return {'workspace':str(workspace),'source_sha256':hashlib.sha256((workspace/'vault.py').read_bytes()).hexdigest(),
            'issue_count':int(not passed),'failed_cases':int(not passed),'case':'foreign_malformed_text_isolated',
            'pass':passed,'exception':error,'receipt':receipt,'other_tenant_unchanged':accounts[2:]==before[2:]}


if __name__=='__main__':print(json.dumps(probe(Path(sys.argv[1]).resolve()),indent=2))
