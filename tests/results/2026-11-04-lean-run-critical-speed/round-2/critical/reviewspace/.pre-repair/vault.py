from contextlib import closing
import sqlite3
import uuid


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


def _validate_names(*values):
    if any(not isinstance(value, str) or not value for value in values):
        raise ValueError('invalid request')


def balance(path, tenant, account):
    _validate_names(tenant, account)
    with closing(sqlite3.connect(path)) as con:
        row = con.execute(
            'SELECT balance FROM accounts WHERE tenant=? AND name=?',
            (tenant, account),
        ).fetchone()
        if row is None:
            raise ValueError('account unavailable')
        return row[0]


def _write_one(con, sql, values):
    # A trigger may silently ignore a write; that cannot count as a transfer.
    if con.execute(sql, values).rowcount != 1:
        raise sqlite3.IntegrityError('transfer write failed')


def _tokens(sql):
    """Locate SQL spans; SQLite, rather than this scanner, validates grammar."""
    offset = 0
    while offset < len(sql):
        start = offset
        char = sql[offset]
        if char.isspace():
            offset += 1
            continue
        if sql.startswith('--', offset):
            end = sql.find('\n', offset)
            offset = len(sql) if end < 0 else end + 1
            continue
        if sql.startswith('/*', offset):
            end = sql.find('*/', offset + 2)
            offset = len(sql) if end < 0 else end + 2
            continue
        if char in "'\"`":
            offset += 1
            while offset < len(sql):
                if sql[offset] == char:
                    offset += 1
                    if offset == len(sql) or sql[offset] != char:
                        break
                offset += 1
        elif char == '[':
            offset = sql.index(']', offset) + 1
        elif char.isalnum() or char in '_$' or ord(char) >= 128:
            offset += 1
            while offset < len(sql) and (
                sql[offset].isalnum() or sql[offset] in '_$' or ord(sql[offset]) >= 128
            ):
                offset += 1
        else:
            offset += 1
        yield start, offset, sql[start:offset].upper()


def _quote_name(name):
    return '"' + name.replace('"', '""') + '"'


def _guard_trigger(con, sql, tag, enter, step, leave):
    """Retain native nonrecursive execution while observers see REPLACE deletes."""
    tokens = list(_tokens(sql))

    def valid_header(prefix):
        try:
            con.execute('EXPLAIN ' + prefix + '\nBEGIN SELECT 1; END')
            return True
        except sqlite3.OperationalError:
            return False

    # Names and WHEN expressions may themselves contain BEGIN/WHEN tokens.
    # Only the engine can accept a complete trigger header at these boundaries.
    begin = next(index for index, token in enumerate(tokens)
                 if token[2] == 'BEGIN' and valid_header(sql[:token[0]]))
    when = next((index for index, token in enumerate(tokens[:begin])
                 if token[2] == 'WHEN' and valid_header(sql[:token[0]])), None)
    end = len(tokens) - 1
    if tokens[end][2] == ';':
        end -= 1

    # Skip the fixed CREATE TRIGGER prefix and its (possibly qualified) name.
    index = 1
    if tokens[index][2] in ('TEMP', 'TEMPORARY'):
        index += 1
    index += 1  # TRIGGER
    if [token[2] for token in tokens[index:index + 3]] == ['IF', 'NOT', 'EXISTS']:
        index += 3  # IF NOT EXISTS
    index += 1  # trigger name, including quoted or Unicode identifiers
    if tokens[index][2] == '.':
        index += 2
    if tokens[index][2] in ('BEFORE', 'AFTER'):
        index += 1
    elif tokens[index][2] == 'INSTEAD':
        index += 2
    event = tokens[index][2]

    def unwind_ignores(fragment):
        spans = list(_tokens(fragment))
        parts, start = [], 0
        for index in range(len(spans) - 3):
            if [token[2] for token in spans[index:index + 4]] == ['RAISE', '(', 'IGNORE', ')']:
                left, right = spans[index][0], spans[index + 3][1]
                parts.extend((fragment[start:left],
                              f'(CASE WHEN {leave}({tag}) THEN NULL ELSE ',
                              fragment[left:right], ' END)'))
                start = right
        return ''.join(parts) + fragment[start:]

    condition = '1' if when is None else sql[tokens[when][1]:tokens[begin][0]]
    header = sql[:tokens[begin if when is None else when][0]]
    guarded = (header + f'\nWHEN CASE WHEN {enter}({tag}, \'{event}\') THEN '
               f'CASE WHEN (\n{unwind_ignores(condition)}\n) THEN 1 '
               f'ELSE {leave}({tag}) END ELSE 0 END\nBEGIN\n')
    start, command = tokens[begin][1], None
    for left, right, word in tokens[begin + 1:end]:
        if command is None:
            command = 'INSERT' if word == 'REPLACE' else word
        if word == ';':
            guarded += (f'\nSELECT {step}({tag}, \'{command}\');\n'
                        + unwind_ignores(sql[start:right]))
            start, command = right, None
    return (guarded + sql[start:tokens[end][0]]
            + f'\nSELECT {leave}({tag});\n' + sql[tokens[end][0]:])


