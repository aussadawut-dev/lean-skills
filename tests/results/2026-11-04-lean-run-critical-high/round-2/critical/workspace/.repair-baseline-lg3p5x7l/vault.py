import sqlite3
from contextlib import closing

from _vault_effects import Effects


def init_db(path):
    with closing(sqlite3.connect(path)) as con, con:
        con.executescript("""
        CREATE TABLE IF NOT EXISTS accounts (
          tenant TEXT, name TEXT, balance INTEGER,
          PRIMARY KEY(tenant,name));
        CREATE TABLE IF NOT EXISTS transfers (
          tenant TEXT, key TEXT, source TEXT, target TEXT, amount INTEGER,
          PRIMARY KEY(tenant,key));
        CREATE TABLE IF NOT EXISTS audit (
          tenant TEXT, key TEXT, source TEXT, target TEXT, amount INTEGER);
        """)


def _validate_names(*values):
    if any(not isinstance(value, str) or not value for value in values):
        raise ValueError("invalid request")


def _account_balance(con, tenant, account):
    row = con.execute(
        "SELECT balance FROM accounts WHERE tenant=? AND name=?",
        (tenant, account),
    ).fetchone()
    if row is None:
        raise ValueError("account unavailable")
    if not isinstance(row[0], int):
        raise sqlite3.DataError("invalid account balance")
    return row[0]


def balance(path, tenant, account):
    _validate_names(tenant, account)
    with closing(sqlite3.connect(path, timeout=30)) as con:
        return _account_balance(con, tenant, account)


def transfer(path, tenant, source, target, amount, key):
    _validate_names(tenant, source, target, key)
    if source == target or isinstance(amount, bool) or not isinstance(amount, int) or amount <= 0:
        raise ValueError("invalid request")

    with closing(sqlite3.connect(path, timeout=30)) as con, con:
        con.row_factory = sqlite3.Row
        # Acquire the writer lock before reading receipts or balances. Separate
        # connections then serialize replay decisions and cannot spend stale funds.
        con.execute("BEGIN IMMEDIATE")
        old = con.execute(
            "SELECT tenant, key, source, target, amount FROM transfers WHERE tenant=? AND key=?",
            (tenant, key),
        ).fetchone()
        if old is not None:
            if (old["source"], old["target"], old["amount"]) != (source, target, amount):
                raise ValueError("key conflict")
            return dict(old)
        funds = _account_balance(con, tenant, source)
        target_funds = _account_balance(con, tenant, target)
        if funds < amount:
            raise ValueError("insufficient funds")

        effects = Effects(con)
        con.execute(
            "UPDATE accounts SET balance=? WHERE tenant=? AND name=?",
            (funds - amount, tenant, source),
        )
        # Compute with Python integers so SQLite cannot silently promote an
        # overflowing credit to REAL. A binding failure rolls back the debit.
        con.execute(
            "UPDATE accounts SET balance=? WHERE tenant=? AND name=?",
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
        effects.verify(tenant, source, target, funds, target_funds, amount, key)
        # The connection context commits all four effects before returning, and
        # rolls all of them back on any statement or commit failure.
        return dict(tenant=tenant, key=key, source=source, target=target, amount=amount)
