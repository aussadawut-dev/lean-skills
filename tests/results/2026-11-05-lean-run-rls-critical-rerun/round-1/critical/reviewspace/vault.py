"""Tenant-scoped accounting with transactional trigger execution.

Requires SQLite's trigger configuration API (Python 3.12 or later).
Account and receipt identities are their declared composite keys, not rowids.
"""
from collections import Counter
from contextlib import closing
import sqlite3


_COLUMNS = {
    'accounts': ('tenant', 'name', 'balance'),
    'transfers': ('tenant', 'key', 'source', 'target', 'amount'),
    'audit': ('tenant', 'key', 'source', 'target', 'amount'),
}
_ERROR = 'invalid request'


def _text(value):
    if not isinstance(value, str) or not value:
        raise ValueError(_ERROR)
    try:
        value.encode('utf-8')
    except UnicodeError:
        raise ValueError(_ERROR) from None


def _connect(path):
    return sqlite3.connect(path, timeout=30)


def init_db(path):
    with closing(_connect(path)) as con, con:
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
    _text(tenant)
    _text(account)
    with closing(_connect(path)) as con:
        row = con.execute(
            'SELECT balance FROM accounts WHERE tenant=? AND name=?',
            (tenant, account),
        ).fetchone()
        if row is None or type(row[0]) is not int:
            raise ValueError(_ERROR)
        return row[0]


def _typed(values):
    """The storage types expected for a validated API record."""
    result = []
    for value in values:
        if isinstance(value, str):
            result.extend((b'text', value.encode('utf-8')))
        else:
            result.extend((b'integer', value))
    return tuple(result)


def _rows(con, table):
    # Bytes plus explicit SQLite types preserve even malformed text, BLOBs,
    # duplicate audit rows and NULLs without decoding another tenant's data.
    fields = ','.join(f'typeof("{col}"),"{col}"' for col in _COLUMNS[table])
    return Counter(con.execute(f'SELECT {fields} FROM main."{table}"'))


def _hide_other_tenants(con, tenant):
    """Make the protected rows unreachable by persistent triggers and views.

    TEMP storage is private to this connection; persistent SQLite triggers
    cannot reference it. Triggers are disabled only for internal relocation,
    never for the actual debit, credit, receipt or audit insert. The writer
    lock and enclosing transaction hide relocation from other connections.
    """
    con.setconfig(sqlite3.SQLITE_DBCONFIG_ENABLE_TRIGGER, False)
    for table in _COLUMNS:
        con.execute(
            f'CREATE TEMP TABLE "_vault_saved_{table}" AS '
            f'SELECT rowid AS saved_rowid,* FROM main."{table}" '
            'WHERE tenant IS NOT ?', (tenant,),
        )
        con.execute(f'DELETE FROM main."{table}" WHERE tenant IS NOT ?', (tenant,))
    # Relocation must not leak hidden row counts through SQLite counters.
    # This function retains SQLite's native in-trigger total_changes semantics.
    offset = con.total_changes
    con.create_function('total_changes', 0, lambda: con.total_changes - offset)
    con.execute('UPDATE main.accounts SET balance=balance WHERE 0')
    con.setconfig(sqlite3.SQLITE_DBCONFIG_ENABLE_TRIGGER, True)


def _restore_other_tenants(con):
    con.setconfig(sqlite3.SQLITE_DBCONFIG_ENABLE_TRIGGER, False)
    for table, columns in _COLUMNS.items():
        fields = ','.join(f'"{col}"' for col in columns)
        saved = f'temp."_vault_saved_{table}"'
        # Preserve existing rowids where possible. New tenant-local inserts
        # can legitimately reuse a hidden rowid; relocate only those saved
        # rows, keeping all their column values and storage types unchanged.
        con.execute(
            f'CREATE TEMP TABLE "_vault_collisions_{table}" AS '
            f'SELECT {fields} FROM {saved} '
            f'WHERE saved_rowid IN (SELECT rowid FROM main."{table}")'
        )
        con.execute(
            f'INSERT INTO main."{table}" (rowid,{fields}) '
            f'SELECT saved_rowid,{fields} FROM {saved} '
            f'WHERE saved_rowid NOT IN (SELECT rowid FROM main."{table}")'
        )
        con.execute(
            f'INSERT INTO main."{table}" ({fields}) '
            f'SELECT {fields} FROM temp."_vault_collisions_{table}"'
        )
    con.setconfig(sqlite3.SQLITE_DBCONFIG_ENABLE_TRIGGER, True)


def transfer(path, tenant, source, target, amount, key):
    for value in (tenant, source, target, key):
        _text(value)
    if source == target or isinstance(amount, bool) or not isinstance(amount, int) or amount <= 0:
        raise ValueError(_ERROR)
    receipt = dict(tenant=tenant, key=key, source=source, target=target, amount=amount)
    record = _typed(receipt.values())
    with closing(_connect(path)) as con, con:
        con.text_factory = bytes
        # Serialize the read/check/write cycle, including receipt lookup.
        con.execute('BEGIN IMMEDIATE')
        old = con.execute(
            'SELECT typeof(source),source,typeof(target),target,typeof(amount),amount '
            'FROM transfers WHERE tenant=? AND key=?',
            (tenant, key),
        ).fetchone()
        if old is not None:
            if old != _typed((source, target, amount)):
                raise ValueError(_ERROR)
            return receipt
        account_rows = []
        for name in (source, target):
            row = con.execute(
                'SELECT balance FROM accounts WHERE tenant=? AND name=?',
                (tenant, name),
            ).fetchone()
            if row is None or type(row[0]) is not int:
                raise ValueError(_ERROR)
            account_rows.append(row[0])
        funds, credit = account_rows
        if funds < amount:
            raise ValueError(_ERROR)
        if not -(2**63) <= credit + amount < 2**63:
            raise ValueError(_ERROR)

        _hide_other_tenants(con, tenant)
        expected = {table: _rows(con, table) for table in _COLUMNS}
        for name, before, after in ((source, funds, funds - amount),
                                    (target, credit, credit + amount)):
            expected['accounts'][_typed((tenant, name, before))] -= 1
            expected['accounts'][_typed((tenant, name, after))] += 1
        expected['transfers'][record] += 1
        expected['audit'][record] += 1

        con.execute('UPDATE accounts SET balance=balance-? WHERE tenant=? AND name=?',
                    (amount, tenant, source))
        con.execute('UPDATE accounts SET balance=balance+? WHERE tenant=? AND name=?',
                    (amount, tenant, target))
        values = tuple(receipt.values())
        con.execute('INSERT INTO transfers (tenant,key,source,target,amount) VALUES (?,?,?,?,?)', values)
        con.execute('INSERT INTO audit (tenant,key,source,target,amount) VALUES (?,?,?,?,?)', values)
        if any(_rows(con, table) != +expected[table] for table in _COLUMNS):
            raise ValueError(_ERROR)
        _restore_other_tenants(con)
        return receipt