class _TransferEffects:
    """Compare a storage-local OLD/NEW multiset with the authorized delta.

    No foreign account or receipt values are fetched. Rowids are deliberately
    absent: moving a row, a no-op update, or a cancelled intermediate change
    preserves its logical identity and values. Multiplicities still matter.
    """

    def __init__(self, con):
        self.con = con
        self.prefix = '_vault_' + uuid.uuid4().hex
        self.delta = self.prefix + '_delta'
        self.stack = []
        self.command = None
        self.originals = []
        self.observers = []
        self.observed_writes = 0
        observed = self.prefix + '_observed'
        con.create_function(observed, 0, self._observed)
        # Internal delta rows must not alter counters consulted by user triggers.
        # changes() and last_insert_rowid() are already saved/restored by SQLite
        # around each trigger; total_changes() also includes our internal rows.
        con.create_function('total_changes', 0,
                            lambda: con.total_changes - self.observed_writes)
        self.recursive = con.execute('PRAGMA recursive_triggers').fetchone()[0]
        if not self.recursive:
            self.originals = con.execute(
                "SELECT name,sql FROM main.sqlite_master WHERE type='trigger' ORDER BY rowid"
            ).fetchall()
            enter, step, leave = (self.prefix + suffix for suffix in ('_enter', '_step', '_leave'))
            con.create_function(enter, 2, self._enter)
            con.create_function(step, 2, self._step)
            con.create_function(leave, 1, self._leave)
            for name, _ in self.originals:
                con.execute('DROP TRIGGER main.' + _quote_name(name))
            for tag, (_, sql) in enumerate(self.originals):
                con.execute(_guard_trigger(con, sql, tag, enter, step, leave))

        # SQLite only reports REPLACE's implicit deletions to DELETE triggers
        # with recursion enabled. Original triggers retain their prior behavior.
        con.execute('PRAGMA recursive_triggers=ON')
        con.execute(f'CREATE TEMP TABLE {self.delta} (kind, sign, v1, v2, v3, v4, v5)')
        for table, columns in (
            ('accounts', ('tenant', 'name', 'balance')),
            ('transfers', ('tenant', 'key', 'source', 'target', 'amount')),
            ('audit', ('tenant', 'key', 'source', 'target', 'amount')),
        ):
            for event in ('INSERT', 'UPDATE', 'DELETE'):
                body = ''
                for row, sign in (('OLD', -1), ('NEW', 1)):
                    if (row == 'OLD' and event == 'INSERT') or (row == 'NEW' and event == 'DELETE'):
                        continue
                    values = [row + '.' + _quote_name(column) for column in columns]
                    values += ['NULL'] * (5 - len(values))
                    body += (f"INSERT INTO {self.delta} VALUES ('{table}',{sign},"
                             + ','.join(values) + f'); SELECT {observed}();')
                name = self.prefix + '_' + table + '_' + event
                # TEMP AFTER observers run before persistent AFTER triggers,
                # including those which end their statement with RAISE(IGNORE).
                con.execute(f'CREATE TEMP TRIGGER {name} AFTER {event} ON main.{table} '
                            f'BEGIN {body} END')
                self.observers.append(name)

    def _observed(self):
        self.observed_writes += 1

    def _enter(self, tag, event):
        command = self.stack[-1][1] if self.stack else self.command
        if any(frame[0] == tag for frame in self.stack):
            return 0
        # With recursion off, native DELETE triggers do not run for implicit
        # REPLACE victims. Explicit DELETE statements must still invoke them.
        if event == 'DELETE' and command != 'DELETE':
            return 0
        self.stack.append([tag, command])
        return 1

    def _step(self, tag, command):
        assert self.stack[-1][0] == tag
        self.stack[-1][1] = command

    def _leave(self, tag):
        assert self.stack[-1][0] == tag
        self.stack.pop()
        return 0

    def write(self, sql, values):
        self.command = sql.split()[0]
        _write_one(self.con, sql, values)
        if self.stack:
            raise sqlite3.IntegrityError('transfer trigger failed')

    def verify(self, tenant, source, target, accounts, amount, values):
        # Subtract the intended delta. All remaining logical changes must sum
        # to zero, including changes to history or other tenants by triggers.
        expected = []
        for name, change in ((source, -amount), (target, amount)):
            expected.extend((('accounts', 1, tenant, name, accounts[name], None, None),
                             ('accounts', -1, tenant, name, accounts[name] + change, None, None)))
        expected.extend((table, -1, *values) for table in ('transfers', 'audit'))
        self.con.executemany(f'INSERT INTO {self.delta} VALUES (?,?,?,?,?,?,?)', expected)
        groups = ','.join(f'typeof(v{index}),v{index} COLLATE BINARY' for index in range(1, 6))
        if self.con.execute(f'SELECT 1 FROM {self.delta} GROUP BY kind,{groups} '
                            'HAVING sum(sign) != 0 LIMIT 1').fetchone() is not None:
            raise sqlite3.IntegrityError('unexpected transfer effects')
        for name in self.observers:
            self.con.execute('DROP TRIGGER temp.' + name)
        self.con.execute('DROP TABLE temp.' + self.delta)
        for name, _ in self.originals:
            self.con.execute('DROP TRIGGER main.' + _quote_name(name))
        for _, sql in self.originals:
            self.con.execute(sql)
        self.con.execute(f'PRAGMA recursive_triggers={self.recursive}')


