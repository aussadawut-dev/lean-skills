"""Tenant-scoped transfers, executed and checked before their atomic merge."""

from collections import Counter
from contextlib import closing, contextmanager
import sqlite3
from uuid import uuid4


_LEDGER = {
    "accounts": ("tenant", "name", "balance"),
    "transfers": ("tenant", "key", "source", "target", "amount"),
    "audit": ("tenant", "key", "source", "target", "amount"),
}
_ERROR = "invalid request"
_ASCII_LOWER = str.maketrans('ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz')
_MAP_MARKER = 'vault private rowid mapping v1'


def _connect(path):
    return sqlite3.connect(path, timeout=30, isolation_level=None, uri=True)


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


def _account(con, tenant, account):
    row = con.execute(
        'SELECT balance FROM accounts '
        'WHERE tenant = ? COLLATE BINARY AND name = ? COLLATE BINARY',
        (tenant, account),
    ).fetchone()
    if row is None or type(row[0]) is not int:
        raise ValueError(_ERROR)
    return row[0]


def balance(path, tenant, account):
    _strings(tenant, account)
    with closing(_connect(path)) as con:
        return _account(con, tenant, account)


def _quote(identifier):
    return '"' + identifier.replace('"', '""') + '"'


def _rows(con, table, columns, schema="main"):
    # Preserve SQLite types, duplicate rows, and even malformed TEXT. Ledger
    # validation compares values; projection and merge also preserve identities.
    expressions = []
    for column in columns:
        column = _quote(column)
        expressions.extend((
            f'typeof({column})',
            f"CASE WHEN typeof({column}) = 'text' "
            f'THEN CAST({column} AS BLOB) ELSE {column} END',
        ))
    return Counter(con.execute(
        f'SELECT {", ".join(expressions)} '
        f'FROM {_quote(schema)}.{_quote(table)}'
    ))


def _typed(values, encoding):
    result = []
    for value in values:
        if isinstance(value, str):
            result.extend(("text", value.encode(encoding)))
        else:
            result.extend(("integer", value))
    return tuple(result)


def _expected(con, tenant, source, target, funds, credit, receipt):
    encoding = con.execute('PRAGMA encoding').fetchone()[0]
    expected = {table: _rows(con, table, columns)
                for table, columns in _LEDGER.items()}
    for account, before, after in (
        (source, funds, funds - receipt[4]),
        (target, credit, credit + receipt[4]),
    ):
        expected["accounts"][_typed((tenant, account, before), encoding)] -= 1
        expected["accounts"][_typed((tenant, account, after), encoding)] += 1
    for table in ("transfers", "audit"):
        expected[table][_typed(receipt, encoding)] += 1
    return expected


def _apply(con, tenant, source, target, amount, receipt):
    for account, delta in ((source, -amount), (target, amount)):
        con.execute(
            'UPDATE accounts SET balance = balance + ? '
            'WHERE tenant = ? COLLATE BINARY AND name = ? COLLATE BINARY',
            (delta, tenant, account),
        )
    con.execute('INSERT INTO transfers VALUES (?,?,?,?,?)', receipt)
    con.execute('INSERT INTO audit VALUES (?,?,?,?,?)', receipt)


def _layouts(con):
    return {row[1].translate(_ASCII_LOWER): (row[1], row[4])
            for row in con.execute('PRAGMA main.table_list')}


def _mapping_table(con):
    # A unique name avoids occupying an application's auxiliary table name.
    # This table is removed from the execution image before triggers can run.
    row = con.execute(
        "SELECT name FROM sqlite_schema WHERE type='table' "
        "AND name GLOB '_vault_rowids_*' AND instr(sql, ?) > 0",
        (_MAP_MARKER,),
    ).fetchone()
    return None if row is None else row[0]


