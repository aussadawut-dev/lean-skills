from collections import Counter
from contextlib import closing
import sqlite3
import uuid


def _validate_names(*names):
    if any(not isinstance(name, str) or not name for name in names):
        raise ValueError('invalid request')


def _account_balance(con, tenant, account):
    row = con.execute(
        'SELECT balance FROM accounts WHERE tenant = ? AND name = ?',
        (tenant, account),
    ).fetchone()
    if row is None or not isinstance(row[0], int):
        # Missing and inaccessible accounts deliberately have the same error.
        raise ValueError('invalid request')
    return row[0]


def _quote(name):
    return '"' + name.replace('"', '""') + '"'


def _sql_tokens(sql):
    """Locate SQL spans, leaving grammar validation to SQLite itself.

    SQLite's separators differ from Python's isspace(): VT is illegal, NBSP
    is an identifier character, and BOM is space only at a token boundary.
    Quoted text and comments must remain intact, including their semicolons.
    """
    index = 0
    while index < len(sql):
        start = index
        char = sql[index]
        if char in ' \t\r\n\f\ufeff':
            index += 1
            continue
        if sql.startswith('--', index):
            end = sql.find('\n', index + 2)
            index = len(sql) if end < 0 else end + 1
            continue
        if sql.startswith('/*', index):
            end = sql.find('*/', index + 2)
            index = len(sql) if end < 0 else end + 2
            continue
        if char in "'\"`[":
            close = ']' if char == '[' else char
            index += 1
            while index < len(sql):
                if sql[index] == close:
                    index += 1
                    if close != ']' and index < len(sql) and sql[index] == close:
                        index += 1
                        continue
                    break
                index += 1
        elif char.isascii() and (char.isalnum() or char in '_$') or ord(char) >= 128:
            index += 1
            while index < len(sql):
                char = sql[index]
                if not (char.isascii() and (char.isalnum() or char in '_$') or ord(char) >= 128):
                    break
                index += 1
        else:
            index += 1
        yield start, index, sql[start:index].upper()


def _instrument_trigger(con, sql, number, function, probe_name):
    tokens = list(_sql_tokens(sql))
    position = 2 if tokens[1][2] == 'TRIGGER' else 3
    if tokens[position][2] == 'IF':
        position += 3  # IF NOT EXISTS
    name_start, name_end, _ = tokens[position]
    position += 1
    if tokens[position][2] == '.':
        name_end = tokens[position + 1][1]
        position += 2
    if tokens[position][2] in ('BEFORE', 'AFTER'):
        position += 1
    elif tokens[position][2] == 'INSTEAD':
        position += 2
    event = tokens[position][2]
    tail = len(tokens) - 1
    while tokens[tail][2] == ';':
        tail -= 1
    guard = f"{function}('allowed', {number}, '{event}')"

    # BEGIN/WHEN can also be identifiers or occur inside CASE expressions.
    # Try preserved spans and let the installed engine choose a valid grammar,
    # rather than treating the first matching word as the trigger boundary.
    for begin in range(position + 1, tail):
        if tokens[begin][2] != 'BEGIN':
            continue
        cursor = tokens[begin][1]
        first = begin + 1
        body = []
        for end in range(begin + 1, tail):
            if tokens[end][2] != ';':
                continue
            operation = tokens[first][2]
            if operation not in ('INSERT', 'REPLACE', 'UPDATE', 'DELETE', 'SELECT'):
                break
            body.append(f"\nSELECT {function}('enter', {number}, '{operation}');\n")
            body.append(sql[cursor:tokens[end][1]])
            body.append(f"\nSELECT {function}('leave', {number}, '{operation}');\n")
            cursor = tokens[end][1]
            first = end + 1
        else:
            if not body:
                continue
            body.append(sql[cursor:])
            whens = [i for i in range(position + 1, begin) if tokens[i][2] == 'WHEN']
            for when in [*whens, None]:
                if when is None:
                    header = sql[:tokens[begin][0]] + 'WHEN ' + guard + '\n'
                else:
                    header = (sql[:tokens[when][0]] + 'WHEN ' + guard + ' AND ('
                              + sql[tokens[when][1]:tokens[begin][0]] + '\n) ')
                candidate = header + 'BEGIN' + ''.join(body)
                probe = candidate[:name_start] + _quote(probe_name) + candidate[name_end:]
                try:
                    con.execute('EXPLAIN ' + probe).fetchall()
                except sqlite3.Error:
                    continue
                return candidate
    raise sqlite3.IntegrityError('cannot observe storage effects')


