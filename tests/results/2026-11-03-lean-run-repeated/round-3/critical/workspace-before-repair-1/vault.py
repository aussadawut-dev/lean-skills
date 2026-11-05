"""Tenant-scoped account reads and atomic, idempotent SQLite transfers."""

import sqlite3
from contextlib import closing


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


def _validate_text(*values):
    if any(not isinstance(value, str) or not value for value in values):
        raise ValueError("invalid request")


def _read_balance(con, tenant, account):
    row = con.execute(
        "SELECT balance FROM accounts WHERE tenant=? AND name=?",
        (tenant, account),
    ).fetchone()
    if row is None:
        raise ValueError("account unavailable")
    if not isinstance(row[0], int):
        raise sqlite3.DatabaseError("invalid stored balance")
    return row[0]


def _write_one(con, statement, parameters):
    # RAISE(IGNORE) triggers can silently suppress a write without raising.
    if con.execute(statement, parameters).rowcount != 1:
        raise sqlite3.IntegrityError("required write did not complete")


def balance(path, tenant, account):
    _validate_text(tenant, account)
    with closing(sqlite3.connect(path)) as con:
        return _read_balance(con, tenant, account)


def transfer(path, tenant, source, target, amount, key):
    _validate_text(tenant, source, target, key)
    if (source == target or isinstance(amount, bool)
            or not isinstance(amount, int) or amount <= 0):
        raise ValueError("invalid request")

    receipt = dict(tenant=tenant, key=key, source=source, target=target, amount=amount)
    with closing(sqlite3.connect(path, timeout=30)) as con, con:
        con.row_factory = sqlite3.Row
        # Acquire the writer lock before reading receipts or funds. Concurrent
        # callers then see the committed outcome of the preceding transfer.
        con.execute("BEGIN IMMEDIATE")
        old = con.execute(
            "SELECT tenant, key, source, target, amount FROM transfers WHERE tenant=? AND key=?",
            (tenant, key),
        ).fetchone()
        if old is not None:
            if dict(old) != receipt:
                raise ValueError("key conflict")
            return dict(old)

        funds = _read_balance(con, tenant, source)
        target_funds = _read_balance(con, tenant, target)
        if funds < amount:
            raise ValueError("insufficient funds")
        credited = target_funds + amount
        # SQLite arithmetic would otherwise silently promote overflow to REAL.
        if credited > 2**63 - 1:
            raise ValueError("balance out of range")

        _write_one(con, "UPDATE accounts SET balance=? WHERE tenant=? AND name=?",
                   (funds - amount, tenant, source))
        _write_one(con, "UPDATE accounts SET balance=? WHERE tenant=? AND name=?",
                   (credited, tenant, target))
        values = (tenant, key, source, target, amount)
        _write_one(con, "INSERT INTO transfers (tenant, key, source, target, amount) "
                   "VALUES (?, ?, ?, ?, ?)", values)
        _write_one(con, "INSERT INTO audit (tenant, key, source, target, amount) "
                   "VALUES (?, ?, ?, ?, ?)", values)
        # The connection context commits only after all four writes succeed,
        # and rolls them all back on any write or commit failure.
        return receipt
