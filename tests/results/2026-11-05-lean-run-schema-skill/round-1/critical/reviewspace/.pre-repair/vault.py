"""Tenant-scoped accounting with native, isolated SQLite trigger execution."""

from collections import Counter
from contextlib import closing
import sqlite3


_COLUMNS = {
    "accounts": ("tenant", "name", "balance"),
    "transfers": ("tenant", "key", "source", "target", "amount"),
    "audit": ("tenant", "key", "source", "target", "amount"),
}


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


def _text(value):
    if not isinstance(value, str):
        raise ValueError("invalid request")
    value = str.__str__(value)
    if not value:
        raise ValueError("invalid request")
    return value


def _balance(con, tenant, account):
    row = con.execute(
        'SELECT balance FROM accounts WHERE tenant = ? COLLATE BINARY '
        'AND name = ? COLLATE BINARY', (tenant, account)
    ).fetchone()
    if row is None or type(row[0]) is not int:
        raise ValueError("invalid account")
    return row[0]


def balance(path, tenant, account):
    tenant, account = _text(tenant), _text(account)
    with closing(sqlite3.connect(path)) as con:
        return _balance(con, tenant, account)


def _quote(name):
    return '"' + name.replace('"', '""') + '"'


def _multiset(rows):
    # SQLite distinguishes integer, real, text, blob and null values.
    return Counter(tuple((type(value), value) for value in row) for row in rows)


def _core_rows(con, tenant=None):
    result = {}
    for table, columns in _COLUMNS.items():
        sql = 'SELECT ' + ','.join(map(_quote, columns)) + ' FROM ' + table
        if tenant is None:
            result[table] = con.execute(sql).fetchall()
        else:
            result[table] = con.execute(
                sql + ' WHERE tenant = ? COLLATE BINARY', (tenant,)
            ).fetchall()
    return result


def _image(con):
    data = con.serialize()
    # A deserialized in-memory database cannot open a WAL sidecar. The image
    # already contains the complete transaction snapshot, including WAL pages.
    if data[18:20] != b'\x01\x01':
        data = data[:18] + b'\x01\x01' + data[20:]
    return data


def _isolate(con, tenant):
    """Remove inaccessible data before any user trigger can execute.

    Use a second fresh connection after projection so changes(),
    total_changes() and last_insert_rowid() cannot expose projection work.
    No schema objects are created, removed or rewritten.
    """
    with closing(sqlite3.connect(':memory:')) as projection:
        projection.deserialize(_image(con))
        projection.setconfig(sqlite3.SQLITE_DBCONFIG_ENABLE_TRIGGER, False)
        rowid_tables = {row[1].lower() for row in projection.execute('PRAGMA table_list')
                        if row[0] == 'main' and not row[4]}
        for table in _COLUMNS:
            projection.execute(
                f'DELETE FROM {table} WHERE tenant IS NOT ? COLLATE BINARY',
                (tenant,),
            )
            # Accounts already have durable row identities. The transfer only
            # updates their balances, so keep references used by user triggers.
            if table != 'accounts' and table in rowid_tables:
                # Global physical rowids can encode hidden insertion history,
                # including earlier commits by this function. Expose local
                # rowids in tenant insertion order, never global addresses.
                columns = ','.join(map(_quote, _COLUMNS[table]))
                rows = projection.execute(
                    f'SELECT {columns} FROM {table} ORDER BY rowid'
                ).fetchall()
                projection.execute(f'DELETE FROM {table}')
                projection.executemany(
                    f'INSERT INTO {table} ({columns}) VALUES (' +
                    ','.join('?' for _ in _COLUMNS[table]) + ')', rows,
                )
        projection.commit()
        scoped = sqlite3.connect(':memory:')
        try:
            scoped.deserialize(_image(projection))
        except BaseException:
            scoped.close()
            raise
        return scoped


def _auxiliary_rows(con):
    """Snapshot stored tables, including virtual-table backing state.

    A virtual table's SELECT result need not describe its persistent state,
    and some virtual tables are read-only. Their shadow tables contain the
    committed state and can be copied without replaying virtual commands.
    """
    result = {}
    for schema, table, kind, _, without_rowid, _ in con.execute('PRAGMA table_list'):
        if schema != 'main' or kind not in ('table', 'shadow'):
            continue
        if table.lower() in _COLUMNS or table.lower() == 'sqlite_schema':
            continue
        info = con.execute('PRAGMA table_xinfo(' + _quote(table) + ')').fetchall()
        columns = [row[1] for row in info if row[6] == 0]
        names = {row[1].lower() for row in info}
        if not without_rowid:
            alias = next((name for name in ('rowid', '_rowid_', 'oid')
                          if name not in names), None)
            if alias is not None:
                columns.insert(0, alias)
        sql = 'SELECT ' + ','.join(map(_quote, columns)) + ' FROM ' + _quote(table)
        result[table] = (columns, con.execute(sql).fetchall())
    return result


