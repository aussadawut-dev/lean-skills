"""Apply review-2 findings equally to historical and current critical candidates."""
from collections import Counter
import hashlib
import importlib.util
import json
from pathlib import Path
import sqlite3
import sys
import tempfile


def probe(workspace):
    spec = importlib.util.spec_from_file_location('candidate', workspace / 'vault.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    cases = [
        ('history_rewritten', "WHEN NEW.tenant='a' BEGIN UPDATE audit SET amount=999 WHERE tenant='b' AND key='old'; END", False),
        ('history_deleted_duplicate_added', "WHEN NEW.tenant='a' BEGIN DELETE FROM audit WHERE tenant='b' AND key='old'; INSERT INTO audit VALUES('b',NEW.key,NEW.source,NEW.target,NEW.amount); END", False),
        ('valid_rowid_relocation', 'BEGIN UPDATE audit SET rowid=NEW.rowid+1000 WHERE rowid=NEW.rowid; END', True),
    ]
    results = []
    for name, body, valid in cases:
        with tempfile.TemporaryDirectory(prefix='lean-audit-followup-') as directory:
            db = str(Path(directory) / 'probe.sqlite')
            module.init_db(db)
            con = sqlite3.connect(db)
            try:
                con.executemany('INSERT INTO accounts VALUES(?,?,?)', [('a','source',100),('a','target',0),('b','source',77),('b','target',0)])
                for table in ('transfers','audit'):
                    con.execute(f'INSERT INTO {table} VALUES(?,?,?,?,?)', ('b','old','source','target',2))
                con.execute('CREATE TRIGGER audit_probe AFTER INSERT ON audit ' + body)
                con.commit()
                def snapshot():
                    return {table:con.execute(f'SELECT * FROM {table} ORDER BY rowid').fetchall()
                            for table in ('accounts','transfers','audit')}
                before = snapshot()
                error = None
                receipt = None
                try:
                    receipt = module.transfer(db,'a','source','target',10,'new')
                except Exception as exception:
                    error = type(exception).__name__
                after = snapshot()
                present = con.execute("SELECT COUNT(*) FROM sqlite_master WHERE type='trigger' AND name='audit_probe'").fetchone()[0] == 1
                if valid:
                    added = ('a','new','source','target',10)
                    expected_accounts = [('a','source',90),('a','target',10),('b','source',77),('b','target',0)]
                    expected_receipt = dict(tenant='a',key='new',source='source',target='target',amount=10)
                    passed = (error is None and receipt == expected_receipt and present
                              and Counter(after['accounts']) == Counter(expected_accounts)
                              and all(Counter(after[t]) == Counter(before[t] + [added]) for t in ('transfers','audit')))
                else:
                    passed = error is not None and before == after and present
                results.append({'case':name,'pass':passed,'valid_transfer_expected':valid,'exception':error,
                                'receipt':receipt,'before':before,'after':after,'trigger_preserved':present})
            finally:
                con.close()
    groups = {'audit_history_preservation':any(not row['pass'] for row in results if not row['valid_transfer_expected']),
              'valid_rowid_relocation':any(not row['pass'] for row in results if row['valid_transfer_expected'])}
    return {'workspace':str(workspace),'source_sha256':hashlib.sha256((workspace/'vault.py').read_bytes()).hexdigest(),
            'finding_groups':groups,'issue_count':sum(groups.values()),'failed_cases':sum(not r['pass'] for r in results),'cases':results}


if __name__ == '__main__':
    print(json.dumps(probe(Path(sys.argv[1]).resolve()),indent=2))