def transfer(path, tenant, source, target, amount, key):
    _validate_names(tenant, source, target, key)
    if (source == target or isinstance(amount, bool)
            or not isinstance(amount, int) or amount <= 0):
        raise ValueError('invalid request')

    receipt = dict(tenant=tenant, key=key, source=source,
                   target=target, amount=amount)
    with closing(sqlite3.connect(path, timeout=30)) as con, con:
        con.row_factory = sqlite3.Row
        # Acquire the writer lock before checking balances or replay state.
        # Separate connections then observe the preceding committed transfer.
        con.execute('BEGIN IMMEDIATE')
        old = con.execute(
            'SELECT tenant,key,source,target,amount FROM transfers '
            'WHERE tenant=? AND key=?', (tenant, key),
        ).fetchone()
        if old is not None:
            if dict(old) != receipt:
                raise ValueError('key conflict')
            return dict(old)

        accounts = {
            row['name']: row['balance']
            for row in con.execute(
                'SELECT name,balance FROM accounts '
                'WHERE tenant=? AND name IN (?,?)',
                (tenant, source, target),
            )
        }
        if source not in accounts or target not in accounts:
            raise ValueError('account unavailable')

        if accounts[source] < amount:
            raise ValueError('insufficient funds')

        effects = _TransferEffects(con)
        # Bind integer results rather than letting SQLite promote overflowing
        # integer arithmetic to floating point.
        effects.write('UPDATE accounts SET balance=? WHERE tenant=? AND name=?',
                      (accounts[source] - amount, tenant, source))
        effects.write('UPDATE accounts SET balance=? WHERE tenant=? AND name=?',
                      (accounts[target] + amount, tenant, target))
        values = (tenant, key, source, target, amount)
        effects.write('INSERT INTO transfers (tenant,key,source,target,amount) '
                      'VALUES (?,?,?,?,?)', values)
        effects.write('INSERT INTO audit (tenant,key,source,target,amount) '
                      'VALUES (?,?,?,?,?)', values)
        effects.verify(tenant, source, target, accounts, amount, values)
        return receipt