def _project(con, tenant):
    con.setconfig(sqlite3.SQLITE_DBCONFIG_ENABLE_TRIGGER, False)
    con.execute('PRAGMA ignore_check_constraints=ON')
    layouts = _layouts(con)
    mapping = _mapping_table(con)
    for ledger, columns in _LEDGER.items():
        table, without_rowid = layouts[ledger]
        fields = ', '.join(map(_quote, columns))
        identity = ''
        if not without_rowid:
            identity = 'rowid'
            if mapping:
                identity = (
                    f'coalesce((SELECT logical FROM {_quote(mapping)} AS m '
                    f'WHERE m.ledger = \'{ledger}\' AND m.tenant = t.tenant COLLATE BINARY '
                    'AND m.physical = t.rowid), t.rowid)'
                )
            identity += ' AS vault_identity, '
        con.execute(
            f'CREATE TEMP TABLE vault_rows AS SELECT {identity}{fields} '
            f'FROM main.{_quote(table)} AS t WHERE tenant = ? COLLATE BINARY', (tenant,),
        )
        con.execute(f'DELETE FROM main.{_quote(table)}')
        destination = fields if without_rowid else 'rowid, ' + fields
        origin = fields if without_rowid else 'vault_identity, ' + fields
        con.execute(
            f'INSERT INTO main.{_quote(table)} ({destination}) '
            f'SELECT {origin} FROM temp.vault_rows'
        )
        con.execute('DROP TABLE temp.vault_rows')
    if mapping:
        con.execute(f'DROP TABLE {_quote(mapping)}')


def _merge_ledger(con, tenant):
    mapping = _mapping_table(con)
    layouts = _layouts(con)
    remapped = []
    for ledger, columns in _LEDGER.items():
        table, without_rowid = layouts[ledger]
        fields = ', '.join(map(_quote, columns))
        physical_by_logical = {}
        if not without_rowid:
            physical_by_logical = {row[0]: row[0] for row in con.execute(
                f'SELECT rowid FROM main.{_quote(table)} WHERE tenant = ? COLLATE BINARY',
                (tenant,),
            )}
            if mapping:
                for physical, logical in con.execute(
                    f'SELECT physical,logical FROM {_quote(mapping)} '
                    'WHERE ledger = ? AND tenant = ? COLLATE BINARY', (ledger, tenant),
                ):
                    physical_by_logical.pop(physical, None)
                physical_by_logical.update(con.execute(
                    f'SELECT logical,physical FROM {_quote(mapping)} '
                    'WHERE ledger = ? AND tenant = ? COLLATE BINARY', (ledger, tenant),
                ))
        con.execute(f'DELETE FROM main.{_quote(table)} WHERE tenant = ? COLLATE BINARY', (tenant,))
        if without_rowid:
            con.execute(f'INSERT INTO main.{_quote(table)} ({fields}) '
                        f'SELECT {fields} FROM vault_result.{_quote(table)}')
            continue
        logical_ids = [row[0] for row in con.execute(
            f'SELECT rowid FROM vault_result.{_quote(table)} ORDER BY rowid'
        )]
        # Reserve surviving physical identities before allocating new ones.
        logical_ids.sort(key=lambda rowid: rowid not in physical_by_logical)
        for logical in logical_ids:
            physical = physical_by_logical.get(logical, logical)
            occupied = con.execute(
                f'SELECT 1 FROM main.{_quote(table)} WHERE rowid = ?', (physical,),
            ).fetchone()
            if occupied:
                physical = None  # SQLite allocates storage; the stage identity stays local.
            cursor = con.execute(
                f'INSERT INTO main.{_quote(table)} (rowid, {fields}) '
                f'SELECT ?, {fields} FROM vault_result.{_quote(table)} WHERE rowid = ?',
                (physical, logical),
            )
            if cursor.lastrowid != logical:
                remapped.append((ledger, tenant, cursor.lastrowid, logical))
    if mapping:
        con.execute(f'DELETE FROM {_quote(mapping)} WHERE tenant = ? COLLATE BINARY', (tenant,))
    elif remapped:
        mapping = '_vault_rowids_' + uuid4().hex
        con.execute(f'CREATE TABLE {_quote(mapping)} ('
                    f'ledger TEXT /* {_MAP_MARKER} */, tenant TEXT, '
                    'physical INTEGER, logical INTEGER, PRIMARY KEY(ledger,tenant,physical))')
    if remapped:
        con.executemany(f'INSERT INTO {_quote(mapping)} VALUES (?,?,?,?)', remapped)
    return mapping


