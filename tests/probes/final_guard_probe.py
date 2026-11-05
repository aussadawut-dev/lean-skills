#!/usr/bin/env python3
"""Replay final reviewer guard cases; requires foreign_guard_probe.py nearby."""
from contextlib import closing
import hashlib
import importlib
import json
from pathlib import Path
import sqlite3
import sys
import tempfile

import foreign_guard_probe as helper


def main():
    workspace = Path(sys.argv[1]).resolve()
    sys.path.insert(0, str(workspace))
    sys.dont_write_bytecode = True
    vault = importlib.import_module('vault')
    cases = []
    for target in ('accounts', 'main.accounts'):
        sql = f"""
            CREATE TRIGGER observe BEFORE UPDATE ON {target}
            WHEN OLD.tenant='beta' AND OLD.balance=777
            BEGIN SELECT RAISE(ABORT,'foreign balance'); END;
            CREATE TRIGGER invoke AFTER INSERT ON audit
            BEGIN UPDATE accounts SET balance=balance WHERE tenant='beta' AND name='private'; END;
        """
        for balance in (777, 778):
            cases.append((f'{target}_{balance}', sql, balance,
                          'foreign balance' if balance == 777 else None, True))
    for suffix, threshold in (('harmless', 999), ('abort', 90)):
        sql = f"""
            CREATE TRIGGER natural_guard BEFORE INSERT ON audit WHEN
            (SELECT balance FROM accounts NATURAL JOIN
               (SELECT 'alpha' AS tenant, 'cash' AS name))={threshold}
            BEGIN SELECT RAISE(ABORT,'local guard'); END;
        """
        cases.append((f'natural_join_{suffix}', sql, 777,
                      'local guard' if suffix == 'abort' else None, False))
    entries = {'native': helper.native, 'api': lambda path: helper.api(path, vault),
               'cli': lambda path: helper.cli(path, workspace)}
    results = {}
    with tempfile.TemporaryDirectory(prefix='review3-guard-') as directory:
        for name, sql, balance, expected_error, foreign_guard in cases:
            case = results[name] = {'failures': []}
            for entry, call in entries.items():
                path = Path(directory) / f'{name}-{entry}.db'
                vault.init_db(path)
                with closing(sqlite3.connect(path)) as con, con:
                    con.executemany('INSERT INTO accounts VALUES (?,?,?)', [
                        ('alpha', 'cash', 100), ('alpha', 'savings', 0), ('beta', 'private', balance),
                    ])
                    con.executescript(sql)
                observed = case[entry] = helper.check(path, call, helper.snapshot(path), entry, balance)
                if not observed['state_pass']:
                    case['failures'].append(entry + ':persistence_or_interface')
                error = observed.get('error')
                if entry == 'cli' and error in ('foreign balance', 'local guard'):
                    case['failures'].append('cli:nongeneric_error')
                if entry == 'native' or not foreign_guard:
                    expected_status = 'rejected' if expected_error else 'success'
                    if observed['status'] != expected_status:
                        case['failures'].append(entry + ':status')
                    if entry != 'cli' and error != expected_error:
                        case['failures'].append(entry + ':guard_cause')
    for target in ('accounts', 'main.accounts'):
        pair = results[f'{target}_privacy_pair'] = {'failures': []}
        for entry in ('api', 'cli'):
            matched = results[f'{target}_777'][entry]
            missed = results[f'{target}_778'][entry]
            if any(matched.get(key) != missed.get(key) for key in ('status', 'error', 'receipt', 'type')):
                pair['failures'].append(entry + ':observable_foreign_predicate')

    files = [path for path in workspace.glob('*.py') if not path.name.startswith('test')]
    hashes = {path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in sorted(files)}
    failed = [name for name, case in results.items() if case['failures']]
    print(json.dumps(dict(workspace=str(workspace), sqlite_version=sqlite3.sqlite_version,
                          source_sha256=hashes['vault.py'], application_sha256=hashes,
                          failed_cases=len(failed), failed_case_names=failed, cases=results), indent=2))
    return bool(failed)


if __name__ == '__main__':
    raise SystemExit(main())
