"""Tenant-scoped balances and durable, atomic SQLite transfers."""

from contextlib import closing
import sqlite3


_RECEIPT = ("tenant", "key", "source", "target", "amount")
_TABLES = {
    "accounts": (("tenant", "name", "balance"), ("tenant", "name")),
    "transfers": (_RECEIPT, ("tenant", "key")),
    "audit": (_RECEIPT, _RECEIPT),
}


def _connect(path):
    return sqlite3.connect(path, timeout=30, isolation_level=None)


def _strings(*values):
    if any(not isinstance(value, str) or not value for value in values):
        raise ValueError("invalid request")


def init_db(path):
    with closing(_connect(path)) as con, con:
        con.execute("BEGIN")
        con.execute("""CREATE TABLE IF NOT EXISTS accounts (
            tenant TEXT, name TEXT, balance INTEGER,
            PRIMARY KEY(tenant,name))""")
        con.execute("""CREATE TABLE IF NOT EXISTS transfers (
            tenant TEXT, key TEXT, source TEXT, target TEXT, amount INTEGER,
            PRIMARY KEY(tenant,key))""")
        con.execute("""CREATE TABLE IF NOT EXISTS audit (
            tenant TEXT, key TEXT, source TEXT, target TEXT, amount INTEGER)""")


def balance(path, tenant, account):
    _strings(tenant, account)
    with closing(_connect(path)) as con:
        row = con.execute(
            "SELECT balance FROM accounts WHERE tenant=? AND name=?",
            (tenant, account),
        ).fetchone()
        if row is None:
            raise ValueError("account unavailable")
        if type(row[0]) is not int:
            raise sqlite3.DataError("invalid account balance")
        return row[0]


class _WriteGuard:
    """Check the logical write set, including side effects of stored triggers.

    Before-images of touched identities stay inside SQLite TEMP storage. No
    other tenant's account or receipt contents are loaded into Python. Capture
    both primary-key and rowid replacement victims: SQLite does not invoke
    DELETE triggers for REPLACE with its default recursive_triggers setting.
    Keeping that setting unchanged also preserves benign trigger behavior.

    Checking final values and multiplicity permits ignored writes, no-op
    updates and rowid relocation, while catching skipped/extra effects and
    destruction of unrelated history. TEMP objects disappear on close.
    """

    def __init__(self, con):
        self.con = con
        for table, (columns, keys) in _TABLES.items():
            # Additional UNIQUE indexes can cause implicit REPLACE deletions
            # beyond the primary-key/rowid victims captured below. Such a
            # deletion must also lose a row: all effective additions and
            # updates are journaled and checked separately. Keep only the
            # aggregate in SQLite, without reading other tenants into Python.
            added = 0 if table == "accounts" else 1
            con.execute(f"CREATE TEMP TABLE _vault_count_{table} AS "
                        f"SELECT count(*)+{added} AS expected FROM main.{table}")
            # No affinity or uniqueness constraints: retain even malformed
            # unrelated values and duplicate audit rows without decoding them.
            con.execute(f"CREATE TEMP TABLE _vault_before_{table} ({', '.join(columns)})")
            con.execute(f"CREATE TEMP TABLE _vault_seen_{table} ({', '.join(keys)})")
            for event in ("INSERT", "UPDATE", "DELETE"):
                statements = []
                if event != "INSERT":
                    statements.extend(self._remember(table, "OLD"))
                if event != "DELETE":
                    statements.extend(self._remember(table, "NEW"))
                    victim = " AND ".join(f"v.{key} IS r.{key}" for key in keys)
                    unseen = self._unseen(table, "r")
                    # Include all duplicates of an audit victim, not just the
                    # row occupying the colliding rowid.
                    statements.append(f"""
                        INSERT INTO _vault_before_{table}
                        SELECT {', '.join('r.' + col for col in columns)}
                        FROM main.{table} AS r
                        WHERE EXISTS (SELECT 1 FROM main.{table} AS v
                            WHERE v.rowid=NEW.rowid AND {victim}) AND {unseen}
                    """)
                    statements.append(f"""
                        INSERT INTO _vault_seen_{table}
                        SELECT {', '.join('r.' + key for key in keys)}
                        FROM main.{table} AS r
                        WHERE r.rowid=NEW.rowid AND {unseen}
                    """)
                con.execute(f"""CREATE TEMP TRIGGER _vault_{table}_{event}
                    BEFORE {event} ON main.{table} BEGIN
                    {';'.join(statements)};
                    END""")

    @staticmethod
    def _unseen(table, reference):
        keys = _TABLES[table][1]
        match = " AND ".join(f"s.{key} IS {reference}.{key}" for key in keys)
        return f"NOT EXISTS (SELECT 1 FROM _vault_seen_{table} AS s WHERE {match})"

    def _remember(self, table, reference):
        columns, keys = _TABLES[table]
        match = " AND ".join(f"r.{key} IS {reference}.{key}" for key in keys)
        unseen = self._unseen(table, reference)
        return [
            f"INSERT INTO _vault_before_{table} "
            f"SELECT {', '.join('r.' + col for col in columns)} "
            f"FROM main.{table} AS r WHERE {match} AND {unseen}",
            f"INSERT INTO _vault_seen_{table} "
            f"SELECT {', '.join(reference + '.' + key for key in keys)} WHERE {unseen}",
        ]

    def expect(self, table, identity, rows):
        """Seed the intended write set even if a trigger skips every write."""
        columns, keys = _TABLES[table]
        match = " AND ".join(f"{key} IS ?" for key in keys)
        self.con.execute(
            f"INSERT INTO _vault_before_{table} SELECT {', '.join(columns)} "
            f"FROM main.{table} WHERE {match}", identity,
        )
        self.con.execute(
            f"INSERT INTO _vault_seen_{table} VALUES ({', '.join('?' for _ in keys)})",
            identity,
        )
        # For accounts/receipts the supplied rows are the complete expected
        # result. An audit receipt is an addition to any existing history.
        if table != "audit":
            self.con.execute(f"DELETE FROM _vault_before_{table} WHERE {match}", identity)
        self.con.executemany(
            f"INSERT INTO _vault_before_{table} VALUES ({', '.join('?' for _ in columns)})",
            rows,
        )

    def verify(self):
        for table, (columns, keys) in _TABLES.items():
            values = ", ".join(columns)
            typed_values = values + ", " + ", ".join(f"typeof({col})" for col in columns)
            match = " AND ".join(f"s.{key} IS r.{key}" for key in keys)
            changed = self.con.execute(f"""
                WITH actual AS (
                    SELECT {typed_values}, count(*) AS n FROM main.{table} AS r
                    WHERE EXISTS (SELECT 1 FROM _vault_seen_{table} AS s WHERE {match})
                    GROUP BY {typed_values}
                ), expected AS (
                    SELECT {typed_values}, count(*) AS n FROM _vault_before_{table}
                    GROUP BY {typed_values}
                )
                SELECT EXISTS (SELECT * FROM actual EXCEPT SELECT * FROM expected)
                    OR EXISTS (SELECT * FROM expected EXCEPT SELECT * FROM actual)
                    OR (SELECT count(*) FROM main.{table}) !=
                       (SELECT expected FROM _vault_count_{table})
            """).fetchone()[0]
            if changed:
                raise sqlite3.IntegrityError("transfer integrity failure")


