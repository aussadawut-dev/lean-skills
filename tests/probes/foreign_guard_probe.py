#!/usr/bin/env python3
"""Compare two account databases differing only in an unauthorized balance.

The noninterference check is necessary, and inspecting the read boundary is
also required to establish that a candidate never reads foreign account data.
"""
from contextlib import closing
import hashlib
import importlib
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile


RECEIPT = dict(tenant='alpha', key='k', source='cash', target='savings', amount=10)
ARGS = ('alpha', 'cash', 'savings', 10, 'k')
ROW = tuple(RECEIPT.values())


def snapshot(path):
    with closing(sqlite3.connect(path)) as con:
        return dict(
            accounts=con.execute('SELECT * FROM accounts ORDER BY tenant,name').fetchall(),
            transfers=con.execute('SELECT * FROM transfers').fetchall(),
            audit=con.execute('SELECT * FROM audit').fetchall(),
            schema=con.execute('SELECT type,name,tbl_name,sql FROM sqlite_schema ORDER BY type,name').fetchall(),
        )


def setup(path, vault, target, private_balance):
    vault.init_db(path)
    tenant, account = target
    with closing(sqlite3.connect(path)) as con, con:
        con.executemany('INSERT INTO accounts VALUES (?,?,?)', [
            ('alpha', 'cash', 100), ('alpha', 'savings', 0), ('beta', 'private', private_balance),
        ])
        threshold = 777 if tenant == 'beta' else 10
        con.executescript(f"""
            CREATE TRIGGER scope_probe BEFORE INSERT ON audit
            WHEN (SELECT balance FROM accounts WHERE tenant='{tenant}' AND name='{account}')={threshold}
            BEGIN SELECT RAISE(ABORT,'audit rule'); END;
        """)


def native(path):
    with closing(sqlite3.connect(path)) as con:
        try:
            with con:
                con.execute('BEGIN IMMEDIATE')
                con.execute("UPDATE accounts SET balance=90 WHERE tenant='alpha' AND name='cash'")
                con.execute("UPDATE accounts SET balance=10 WHERE tenant='alpha' AND name='savings'")
                con.execute('INSERT INTO transfers VALUES (?,?,?,?,?)', ROW)
                con.execute('INSERT INTO audit VALUES (?,?,?,?,?)', ROW)
        except sqlite3.Error as error:
            return {'status': 'rejected', 'error': str(error)}
    return {'status': 'success', 'receipt': RECEIPT}


def api(path, vault):
    try:
        return {'status': 'success', 'receipt': vault.transfer(path, *ARGS)}
    except Exception as error:
        return {'status': 'rejected', 'error': str(error), 'type': type(error).__name__}


def cli(path, workspace):
    command = [sys.executable, '-B', str(workspace / 'app.py'), str(path),
               json.dumps(dict(op='transfer', **RECEIPT))]
    run = subprocess.run(command, cwd=workspace, capture_output=True, text=True, timeout=15)
    try:
        if run.returncode == 0 and not run.stderr:
            return {'status': 'success', 'receipt': json.loads(run.stdout)}
        if run.returncode == 2 and not run.stdout:
            message = json.loads(run.stderr)
            if isinstance(message, dict) and isinstance(message.get('error'), str):
                error = message['error']
                if not any(word in error.lower()
                           for word in ('beta', 'private', '777', '778', 'select', 'traceback', 'audit rule')):
                    return {'status': 'rejected', 'error': error}
    except ValueError:
        pass
    return dict(status='invalid_cli', code=run.returncode, stdout=run.stdout, stderr=run.stderr)


def check(path, call, before, entry, private_balance):
    result = call(path)
    after = snapshot(path)
    expected = before if result['status'] != 'success' else dict(
        before, accounts=[('alpha', 'cash', 90), ('alpha', 'savings', 10),
                          ('beta', 'private', private_balance)],
        transfers=[ROW], audit=[ROW],
    )
    valid = (after == expected and result['status'] in ('success', 'rejected')
             and (result['status'] != 'success' or result.get('receipt') == RECEIPT))
    if entry != 'native' and result['status'] == 'success':
        replay = call(path)
        valid &= replay == result and snapshot(path) == after
        result['replay'] = replay
    return dict(result, state_pass=valid, reopened_accounts=after['accounts'],
                reopened_transfers=after['transfers'], reopened_audit=after['audit'],
                schema_preserved=before['schema'] == after['schema'])


def main():
    workspace = Path(sys.argv[1]).resolve()
    sys.path.insert(0, str(workspace))
    sys.dont_write_bytecode = True
    vault = importlib.import_module('vault')
    entries = {'native': native, 'api': lambda path: api(path, vault),
               'cli': lambda path: cli(path, workspace)}
    cases = {}
    with tempfile.TemporaryDirectory(prefix='foreign-guard-') as directory:
        for name, target, balance in (
            ('foreign_match', ('beta', 'private'), 777),
            ('foreign_miss', ('beta', 'private'), 778),
            ('local_abort', ('alpha', 'savings'), 777),
            ('local_harmless', ('alpha', 'cash'), 777),
        ):
            cases[name] = {}
            for entry, call in entries.items():
                path = Path(directory) / f'{name}-{entry}.db'
                setup(path, vault, target, balance)
                cases[name][entry] = check(path, call, snapshot(path), entry, balance)

    failures = []
    for name, results in cases.items():
        expected = 'rejected' if name.endswith(('match', 'abort')) else 'success'
        for entry, result in results.items():
            if not result['state_pass']:
                failures.append(f'{name}:{entry}:invalid_state_or_interface')
            if (entry == 'native' or name.startswith('local_')) and result['status'] != expected:
                failures.append(f'{name}:{entry}:guard_outcome')
    for entry in ('api', 'cli'):
        fields = ('status', 'receipt', 'error', 'type')
        match = cases['foreign_match'][entry]
        miss = cases['foreign_miss'][entry]
        if any(match.get(field) != miss.get(field) for field in fields):
            failures.append(f'foreign_guard:{entry}:observable_private_predicate')
    print(json.dumps({
        'workspace': str(workspace),
        'sqlite_version': sqlite3.sqlite_version,
        'source_sha256': hashlib.sha256((workspace / 'vault.py').read_bytes()).hexdigest(),
        'failed_cases': len(failures), 'failures': failures, 'cases': cases,
    }, indent=2))
    return bool(failures)


if __name__ == '__main__':
    raise SystemExit(main())
