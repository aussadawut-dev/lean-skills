import sqlite3
from collections import Counter
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


def _audit_contents(con):
    # Audit has no unique key: preserve every contracted value and its multiplicity.
    # Internal rowids may legitimately change in an existing trigger.
    return Counter(tuple(row) for row in con.execute(
        "SELECT tenant, key, source, target, amount FROM audit"
    ))


def _row_counts(con):
    # Only cardinalities, never other tenants' account or receipt contents.
    return tuple(con.execute(
        "SELECT (SELECT COUNT(*) FROM accounts), (SELECT COUNT(*) FROM transfers)"
    ).fetchone())


def _guard_preserved_rows(con, values):
    # Connection-local guards inspect affected rows, so preservation needs no
    # unscoped account/receipt lookup and does not alter the stored schema/triggers.
    con.execute("CREATE TEMP TABLE _vault_request (tenant, key, source, target, amount)")
    con.execute("INSERT INTO temp._vault_request VALUES (?, ?, ?, ?, ?)", values)
    columns = ("tenant", "key", "source", "target", "amount")
    guards = (
        ("accounts", "INSERT", "1"),
        ("accounts", "DELETE", "1"),
        ("accounts", "UPDATE", """
            OLD.tenant IS NOT NEW.tenant OR OLD.name IS NOT NEW.name OR
            (OLD.balance IS NOT NEW.balance AND NOT EXISTS (
                SELECT 1 FROM temp._vault_request
                WHERE tenant IS OLD.tenant AND OLD.name IN (source, target)
            ))
        """),
        ("transfers", "DELETE", "1"),
        ("transfers", "UPDATE", " OR ".join(
            f"OLD.{column} IS NOT NEW.{column}" for column in columns
        )),
        ("transfers", "INSERT", "NOT EXISTS (SELECT 1 FROM temp._vault_request WHERE "
         + " AND ".join(f"{column} IS NEW.{column}" for column in columns) + ")"),
    )
    for table, event, condition in guards:
        # execute(), not executescript(): keep the existing transaction open.
        con.execute(
            f"CREATE TEMP TRIGGER _vault_{table}_{event} BEFORE {event} ON main.{table} "
            f"WHEN {condition} BEGIN SELECT RAISE(ABORT, 'incomplete transfer'); END"
        )


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
        values = (tenant, key, source, target, amount)
        expected_audit = _audit_contents(con)
        expected_audit[values] += 1
        account_count, receipt_count = _row_counts(con)
        _guard_preserved_rows(con, values)
        for account, new_balance in expected.items():
            # Bind integer results instead of letting SQLite arithmetic overflow
            # into a floating-point balance. A binding failure also rolls back.
            _write_one(
                con,
                "UPDATE accounts SET balance = ? WHERE tenant = ? AND name = ?",
                (new_balance, tenant, account),
            )
        _write_one(
            con,
            "INSERT INTO transfers (tenant, key, source, target, amount) VALUES (?, ?, ?, ?, ?)",
            values,
        )
        _write_one(
            con,
            "INSERT INTO audit (tenant, key, source, target, amount) VALUES (?, ?, ?, ?, ?)",
            values,
        )

        # Validate the complete audit, including unrelated history and duplicates.
        # REPLACE can silently delete a row without firing DELETE triggers; the
        # guards prohibit extra rows, and these counts detect implicit deletions.
        if (
            _balances(con, tenant, source, target) != expected
            or _receipt(con, tenant, key) != receipt
            or _audit_contents(con) != expected_audit
            or _row_counts(con) != (account_count, receipt_count + 1)
        ):
            raise sqlite3.IntegrityError("incomplete transfer")
        return receipt