def transfer(path, tenant, source, target, amount, key):
    _strings(tenant, source, target, key)
    if source == target or not isinstance(amount, int) or isinstance(amount, bool) or amount <= 0:
        raise ValueError("invalid request")
    receipt = dict(zip(_RECEIPT, (tenant, key, source, target, amount)))
    with closing(_connect(path)) as con, con:
        # Serialize the check and all effects across separate connections.
        # A waiting duplicate observes the committed receipt before proceeding.
        con.execute("BEGIN IMMEDIATE")
        accounts = dict(con.execute(
            "SELECT name, balance FROM accounts WHERE tenant=? AND name IN (?,?)",
            (tenant, source, target),
        ))
        if source not in accounts or target not in accounts:
            raise ValueError("account unavailable")
        old = con.execute(
            "SELECT tenant, key, source, target, amount FROM transfers WHERE tenant=? AND key=?",
            (tenant, key),
        ).fetchone()
        if old is not None:
            original = dict(zip(_RECEIPT, old))
            if original != receipt:
                raise ValueError("key conflict")
            return original
        funds, credit = accounts[source], accounts[target]
        if type(funds) is not int or type(credit) is not int:
            raise sqlite3.DataError("invalid account balance")
        if funds < amount:
            raise ValueError("insufficient funds")
        if credit + amount > 2**63 - 1:
            raise ValueError("balance out of range")

        guard = _WriteGuard(con)
        guard.expect("accounts", (tenant, source), [(tenant, source, funds - amount)])
        guard.expect("accounts", (tenant, target), [(tenant, target, credit + amount)])
        guard.expect("transfers", (tenant, key), [tuple(receipt.values())])
        guard.expect("audit", tuple(receipt.values()), [tuple(receipt.values())])
        con.execute("UPDATE accounts SET balance=? WHERE tenant=? AND name=?",
                    (funds - amount, tenant, source))
        con.execute("UPDATE accounts SET balance=? WHERE tenant=? AND name=?",
                    (credit + amount, tenant, target))
        con.execute("INSERT INTO transfers (tenant,key,source,target,amount) VALUES (?,?,?,?,?)",
                    tuple(receipt.values()))
        con.execute("INSERT INTO audit (tenant,key,source,target,amount) VALUES (?,?,?,?,?)",
                    tuple(receipt.values()))
        guard.verify()
        return receipt
