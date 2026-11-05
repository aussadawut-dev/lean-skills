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


def _guard_effects(con, account_changes, receipt):
    # These connection-local tables contain only the authenticated request and
    # its two balances. Observe actual writes inside SQLite instead of reading
    # other tenants' accounts or receipts into application integrity snapshots.
    # Use execute, not executescript, to keep setup inside BEGIN IMMEDIATE.
    con.execute("CREATE TEMP TABLE _vault_accounts "
                "(tenant, name, before, after, seen INTEGER DEFAULT 0)")
    con.executemany("INSERT INTO _vault_accounts (tenant, name, before, after) "
                    "VALUES (?, ?, ?, ?)", account_changes)
    con.execute("CREATE TEMP TABLE _vault_receipt "
                "(tenant, key, source, target, amount, "
                "transfers INTEGER DEFAULT 0, audit INTEGER DEFAULT 0)")
    con.execute("INSERT INTO _vault_receipt (tenant, key, source, target, amount) "
                "VALUES (?, ?, ?, ?, ?)", receipt)

    reject = "SELECT RAISE(ABORT, 'unexpected stored transfer effects');"
    require_match = ("SELECT CASE WHEN changes() != 1 THEN "
                     "RAISE(ABORT, 'unexpected stored transfer effects') END;")
    columns = {
        "accounts": ("tenant", "name", "balance"),
        "transfers": ("tenant", "key", "source", "target", "amount"),
        "audit": ("tenant", "key", "source", "target", "amount"),
    }
    for table, fields in columns.items():
        # A physical relocation must not replace another row. SQLite can omit
        # DELETE triggers for REPLACE, so enforce rowid uniqueness before the
        # move, inside SQLite, without fetching any account/receipt contents.
        con.execute(f"CREATE TEMP TRIGGER _vault_{table}_rowid "
                    f"BEFORE UPDATE ON main.{table} "
                    "WHEN OLD.rowid IS NOT NEW.rowid BEGIN "
                    "SELECT CASE WHEN EXISTS "
                    f"(SELECT 1 FROM {table} WHERE rowid=NEW.rowid) THEN "
                    "RAISE(ABORT, 'unexpected stored transfer effects') END; END")
        # No-op updates and rowid relocation leave all contracted columns equal.
        changed = " OR ".join(f"OLD.{field} IS NOT NEW.{field}" for field in fields)
        if table == "accounts":
            update = ("UPDATE _vault_accounts SET seen=seen+1 "
                      "WHERE tenant IS OLD.tenant AND tenant IS NEW.tenant "
                      "AND name IS OLD.name AND name IS NEW.name "
                      "AND before IS OLD.balance AND after IS NEW.balance; "
                      + require_match)
            insert = reject
        else:
            update = reject
            matches = " AND ".join(f"{field} IS NEW.{field}" for field in fields)
            insert = (f"UPDATE _vault_receipt SET {table}={table}+1 "
                      f"WHERE {matches}; " + require_match)
        for event, condition, body in (("INSERT", "", insert),
                                       ("UPDATE", f"WHEN {changed}", update),
                                       ("DELETE", "", reject)):
            # AFTER sees only effective writes, allowing INSERT OR IGNORE and
            # no-match updates. Reject unexpected inserts too: REPLACE need not
            # fire DELETE triggers when recursive_triggers is disabled.
            con.execute(f"CREATE TEMP TRIGGER _vault_{table}_{event} "
                        f"AFTER {event} ON main.{table} {condition} BEGIN {body} END")


def _verify_effects(con):
    # Only request-local counters are read. Every required write must occur once;
    # the guards reject any other change to the three tables' contracted data.
    if con.execute("SELECT 1 FROM _vault_accounts WHERE seen != 1 "
                   "UNION ALL SELECT 1 FROM _vault_receipt "
                   "WHERE transfers != 1 OR audit != 1 LIMIT 1").fetchone() is not None:
        raise sqlite3.IntegrityError("unexpected stored transfer effects")


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

        values = (tenant, key, source, target, amount)
        _guard_effects(con, ((tenant, source, funds, funds - amount),
                             (tenant, target, target_funds, credited)), values)

        _write_one(con, "UPDATE accounts SET balance=? WHERE tenant=? AND name=?",
                   (funds - amount, tenant, source))
        _write_one(con, "UPDATE accounts SET balance=? WHERE tenant=? AND name=?",
                   (credited, tenant, target))
        _write_one(con, "INSERT INTO transfers (tenant, key, source, target, amount) "
                   "VALUES (?, ?, ?, ?, ?)", values)
        _write_one(con, "INSERT INTO audit (tenant, key, source, target, amount) "
                   "VALUES (?, ?, ?, ?, ?)", values)
        _verify_effects(con)
        return receipt
