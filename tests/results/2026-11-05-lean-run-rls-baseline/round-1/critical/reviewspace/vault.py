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
    row = dict(zip((_column_key(column[0]) for column in cursor.description), rows[0]))
    if type(row['balance']) is not int:
        raise ValueError(_ERROR)
    return row


def balance(path, tenant, account):
    _strings(tenant, account)
    with closing(_connect(path)) as con:
        return _account(con, tenant, account)['balance']


def _identifier(name):
    return '"' + name.replace('"', '""') + '"'


def _column_key(name):
    # SQLite identifiers fold ASCII letters only (not Unicode casefolding).
    return name.translate(str.maketrans('ABCDEFGHIJKLMNOPQRSTUVWXYZ',
                                       'abcdefghijklmnopqrstuvwxyz'))


def _typed(row, encoding):
    # SQLite storage types and duplicate multiplicities are part of the state.
    # Physical rowids are not account or receipt identities.
    kinds = {int: 'integer', float: 'real', bytes: 'blob', type(None): 'null'}
    return tuple(('text', value.encode(encoding)) if isinstance(value, str)
                 else ('integer', int(value)) if isinstance(value, int)
                 else (kinds[type(value)], value) for value in row)


def _storage_fields(names):
    # Transport TEXT as bytes in the database encoding, keeping its storage
    # class distinct from BLOB. Python must not decode stored payloads.
    fields = []
    for name in names:
        field = _identifier(name)
        fields.extend(('typeof(' + field + ')',
                       'CASE WHEN typeof(' + field + ")='text' THEN CAST(" +
                       field + ' AS BLOB) ELSE ' + field + ' END'))
    return ','.join(fields)


def _state(con, columns):
    return {
        table: Counter(tuple(zip(row[::2], row[1::2])) for row in con.execute(
            'SELECT ' + _storage_fields(names) +
            ' FROM ' + _identifier(table)))
        for table, names in columns.items()
    }


def _load_projection(original, local, tenant):
    """Construct a store where protected rows cannot be reached by any SQL.

    Preserve native schema order, encoding and visible rowids. Global rowid
    allocators and statistics can encode hidden tenants, so they are rebuilt
    from visible rows. No SQL is parsed or rewritten.
    """
    encoding = original.execute('PRAGMA main.encoding').fetchone()[0]
    local.execute('PRAGMA encoding=' + _identifier(encoding))
    schema = original.execute(
        "SELECT type, name, sql FROM main.sqlite_schema "
        "WHERE sql IS NOT NULL AND name NOT GLOB 'sqlite_*' "
        "ORDER BY rowid").fetchall()
    tables = [name for kind, name, sql in schema if kind == 'table']
    for kind, name, sql in schema:
        local.execute(sql)

    # Loading history must not execute triggers or insertion-time CHECKs.
    local.setconfig(sqlite3.SQLITE_DBCONFIG_ENABLE_TRIGGER, False)
    local.execute('PRAGMA ignore_check_constraints = ON')
    without_rowid = {row[1] for row in original.execute('PRAGMA main.table_list')
                     if row[4]}
    for table in tables:
        info = original.execute(
            'PRAGMA main.table_xinfo(' + _identifier(table) + ')').fetchall()
        writable = [row[1] for row in info if row[6] == 0]
        names = {_column_key(row[1]): row[1] for row in info}
        # An unshadowed alias exposes the original physical rowid without
        # changing SELECT * or view shapes. WITHOUT ROWID tables have no alias.
        if table not in without_rowid:
            alias = next((name for name in ('rowid', '_rowid_', 'oid')
                          if name not in names), None)
            if alias is not None:
                writable.insert(0, alias)
        fields = ','.join(map(_identifier, writable))
        query = 'SELECT ' + _storage_fields(writable) + ' FROM ' + _identifier(table)
        parameters = ()
        if 'tenant' in names:
            query += ' WHERE ' + _identifier(names['tenant']) + ' = ? COLLATE BINARY'
            parameters = (tenant,)
        for row in original.execute(query, parameters):
            values = []
            placeholders = []
            for kind, value in zip(row[::2], row[1::2]):
                if kind == 'text':
                    # Bound blobs carry SQLite's UTF-8 tag. A hex literal
                    # casts using the database encoding, including UTF-16.
                    placeholders.append("CAST(x'" + value.hex() + "' AS TEXT)")
                else:
                    placeholders.append('?')
                    values.append(value)
            local.execute(
                'INSERT INTO ' + _identifier(table) + ' (' + fields + ') VALUES (' +
                ','.join(placeholders) + ')', values)

    local.execute('PRAGMA ignore_check_constraints = OFF')
    local.setconfig(sqlite3.SQLITE_DBCONFIG_ENABLE_TRIGGER, True)


def _project(original, local, tenant):
    with closing(_connect(':memory:')) as loader:
        _load_projection(original, loader, tenant)
        # A fresh connection must start with native changes()/total_changes()
        # and last_insert_rowid() counters. Loading fixture data is not part of
        # the transfer and must not be observable as preceding statements.
        local.deserialize(loader.serialize())

    # Foreign rows are absent while triggers run. Check final effects below,
    # allowing native temporary inserts/deletes and conflict/IGNORE behavior.
    columns = {}
    for (table,) in local.execute(
            "SELECT name FROM main.sqlite_schema WHERE type='table'"):
        columns[table] = [row[1] for row in local.execute(
            'PRAGMA main.table_xinfo(' + _identifier(table) + ')') if row[6] != 1]
    return columns


def _expected(before, columns, source_row, target_row, receipt, encoding):
    expected = {table: rows.copy() for table, rows in before.items()}
    for row, change in ((source_row, -receipt['amount']),
                        (target_row, receipt['amount'])):
        old = tuple(row[_column_key(name)] for name in columns['accounts'])
        updated = dict(row, balance=row['balance'] + change)
        new = tuple(updated[_column_key(name)] for name in columns['accounts'])
        expected['accounts'][_typed(old, encoding)] -= 1
        expected['accounts'][_typed(new, encoding)] += 1
    for table in ('transfers', 'audit'):
        row = tuple(receipt[_column_key(name)] for name in columns[table])
        expected[table][_typed(row, encoding)] += 1
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
            raise sqlite3.IntegrityError(_ERROR)
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
            columns = _project(original, local, tenant)
            source_row = _account(local, tenant, source)
            target_row = _account(local, tenant, target)
            if source_row['balance'] < amount:
                raise ValueError(_ERROR)
            if target_row['balance'] + amount > _MAX_INTEGER:
                raise sqlite3.IntegrityError(_ERROR)
            before = _state(local, columns)
            encoding = local.execute('PRAGMA main.encoding').fetchone()[0]
            expected = _expected(before, columns, source_row, target_row, receipt, encoding)
            local.execute('BEGIN')
            _write(local, source_row, target_row, receipt)
            if _state(local, columns) != expected:
                raise sqlite3.IntegrityError(_ERROR)

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
