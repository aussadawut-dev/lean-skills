from contextlib import closing
import sqlite3


def _require_names(*values):
    if any(not isinstance(value, str) or not value for value in values):
        raise ValueError('invalid request')


def _write_one(con, statement, values):
    if con.execute(statement, values).rowcount != 1:
        raise sqlite3.IntegrityError('required transfer write did not occur')


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


def balance(path, tenant, account):
    _require_names(tenant, account)
    with closing(sqlite3.connect(path)) as con:
        row = con.execute(
            'SELECT balance FROM accounts WHERE tenant=? AND name=?',
            (tenant, account),
        ).fetchone()
        if row is None:
            raise ValueError('account unavailable')
        return row[0]


def transfer(path, tenant, source, target, amount, key):
    _require_names(tenant, source, target, key)
    if not isinstance(amount, int) or isinstance(amount, bool) or amount <= 0:
        raise ValueError('invalid request')
    if source == target:
        raise ValueError('invalid request')

    # Reserve the writer before checking receipts or funds. Separate connections
    # then see the previous transfer's committed state before making a decision.
    with closing(sqlite3.connect(path, timeout=30)) as con, con:
        con.row_factory = sqlite3.Row
        con.execute('BEGIN IMMEDIATE')
        old = con.execute(
            'SELECT tenant,key,source,target,amount FROM transfers '
            'WHERE tenant=? AND key=?',
            (tenant, key),
        ).fetchone()
        if old is not None:
            if (old['source'], old['target'], old['amount']) != (source, target, amount):
                raise ValueError('key conflict')
            return dict(old)

        accounts = dict(con.execute(
            'SELECT name,balance FROM accounts WHERE tenant=? AND name IN (?,?)',
            (tenant, source, target),
        ))
        if source not in accounts or target not in accounts:
            raise ValueError('account unavailable')
        if accounts[source] < amount:
            raise ValueError('insufficient funds')

        # Compute with Python integers so SQLite cannot silently round an
        # overflowing balance into a floating-point value. Binding a value that
        # SQLite cannot store raises and rolls back the entire transaction.
        _write_one(
            con,
            'UPDATE accounts SET balance=? WHERE tenant=? AND name=?',
            (accounts[source] - amount, tenant, source),
        )
        _write_one(
            con,
            'UPDATE accounts SET balance=? WHERE tenant=? AND name=?',
            (accounts[target] + amount, tenant, target),
        )
        receipt = dict(tenant=tenant, key=key, source=source, target=target, amount=amount)
        values = (tenant, key, source, target, amount)
        _write_one(con, 'INSERT INTO transfers (tenant,key,source,target,amount) VALUES (?,?,?,?,?)', values)
        _write_one(con, 'INSERT INTO audit (tenant,key,source,target,amount) VALUES (?,?,?,?,?)', values)
        return receipt
