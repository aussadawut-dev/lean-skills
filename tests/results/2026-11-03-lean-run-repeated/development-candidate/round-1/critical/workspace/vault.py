import sqlite3
from contextlib import closing


def _require_text(*values):
    if any(not isinstance(value, str) or not value for value in values):
        raise ValueError("Invalid request")


def _account_balance(con, tenant, account):
    row = con.execute(
        "SELECT balance FROM accounts WHERE tenant=? AND name=?",
        (tenant, account),
    ).fetchone()
    if row is None:
        raise ValueError("Account unavailable")
    if not isinstance(row[0], int):
        raise sqlite3.DatabaseError("Invalid stored balance")
    return row[0]


def _receipt(con, tenant, key):
    row = con.execute(
        "SELECT tenant, key, source, target, amount FROM transfers "
        "WHERE tenant=? AND key=?",
        (tenant, key),
    ).fetchone()
    return dict(row) if row is not None else None


def _require_write(cursor):
    # RAISE(IGNORE) in a trigger can silently suppress a successful statement.
    if cursor.rowcount != 1:
        raise sqlite3.DatabaseError("Incomplete transfer")


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
    _require_text(tenant, account)
    with closing(sqlite3.connect(path)) as con:
        return _account_balance(con, tenant, account)


def transfer(path, tenant, source, target, amount, key):
    _require_text(tenant, source, target, key)
    if (
        source == target
        or not isinstance(amount, int)
        or isinstance(amount, bool)
        or amount <= 0
    ):
        raise ValueError("Invalid request")

    receipt = dict(tenant=tenant, key=key, source=source, target=target, amount=amount)
    with closing(sqlite3.connect(path, timeout=30)) as con, con:
        con.row_factory = sqlite3.Row
        # Serialize the receipt lookup and funds check with all writes. Waiting
        # duplicate requests will observe the first request's committed receipt.
        con.execute("BEGIN IMMEDIATE")
        old = _receipt(con, tenant, key)
        if old is not None:
            if old != receipt:
                raise ValueError("Key conflict")
            return old

        funds = _account_balance(con, tenant, source)
        target_funds = _account_balance(con, tenant, target)
        if funds < amount:
            raise ValueError("Insufficient funds")
        credited = target_funds + amount
        if credited > 2**63 - 1:
            # SQLite otherwise promotes overflowing integer arithmetic to REAL.
            raise ValueError("Balance out of range")

        _require_write(con.execute(
            "UPDATE accounts SET balance=? WHERE tenant=? AND name=? AND balance=?",
            (funds - amount, tenant, source, funds),
        ))
        _require_write(con.execute(
            "UPDATE accounts SET balance=? WHERE tenant=? AND name=? AND balance=?",
            (credited, tenant, target, target_funds),
        ))
        values = (tenant, key, source, target, amount)
        _require_write(con.execute(
            "INSERT INTO transfers (tenant, key, source, target, amount) "
            "VALUES (?, ?, ?, ?, ?)", values,
        ))
        _require_write(con.execute(
            "INSERT INTO audit (tenant, key, source, target, amount) "
            "VALUES (?, ?, ?, ?, ?)", values,
        ))

        # AFTER triggers can undo or change a write despite a rowcount of one.
        # Check all required effects while rollback is still possible.
        balances = dict(con.execute(
            "SELECT name, balance FROM accounts WHERE tenant=? AND name IN (?, ?)",
            (tenant, source, target),
        ))
        audit = con.execute(
            "SELECT tenant, key, source, target, amount FROM audit "
            "WHERE tenant=? AND key=?", (tenant, key),
        ).fetchall()
        if (
            balances != {source: funds - amount, target: credited}
            or _receipt(con, tenant, key) != receipt
            or [tuple(row) for row in audit] != [values]
        ):
            raise sqlite3.DatabaseError("Incomplete transfer")
        # The connection context commits all four effects together, or rolls
        # them all back on any exception (including a failed commit).
        return receipt
