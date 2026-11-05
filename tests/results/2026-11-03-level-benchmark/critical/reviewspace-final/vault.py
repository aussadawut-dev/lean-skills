import sqlite3
from contextlib import closing


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


def _require_strings(*values):
    if any(not isinstance(value, str) or not value for value in values):
        raise ValueError("invalid request")


def _account_balance(con, tenant, account):
    row = con.execute(
        "SELECT balance FROM accounts WHERE tenant = ? AND name = ?",
        (tenant, account),
    ).fetchone()
    if row is None:
        # Missing and inaccessible accounts must be indistinguishable.
        raise ValueError("account unavailable")
    return row[0]


def balance(path, tenant, account):
    _require_strings(tenant, account)
    with closing(sqlite3.connect(path)) as con:
        return _account_balance(con, tenant, account)


def transfer(path, tenant, source, target, amount, key):
    _require_strings(tenant, source, target, key)
    if (
        not isinstance(amount, int)
        or isinstance(amount, bool)
        or amount <= 0
        or source == target
    ):
        raise ValueError("invalid request")

    with closing(sqlite3.connect(path, timeout=30)) as con, con:
        con.row_factory = sqlite3.Row
        # Serialize writers before either the replay check or the balance read.
        # The connection context commits all four writes, or rolls them all back.
        con.execute("BEGIN IMMEDIATE")
        funds = _account_balance(con, tenant, source)
        target_funds = _account_balance(con, tenant, target)
        old = con.execute(
            "SELECT tenant, key, source, target, amount FROM transfers "
            "WHERE tenant = ? AND key = ?",
            (tenant, key),
        ).fetchone()
        if old is not None:
            if (old["source"], old["target"], old["amount"]) != (source, target, amount):
                raise ValueError("key conflict")
            return dict(old)

        if funds < amount:
            raise ValueError("insufficient funds")

        # Bind integer results so SQLite cannot silently promote an overflow to REAL.
        # RAISE(IGNORE) can suppress a write without raising a SQLite exception.
        if con.execute(
            "UPDATE accounts SET balance = ? WHERE tenant = ? AND name = ?",
            (funds - amount, tenant, source),
        ).rowcount != 1:
            raise sqlite3.DatabaseError("transfer write failed")
        if con.execute(
            "UPDATE accounts SET balance = ? WHERE tenant = ? AND name = ?",
            (target_funds + amount, tenant, target),
        ).rowcount != 1:
            raise sqlite3.DatabaseError("transfer write failed")
        values = (tenant, key, source, target, amount)
        if con.execute(
            "INSERT INTO transfers (tenant, key, source, target, amount) "
            "VALUES (?, ?, ?, ?, ?)",
            values,
        ).rowcount != 1:
            raise sqlite3.DatabaseError("transfer write failed")
        if con.execute(
            "INSERT INTO audit (tenant, key, source, target, amount) "
            "VALUES (?, ?, ?, ?, ?)",
            values,
        ).rowcount != 1:
            raise sqlite3.DatabaseError("transfer write failed")
        return dict(tenant=tenant, key=key, source=source, target=target, amount=amount)
