"""Tenant-scoped transfers with durable, transactional receipts."""

import sqlite3
from contextlib import closing


_COLUMNS = {
    'accounts': ('tenant', 'name', 'balance'),
    'transfers': ('tenant', 'key', 'source', 'target', 'amount'),
    'audit': ('tenant', 'key', 'source', 'target', 'amount'),
}


def init_db(path):
    with closing(sqlite3.connect(path)) as con:
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
        raise ValueError('invalid request')


def _balance(con, tenant, account):
    row = con.execute(
        'SELECT balance FROM accounts WHERE tenant=? AND name=?',
        (tenant, account),
    ).fetchone()
    if row is None:
        raise ValueError('account unavailable')
    if not isinstance(row[0], int):
        raise sqlite3.IntegrityError('invalid account balance')
    return row[0]


def balance(path, tenant, account):
    _strings(tenant, account)
    with closing(sqlite3.connect(path)) as con:
        return _balance(con, tenant, account)


def _same(left, right, columns):
    # Preserve NULLs and storage types, including malformed unrelated rows.
    return ' AND '.join(
        f'{left}.{col} IS {right}.{col} '
        f'AND typeof({left}.{col}) = typeof({right}.{col})'
        for col in columns
    )


def _remember(table, values, where):
    """SQL to remember the initial multiplicity of a touched logical row.

    These snapshots stay inside SQLite. The caller never reads another
    tenant's account or history into Python. Record values, not rowids, so
    ignored writes and harmless internal row movement remain valid.
    """
    columns = _COLUMNS[table]
    names = ', '.join(columns)
    fields = ', '.join(f'{values}.{col}' for col in columns)
    return f'''
        INSERT INTO _vault_before_{table} ({names}, initial_count)
        SELECT {fields}, (
            SELECT count(*) FROM main.{table} AS actual
            WHERE {_same('actual', values, columns)}
        )
        {where}
        AND NOT EXISTS (
            SELECT 1 FROM _vault_before_{table} AS saved
            WHERE {_same('saved', values, columns)}
        )
    '''


def _guard_writes(con, expected):
    """Observe attempted writes, then validate their complete effective result.

    BEFORE observers also remember possible REPLACE victims: SQLite does not
    fire DELETE triggers for these with recursive_triggers off. Observing
    candidates, rather than rejecting attempts, permits ignored conflicts.
    Existing triggers and their recursion behavior are left intact.
    """
    for table, columns in _COLUMNS.items():
        names = ', '.join(columns)
        # No affinities: retain the original SQLite types in the snapshots.
        con.execute(f'CREATE TEMP TABLE _vault_before_{table} '
                    f'({names}, initial_count INTEGER)')
        con.execute(f'CREATE TEMP TABLE _vault_expected_{table} '
                    f'({names}, change INTEGER)')
        placeholders = ', '.join('?' for _ in range(len(columns) + 1))
        con.executemany(
            f'INSERT INTO _vault_expected_{table} VALUES ({placeholders})',
            expected[table],
        )
        group = ', '.join(
            [f'wanted.{col}' for col in columns]
            + [f'typeof(wanted.{col})' for col in columns]
        )
        con.execute(_remember(
            table, 'wanted', f'FROM _vault_expected_{table} AS wanted WHERE 1'
        ) + f' GROUP BY {group}')

        for event in ('INSERT', 'UPDATE', 'DELETE'):
            statements = []
            if event != 'INSERT':
                statements.append(_remember(table, 'OLD', 'WHERE 1'))
            if event != 'DELETE':
                statements.append(_remember(table, 'NEW', 'WHERE 1'))
                collision = 'victim.rowid IS NEW.rowid'
                if table != 'audit':
                    key = 'name' if table == 'accounts' else 'key'
                    collision += (f' OR (victim.tenant IS NEW.tenant '
                                  f'AND victim.{key} IS NEW.{key})')
                group = ', '.join(
                    [f'victim.{col}' for col in columns]
                    + [f'typeof(victim.{col})' for col in columns]
                )
                statements.append(_remember(
                    table, 'victim',
                    f'FROM main.{table} AS victim WHERE ({collision})',
                ) + f' GROUP BY {group}')
            body = ';\n'.join(statements)
            # execute(), not executescript(), keeps the active transaction.
            con.execute(f'''
                CREATE TEMP TRIGGER _vault_watch_{table}_{event}
                BEFORE {event} ON main.{table}
                BEGIN {body}; END
            ''')


def _check_writes(con):
    for table, columns in _COLUMNS.items():
        bad = con.execute(f'''
            SELECT 1 FROM _vault_before_{table} AS saved
            WHERE (
                SELECT count(*) FROM main.{table} AS actual
                WHERE {_same('actual', 'saved', columns)}
            ) != saved.initial_count + coalesce((
                SELECT sum(change) FROM _vault_expected_{table} AS wanted
                WHERE {_same('wanted', 'saved', columns)}
            ), 0)
            LIMIT 1
        ''').fetchone()
        if bad:
            raise sqlite3.IntegrityError('transfer integrity check failed')


def transfer(path, tenant, source, target, amount, key):
    _strings(tenant, source, target, key)
    if source == target or not isinstance(amount, int) or isinstance(amount, bool):
        raise ValueError('invalid request')
    if amount <= 0:
        raise ValueError('invalid request')
    receipt = dict(tenant=tenant, key=key, source=source, target=target, amount=amount)

    with closing(sqlite3.connect(path, timeout=30)) as con:
        with con:
            # Reserve the writer before reading receipts or funds. Other
            # connections then see either the committed result or a rollback.
            con.execute('BEGIN IMMEDIATE')
            old = con.execute(
                'SELECT tenant, key, source, target, amount FROM transfers '
                'WHERE tenant=? AND key=?', (tenant, key),
            ).fetchone()
            if old is not None:
                if old != (tenant, key, source, target, amount):
                    raise ValueError('key conflict')
                return dict(zip(_COLUMNS['transfers'], old))

            funds = _balance(con, tenant, source)
            credit = _balance(con, tenant, target)
            if funds < amount:
                raise ValueError('insufficient funds')
            if credit + amount > 2**63 - 1:
                raise sqlite3.IntegrityError('invalid account balance')

            row = (tenant, key, source, target, amount)
            _guard_writes(con, {
                'accounts': [
                    (tenant, source, funds, -1),
                    (tenant, source, funds - amount, 1),
                    (tenant, target, credit, -1),
                    (tenant, target, credit + amount, 1),
                ],
                'transfers': [(*row, 1)],
                'audit': [(*row, 1)],
            })
            con.execute(
                'UPDATE accounts SET balance=balance-? WHERE tenant=? AND name=?',
                (amount, tenant, source),
            )
            con.execute(
                'UPDATE accounts SET balance=balance+? WHERE tenant=? AND name=?',
                (amount, tenant, target),
            )
            con.execute(
                'INSERT INTO transfers (tenant, key, source, target, amount) '
                'VALUES (?, ?, ?, ?, ?)', row,
            )
            con.execute(
                'INSERT INTO audit (tenant, key, source, target, amount) '
                'VALUES (?, ?, ?, ?, ?)', row,
            )
            _check_writes(con)
        return receipt