@contextmanager
def _auxiliary_columns(con, table, without_rowid):
    info = con.execute(f'PRAGMA main.table_xinfo({_quote(table)})').fetchall()
    columns = [row[1] for row in info if row[6] == 0]
    names = {row[1].translate(_ASCII_LOWER) for row in info}
    renamed = None
    if not without_rowid:
        alias = next((name for name in ('rowid', '_rowid_', 'oid') if name not in names), None)
        if alias is None:
            # All aliases are shadowed. Temporarily expose the engine identity
            # in both images; SQLite itself maintains dependent schema objects.
            original = next(row[1] for row in info if row[1].translate(_ASCII_LOWER) == 'rowid')
            renamed = (original, '_vault_column_' + uuid4().hex)
            for schema in ('main', 'vault_result'):
                con.execute(f'ALTER TABLE {schema}.{_quote(table)} '
                            f'RENAME COLUMN {_quote(original)} TO {_quote(renamed[1])}')
            columns = [renamed[1] if name == original else name for name in columns]
            alias = 'rowid'
        columns.insert(0, alias)
    try:
        yield columns
    finally:
        if renamed:
            for schema in ('vault_result', 'main'):
                con.execute(f'ALTER TABLE {schema}.{_quote(table)} '
                            f'RENAME COLUMN {_quote(renamed[1])} TO {_quote(renamed[0])}')


def _merge_auxiliary(con, mapping):
    # The attached result was produced by native SQLite with all application
    # triggers enabled. Copy their effects without executing those triggers a
    # second time. INSERT ... SELECT keeps storage types intact.
    tables = con.execute('PRAGMA main.table_list').fetchall()
    tables.sort(key=lambda item: item[1] == 'sqlite_sequence')
    for schema, table, kind, _, without_rowid, _ in tables:
        if (schema != 'main' or table.translate(_ASCII_LOWER) in _LEDGER
                or table in ('sqlite_schema', mapping)):
            continue
        if kind not in ('table', 'shadow'):
            continue
        with _auxiliary_columns(con, table, without_rowid) as columns:
            if _rows(con, table, columns) == _rows(con, table, columns, 'vault_result'):
                continue
            fields = ', '.join(map(_quote, columns))
            con.execute(f'DELETE FROM main.{_quote(table)}')
            con.execute(
                f'INSERT INTO main.{_quote(table)} ({fields}) '
                f'SELECT {fields} FROM vault_result.{_quote(table)}'
            )


def transfer(path, tenant, source, target, amount, key):
    _strings(tenant, source, target, key)
    if source == target or isinstance(amount, bool) or not isinstance(amount, int) or amount <= 0:
        raise ValueError(_ERROR)
    receipt = (tenant, key, source, target, amount)
    with closing(_connect(path)) as stored:
        # Acquire the writer reservation before reading receipts or balances.
        # It remains held through execution, validation and the durable commit.
        stored.execute('BEGIN IMMEDIATE')
        try:
            funds = _account(stored, tenant, source)
            credit = _account(stored, tenant, target)
            old = stored.execute(
                'SELECT tenant,key,source,target,amount FROM transfers '
                'WHERE tenant = ? COLLATE BINARY AND key = ? COLLATE BINARY',
                (tenant, key),
            ).fetchone()
            if old is not None:
                if old != receipt:
                    raise ValueError(_ERROR)
                stored.rollback()
                return dict(zip(_LEDGER['transfers'], old))
            if funds < amount or credit + amount > 2**63 - 1:
                raise ValueError(_ERROR)

            stage_uri = f'file:vault_{uuid4().hex}?mode=memory&cache=shared'
            with closing(_connect(':memory:')) as projection, closing(_connect(stage_uri)) as stage:
                # A separate reader can back up the committed image while our
                # writer reservation prevents concurrent modifications. This
                # also works with WAL databases.
                with closing(_connect(path)) as reader:
                    reader.backup(projection)
                _project(projection, tenant)
                expected = _expected(projection, tenant, source, target, funds, credit, receipt)
                # Backup into a fresh connection resets changes(), total_changes()
                # and last_insert_rowid(): projection work cannot leak through
                # SQLite's connection-local counters. Triggers are never dropped.
                projection.backup(stage)
                stage.execute('BEGIN')
                _apply(stage, tenant, source, target, amount, receipt)
                for table, columns in _LEDGER.items():
                    if _rows(stage, table, columns) != +expected[table]:
                        raise ValueError(_ERROR)
                stage.commit()

                stored.execute('ATTACH DATABASE ? AS vault_result', (stage_uri,))
                stored.setconfig(sqlite3.SQLITE_DBCONFIG_ENABLE_TRIGGER, False)
                # CHECK expressions, like triggers, have already run natively
                # in stage. Re-evaluating connection-dependent expressions while
                # copying validated effects would change their meaning.
                stored.execute('PRAGMA ignore_check_constraints=ON')
                mapping = _merge_ledger(stored, tenant)
                _merge_auxiliary(stored, mapping)
                stored.commit()
            return dict(zip(_LEDGER['transfers'], receipt))
        except BaseException:
            stored.rollback()
            raise
