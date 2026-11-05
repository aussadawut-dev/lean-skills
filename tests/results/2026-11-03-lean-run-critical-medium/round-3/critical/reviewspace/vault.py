"""Tenant-scoped balances and durable, atomic SQLite transfers."""

from contextlib import closing
import re
import sqlite3


_RECEIPT = ("tenant", "key", "source", "target", "amount")
_TABLES = {
    "accounts": ("tenant", "name", "balance"),
    "transfers": _RECEIPT,
    "audit": _RECEIPT,
}

# Token positions let us instrument stored trigger programs without treating
# quoted identifiers, string contents or comments as SQL keywords.
_SQL_TOKEN = re.compile(r"""
    (?P<skip>\s+|--[^\n]*|/\*[\s\S]*?\*/)
    |'(?:''|[^'])*'|"(?:""|[^"])*"|`(?:``|[^`])*`|\[[^\]]*\]
    |[a-zA-Z_\u0080-\U0010ffff][a-zA-Z_0-9$\u0080-\U0010ffff]*|.
""", re.VERBOSE)


def _tokens(sql):
    return [(m.group().upper(), m.start(), m.end())
            for m in _SQL_TOKEN.finditer(sql) if m.lastgroup != "skip"]


def _release_on_ignore(sql, number):
    tokens = _tokens(sql)
    for i in range(len(tokens) - 4, -1, -1):
        if [t[0] for t in tokens[i:i + 4]] == ["RAISE", "(", "IGNORE", ")"]:
            start, end = tokens[i][1], tokens[i + 3][2]
            sql = (sql[:start] + f"CASE WHEN _vault_trigger('leave',{number},'') "
                   "THEN RAISE(IGNORE) END" + sql[end:])
    return sql


def _instrument_trigger(sql, number):
    """Add nonrecursive entry and statement bookkeeping to a trigger."""
    tokens = _tokens(sql)
    i = 2  # CREATE TRIGGER
    if tokens[i][0] == "IF":
        i += 3  # IF NOT EXISTS
    i += 1  # trigger name, including quoted/keyword/Unicode names
    if tokens[i][0] == ".":
        i += 2
    if tokens[i][0] in ("BEFORE", "AFTER"):
        i += 1
    elif tokens[i][0] == "INSTEAD":
        i += 2
    event = tokens[i][0]
    i += 1
    if tokens[i][0] == "OF":
        i += 2  # first UPDATE OF column
        while tokens[i][0] == ",":
            i += 2
    i += 1  # ON
    i += 1
    if tokens[i][0] == ".":
        i += 2
    if tokens[i][0] == "FOR":
        i += 3  # FOR EACH ROW
    header_end = tokens[i][1]
    condition = "1"
    if tokens[i][0] == "WHEN":
        condition_start = tokens[i][2]
        i += 1
        depth = 0
        # A SQLite SELECT statement can also start with VALUES or WITH.
        while not (tokens[i][0] == "BEGIN" and depth == 0
                   and tokens[i + 1][0] in ("SELECT", "VALUES", "WITH", "INSERT", "UPDATE", "DELETE", "REPLACE")):
            depth += (tokens[i][0] == "(") - (tokens[i][0] == ")")
            i += 1
        condition = sql[condition_start:tokens[i][1]]
    body_start = tokens[i][2]  # BEGIN
    statements = [f"SELECT _vault_trigger('enter',{number},'');"]
    statement_event = None
    for token, start, end in tokens[i + 1:]:
        if token == ";":
            statement = _release_on_ignore(sql[body_start:end], number)
            statements.extend([
                f"SELECT _vault_trigger('push',{number},'{statement_event}');",
                statement,
                f"SELECT _vault_trigger('pop',{number},'');",
            ])
            body_start, statement_event = end, None
        elif statement_event is None:
            statement_event = token
        if statement_event == "END":
            break
    statements.append(f"SELECT _vault_trigger('leave',{number},'');")
    condition = _release_on_ignore(condition, number)
    return (sql[:header_end] + f" WHEN CASE WHEN _vault_trigger('allow',{number},'{event}') "
            + f"THEN ({condition}\n) ELSE 0 END BEGIN\n"
            + "\n".join(statements) + "\nEND")


def _replace_triggers(con, definitions):
    for name, sql in definitions:
        con.execute('DROP TRIGGER main."' + name.replace('"', '""') + '"')
        con.execute(sql)


