"""Tenant-scoped transfers with isolated, native SQLite trigger execution."""

from collections import Counter
from contextlib import closing
import sqlite3


_ERROR = 'invalid request'
_RECEIPT_COLUMNS = ('tenant', 'key', 'source', 'target', 'amount')
_MAX_INTEGER = (1 << 63) - 1


def _connect(path):
    return sqlite3.connect(path, timeout=30, isolation_level=None)


def init_db(path):
    with closing(_connect(path)) as con:
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


def _strings(*values):
    if any(not isinstance(value, str) or not value for value in values):
        raise ValueError(_ERROR)


def _account(con, tenant, name):
    cursor = con.execute(
        'SELECT * FROM accounts WHERE tenant = ? COLLATE BINARY '
        'AND name = ? COLLATE BINARY', (tenant, name))
    rows = cursor.fetchall()
    if len(rows) != 1:
        raise ValueError(_ERROR)
    row = dict(zip((column[0] for column in cursor.description), rows[0]))
    if type(row['balance']) is not int:
        raise ValueError(_ERROR)
    return row


def balance(path, tenant, account):
    _strings(tenant, account)
    with closing(_connect(path)) as con:
        return _account(con, tenant, account)['balance']


def _identifier(name):
    return '"' + name.replace('"', '""') + '"'


def _typed(row):
    # SQLite storage types and duplicate multiplicities are part of the state.
    # Physical rowids are not account or receipt identities.
    return tuple((type(value), value) for value in row)


def _state(con, columns):
    return {
        table: Counter(_typed(row) for row in con.execute(
            'SELECT ' + ','.join(map(_identifier, names)) +
            ' FROM ' + _identifier(table)))
        for table, names in columns.items()
    }


def _load_projection(original, local, tenant):
    """Construct a store where protected rows cannot be reached by any SQL.

    Install original indexes, views and triggers only after loading visible
    data. Do not copy global rowid allocators or statistics: those can encode
    hidden tenants. Canonical insertion order also avoids hidden row allocation
    influencing subsequent trigger results. No SQL is parsed or rewritten.
    """
    schema = original.execute(
        "SELECT type, name, sql FROM main.sqlite_schema "
        "WHERE sql IS NOT NULL AND name NOT GLOB 'sqlite_*' "
        "ORDER BY type, name").fetchall()
    tables = [name for kind, name, sql in schema if kind == 'table']
    for kind, name, sql in schema:
        if kind == 'table':
            local.execute(sql)

    # Loading history must not re-evaluate insertion-time CHECK expressions.
    local.execute('PRAGMA ignore_check_constraints = ON')
    scoped_tables = []
    for table in tables:
        info = original.execute(
            'PRAGMA main.table_xinfo(' + _identifier(table) + ')').fetchall()
        writable = [row[1] for row in info if row[6] == 0]
        fields = ','.join(map(_identifier, writable))
        query = 'SELECT ' + fields + ' FROM ' + _identifier(table)
        parameters = ()
        if 'tenant' in writable:
            query += ' WHERE tenant = ? COLLATE BINARY'
            parameters = (tenant,)
            scoped_tables.append(table)
        query += ' ORDER BY ' + fields
        local.executemany(
            'INSERT INTO ' + _identifier(table) + ' (' + fields + ') VALUES (' +
            ','.join('?' for _ in writable) + ')',
            original.execute(query, parameters))

    local.execute('PRAGMA ignore_check_constraints = OFF')

    for kind in ('index', 'view', 'trigger'):
        for item_kind, name, sql in schema:
            if item_kind == kind:
                local.execute(sql)

    return scoped_tables


def _project(original, local, tenant):
    with closing(_connect(':memory:')) as loader:
        scoped_tables = _load_projection(original, loader, tenant)
        # A fresh connection must start with native changes()/total_changes()
        # and last_insert_rowid() counters. Loading fixture data is not part of
        # the transfer and must not be observable as preceding statements.
        local.deserialize(loader.serialize())

    violated = [False]

    def allowed(candidate):
        matches = type(candidate) is str and candidate == tenant
        if not matches:
            violated[0] = True
        return matches

    local.create_function('_vault_allowed_tenant', 1, allowed)
    # Data absence handles all reads and updates/deletes of hidden rows. These
    # guards additionally reject even transient creation of a foreign row.
    for index, table in enumerate(scoped_tables):
        for event in ('INSERT', 'UPDATE'):
            local.execute(
                'CREATE TEMP TRIGGER ' + _identifier(f'_vault_{index}_{event}') +
                ' BEFORE ' + event + ' ON main.' + _identifier(table) +
                ' WHEN NOT _vault_allowed_tenant(NEW.tenant) BEGIN '
                "SELECT RAISE(ABORT, 'invalid request'); END")

    columns = {}
    for (table,) in local.execute(
            "SELECT name FROM main.sqlite_schema WHERE type='table'"):
        columns[table] = [row[1] for row in local.execute(
            'PRAGMA main.table_xinfo(' + _identifier(table) + ')') if row[6] != 1]
    return columns, violated


