"""Tenant-scoped balances and durable, atomic SQLite transfers."""

from contextlib import closing
import sqlite3


def _validate_names(*values):
    if any(not isinstance(value, str) or not value for value in values):
        raise ValueError("invalid request")


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


def balance(path, tenant, account):
    _validate_names(tenant, account)
    with closing(sqlite3.connect(path)) as con:
        row = con.execute(
            "SELECT balance FROM accounts WHERE tenant=? AND name=?",
            (tenant, account),
        ).fetchone()
        if row is None:
            raise ValueError("account unavailable")
        return row[0]


def transfer(path, tenant, source, target, amount, key):
    _validate_names(tenant, source, target, key)
    if source == target or isinstance(amount, bool) or not isinstance(amount, int) or amount <= 0:
        raise ValueError("invalid request")

    with closing(sqlite3.connect(path, timeout=30)) as con, con:
        con.row_factory = sqlite3.Row
        # Acquire the writer lock before replay and balance checks. A waiting
        # caller then observes the committed receipt or the latest balances.
        con.execute("BEGIN IMMEDIATE")
        old = con.execute(
            "SELECT tenant,key,source,target,amount FROM transfers WHERE tenant=? AND key=?",
            (tenant, key),
        ).fetchone()
        if old is not None:
            if (old["source"], old["target"], old["amount"]) != (source, target, amount):
                raise ValueError("key conflict")
            return dict(old)

        accounts = {
            row["name"]: row["balance"]
            for row in con.execute(
                "SELECT name,balance FROM accounts WHERE tenant=? AND name IN (?,?)",
                (tenant, source, target),
            )
        }
        if len(accounts) != 2:
            raise ValueError("account unavailable")
        if accounts[source] < amount:
            raise ValueError("insufficient funds")

        for account, funds in (
            (source, accounts[source] - amount),
            (target, accounts[target] + amount),
        ):
            # Bind integer results instead of letting SQLite silently promote
            # overflowing integer arithmetic to an imprecise REAL value.
            changed = con.execute(
                "UPDATE accounts SET balance=? WHERE tenant=? AND name=?",
                (funds, tenant, account),
            )
            if changed.rowcount != 1:
                raise sqlite3.IntegrityError("account update failed")

        values = (tenant, key, source, target, amount)
        receipt = con.execute(
            "INSERT INTO transfers (tenant,key,source,target,amount) VALUES (?,?,?,?,?)",
            values,
        )
        if receipt.rowcount != 1:
            raise sqlite3.IntegrityError("receipt insert failed")
        audit = con.execute(
            "INSERT INTO audit (tenant,key,source,target,amount) VALUES (?,?,?,?,?)",
            values,
        )
        if audit.rowcount != 1:
            raise sqlite3.IntegrityError("audit insert failed")
        return dict(tenant=tenant, key=key, source=source, target=target, amount=amount)
