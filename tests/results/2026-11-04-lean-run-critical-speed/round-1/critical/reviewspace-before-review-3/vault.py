from contextlib import closing
import sqlite3

from _integrity import TransferEffects


_RECEIPT_COLUMNS = ('tenant', 'key', 'source', 'target', 'amount')
_MAX_BALANCE = 2**63 - 1


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


def _validate_names(*values):
    if any(not isinstance(value, str) or not value for value in values):
        raise ValueError('invalid request')


def _balance(con, tenant, account):
    row = con.execute(
        'SELECT balance FROM accounts WHERE tenant=? AND name=?',
        (tenant, account),
    ).fetchone()
    if row is None or not isinstance(row[0], int):
        raise ValueError('account unavailable')
    return row[0]


def balance(path, tenant, account):
    _validate_names(tenant, account)
    with closing(sqlite3.connect(path)) as con:
        return _balance(con, tenant, account)


def _receipt(con, tenant, key):
    return con.execute(
        'SELECT tenant, key, source, target, amount FROM transfers '
        'WHERE tenant=? AND key=?', (tenant, key),
    ).fetchone()


def transfer(path, tenant, source, target, amount, key):
    _validate_names(tenant, source, target, key)
    if (source == target or isinstance(amount, bool)
            or not isinstance(amount, int) or amount <= 0):
        raise ValueError('invalid request')

    values = (tenant, key, source, target, amount)
    with closing(sqlite3.connect(path, timeout=30)) as con, con:
        # Lock before reading either the key or the balances. Separate callers
        # then observe the previous committed transfer before making decisions.
        con.execute('BEGIN IMMEDIATE')
        old = _receipt(con, tenant, key)
        if old is not None:
            if old != values:
                raise ValueError('key conflict')
            return dict(zip(_RECEIPT_COLUMNS, old))

        source_balance = _balance(con, tenant, source)
        target_balance = _balance(con, tenant, target)
        if source_balance < amount:
            raise ValueError('insufficient funds')
        debit = source_balance - amount
        credit = target_balance + amount
        if credit > _MAX_BALANCE:
            raise ValueError('balance out of range')
        effects = TransferEffects(con)
        effects.execute('UPDATE accounts SET balance=? WHERE tenant=? AND name=?',
                        (debit, tenant, source))
        effects.execute('UPDATE accounts SET balance=? WHERE tenant=? AND name=?',
                        (credit, tenant, target))
        effects.execute('INSERT INTO transfers (tenant,key,source,target,amount) '
                        'VALUES (?,?,?,?,?)', values)
        effects.execute('INSERT INTO audit (tenant,key,source,target,amount) '
                        'VALUES (?,?,?,?,?)', values)

        # Cancel the intended delta against observed OLD/NEW effects. A nonzero
        # remainder means a missing effect or a change to an unrelated row.
        effects.finish([
            ('accounts', tenant, source, None, None, source_balance, 1),
            ('accounts', tenant, source, None, None, debit, -1),
            ('accounts', tenant, target, None, None, target_balance, 1),
            ('accounts', tenant, target, None, None, credit, -1),
            ('transfers', *values, -1),
            ('audit', *values, -1),
        ])
        return dict(zip(_RECEIPT_COLUMNS, values))
