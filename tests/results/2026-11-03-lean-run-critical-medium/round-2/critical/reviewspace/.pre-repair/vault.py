"""Tenant-scoped transfers with durable, transactional receipts."""

import sqlite3
import re
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


_TOKENS = re.compile(
    r"\s+|--[^\n]*(?:\n|$)|/\*.*?\*/|'(?:''|[^'])*'|"
    r'"(?:""|[^"])*"|`(?:``|[^`])*`|\[[^\]]*\]|[\w$]+|.',
    re.DOTALL,
)


def _tokens(sql):
    return [match for match in _TOKENS.finditer(sql)
            if not match[0].isspace() and not match[0].startswith(('--', '/*'))]


def _identifier(name):
    return '"' + name.replace('"', '""') + '"'


def _literal(value):
    return "'" + value.replace("'", "''") + "'"


def _observed_trigger(name, sql):
    """Retain nonrecursive trigger semantics while DELETE events are enabled.

    Only trigger control flow is instrumented; each original statement still
    executes. In particular, IGNORE must unwind the current trigger, and an
    implicit REPLACE deletion must not invoke an existing DELETE trigger.
    Quoted text and comments are never interpreted as SQL control tokens.
    """
    tokens = _tokens(sql)
    begin = next(i for i, token in enumerate(tokens) if token[0].upper() == 'BEGIN')
    when = next((i for i in range(begin) if tokens[i][0].upper() == 'WHEN'), begin)
    event = next(token[0].upper() for token in tokens[:when]
                 if token[0].upper() in ('INSERT', 'UPDATE', 'DELETE'))
    condition = sql[tokens[when].end():tokens[begin].start()] if when < begin else '1'
    label = _literal(name)

    def unwind_ignore(fragment):
        parts = _tokens(fragment)
        for i in range(len(parts) - 4, -1, -1):
            if [token[0].upper() for token in parts[i:i+4]] == ['RAISE', '(', 'IGNORE', ')']:
                fragment = (fragment[:parts[i].start()]
                            + f'CASE WHEN _vault_leave({label}) THEN RAISE(IGNORE) END'
                            + fragment[parts[i+3].end():])
        return fragment

    header = sql[:tokens[when].start()]
    explicit = "_vault_operation() = 'DELETE' AND " if event == 'DELETE' else ''
    body = []
    start = tokens[begin].end()
    for token in tokens[begin+1:]:
        if token[0] == ';':
            statement = sql[start:token.start()]
            kind = _tokens(statement)[0][0].upper()
            body.extend((f'SELECT _vault_operation({_literal(kind)})',
                         unwind_ignore(statement)))
            start = token.end()
    body.append(f'SELECT _vault_leave({label})')
    return (header + f' WHEN CASE WHEN _vault_active({label}) THEN 0 '
            f'WHEN {explicit}({unwind_ignore(condition)}) '
            f'THEN _vault_enter({label}) ELSE 0 END BEGIN\n'
            + ';\n'.join(body) + '; END')


class _WriteGuard:
    """Compare expected and effective row deltas, entirely inside SQLite.

    AFTER observers see successful changes, including every unique-index
    REPLACE victim. They use OLD/NEW only: no preservation query reads the
    accounts or receipts of another tenant. Typed row values and multiplicity
    matter; internal rowids do not.
    """

    def __init__(self, con, expected):
        self.con = con
        self.active = set()
        self.stack = []
        self.operation = None
        self.originals = []
        recursive = con.execute('PRAGMA recursive_triggers').fetchone()[0]
        if not recursive:
            self.originals = con.execute(
                "SELECT name, sql FROM sqlite_schema WHERE type='trigger' ORDER BY rowid"
            ).fetchall()
            con.create_function('_vault_active', 1, lambda name: name in self.active)
            con.create_function('_vault_enter', 1, self.enter)
            con.create_function('_vault_leave', 1, self.leave)
            con.create_function('_vault_operation', -1, self.set_operation)
            # This is inside BEGIN IMMEDIATE. All original trigger statements
            # remain active, and exact definitions are restored before commit.
            self.replace_triggers([(name, _observed_trigger(name, sql))
                                   for name, sql in self.originals])
            con.execute('PRAGMA recursive_triggers=ON')

        for table, columns in _COLUMNS.items():
            names = ', '.join(columns)
            # No affinities: retain NULLs and original SQLite storage types.
            con.execute(f'CREATE TEMP TABLE _vault_changes_{table} ({names}, change INTEGER)')
            placeholders = ', '.join('?' for _ in range(len(columns) + 1))
            con.executemany(
                f'INSERT INTO _vault_changes_{table} VALUES ({placeholders})',
                [(*row[:-1], -row[-1]) for row in expected[table]],
            )
            for event in ('INSERT', 'UPDATE', 'DELETE'):
                statements = []
                for values, change in (('OLD', -1), ('NEW', 1)):
                    if (values == 'OLD' and event == 'INSERT') or (values == 'NEW' and event == 'DELETE'):
                        continue
                    fields = ', '.join(f'{values}.{col}' for col in columns)
                    statements.append(f'INSERT INTO _vault_changes_{table} '
                                      f'VALUES ({fields}, {change})')
                con.execute(f'''
                    CREATE TEMP TRIGGER _vault_watch_{table}_{event}
                    AFTER {event} ON main.{table}
                    BEGIN {'; '.join(statements)}; END
                ''')

    def replace_triggers(self, definitions):
        for name, _ in self.originals:
            self.con.execute(f'DROP TRIGGER main.{_identifier(name)}')
        for _, sql in definitions:
            self.con.execute(sql)

    def enter(self, name):
        self.active.add(name)
        self.stack.append((name, self.operation))
        return 1

    def leave(self, name):
        if self.stack and self.stack[-1][0] == name:
            _, self.operation = self.stack.pop()
            self.active.remove(name)
        return 1

    def set_operation(self, *operation):
        if operation:
            self.operation = operation[0]
        return self.operation

    def execute(self, sql, parameters):
        self.operation = sql.split()[0].upper()
        return self.con.execute(sql, parameters)

    def check(self):
        for table, columns in _COLUMNS.items():
            group = ', '.join([*columns, *(f'typeof({col})' for col in columns)])
            if self.con.execute(f'''
                SELECT 1 FROM _vault_changes_{table}
                GROUP BY {group} HAVING sum(change) != 0 LIMIT 1
            ''').fetchone():
                raise sqlite3.IntegrityError('transfer integrity check failed')
        self.replace_triggers(self.originals)


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
            guard = _WriteGuard(con, {
                'accounts': [
                    (tenant, source, funds, -1),
                    (tenant, source, funds - amount, 1),
                    (tenant, target, credit, -1),
                    (tenant, target, credit + amount, 1),
                ],
                'transfers': [(*row, 1)],
                'audit': [(*row, 1)],
            })
            guard.execute(
                'UPDATE accounts SET balance=balance-? WHERE tenant=? AND name=?',
                (amount, tenant, source),
            )
            guard.execute(
                'UPDATE accounts SET balance=balance+? WHERE tenant=? AND name=?',
                (amount, tenant, target),
            )
            guard.execute(
                'INSERT INTO transfers (tenant, key, source, target, amount) '
                'VALUES (?, ?, ?, ?, ?)', row,
            )
            guard.execute(
                'INSERT INTO audit (tenant, key, source, target, amount) '
                'VALUES (?, ?, ?, ?, ?)', row,
            )
            guard.check()
        return receipt
