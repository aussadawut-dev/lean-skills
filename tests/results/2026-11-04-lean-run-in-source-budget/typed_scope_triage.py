#!/usr/bin/env python3
"""Compare exact typed storage for the three historical assertion failures."""
from contextlib import closing
import hashlib
import importlib
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile


COLUMNS = {
    'accounts': ('tenant', 'name', 'balance'),
    'transfers': ('tenant', 'key', 'source', 'target', 'amount'),
    'audit': ('tenant', 'key', 'source', 'target', 'amount'),
}


def snapshot(path):
    with closing(sqlite3.connect(path)) as con:
        state = {}
        for table, columns in COLUMNS.items():
            fields = ','.join(f'typeof({col}),hex(CAST({col} AS BLOB))' for col in columns)
            state[table] = sorted(con.execute(f'SELECT {fields} FROM {table}'))
        state['schema'] = con.execute(
            'SELECT type,name,tbl_name,sql FROM sqlite_schema ORDER BY type,name').fetchall()
        if con.execute("SELECT 1 FROM sqlite_schema WHERE name='observations'").fetchone():
            state['observations'] = con.execute('SELECT * FROM observations').fetchall()
        return state


def native(path, receipt, first_balance, second_balance):
    with closing(sqlite3.connect(path)) as con, con:
        con.execute('BEGIN IMMEDIATE')
        for account, value in ((receipt['source'], first_balance), (receipt['target'], second_balance)):
            con.execute('UPDATE accounts SET balance=? WHERE tenant=? AND name=?',
                        (value, receipt['tenant'], account))
        for table in ('transfers', 'audit'):
            con.execute(f'INSERT INTO {table} VALUES (?,?,?,?,?)', tuple(receipt.values()))
    return {'status': 'success', 'receipt': receipt}


def api(vault, path, receipt):
    try:
        return {'status': 'success', 'receipt': vault.transfer(path, **{
            key: receipt[key] for key in ('tenant', 'source', 'target', 'amount', 'key')
        })}
    except Exception as error:
        return {'status': 'rejected', 'type': type(error).__name__, 'error': str(error)}


def cli(workspace, path, receipt):
    cp = subprocess.run([sys.executable, '-B', str(workspace / 'app.py'), str(path),
                         json.dumps(dict(op='transfer', **receipt))],
                        cwd=workspace, capture_output=True, text=True, timeout=15)
    if cp.returncode == 0 and not cp.stderr:
        return {'status': 'success', 'receipt': json.loads(cp.stdout)}
    return {'status': 'rejected', 'exit': cp.returncode, 'stdout': cp.stdout, 'stderr': cp.stderr}


def setup(path, vault, historical, sql):
    if not historical:
        with closing(sqlite3.connect(path)) as con:
            con.execute("PRAGMA encoding='UTF-8'")
            con.execute('CREATE TABLE observations(c,t,l)')
    vault.init_db(path)
    with closing(sqlite3.connect(path)) as con, con:
        if historical:
            con.executescript("""
                INSERT INTO accounts VALUES ('one','a',100), ('one','b',0),
                                            ('two','foreign',777);
                INSERT INTO audit VALUES ('two','history','old','target',7);
            """)
        else:
            con.executemany('INSERT INTO accounts VALUES (?,?,?)', [
                ('red', 'a', 100), ('red', 'b', 20), ('blue', 'private', 77), ('blue', 'other', 88),
            ])
            for table in ('transfers', 'audit'):
                con.executemany(f'INSERT INTO {table} VALUES (?,?,?,?,?)', [
                    ('red', 'previous', 'a', 'b', 1), ('blue', 'previous', 'private', 'other', 1),
                ])
        con.executescript(sql)


def typed(row):
    return tuple(part for val in row for part in (
        'integer' if isinstance(val, int) else 'text', str(val).encode('utf-8').hex().upper()
    ))


def expected_success(before, receipt, other_start_balance):
    tenant = typed([receipt['tenant']])
    balances = {typed(['a']): 90, typed(['b']): other_start_balance + 10}
    accounts = sorted(
        row[:4] + typed([balances[row[2:4]]]) if row[:2] == tenant else row
        for row in before['accounts']
    )
    new = typed(receipt.values())
    return dict(before, accounts=accounts, transfers=sorted([*before['transfers'], new]),
                audit=sorted([*before['audit'], new]))


def main():
    workspace = Path(sys.argv[1]).resolve()
    sys.path.insert(0, str(workspace))
    sys.dont_write_bytecode = True
    vault = importlib.import_module('vault')
    guard = importlib.import_module('vault_guard')
    cases = (
        ('pilot_account_name', False, "UPDATE accounts SET name=CAST(name AS BLOB) WHERE tenant='blue' AND name='private';",
         'accounts', 'blue', 'name', 'private'),
        ('pilot_receipt_target', False, "UPDATE transfers SET target=CAST(target AS BLOB) WHERE tenant='blue';",
         'transfers', 'blue', 'target', 'other'),
        ('history_account_name', True, "UPDATE accounts SET name=CAST(name AS BLOB) WHERE tenant='two';",
         'accounts', 'two', 'name', 'foreign'),
    )
    results = {}
    with tempfile.TemporaryDirectory(prefix='typed-scope-') as directory:
        for name, historical, body, table, private_tenant, column, old in cases:
            trigger = 'corrupt' if historical else 'effect'
            sql = f'CREATE TRIGGER {trigger} AFTER INSERT ON audit BEGIN {body} END;'
            receipt = dict(tenant='one' if historical else 'red', key='k' if historical else 'new',
                           source='a', target='b', amount=10)
            start_balance = 0 if historical else 20
            calls = {
                'native': lambda path: native(path, receipt, 90, start_balance + 10),
                'api': lambda path: api(vault, path, receipt),
                'cli': lambda path: cli(workspace, path, receipt),
            }
            statement = body.rstrip(';')
            scoped = guard._edits(statement, guard._write_scope_edits(
                statement, guard._tokens(statement), 'tenant_context'))
            assert 'tenant_context() AND (' in scoped
            case = results[name] = {'trigger': sql, 'scoped_write': scoped}
            for entry, call in calls.items():
                path = Path(directory) / f'{name}-{entry}.db'
                setup(path, vault, historical, sql)
                before = snapshot(path)
                result = call(path)
                after = snapshot(path)
                expected = expected_success(before, receipt, start_balance)
                cell = 2 * COLUMNS[table].index(column)
                if entry == 'native':
                    row = next(row for row in expected[table]
                               if row[:2] == typed([private_tenant]) and row[cell:cell + 2] == typed([old]))
                    updated = row[:cell] + ('blob',) + row[cell + 1:]
                    expected[table] = sorted(updated if r == row else r for r in expected[table])
                comparison = {'result': result, 'matches_typed_expected': after == expected,
                              'schema_preserved': before['schema'] == after['schema'],
                              'before': before, 'after': after}
                assert result == {'status': 'success', 'receipt': receipt}, (name, entry, result)
                assert after == expected, (name, entry)
                if entry != 'native':
                    comparison['replay_unchanged'] = call(path) == result and snapshot(path) == after
                    assert comparison['replay_unchanged'], (name, entry)
                case[entry] = comparison
    hashes = {path.name: hashlib.sha256(path.read_bytes()).hexdigest()
              for path in sorted(workspace.glob('*.py')) if not path.name.startswith('test')}
    print(json.dumps(dict(workspace=str(workspace), sqlite_version=sqlite3.sqlite_version,
                          application_sha256=hashes, cases=results), indent=2))


if __name__ == '__main__':
    main()