def _preserve_nonrecursive_triggers(con):
    """Instrument programs transactionally, restoring them before commit.

    Recursive triggers expose REPLACE deletions to our observers. Existing
    programs still need SQLite's usual nonrecursive behavior: an active
    trigger cannot reenter, and implicit REPLACE deletions do not invoke its
    DELETE triggers. Only program identities/statement kinds enter Python.
    """
    active, statements = set(), []

    def control(action, number, event):
        if action == "allow":
            return number not in active and (event != "DELETE" or
                                            bool(statements and statements[-1][1] == "DELETE"))
        if action == "enter":
            active.add(number)
        elif action == "push":
            statements.append((number, event))
        elif action == "pop":
            statements.pop()
        elif action == "leave":
            active.discard(number)
            # RAISE(IGNORE) exits this program without reaching its suffix.
            while statements and statements[-1][0] == number:
                statements.pop()
        return 1

    con.create_function("_vault_trigger", 3, control)
    # Recreate in original order to retain SQLite's order among sibling
    # triggers. TEMP copies cannot guarantee that order (their hash can grow).
    definitions = con.execute("SELECT name, sql FROM main.sqlite_schema "
                              "WHERE type='trigger' ORDER BY rowid").fetchall()
    _replace_triggers(con, [(name, _instrument_trigger(sql, number))
                           for number, (name, sql) in enumerate(definitions)])
    return definitions


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
    """Compare actual row-change deltas with the authorized transaction.

    AFTER observers consume OLD/NEW directly, without looking up any stored
    accounts or history. Signed multiplicities preserve duplicate audit rows;
    types distinguish integer balances from equal-looking text/reals. Ignored
    writes produce no events, while no-ops, identical replacement and rowid
    moves cancel out. All temporary state disappears when the connection closes.
    """

    def __init__(self, con):
        self.con = con
        recursive = con.execute("PRAGMA recursive_triggers").fetchone()[0]
        con.execute("PRAGMA recursive_triggers=ON")
        for table, columns in _TABLES.items():
            con.execute(f"CREATE TEMP TABLE _vault_delta_{table} ({', '.join(columns)}, delta)")
            for event in ("INSERT", "UPDATE", "DELETE"):
                statements = []
                if event != "INSERT":
                    statements.append(f"INSERT INTO _vault_delta_{table} VALUES "
                                      f"({', '.join('OLD.' + col for col in columns)}, -1)")
                if event != "DELETE":
                    statements.append(f"INSERT INTO _vault_delta_{table} VALUES "
                                      f"({', '.join('NEW.' + col for col in columns)}, 1)")
                con.execute(f"""CREATE TEMP TRIGGER _vault_{table}_{event}
                    AFTER {event} ON main.{table} BEGIN
                    {';'.join(statements)};
                    END""")
        self.triggers = _preserve_nonrecursive_triggers(con) if not recursive else []

    def expect(self, table, before, after):
        """Subtract the intended delta, using only authenticated input/reads."""
        self.con.executemany(
            f"INSERT INTO _vault_delta_{table} VALUES ({', '.join('?' for _ in _TABLES[table])}, ?)",
            [tuple(row) + (1,) for row in before] + [tuple(row) + (-1,) for row in after],
        )

    def verify(self):
        for table, columns in _TABLES.items():
            values = ", ".join(columns)
            typed_values = values + ", " + ", ".join(f"typeof({col})" for col in columns)
            changed = self.con.execute(f"""
                SELECT EXISTS (
                    SELECT 1 FROM _vault_delta_{table}
                    GROUP BY {typed_values} HAVING sum(delta) != 0
                )
            """).fetchone()[0]
            if changed:
                raise sqlite3.IntegrityError("transfer integrity failure")
        # Audit programs ran with their original bodies, including failures.
        # On any earlier exception the enclosing rollback restores them too.
        _replace_triggers(self.con, self.triggers)


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
        guard.expect("accounts", [(tenant, source, funds)], [(tenant, source, funds - amount)])
        guard.expect("accounts", [(tenant, target, credit)], [(tenant, target, credit + amount)])
        guard.expect("transfers", [], [tuple(receipt.values())])
        guard.expect("audit", [], [tuple(receipt.values())])
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
