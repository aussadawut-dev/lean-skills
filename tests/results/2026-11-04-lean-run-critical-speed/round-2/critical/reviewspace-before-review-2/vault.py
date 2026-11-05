from contextlib import closing
import sqlite3


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


def balance(path, tenant, account):
    _validate_names(tenant, account)
    with closing(sqlite3.connect(path)) as con:
        row = con.execute(
            'SELECT balance FROM accounts WHERE tenant=? AND name=?',
            (tenant, account),
        ).fetchone()
        if row is None:
            raise ValueError('account unavailable')
        return row[0]


def _write_one(con, sql, values):
    # A trigger may silently ignore a write; that cannot count as a transfer.
    if con.execute(sql, values).rowcount != 1:
        raise sqlite3.IntegrityError('transfer write failed')


def transfer(path, tenant, source, target, amount, key):
    _validate_names(tenant, source, target, key)
    if (source == target or isinstance(amount, bool)
            or not isinstance(amount, int) or amount <= 0):
        raise ValueError('invalid request')

    receipt = dict(tenant=tenant, key=key, source=source,
                   target=target, amount=amount)
    with closing(sqlite3.connect(path, timeout=30)) as con, con:
        con.row_factory = sqlite3.Row
        # Acquire the writer lock before checking balances or replay state.
        # Separate connections then observe the preceding committed transfer.
        con.execute('BEGIN IMMEDIATE')
        accounts = {
            row['name']: row['balance']
            for row in con.execute(
                'SELECT name,balance FROM accounts '
                'WHERE tenant=? AND name IN (?,?)',
                (tenant, source, target),
            )
        }
        if source not in accounts or target not in accounts:
            raise ValueError('account unavailable')

        old = con.execute(
            'SELECT tenant,key,source,target,amount FROM transfers '
            'WHERE tenant=? AND key=?', (tenant, key),
        ).fetchone()
        if old is not None:
            if dict(old) != receipt:
                raise ValueError('key conflict')
            return dict(old)

        if accounts[source] < amount:
            raise ValueError('insufficient funds')

        # Bind integer results rather than letting SQLite promote overflowing
        # integer arithmetic to floating point.
        _write_one(con, 'UPDATE accounts SET balance=? WHERE tenant=? AND name=?',
                   (accounts[source] - amount, tenant, source))
        _write_one(con, 'UPDATE accounts SET balance=? WHERE tenant=? AND name=?',
                   (accounts[target] + amount, tenant, target))
        values = (tenant, key, source, target, amount)
        _write_one(con, 'INSERT INTO transfers (tenant,key,source,target,amount) '
                   'VALUES (?,?,?,?,?)', values)
        _write_one(con, 'INSERT INTO audit (tenant,key,source,target,amount) '
                   'VALUES (?,?,?,?,?)', values)
        return receipt
