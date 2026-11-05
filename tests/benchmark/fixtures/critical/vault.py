"""Tenant-scoped SQLite transfers with a final-effects check; synthetic candidate.

The base candidate verifies, before commit and inside SQLite, that the three
ledger tables changed by exactly the debit, the credit, one receipt and one
audit row, whatever user triggers did. It does not hide other tenants' rows.
The deliberately defective variants used by the unit tests patch _check_schema
or VERIFY_EFFECTS; see tests/synthetic_cohorts.py.
"""
from contextlib import closing
import sqlite3

TABLES = {
    'accounts': 'tenant,name,balance',
    'transfers': 'tenant,key,source,target,amount',
    'audit': 'tenant,key,source,target,amount',
}
VERIFY_EFFECTS = True


def _validate_names(*values):
    if any(not isinstance(value, str) or not value for value in values):
        raise ValueError('invalid request')


def _check_schema(con):
    """Hook for the defective fixture variants; the base candidate accepts any schema."""
    return None


def _snapshot(con):
    """Copy the ledger tables into TEMP storage; no value reaches Python."""
    for table, columns in TABLES.items():
        con.execute(f'DROP TABLE IF EXISTS temp.snapshot_{table}')
        con.execute(f'CREATE TEMP TABLE snapshot_{table} AS SELECT {columns} FROM main.{table}')


def _difference(con, table):
    columns = TABLES[table]
    added, removed = (con.execute(
        f'SELECT count(*) FROM (SELECT {columns} FROM {left} EXCEPT SELECT {columns} FROM {right})'
    ).fetchone()[0] for left, right in ((f'main.{table}', f'temp.snapshot_{table}'),
                                        (f'temp.snapshot_{table}', f'main.{table}')))
    grown = (con.execute(f'SELECT count(*) FROM main.{table}').fetchone()[0]
             - con.execute(f'SELECT count(*) FROM temp.snapshot_{table}').fetchone()[0])
    return added, removed, grown


def _verify_effects(con, tenant, source, target, accounts, amount, values):
    """Exactly the debit, the credit, one receipt and one audit row changed."""
    final = {row[0]: (row[1], row[2]) for row in con.execute(
        'SELECT name,balance,typeof(balance) FROM main.accounts WHERE tenant=? AND name IN (?,?)',
        (tenant, source, target))}
    expected = {source: (accounts[source] - amount, 'integer'), target: (accounts[target] + amount, 'integer')}
    receipts = [con.execute(
        f'SELECT count(*) FROM main.{table} WHERE tenant=? AND key=? AND source=? AND target=? AND amount=?',
        values).fetchone()[0] for table in ('transfers', 'audit')]
    if (final != expected or _difference(con, 'accounts') != (2, 2, 0) or receipts != [1, 1]
            or _difference(con, 'transfers') != (1, 0, 1) or _difference(con, 'audit') != (1, 0, 1)):
        raise sqlite3.IntegrityError('transaction effects rejected')


def init_db(path):
    with closing(sqlite3.connect(path)) as con, con:
        con.executescript('''
        CREATE TABLE IF NOT EXISTS accounts (
          tenant TEXT, name TEXT, balance INTEGER,
          PRIMARY KEY(tenant,name));
        CREATE TABLE IF NOT EXISTS transfers (
          tenant TEXT, key TEXT, source TEXT, target TEXT, amount INTEGER,
          PRIMARY KEY(tenant,key));
        CREATE TABLE IF NOT EXISTS audit (
          tenant TEXT, key TEXT, source TEXT, target TEXT, amount INTEGER);
        ''')


def balance(path, tenant, account):
    _validate_names(tenant, account)
    with closing(sqlite3.connect(path)) as con:
        row = con.execute('SELECT balance FROM accounts WHERE tenant=? AND name=?',
                          (tenant, account)).fetchone()
        if row is None:
            raise ValueError('account unavailable')
        return row[0]


def transfer(path, tenant, source, target, amount, key):
    _validate_names(tenant, source, target, key)
    if source == target or isinstance(amount, bool) or not isinstance(amount, int) or amount <= 0:
        raise ValueError('invalid request')
    with closing(sqlite3.connect(path, timeout=30)) as con, con:
        con.row_factory = sqlite3.Row
        con.execute('BEGIN IMMEDIATE')
        old = con.execute('SELECT tenant,key,source,target,amount FROM transfers WHERE tenant=? AND key=?',
                          (tenant, key)).fetchone()
        if old is not None:
            if (old['source'], old['target'], old['amount']) != (source, target, amount):
                raise ValueError('key conflict')
            return dict(old)
        accounts = {row['name']: row['balance'] for row in con.execute(
            'SELECT name,balance FROM accounts WHERE tenant=? AND name IN (?,?)', (tenant, source, target))}
        if len(accounts) != 2:
            raise ValueError('account unavailable')
        if accounts[source] < amount:
            raise ValueError('insufficient funds')
        _check_schema(con)
        if VERIFY_EFFECTS:
            _snapshot(con)
        con.execute('UPDATE accounts SET balance=? WHERE tenant=? AND name=?',
                    (accounts[source] - amount, tenant, source))
        con.execute('UPDATE accounts SET balance=? WHERE tenant=? AND name=?',
                    (accounts[target] + amount, tenant, target))
        values = (tenant, key, source, target, amount)
        con.execute('INSERT INTO transfers (tenant,key,source,target,amount) VALUES (?,?,?,?,?)', values)
        con.execute('INSERT INTO audit (tenant,key,source,target,amount) VALUES (?,?,?,?,?)', values)
        if VERIFY_EFFECTS:
            _verify_effects(con, tenant, source, target, accounts, amount, values)
        return dict(tenant=tenant, key=key, source=source, target=target, amount=amount)
