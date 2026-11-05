from contextlib import closing
import sqlite3


def _validate_names(*names):
    if any(not isinstance(name, str) or not name for name in names):
        raise ValueError('invalid request')


def _account_balance(con, tenant, account):
    row = con.execute(
        'SELECT balance FROM accounts WHERE tenant = ? AND name = ?',
        (tenant, account),
    ).fetchone()
    if row is None or not isinstance(row[0], int):
        # Missing and inaccessible accounts deliberately have the same error.
        raise ValueError('invalid request')
    return row[0]


def _write_one(con, statement, values):
    # A trigger can suppress a statement with RAISE(IGNORE) without raising a
    # SQLite exception. Treat a missing required effect as a storage failure.
    if con.execute(statement, values).rowcount != 1:
        raise sqlite3.IntegrityError('required write was not applied')


def init_db(path):
    with closing(sqlite3.connect(path, timeout=30)) as con:
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
    with closing(sqlite3.connect(path, timeout=30)) as con:
        return _account_balance(con, tenant, account)


def transfer(path, tenant, source, target, amount, key):
    _validate_names(tenant, source, target, key)
    if source == target or isinstance(amount, bool) or not isinstance(amount, int) or amount <= 0:
        raise ValueError('invalid request')

    receipt = dict(tenant=tenant, key=key, source=source, target=target, amount=amount)
    with closing(sqlite3.connect(path, timeout=30, isolation_level=None)) as con:
        con.row_factory = sqlite3.Row
        with con:
            # Serialize writers before reading either balances or replay keys.
            # A waiting request then sees the preceding transaction's commit.
            con.execute('BEGIN IMMEDIATE')
            funds = _account_balance(con, tenant, source)
            destination = _account_balance(con, tenant, target)
            old = con.execute(
                'SELECT tenant, key, source, target, amount FROM transfers '
                'WHERE tenant = ? AND key = ?', (tenant, key),
            ).fetchone()
            if old is not None:
                if dict(old) != receipt:
                    raise ValueError('invalid request')
                return dict(old)

            if funds < amount:
                raise ValueError('invalid request')

            # Bind integer results: SQLite arithmetic otherwise converts an
            # overflowing integer credit into an inexact floating point value.
            _write_one(con, 'UPDATE accounts SET balance = ? WHERE tenant = ? AND name = ?',
                       (funds - amount, tenant, source))
            _write_one(con, 'UPDATE accounts SET balance = ? WHERE tenant = ? AND name = ?',
                       (destination + amount, tenant, target))
            values = (tenant, key, source, target, amount)
            _write_one(con, 'INSERT INTO transfers (tenant, key, source, target, amount) '
                       'VALUES (?, ?, ?, ?, ?)', values)
            _write_one(con, 'INSERT INTO audit (tenant, key, source, target, amount) '
                       'VALUES (?, ?, ?, ?, ?)', values)
        # The context commits all four effects, or rolls them all back on error.
        return receipt
