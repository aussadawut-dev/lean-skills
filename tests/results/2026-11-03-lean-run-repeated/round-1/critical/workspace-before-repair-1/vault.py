"""Tenant-scoped balances and atomic, idempotent SQLite transfers."""

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


def _validate_strings(*values):
    if any(not isinstance(value, str) or not value for value in values):
        raise ValueError("invalid request")


def _account_balance(con, tenant, account):
    row = con.execute(
        "SELECT balance FROM accounts WHERE tenant=? AND name=?", (tenant, account)
    ).fetchone()
    if row is None:
        raise ValueError("account unavailable")
    return row[0]


def balance(path, tenant, account):
    _validate_strings(tenant, account)
    with closing(sqlite3.connect(path)) as con:
        return _account_balance(con, tenant, account)


def _write_one(con, statement, parameters):
    # RAISE(IGNORE) triggers can suppress a write without raising an exception.
    if con.execute(statement, parameters).rowcount != 1:
        raise sqlite3.IntegrityError("required write did not apply")


def transfer(path, tenant, source, target, amount, key):
    _validate_strings(tenant, source, target, key)
    if source == target or isinstance(amount, bool) or not isinstance(amount, int) or amount <= 0:
        raise ValueError("invalid request")

    receipt = dict(tenant=tenant, key=key, source=source, target=target, amount=amount)
    with closing(sqlite3.connect(path, timeout=30)) as con:
        con.row_factory = sqlite3.Row
        with con:
            # Acquire the writer lock before reading receipts or balances. Other
            # connections then observe the committed result before making a decision.
            con.execute("BEGIN IMMEDIATE")
            old = con.execute(
                "SELECT tenant, key, source, target, amount FROM transfers WHERE tenant=? AND key=?",
                (tenant, key),
            ).fetchone()
            if old is not None:
                original = dict(old)
                if original != receipt:
                    raise ValueError("key conflict")
                return original

            funds = _account_balance(con, tenant, source)
            target_funds = _account_balance(con, tenant, target)
            if funds < amount:
                raise ValueError("insufficient funds")

            # Bind integer results instead of allowing SQLite arithmetic to
            # silently promote an overflowing integer balance to a float.
            _write_one(con, "UPDATE accounts SET balance=? WHERE tenant=? AND name=?",
                       (funds - amount, tenant, source))
            _write_one(con, "UPDATE accounts SET balance=? WHERE tenant=? AND name=?",
                       (target_funds + amount, tenant, target))
            values = (tenant, key, source, target, amount)
            _write_one(con, "INSERT INTO transfers (tenant, key, source, target, amount) VALUES (?, ?, ?, ?, ?)",
                       values)
            _write_one(con, "INSERT INTO audit (tenant, key, source, target, amount) VALUES (?, ?, ?, ?, ?)",
                       values)
        return receipt