def _verify(actual, expected):
    if any(_multiset(actual[table]) != _multiset(expected[table])
           for table in _COLUMNS):
        raise ValueError("invalid transfer effects")


def _apply_auxiliary(con, before, after):
    # Triggers have already executed natively in the isolated database. Import
    # their effects with triggers disabled; retain explicit rowids and sequence
    # values, including legitimate deletes, replacements and ignored writes.
    for table in sorted(after, key=lambda name: name == 'sqlite_sequence'):
        columns, rows = after[table]
        if _multiset(before[table][1]) == _multiset(rows):
            continue
        con.execute('DELETE FROM ' + _quote(table))
        if rows:
            sql = ('INSERT INTO ' + _quote(table) + ' (' +
                   ','.join(map(_quote, columns)) + ') VALUES (' +
                   ','.join('?' for _ in columns) + ')')
            con.executemany(sql, rows)


def transfer(path, tenant, source, target, amount, key):
    tenant, source, target, key = map(_text, (tenant, source, target, key))
    if not isinstance(amount, int) or isinstance(amount, bool):
        raise ValueError("invalid request")
    amount = int.__int__(amount)
    if amount <= 0 or source == target:
        raise ValueError("invalid request")
    receipt = dict(tenant=tenant, key=key, source=source, target=target, amount=amount)
    values = tuple(receipt.values())

    # Lock before reading funds or receipts, serializing deduplication and commit.
    with closing(sqlite3.connect(path, timeout=30)) as con, con:
        con.execute('BEGIN IMMEDIATE')
        funds = _balance(con, tenant, source)
        target_funds = _balance(con, tenant, target)
        old = con.execute(
            'SELECT tenant,key,source,target,amount FROM transfers '
            'WHERE tenant = ? COLLATE BINARY AND key = ? COLLATE BINARY',
            (tenant, key),
        ).fetchone()
        if old is not None:
            if _multiset([old]) != _multiset([values]):
                raise ValueError("key conflict")
            return dict(zip(_COLUMNS['transfers'], old))
        if funds < amount:
            raise ValueError("insufficient funds")

        with closing(_isolate(con, tenant)) as scoped:
            expected = _core_rows(scoped)
            expected['accounts'] = [
                (owner, name, value - amount if name == source else
                 value + amount if name == target else value)
                for owner, name, value in expected['accounts']
            ]
            expected['transfers'].append(values)
            expected['audit'].append(values)
            before = _auxiliary_rows(scoped)
            scoped.execute(
                'UPDATE accounts SET balance=balance-? '
                'WHERE tenant=? COLLATE BINARY AND name=? COLLATE BINARY',
                (amount, tenant, source),
            )
            scoped.execute(
                'UPDATE accounts SET balance=balance+? '
                'WHERE tenant=? COLLATE BINARY AND name=? COLLATE BINARY',
                (amount, tenant, target),
            )
            scoped.execute('INSERT INTO transfers VALUES (?,?,?,?,?)', values)
            scoped.execute('INSERT INTO audit VALUES (?,?,?,?,?)', values)
            # Virtual tables may buffer index changes until xSync at commit.
            # Flush before verifying final effects or reading backing state.
            scoped.commit()
            _verify(_core_rows(scoped), expected)
            after = _auxiliary_rows(scoped)

        con.setconfig(sqlite3.SQLITE_DBCONFIG_ENABLE_TRIGGER, False)
        con.execute('UPDATE accounts SET balance=? '
                    'WHERE tenant=? COLLATE BINARY AND name=? COLLATE BINARY',
                    (funds - amount, tenant, source))
        con.execute('UPDATE accounts SET balance=? '
                    'WHERE tenant=? COLLATE BINARY AND name=? COLLATE BINARY',
                    (target_funds + amount, tenant, target))
        con.execute('INSERT INTO transfers VALUES (?,?,?,?,?)', values)
        con.execute('INSERT INTO audit VALUES (?,?,?,?,?)', values)
        _apply_auxiliary(con, before, after)
        _verify(_core_rows(con, tenant), expected)
        return receipt
