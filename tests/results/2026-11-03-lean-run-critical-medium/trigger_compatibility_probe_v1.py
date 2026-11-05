"""Posthoc reproductions of demonstrated round-2 Critical findings; no model calls."""
from collections import Counter
import hashlib
import importlib.util
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile


def probe(workspace):
    sys.path.insert(0, str(workspace))
    spec = importlib.util.spec_from_file_location('trigger_probe_vault', workspace / 'vault.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    expected = dict(tenant='one', key='k', source='a', target='b', amount=10)
    historical = dict(tenant='two', key='old', source='private', target='spare', amount=7)
    cases = []
    for name in ('benign_keyword_trigger', 'unique_audit_replace', 'unique_audit_ignore'):
        valid = name != 'unique_audit_replace'
        for journal in ('DELETE', 'WAL'):
            for interface in ('API', 'CLI'):
                with tempfile.TemporaryDirectory(prefix='lean-trigger-followup-') as temporary:
                    db = str(Path(temporary) / 'probe.sqlite')
                    module.init_db(db)
                    con = sqlite3.connect(db)
                    try:
                        actual_journal = con.execute('PRAGMA journal_mode=' + journal).fetchone()[0]
                        con.executemany('INSERT INTO accounts VALUES(?,?,?)',
                                        [('one', 'a', 100), ('one', 'b', 0),
                                         ('two', 'private', 456), ('two', 'spare', 789)])
                        for table in ('transfers', 'audit'):
                            con.execute(f'INSERT INTO {table} VALUES(?,?,?,?,?)', tuple(historical.values()))
                        if name == 'benign_keyword_trigger':
                            con.execute('CREATE TRIGGER begin AFTER INSERT ON audit BEGIN SELECT 1; END')
                        else:
                            con.execute('CREATE UNIQUE INDEX audit_identity ON audit(tenant,key)')
                            conflict = 'REPLACE' if name == 'unique_audit_replace' else 'IGNORE'
                            con.execute("CREATE TRIGGER fault AFTER INSERT ON audit WHEN NEW.tenant='one' BEGIN "
                                        f"INSERT OR {conflict} INTO audit VALUES('two','old','temporary','spare',1); "
                                        "DELETE FROM audit WHERE tenant='two' AND key='old' AND source='temporary'; END")
                        con.commit()

                        def snapshot():
                            return {table: con.execute(f'SELECT * FROM {table} ORDER BY rowid').fetchall()
                                    for table in ('accounts', 'transfers', 'audit')}

                        before = snapshot()
                        schema = con.execute('SELECT type,name,tbl_name,sql FROM sqlite_schema ORDER BY type,name').fetchall()
                        exception = None
                        receipt = None
                        cli = None
                        if interface == 'API':
                            try:
                                receipt = module.transfer(db, 'one', 'a', 'b', 10, 'k')
                            except Exception as error:
                                exception = type(error).__name__ + ': ' + str(error)
                            accepted = exception is None
                            rejected = exception is not None
                        else:
                            request = dict(op='transfer', **expected)
                            p = subprocess.run([sys.executable, '-B', str(workspace / 'app.py'), db,
                                                json.dumps(request)], capture_output=True, text=True, timeout=30)
                            cli = dict(exit_code=p.returncode, stdout=p.stdout, stderr=p.stderr)
                            try:
                                receipt = json.loads(p.stdout) if p.stdout else None
                                error_json = json.loads(p.stderr) if p.stderr else None
                            except ValueError:
                                error_json = None
                            accepted = p.returncode == 0 and p.stderr == ''
                            rejected = (p.returncode == 2 and p.stdout == '' and isinstance(error_json, dict)
                                        and isinstance(error_json.get('error'), str)
                                        and not any(word in p.stderr.lower() for word in
                                                    ('traceback', 'private', 'spare', 'insert ', 'select ')))
                        after = snapshot()
                        schema_same = schema == con.execute('SELECT type,name,tbl_name,sql FROM sqlite_schema ORDER BY type,name').fetchall()
                        inserted = tuple(expected.values())
                        correct = (accepted and receipt == expected
                                   and Counter(after['accounts']) == Counter([
                                       ('one', 'a', 90), ('one', 'b', 10),
                                       ('two', 'private', 456), ('two', 'spare', 789)])
                                   and all(Counter(after[table]) == Counter(before[table] + [inserted])
                                           for table in ('transfers', 'audit'))) if valid else rejected and before == after
                        replay_error = None
                        try:
                            if valid:
                                assert module.transfer(db, 'one', 'a', 'b', 10, 'k') == expected
                            assert module.transfer(db, 'two', 'private', 'spare', 7, 'old') == historical
                            assert snapshot() == after
                        except Exception as error:
                            replay_error = type(error).__name__ + ': ' + str(error)
                        cases.append(dict(case=name, journal=journal, actual_journal=actual_journal,
                                          interface=interface, valid_success_expected=valid,
                                          passed=bool(correct and schema_same and replay_error is None),
                                          exception=exception, receipt=receipt, cli=cli, before=before, after=after,
                                          schema_preserved=schema_same, replay_error=replay_error))
                    finally:
                        con.close()
    groups = {name: any(not row['passed'] for row in cases if row['case'] == name)
              for name in ('benign_keyword_trigger', 'unique_audit_replace', 'unique_audit_ignore')}
    return dict(workspace=str(workspace), source_sha256=hashlib.sha256((workspace / 'vault.py').read_bytes()).hexdigest(),
                finding_groups=groups, issue_count=sum(groups.values()),
                failed_cases=sum(not row['passed'] for row in cases), cases=cases)


if __name__ == '__main__':
    print(json.dumps(probe(Path(sys.argv[1]).resolve()), indent=2))
