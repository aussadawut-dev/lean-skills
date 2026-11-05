from contextlib import closing
import sqlite3

from _vault_effects import transfer_effects


def init_db(path):
    with closing(sqlite3.connect(path)) as con:
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


def _require_text(*values):
    if any(not isinstance(value, str) or not value for value in values):
        raise ValueError('invalid request')


def _account_balance(con, tenant, account):
    row = con.execute(
        'SELECT balance FROM accounts WHERE tenant=? AND name=?',
        (tenant, account),
    ).fetchone()
    if row is None:
        raise ValueError('account unavailable')
    if not isinstance(row[0], int):
        raise sqlite3.DatabaseError('invalid stored balance')
    return row[0]


def balance(path, tenant, account):
    _require_text(tenant, account)
    with closing(sqlite3.connect(path)) as con:
        return _account_balance(con, tenant, account)


def _write_one(con, statement, parameters):
    if con.execute(statement, parameters).rowcount != 1:
        # A trigger can silently ignore a write. That is not a complete transfer.
        raise sqlite3.IntegrityError('transfer write failed')


def transfer(path, tenant, source, target, amount, key):
    _require_text(tenant, source, target, key)
    if source == target or isinstance(amount, bool) or not isinstance(amount, int) or amount <= 0:
        raise ValueError('invalid request')

    receipt = dict(tenant=tenant, key=key, source=source, target=target, amount=amount)
    with closing(sqlite3.connect(path, timeout=30)) as con, con:
        con.row_factory = sqlite3.Row
        # Serialize the replay/funds checks with all four writes, across connections.
        con.execute('BEGIN IMMEDIATE')
        old = con.execute(
            'SELECT tenant, key, source, target, amount FROM transfers WHERE tenant=? AND key=?',
            (tenant, key),
        ).fetchone()
        if old is not None:
            if dict(old) != receipt:
                raise ValueError('idempotency key conflict')
            return dict(old)

        funds = _account_balance(con, tenant, source)
        target_funds = _account_balance(con, tenant, target)
        if funds < amount:
            raise ValueError('insufficient funds')

        with transfer_effects(con, tenant, source, funds, target, target_funds, amount, key):
            # Bind exact Python integers so SQLite cannot silently overflow to a float.
            _write_one(con, 'UPDATE accounts SET balance=? WHERE tenant=? AND name=?',
                       (funds - amount, tenant, source))
            _write_one(con, 'UPDATE accounts SET balance=? WHERE tenant=? AND name=?',
                       (target_funds + amount, tenant, target))
            values = (tenant, key, source, target, amount)
            _write_one(con, 'INSERT INTO transfers (tenant, key, source, target, amount) '
                       'VALUES (?, ?, ?, ?, ?)', values)
            _write_one(con, 'INSERT INTO audit (tenant, key, source, target, amount) '
                       'VALUES (?, ?, ?, ?, ?)', values)
        return receipt