def _expected(before, columns, source_row, target_row, receipt):
    expected = {table: rows.copy() for table, rows in before.items()}
    for row, change in ((source_row, -receipt['amount']),
                        (target_row, receipt['amount'])):
        old = tuple(row[name] for name in columns['accounts'])
        updated = dict(row, balance=row['balance'] + change)
        new = tuple(updated[name] for name in columns['accounts'])
        expected['accounts'][_typed(old)] -= 1
        expected['accounts'][_typed(new)] += 1
    for table in ('transfers', 'audit'):
        expected[table][_typed(tuple(receipt[name] for name in columns[table]))] += 1
    return expected


def _write(con, source_row, target_row, receipt, *, publish=False):
    # An explicit outer conflict policy overrides policies inside triggers.
    # Preserve their native policies in the isolated execution; publication
    # has no triggers and must never replace an unrelated conflicting row.
    policy = ' OR ABORT' if publish else ''
    for row, change in ((source_row, -receipt['amount']),
                        (target_row, receipt['amount'])):
        cursor = con.execute(
            'UPDATE' + policy + ' accounts SET balance = ? '
            'WHERE tenant = ? COLLATE BINARY AND name = ? COLLATE BINARY',
            (row['balance'] + change, receipt['tenant'], row['name']))
        if cursor.rowcount != 1:
            raise ValueError(_ERROR)
    values = tuple(receipt[name] for name in _RECEIPT_COLUMNS)
    for table in ('transfers', 'audit'):
        con.execute('INSERT' + policy + ' INTO ' + table +
                    ' (tenant,key,source,target,amount) VALUES (?,?,?,?,?)', values)


def transfer(path, tenant, source, target, amount, key):
    _strings(tenant, source, target, key)
    if (source == target or not isinstance(amount, int) or
            isinstance(amount, bool) or amount <= 0):
        raise ValueError(_ERROR)
    receipt = dict(tenant=tenant, key=key, source=source,
                   target=target, amount=amount)
    with closing(_connect(path)) as original, original:
        # Acquire the writer lock BEFORE either replay or balance inspection.
        # Every independent connection therefore observes the preceding commit.
        original.execute('BEGIN IMMEDIATE')
        old = original.execute(
            'SELECT tenant,key,source,target,amount FROM transfers '
            'WHERE tenant = ? COLLATE BINARY AND key = ? COLLATE BINARY',
            (tenant, key)).fetchone()
        if old is not None:
            saved = dict(zip(_RECEIPT_COLUMNS, old))
            if saved != receipt:
                raise ValueError(_ERROR)
            return saved

        with closing(_connect(':memory:')) as local:
            columns, violated = _project(original, local, tenant)
            source_row = _account(local, tenant, source)
            target_row = _account(local, tenant, target)
            if (source_row['balance'] < amount or
                    target_row['balance'] + amount > _MAX_INTEGER):
                raise ValueError(_ERROR)
            before = _state(local, columns)
            expected = _expected(before, columns, source_row, target_row, receipt)
            local.execute('BEGIN')
            try:
                _write(local, source_row, target_row, receipt)
            except sqlite3.Error:
                if violated[0]:
                    raise ValueError(_ERROR) from None
                raise
            if violated[0] or _state(local, columns) != expected:
                raise ValueError(_ERROR)

        # Triggers already ran, with their native SQLite semantics, against
        # the isolated data. Publish only the four validated effects. Disabling
        # execution here is connection-local; no trigger is dropped or altered.
        # OR ABORT prevents schema conflict policies from silently replacing
        # unrelated rows. CHECK expressions also already ran in the tenant
        # context; evaluating them again could expose shared rowid counters.
        # Storage/uniqueness failures still roll back all four writes.
        enabled = original.getconfig(sqlite3.SQLITE_DBCONFIG_ENABLE_TRIGGER)
        original.setconfig(sqlite3.SQLITE_DBCONFIG_ENABLE_TRIGGER, False)
        original.execute('PRAGMA ignore_check_constraints = ON')
        try:
            _write(original, source_row, target_row, receipt, publish=True)
        finally:
            original.execute('PRAGMA ignore_check_constraints = OFF')
            original.setconfig(sqlite3.SQLITE_DBCONFIG_ENABLE_TRIGGER, enabled)
    return receipt
