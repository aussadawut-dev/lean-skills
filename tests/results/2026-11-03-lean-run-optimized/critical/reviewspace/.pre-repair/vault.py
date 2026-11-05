from contextlib import closing
import sqlite3


def _validate_names(*values):
    if any(not isinstance(value, str) or not value for value in values):
        raise ValueError("invalid request")


def _account_balance(con, tenant, account):
    row = con.execute(
        "SELECT balance FROM accounts WHERE tenant = ? AND name = ?",
        (tenant, account),
    ).fetchone()
    if row is None:
        raise ValueError("account unavailable")
    return row[0]


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
    if isinstance(amount, bool) or not isinstance(amount, int) or amount <= 0:
        raise ValueError("invalid amount")
    if source == target:
        raise ValueError("accounts must differ")

    receipt = dict(tenant=tenant, key=key, source=source, target=target, amount=amount)
    with closing(sqlite3.connect(path, timeout=30)) as con, con:
        con.row_factory = sqlite3.Row
        # Acquire the write lock before reading balances or checking the key.
        # Other connections then observe either the whole transfer or none of it.
        con.execute("BEGIN IMMEDIATE")
        funds = _account_balance(con, tenant, source)
        target_funds = _account_balance(con, tenant, target)
        old = con.execute(
            "SELECT tenant, key, source, target, amount FROM transfers "
            "WHERE tenant = ? AND key = ?",
            (tenant, key),
        ).fetchone()
        if old is not None:
            if dict(old) != receipt:
                raise ValueError("key conflict")
            return dict(old)
        if funds < amount:
            raise ValueError("insufficient funds")

        # Bind Python integers so SQLite cannot silently promote an overflowing
        # credit to an imprecise REAL. Binding failures roll back the debit too.
        con.execute(
            "UPDATE accounts SET balance = ? WHERE tenant = ? AND name = ?",
            (funds - amount, tenant, source),
        )
        con.execute(
            "UPDATE accounts SET balance = ? WHERE tenant = ? AND name = ?",
            (target_funds + amount, tenant, target),
        )
        values = (tenant, key, source, target, amount)
        con.execute(
            "INSERT INTO transfers (tenant, key, source, target, amount) VALUES (?, ?, ?, ?, ?)",
            values,
        )
        con.execute(
            "INSERT INTO audit (tenant, key, source, target, amount) VALUES (?, ?, ?, ?, ?)",
            values,
        )
        return receipt
