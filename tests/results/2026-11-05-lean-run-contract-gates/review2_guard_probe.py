#!/usr/bin/env python3
"""Replay review-2 cases. Requires foreign_guard_probe.py beside this script."""
from contextlib import closing
import hashlib
import importlib
import json
from pathlib import Path
import sqlite3
import sys
import tempfile

import foreign_guard_probe as helper


def setup(path, vault, sql, old_audit, foreign):
    vault.init_db(path)
    with closing(sqlite3.connect(path)) as con, con:
        con.executemany('INSERT INTO accounts VALUES (?,?,?)',
                        [('alpha', 'cash', 100), ('alpha', 'savings', 0)])
        if old_audit:
            con.execute("INSERT INTO audit VALUES('alpha','old','cash','savings',1)")
        if foreign is not None:
            con.execute("INSERT INTO accounts VALUES('beta','private',?)", (foreign,))
        con.executescript(sql)


def state(path):
    contents = helper.snapshot(path)
    contents['audit'].sort()
    with closing(sqlite3.connect(path)) as con:
        if con.execute("SELECT 1 FROM sqlite_schema WHERE name='work'").fetchone():
            contents['work'] = con.execute('SELECT * FROM work').fetchall()
    return contents


def row_guard(select, threshold):
    return f"""CREATE TRIGGER guard BEFORE INSERT ON audit
        WHEN ({select})={threshold} BEGIN SELECT RAISE(ABORT,'audit rule'); END;"""


def replace_guard(conflict, write):
    return f"""CREATE TABLE work(x PRIMARY KEY{conflict});
        INSERT INTO work VALUES(1);
        CREATE TRIGGER native_delete_guard BEFORE DELETE ON work
        BEGIN SELECT RAISE(ABORT,'native delete should not run'); END;
        CREATE TRIGGER restore_work AFTER INSERT ON audit BEGIN {write}; END;"""


def main():
    workspace = Path(sys.argv[1]).resolve()
    sys.path.insert(0, str(workspace))
    sys.dont_write_bytecode = True
    vault = importlib.import_module('vault')
    plain = 'SELECT rowid FROM accounts WHERE tenant=NEW.tenant AND name=NEW.source'
    qualified = 'SELECT a.rowid FROM accounts a WHERE a.tenant=NEW.tenant AND a.name=NEW.source'
    dml = """CREATE TRIGGER guard BEFORE INSERT ON audit BEGIN
        UPDATE accounts SET balance=balance WHERE tenant='beta' AND name='private' AND balance=777;
        SELECT CASE WHEN changes()=1 THEN RAISE(ABORT,'audit rule') END;
    END;"""
    cases = (
        ('rowid_false', row_guard(plain, 999), True, None, None),
        ('rowid_true', row_guard(plain, 1), True, None, 'audit rule'),
        ('rowid_qualified', row_guard(qualified, 999), True, None, None),
        ('table_default_replace', replace_guard(' ON CONFLICT REPLACE', 'INSERT INTO work VALUES(1)'),
         False, None, None),
        ('explicit_replace_control', replace_guard('', 'INSERT OR REPLACE INTO work VALUES(1)'),
         False, None, None),
        ('explicit_delete_control', replace_guard(' ON CONFLICT REPLACE', 'DELETE FROM work WHERE x=1'),
         False, None, 'native delete should not run'),
        ('dml_scope_match', dml, False, 777, 'audit rule'),
        ('dml_scope_miss', dml, False, 778, None),
    )
    entries = {'native': helper.native, 'api': lambda path: helper.api(path, vault),
               'cli': lambda path: helper.cli(path, workspace)}
    results = {}
    with tempfile.TemporaryDirectory(prefix='review2-guard-') as directory:
        for name, sql, old_audit, foreign, expected_error in cases:
            result = {'failures': []}
            for entry, call in entries.items():
                path = Path(directory) / f'{name}-{entry}.db'
                setup(path, vault, sql, old_audit, foreign)
                before = state(path)
                observed = call(path)
                after = state(path)
                preserved = before['schema'] == after['schema']
                result[entry] = dict(observed, schema_preserved=preserved,
                                     reopened={k: v for k, v in after.items() if k != 'schema'})
                if not preserved:
                    result['failures'].append(entry + ':schema')
                expected = before
                if observed['status'] == 'success':
                    expected = dict(before, accounts=[
                        (tenant, account, {'cash': 90, 'savings': 10}[account] if tenant == 'alpha' else balance)
                        for tenant, account, balance in before['accounts']
                    ], transfers=[helper.ROW], audit=sorted([*before['audit'], helper.ROW]))
                if after != expected or observed['status'] not in ('success', 'rejected'):
                    result['failures'].append(entry + ':persistence_or_atomicity')
                if entry == 'native':
                    expected_status = 'rejected' if expected_error else 'success'
                    native_error = observed.get('error')
                    native_state = after
                    if observed['status'] != expected_status or native_error != expected_error:
                        result['failures'].append('native:oracle')
                elif foreign is None:
                    if observed['status'] != expected_status:
                        result['failures'].append(entry + ':status')
                    if entry == 'api' and expected_error and observed.get('error') != expected_error:
                        result['failures'].append('api:guard_error')
                    if after != native_state:
                        result['failures'].append(entry + ':state')
                if entry == 'cli' and observed.get('error') == 'native delete should not run':
                    result['failures'].append('cli:nongeneric_error')
                if entry != 'native' and observed['status'] == 'success':
                    replay = call(path)
                    result[entry]['replay'] = replay
                    if replay != observed or replay.get('receipt') != helper.RECEIPT or state(path) != after:
                        result['failures'].append(entry + ':replay')
            results[name] = result
    privacy_failures = []
    for entry in ('api', 'cli'):
        variants = [results[name][entry] for name in ('dml_scope_match', 'dml_scope_miss')]
        if any(variants[0].get(key) != variants[1].get(key)
               for key in ('status', 'error', 'receipt', 'type')):
            privacy_failures.append(entry + ':observable_private_predicate')
    results['dml_scope_pair'] = {'failures': privacy_failures}
    files = [path for path in workspace.glob('*.py') if not path.name.startswith('test')]
    hashes = {path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in sorted(files)}
    failed = [name for name, result in results.items() if result['failures']]
    print(json.dumps(dict(workspace=str(workspace), sqlite_version=sqlite3.sqlite_version,
                          source_sha256=hashes['vault.py'], application_sha256=hashes,
                          failed_cases=len(failed), failed_case_names=failed, cases=results), indent=2))
    return bool(failed)


if __name__ == '__main__':
    raise SystemExit(main())