class _TransferEffects:
    """Observe logical OLD/NEW deltas without selecting foreign stored rows.

    TEMP AFTER triggers see actual effects (including effects before a user's
    AFTER RAISE(IGNORE)). Recursive triggers expose implicit REPLACE deletions
    for every UNIQUE index. Existing triggers are guarded to retain SQLite's
    native nonrecursive behavior and its suppression of implicit DELETE
    triggers. All definition changes are restored within the transaction.
    Observer functions perform no SQL writes, preserving changes() and
    total_changes(). Rowids are deliberately not part of the logical frame.
    """

    def __init__(self, con):
        self.con = con
        self.delta = Counter()
        self.stack = []
        prefix = '_vault_' + uuid.uuid4().hex
        self.context = _quote(prefix + '_context')
        observe = _quote(prefix + '_observe')
        con.create_function(prefix + '_context', 3, self._context)
        con.create_function(prefix + '_observe', -1, self._observe)
        self.recursive = con.execute('PRAGMA recursive_triggers').fetchone()[0]
        self.originals = []
        if not self.recursive:
            self.originals = con.execute(
                "SELECT name, sql FROM main.sqlite_master WHERE type='trigger' ORDER BY rowid"
            ).fetchall()
            replacements = [_instrument_trigger(con, sql, index, self.context, prefix + '_probe')
                            for index, (_, sql) in enumerate(self.originals)]
            self._replace_triggers(replacements)
        con.execute('PRAGMA recursive_triggers=ON')
        columns = {'accounts': ('tenant', 'name', 'balance'),
                   'transfers': ('tenant', 'key', 'source', 'target', 'amount'),
                   'audit': ('tenant', 'key', 'source', 'target', 'amount')}
        for table, names in columns.items():
            for event, versions in (('INSERT', (('NEW', 1),)),
                                    ('DELETE', (('OLD', -1),)),
                                    ('UPDATE', (('OLD', -1), ('NEW', 1)))):
                statements = []
                for version, sign in versions:
                    args = []
                    for name in names:
                        value = version + '.' + _quote(name)
                        # Preserve storage classes and exact numbers; pass TEXT
                        # as bytes so even malformed foreign UTF-8 is opaque.
                        args.extend([f'typeof({value})', f"CASE WHEN typeof({value})='text' "
                                     f'THEN CAST({value} AS BLOB) ELSE {value} END'])
                    statements.append(f"SELECT {observe}('{table}', {sign}, {', '.join(args)});")
                con.execute(f'CREATE TEMP TRIGGER {_quote(prefix + table + event)} '
                            f'AFTER {event} ON main.{table} BEGIN {" ".join(statements)} END')

    def _replace_triggers(self, definitions):
        # Recreate in original order to preserve the order of sibling triggers.
        for name, _ in self.originals:
            self.con.execute('DROP TRIGGER main.' + _quote(name))
        for sql in definitions:
            self.con.execute(sql)

    def _context(self, action, number, operation):
        if action == 'allowed':
            return (not any(frame[0] == number for frame in self.stack)
                    and (operation != 'DELETE' or self.stack[-1][1] == 'DELETE'))
        if action == 'enter':
            self.stack.append((number, operation))
        else:
            for index in range(len(self.stack) - 1, 0, -1):
                if self.stack[index][0] == number:
                    # RAISE(IGNORE) can skip nested epilogues. The caller's
                    # statement boundary also discards those abandoned frames.
                    del self.stack[index:]
                    break

    def _observe(self, table, sign, *row):
        self.delta[(table, row)] += sign

    def execute(self, sql, values):
        self.stack = [(-1, sql.split()[0])]
        try:
            self.con.execute(sql, values)
        finally:
            self.stack.clear()

    def verify(self, tenant, source, target, funds, destination, amount, key):
        expected = Counter()

        def effect(table, sign, *values):
            row = tuple(part for value in values for part in
                        (('text', value.encode('utf-8')) if isinstance(value, str)
                         else ('integer', value)))
            expected[(table, row)] += sign

        effect('accounts', -1, tenant, source, funds)
        effect('accounts', 1, tenant, source, funds - amount)
        effect('accounts', -1, tenant, target, destination)
        effect('accounts', 1, tenant, target, destination + amount)
        for table in ('transfers', 'audit'):
            effect(table, 1, tenant, key, source, target, amount)
        if {row: n for row, n in self.delta.items() if n} != {row: n for row, n in expected.items() if n}:
            raise sqlite3.IntegrityError('unexpected storage effects')
        self._replace_triggers([sql for _, sql in self.originals])
        self.con.execute('PRAGMA recursive_triggers=' + str(self.recursive))


def init_db(path):
    with closing(sqlite3.connect(path, timeout=30)) as con:
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


def balance(path, tenant, account):
    _validate_names(tenant, account)
    with closing(sqlite3.connect(path, timeout=30)) as con:
        return _account_balance(con, tenant, account)


def transfer(path, tenant, source, target, amount, key):
    _validate_names(tenant, source, target, key)
    if source == target or isinstance(amount, bool) or not isinstance(amount, int) or amount <= 0:
        raise ValueError('invalid request')

    receipt = dict(tenant=tenant, key=key, source=source, target=target, amount=amount)
    with closing(sqlite3.connect(path, timeout=30, isolation_level=None)) as con:
        con.row_factory = sqlite3.Row
        with con:
            # Serialize writers before reading either balances or replay keys.
            # A waiting request then sees the preceding transaction's commit.
            con.execute('BEGIN IMMEDIATE')
            old = con.execute(
                'SELECT tenant, key, source, target, amount FROM transfers '
                'WHERE tenant = ? AND key = ?', (tenant, key),
            ).fetchone()
            if old is not None:
                if dict(old) != receipt:
                    raise ValueError('invalid request')
                return dict(old)

            funds = _account_balance(con, tenant, source)
            destination = _account_balance(con, tenant, target)
            if funds < amount:
                raise ValueError('invalid request')

            effects = _TransferEffects(con)
            # Bind integer results: SQLite arithmetic otherwise converts an
            # overflowing integer credit into an inexact floating point value.
            effects.execute('UPDATE accounts SET balance = ? WHERE tenant = ? AND name = ?',
                            (funds - amount, tenant, source))
            effects.execute('UPDATE accounts SET balance = ? WHERE tenant = ? AND name = ?',
                            (destination + amount, tenant, target))
            values = (tenant, key, source, target, amount)
            effects.execute('INSERT INTO transfers (tenant, key, source, target, amount) '
                            'VALUES (?, ?, ?, ?, ?)', values)
            effects.execute('INSERT INTO audit (tenant, key, source, target, amount) '
                            'VALUES (?, ?, ?, ?, ?)', values)
            effects.verify(tenant, source, target, funds, destination, amount, key)
        # The context commits all four effects, or rolls them all back on error.
        return receipt
