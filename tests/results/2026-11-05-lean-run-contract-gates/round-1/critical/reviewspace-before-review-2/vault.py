"""Tenant-scoped transfers, executed and checked before their atomic merge."""

from collections import Counter
from contextlib import closing
import sqlite3
from uuid import uuid4


_LEDGER = {
    "accounts": ("tenant", "name", "balance"),
    "transfers": ("tenant", "key", "source", "target", "amount"),
    "audit": ("tenant", "key", "source", "target", "amount"),
}
_ERROR = "invalid request"


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
    # Preserve SQLite types, duplicate rows, and even non-UTF-8 TEXT. Rowids
    # are deliberately not part of ledger identity, which the contract defines
    # by values. Auxiliary tables retain their rowids when available.
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


def _typed(values):
    result = []
    for value in values:
        if isinstance(value, str):
            result.extend(("text", value.encode("utf-8")))
        else:
            result.extend(("integer", value))
    return tuple(result)


def _expected(con, tenant, source, target, funds, credit, receipt):
    expected = {table: _rows(con, table, columns)
                for table, columns in _LEDGER.items()}
    for account, before, after in (
        (source, funds, funds - receipt[4]),
        (target, credit, credit + receipt[4]),
    ):
        expected["accounts"][_typed((tenant, account, before))] -= 1
        expected["accounts"][_typed((tenant, account, after))] += 1
    for table in ("transfers", "audit"):
        expected[table][_typed(receipt)] += 1
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


def _project(con, tenant):
    con.setconfig(sqlite3.SQLITE_DBCONFIG_ENABLE_TRIGGER, False)
    con.execute('PRAGMA ignore_check_constraints=ON')
    layouts = {row[1]: row[4] for row in con.execute('PRAGMA main.table_list')}
    for table, columns in _LEDGER.items():
        fields = ', '.join(map(_quote, columns))
        # Ledger identity consists of the declared columns, not shared physical
        # rowids. Rebuild each tenant's rowid space in its existing relative order
        # so later inserts and last_insert_rowid() cannot inherit global IDs
        # allocated during earlier transfers. WITHOUT ROWID tables need no IDs.
        ordering = '' if layouts[table] else ' ORDER BY rowid'
        con.execute(
            f'CREATE TEMP TABLE vault_rows AS SELECT {fields} FROM main.{_quote(table)} '
            f'WHERE tenant = ? COLLATE BINARY{ordering}', (tenant,),
        )
        con.execute(f'DELETE FROM main.{_quote(table)}')
        con.execute(
            f'INSERT INTO main.{_quote(table)} ({fields}) '
            f'SELECT {fields} FROM temp.vault_rows ORDER BY rowid'
        )
        con.execute('DROP TABLE temp.vault_rows')


def _merge_auxiliary(con):
    # The attached result was produced by native SQLite with all application
    # triggers enabled. Copy their effects without executing those triggers a
    # second time. INSERT ... SELECT keeps storage types intact.
    tables = con.execute('PRAGMA main.table_list').fetchall()
    tables.sort(key=lambda item: item[1] == 'sqlite_sequence')
    for schema, table, kind, _, without_rowid, _ in tables:
        if schema != 'main' or table in _LEDGER or table == 'sqlite_schema':
            continue
        if kind not in ('table', 'shadow'):
            continue
        info = con.execute(f'PRAGMA main.table_xinfo({_quote(table)})').fetchall()
        columns = [row[1] for row in info if row[6] == 0]
        if not without_rowid:
            names = {row[1].lower() for row in info}
            for rowid in ('rowid', '_rowid_', 'oid'):
                if rowid not in names:
                    columns.insert(0, rowid)
                    break
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
                _apply(stored, tenant, source, target, amount, receipt)
                _merge_auxiliary(stored)
                stored.commit()
            return dict(zip(_LEDGER['transfers'], receipt))
        except BaseException:
            stored.rollback()
            raise
