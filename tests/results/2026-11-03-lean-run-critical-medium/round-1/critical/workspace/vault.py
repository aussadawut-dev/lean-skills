"""Tenant-scoped accounting operations on a local SQLite database."""

from contextlib import closing
import sqlite3


_TABLES = {
    "accounts": ("tenant", "name", "balance"),
    "transfers": ("tenant", "key", "source", "target", "amount"),
    "audit": ("tenant", "key", "source", "target", "amount"),
}
_INVALID_REQUEST = "invalid request"
_INVALID_EFFECT = "invalid storage effect"


def _validate_strings(*values):
    if any(not isinstance(value, str) or not value for value in values):
        raise ValueError(_INVALID_REQUEST)


def init_db(path):
    with closing(sqlite3.connect(path)) as con, con:
        con.execute("BEGIN")
        con.execute("""
            CREATE TABLE IF NOT EXISTS accounts (
                tenant TEXT, name TEXT, balance INTEGER,
                PRIMARY KEY (tenant, name))
        """)
        con.execute("""
            CREATE TABLE IF NOT EXISTS transfers (
                tenant TEXT, key TEXT, source TEXT, target TEXT, amount INTEGER,
                PRIMARY KEY (tenant, key))
        """)
        con.execute("""
            CREATE TABLE IF NOT EXISTS audit (
                tenant TEXT, key TEXT, source TEXT, target TEXT, amount INTEGER)
        """)


def _balance(con, tenant, account):
    row = con.execute(
        "SELECT balance FROM accounts WHERE tenant=? AND name=?",
        (tenant, account),
    ).fetchone()
    if row is None:
        # Missing and inaccessible accounts deliberately have the same error.
        raise ValueError(_INVALID_REQUEST)
    if not isinstance(row[0], int):
        raise sqlite3.IntegrityError(_INVALID_EFFECT)
    return row[0]


def balance(path, tenant, account):
    _validate_strings(tenant, account)
    with closing(sqlite3.connect(path)) as con:
        return _balance(con, tenant, account)


def _record_rows(con, delta):
    for table in _TABLES:
        columns = ("tenant,name,NULL,NULL,balance" if table == "accounts"
                   else "tenant,key,source,target,amount")
        con.execute(
            f"INSERT INTO _vault_changes SELECT ?,{columns},? "
            f"FROM main.{table} WHERE tenant=(SELECT tenant FROM _vault_scope)",
            (table, delta),
        )


def _same_values(columns, left, right):
    return " AND ".join(
        f"{left}.{column} IS {right}.{column} AND "
        f"typeof({left}.{column}) = typeof({right}.{column})"
        for column in columns
    )


def _watch_changes(con, tenant, expected):
    """Protect the write set without changing existing trigger semantics.

    TEMP triggers check effects inside SQLite, preserving ignored conflicts,
    no-op updates and identical replacements. Snapshot this tenant's logical
    rows and compare the final state to the required delta. For other tenants,
    track attempted values AND possible replacement victims before either can
    change. Counts and foreign values stay entirely inside SQLite. Rowids are
    not identities; duplicate rows do count.
    """
    con.execute("CREATE TEMP TABLE _vault_scope (tenant)")
    con.execute("INSERT INTO _vault_scope VALUES (?)", (tenant,))
    con.execute("""
        CREATE TEMP TABLE _vault_changes (
            kind, tenant, identity, source, target, value, delta)
    """)
    con.executemany(
        "INSERT INTO _vault_changes VALUES (?,?,?,?,?,?,?)", expected
    )
    _record_rows(con, -1)

    for table, columns in _TABLES.items():
        pending = f"_vault_{table}_values"
        same = _same_values(columns, "stored", "NEW")
        con.execute(f"CREATE TEMP TABLE {pending} ({','.join(columns)}, initial_count)")
        # REPLACE can silently delete both a rowid victim and an identity
        # victim, even when recursive delete triggers are disabled. Remember
        # their original multiplicities before a later statement restores them.
        collision = "victim.rowid = NEW.rowid"
        if table != "audit":
            identity = "name" if table == "accounts" else "key"
            collision += f" OR (victim.tenant = NEW.tenant AND victim.{identity} = NEW.{identity})"
        victim_same = _same_values(columns, "stored", "victim")
        capture = (
            f"INSERT INTO {pending} SELECT "
            + ",".join(f"NEW.{column}" for column in columns)
            + f",(SELECT count(*) FROM main.{table} AS stored WHERE {same}) "
            "WHERE NEW.tenant IS NOT (SELECT tenant FROM _vault_scope) "
            f"AND NOT EXISTS (SELECT 1 FROM {pending} AS stored WHERE {same}); "
            f"INSERT INTO {pending} SELECT "
            + ",".join(f"victim.{column}" for column in columns)
            + f",(SELECT count(*) FROM main.{table} AS stored WHERE {victim_same}) "
            f"FROM main.{table} AS victim WHERE ({collision}) "
            "AND victim.tenant IS NOT (SELECT tenant FROM _vault_scope) "
            f"AND NOT EXISTS (SELECT 1 FROM {pending} AS stored WHERE {victim_same});"
        )
        # Capture on UPDATE too: a logical no-op can replace a different rowid.
        # Recording a possible victim never rejects an ignored conflict.
        for event in ("INSERT", "UPDATE"):
            con.execute(
                f"CREATE TEMP TRIGGER _vault_{table}_before_{event.lower()} "
                f"BEFORE {event} ON main.{table} BEGIN {capture} END"
            )
        for event, aliases in (
            ("DELETE", ("OLD",)),
            ("UPDATE", ("OLD", "NEW")),
        ):
            condition = ""
            if event == "UPDATE":
                same = _same_values(columns, "OLD", "NEW")
                condition = f"WHEN NOT ({same})"
            statements = []
            for alias in aliases:
                statements.append(
                    f"SELECT RAISE(ABORT, '{_INVALID_EFFECT}') "
                    f"WHERE {alias}.tenant IS NOT "
                    "(SELECT tenant FROM _vault_scope);"
                )
            # All interpolated SQL identifiers are private constants above.
            con.execute(
                f"CREATE TEMP TRIGGER _vault_{table}_{event.lower()} "
                f"AFTER {event} ON main.{table} {condition} BEGIN "
                + " ".join(statements)
                + " END"
            )


