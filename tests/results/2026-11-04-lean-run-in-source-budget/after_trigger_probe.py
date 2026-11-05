"""Follow up a cross-regression discovery without modifying candidate files."""
import hashlib
import importlib.util
import json
from pathlib import Path
import sqlite3
import sys
import tempfile


def probe(workspace):
    module_spec = importlib.util.spec_from_file_location('candidate_vault', workspace / 'vault.py')
    module = importlib.util.module_from_spec(module_spec)
    module_spec.loader.exec_module(module)
    cases = [
        ('credit_undone', "AFTER UPDATE ON accounts WHEN NEW.tenant='a' AND NEW.name='target'",
         'UPDATE accounts SET balance=OLD.balance WHERE tenant=NEW.tenant AND name=NEW.name;'),
        ('receipt_removed', 'AFTER INSERT ON transfers',
         'DELETE FROM transfers WHERE tenant=NEW.tenant AND key=NEW.key;'),
        ('audit_removed', 'AFTER INSERT ON audit', 'DELETE FROM audit WHERE rowid=NEW.rowid;'),
        ('audit_duplicated', 'AFTER INSERT ON audit',
         'INSERT INTO audit VALUES(NEW.tenant,NEW.key,NEW.source,NEW.target,NEW.amount);'),
    ]
    results = []
    for name, event, body in cases:
        with tempfile.TemporaryDirectory(prefix='lean-after-trigger-') as folder:
            path = Path(folder) / 'probe.sqlite'
            module.init_db(str(path))
            con = sqlite3.connect(path)
            try:
                con.executemany('INSERT INTO accounts VALUES(?,?,?)', [('a','source',100),('a','target',0),('b','source',77)])
                con.execute(f'CREATE TRIGGER existing_effect {event} BEGIN {body} END')
                con.commit()
                def snapshot():
                    return {table: con.execute(f'SELECT * FROM {table} ORDER BY rowid').fetchall()
                            for table in ('accounts','transfers','audit')}
                before = snapshot()
                error = None
                receipt = None
                try:
                    receipt = module.transfer(str(path),'a','source','target',10,'key')
                except Exception as exception:
                    error = type(exception).__name__
                after = snapshot()
                trigger_present = con.execute("SELECT COUNT(*) FROM sqlite_master WHERE type='trigger' AND name='existing_effect'").fetchone()[0] == 1
                passed = error is not None and after == before and trigger_present
                results.append({'case':name,'pass':passed,'exception':error,'receipt':receipt,
                                'before':before,'after':after,'trigger_preserved':trigger_present})
            finally:
                con.close()
    return {'workspace':str(workspace),'source_sha256':hashlib.sha256((workspace/'vault.py').read_bytes()).hexdigest(),
            'root_cause':'Missing final-effect validation after successful SQL statements',
            'issue_count':int(any(not result['pass'] for result in results)),
            'failed_cases':sum(not result['pass'] for result in results),'cases':results}


if __name__ == '__main__':
    print(json.dumps(probe(Path(sys.argv[1]).resolve()),indent=2))
