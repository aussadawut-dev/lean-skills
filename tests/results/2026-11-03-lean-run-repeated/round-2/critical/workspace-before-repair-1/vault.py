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


def _require_strings(*values):
    if any(not isinstance(value, str) or not value for value in values):
        raise ValueError("invalid request")


def _stored_balance(value):
    if not isinstance(value, int):
        raise sqlite3.DataError("invalid stored balance")
    return value


def balance(path, tenant, account):
    _require_strings(tenant, account)
    with closing(sqlite3.connect(path)) as con:
        row = con.execute(
            "SELECT balance FROM accounts WHERE tenant = ? AND name = ?",
            (tenant, account),
        ).fetchone()
        if row is None:
            raise ValueError("invalid account")
        return _stored_balance(row[0])


def _balances(con, tenant, source, target):
    rows = con.execute(
        "SELECT name, balance FROM accounts WHERE tenant = ? AND name IN (?, ?)",
        (tenant, source, target),
    ).fetchall()
    return {row["name"]: _stored_balance(row["balance"]) for row in rows}


def _receipt(con, tenant, key):
    row = con.execute(
        "SELECT tenant, key, source, target, amount FROM transfers "
        "WHERE tenant = ? AND key = ?",
        (tenant, key),
    ).fetchone()
    return dict(row) if row is not None else None


def _write_one(con, statement, parameters):
    cursor = con.execute(statement, parameters)
    # A trigger using RAISE(IGNORE) reports success but may skip the write.
    if cursor.rowcount != 1:
        raise sqlite3.IntegrityError("incomplete transfer")
    return cursor


def _audit_count(con, tenant, key):
    return con.execute(
        "SELECT COUNT(*) FROM audit WHERE tenant = ? AND key = ?", (tenant, key)
    ).fetchone()[0]


def transfer(path, tenant, source, target, amount, key):
    _require_strings(tenant, source, target, key)
    if source == target or isinstance(amount, bool) or not isinstance(amount, int) or amount <= 0:
        raise ValueError("invalid request")

    receipt = dict(tenant=tenant, key=key, source=source, target=target, amount=amount)
    with closing(sqlite3.connect(path, timeout=30)) as con, con:
        con.row_factory = sqlite3.Row
        # Lock before reading the key or balances so separate connections cannot
        # both act on stale state. The context commits once, or rolls back all effects.
        con.execute("BEGIN IMMEDIATE")
        old = _receipt(con, tenant, key)
        if old is not None and old != receipt:
            raise ValueError("key conflict")

        funds = _balances(con, tenant, source, target)
        if len(funds) != 2:
            raise ValueError("invalid account")
        if old is not None:
            return old
        if funds[source] < amount:
            raise ValueError("insufficient funds")

        expected = {source: funds[source] - amount, target: funds[target] + amount}
        audit_count = _audit_count(con, tenant, key)
        for account, new_balance in expected.items():
            # Bind integer results instead of letting SQLite arithmetic overflow
            # into a floating-point balance. A binding failure also rolls back.
            _write_one(
                con,
                "UPDATE accounts SET balance = ? WHERE tenant = ? AND name = ?",
                (new_balance, tenant, account),
            )
        values = (tenant, key, source, target, amount)
        _write_one(
            con,
            "INSERT INTO transfers (tenant, key, source, target, amount) VALUES (?, ?, ?, ?, ?)",
            values,
        )
        audit_cursor = _write_one(
            con,
            "INSERT INTO audit (tenant, key, source, target, amount) VALUES (?, ?, ?, ?, ?)",
            values,
        )

        # Row counts alone cannot detect AFTER triggers that undo an effect.
        audit_row = con.execute(
            "SELECT tenant, key, source, target, amount FROM audit "
            "WHERE tenant = ? AND key = ? AND rowid = ?",
            (tenant, key, audit_cursor.lastrowid),
        ).fetchone()
        if (
            _balances(con, tenant, source, target) != expected
            or _receipt(con, tenant, key) != receipt
            or audit_row is None
            or dict(audit_row) != receipt
            or _audit_count(con, tenant, key) != audit_count + 1
        ):
            raise sqlite3.IntegrityError("incomplete transfer")
        return receipt