def _verify_changes(con):
    _record_rows(con, 1)
    checks = [f"""
        SELECT RAISE(ABORT, '{_INVALID_EFFECT}') WHERE EXISTS (
        SELECT 1 FROM _vault_changes
        GROUP BY kind, tenant, typeof(tenant), identity, typeof(identity),
                 source, typeof(source), target, typeof(target), value, typeof(value)
        HAVING sum(delta) != 0
        );
    """]
    for table, columns in _TABLES.items():
        same = _same_values(columns, "stored", "attempted")
        checks.append(
            f"SELECT RAISE(ABORT, '{_INVALID_EFFECT}') WHERE EXISTS ("
            f"SELECT 1 FROM _vault_{table}_values AS attempted "
            f"WHERE initial_count != (SELECT count(*) FROM main.{table} AS stored "
            f"WHERE {same}));"
        )
    # Signal the storage guard without fetching foreign rows, multiplicities
    # or aggregate comparison results into application code.
    con.execute(
        "CREATE TEMP TRIGGER _vault_verify BEFORE UPDATE ON _vault_scope BEGIN "
        + " ".join(checks) + " END"
    )
    con.execute("UPDATE _vault_scope SET tenant=tenant")


def transfer(path, tenant, source, target, amount, key):
    _validate_strings(tenant, source, target, key)
    if (source == target or not isinstance(amount, int)
            or isinstance(amount, bool) or amount <= 0):
        raise ValueError(_INVALID_REQUEST)

    receipt = dict(tenant=tenant, key=key, source=source, target=target, amount=amount)
    values = (tenant, key, source, target, amount)
    with closing(sqlite3.connect(path, timeout=30)) as con, con:
        # Take the write reservation before reading either receipts or balances.
        # Competing connections then observe a committed replay or fresh funds.
        con.execute("BEGIN IMMEDIATE")
        old = con.execute(
            "SELECT tenant,key,source,target,amount FROM transfers "
            "WHERE tenant=? AND key=?", (tenant, key)
        ).fetchone()
        if old is not None:
            if old != values:
                raise ValueError(_INVALID_REQUEST)
            return dict(zip(("tenant", "key", "source", "target", "amount"), old))

        funds = _balance(con, tenant, source)
        target_funds = _balance(con, tenant, target)
        if funds < amount:
            raise ValueError(_INVALID_REQUEST)
        remaining, credited = funds - amount, target_funds + amount
        # SQLite silently promotes overflowing integer arithmetic to REAL.
        # Refuse that storage failure rather than lose monetary precision.
        if not -(2**63) <= credited < 2**63:
            raise sqlite3.DataError(_INVALID_EFFECT)

        _watch_changes(con, tenant, [
            ("accounts", tenant, source, None, None, funds, 1),
            ("accounts", tenant, source, None, None, remaining, -1),
            ("accounts", tenant, target, None, None, target_funds, 1),
            ("accounts", tenant, target, None, None, credited, -1),
            ("transfers", *values, -1),
            ("audit", *values, -1),
        ])
        con.execute(
            "UPDATE accounts SET balance=? WHERE tenant=? AND name=?",
            (remaining, tenant, source),
        )
        con.execute(
            "UPDATE accounts SET balance=? WHERE tenant=? AND name=?",
            (credited, tenant, target),
        )
        con.execute(
            "INSERT INTO transfers (tenant,key,source,target,amount) VALUES (?,?,?,?,?)",
            values,
        )
        con.execute(
            "INSERT INTO audit (tenant,key,source,target,amount) VALUES (?,?,?,?,?)",
            values,
        )
        _verify_changes(con)
    return receipt
