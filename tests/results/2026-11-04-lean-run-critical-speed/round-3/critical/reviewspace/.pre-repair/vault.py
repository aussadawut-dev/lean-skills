"""Tenant-scoped accounting operations backed by SQLite."""

from collections import Counter
from contextlib import closing
import sqlite3


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


def _require_strings(*values):
    if any(not isinstance(value, str) or not value for value in values):
        raise ValueError('invalid request')


def _balance(con, tenant, account):
    row = con.execute(
        'SELECT balance FROM accounts WHERE tenant=? AND name=?',
        (tenant, account),
    ).fetchone()
    if row is None:
        raise ValueError('account not found')
    if not isinstance(row[0], int):
        raise sqlite3.IntegrityError('invalid account balance')
    return row[0]


def balance(path, tenant, account):
    _require_strings(tenant, account)
    with closing(sqlite3.connect(path)) as con:
        return _balance(con, tenant, account)


def _tokens(sql):
    """Locate SQL tokens without interpreting quoted names, strings or comments."""
    tokens = []
    i = 0
    while i < len(sql):
        start = i
        char = sql[i]
        if char in ' \t\r\n\f':
            i += 1
        elif sql.startswith('--', i):
            end = sql.find('\n', i + 2)
            i = len(sql) if end < 0 else end + 1
        elif sql.startswith('/*', i):
            end = sql.find('*/', i + 2)
            i = len(sql) if end < 0 else end + 2
        elif char in "'\"`[":
            quote = ']' if char == '[' else char
            i += 1
            while i < len(sql):
                if sql[i] == quote:
                    i += 1
                    if quote != ']' and i < len(sql) and sql[i] == quote:
                        i += 1
                        continue
                    break
                i += 1
            tokens.append((start, i, None))
        elif char.isalpha() or char == '_' or ord(char) >= 128:
            i += 1
            while i < len(sql) and (sql[i].isalnum() or sql[i] in '_$' or ord(sql[i]) >= 128):
                i += 1
            word = sql[start:i]
            tokens.append((start, i, word.upper() if word.isascii() else word))
        else:
            i += 1
            tokens.append((start, i, char))
    return tokens


def _quoted(name):
    return '"' + name.replace('"', '""') + '"'


def _guarded_trigger(con, sql, identity):
    """Keep SQLite's default nonrecursive trigger behavior with observers on.

    Guard entry and exits, and track explicit DELETE steps so implicit REPLACE
    deletions remain invisible to original DELETE triggers when recursion is off.
    Original SQL spans are preserved; SQLite validates the body boundary.
    """
    tokens = _tokens(sql)
    words = [token[2] for token in tokens]
    i = 1  # CREATE
    if words[i] in ('TEMP', 'TEMPORARY'):
        i += 1
    i += 1  # TRIGGER
    if words[i:i + 3] == ['IF', 'NOT', 'EXISTS']:
        i += 3
    i += 1  # trigger name, which may itself be a keyword
    if words[i] == '.':
        i += 2
    if words[i] in ('BEFORE', 'AFTER'):
        i += 1
    elif words[i:i + 2] == ['INSTEAD', 'OF']:
        i += 2
    event = words[i]
    i += 1  # INSERT / UPDATE / DELETE
    if words[i] == 'OF':
        i += 1
        while words[i] != 'ON':
            i += 1
    if words[i] != 'ON':
        raise sqlite3.IntegrityError('unsupported trigger header')
    i += 2  # ON table name
    if words[i] == '.':
        i += 2
    if words[i:i + 3] == ['FOR', 'EACH', 'ROW']:
        i += 3
    condition = i if words[i] == 'WHEN' else None
    end = len(tokens) - 1
    while words[end] == ';':
        end -= 1
    if words[end] != 'END':
        raise sqlite3.IntegrityError('unsupported trigger body')

    for begin in range(i, end):
        if words[begin] != 'BEGIN':
            continue
        allowed = f'__vault_allowed({identity},{int(event == "DELETE")})'
        if condition is None:
            header_start = tokens[begin][0]
            gate = f'WHEN CASE WHEN {allowed} THEN __vault_enter({identity}) ELSE 0 END\n'
        else:
            header_start = tokens[condition][0]
            expression = sql[tokens[condition][1]:tokens[begin][0]]
            gate = (f'WHEN CASE WHEN NOT {allowed} THEN 0 '
                    f'WHEN ({expression}) THEN __vault_enter({identity}) ELSE 0 END\n')
        edits = [(header_start, tokens[begin][0], gate),
                 (tokens[end][0], tokens[end][0], f'SELECT __vault_leave({identity});\n')]
        for position in range(begin + 1, end):
            if position == begin + 1 or words[position - 1] == ';':
                edits.append((tokens[position][0], tokens[position][0],
                              f'SELECT __vault_step({int(words[position] == "DELETE")});\n'))
        for position in range(begin + 1, end - 3):
            if words[position:position + 4] == ['RAISE', '(', 'IGNORE', ')']:
                edits.append((tokens[position][0], tokens[position + 3][1],
                              f'CASE WHEN __vault_leave({identity}) THEN RAISE(IGNORE) END'))
        rewritten = sql
        for start, stop, replacement in sorted(edits, reverse=True):
            rewritten = rewritten[:start] + replacement + rewritten[stop:]
        try:
            con.execute('EXPLAIN ' + rewritten).close()
        except sqlite3.OperationalError:
            continue  # BEGIN may be an identifier inside the WHEN expression.
        return rewritten
    raise sqlite3.IntegrityError('unsupported trigger body')


class _WriteGuard:
    """Observe actual row deltas, including REPLACE victims, without table scans."""

    columns = {
        'accounts': ('tenant', 'name', 'balance'),
        'transfers': ('tenant', 'key', 'source', 'target', 'amount'),
        'audit': ('tenant', 'key', 'source', 'target', 'amount'),
    }

    def __init__(self, con):
        self.con = con
        self.effects = Counter()
        self.active = set()
        self.stack = []
        self.observers = []
        self.originals = []
        self.recursive = con.execute('PRAGMA recursive_triggers').fetchone()[0]
        con.create_function('__vault_delta', -1, self.observe)
        con.create_function('__vault_allowed', 2, self.allowed)
        con.create_function('__vault_enter', 1, self.enter)
        con.create_function('__vault_leave', 1, self.leave)
        con.create_function('__vault_step', 1, self.step)
        if not self.recursive:
            self.originals = con.execute(
                "SELECT name,sql FROM sqlite_master WHERE type='trigger' ORDER BY rowid"
            ).fetchall()
            for name, _ in self.originals:
                con.execute('DROP TRIGGER main.' + _quoted(name))
            for identity, (_, sql) in enumerate(self.originals):
                con.execute(_guarded_trigger(con, sql, identity))
        # SQLite fires DELETE observers for implicit REPLACE victims only with
        # recursive triggers enabled. Original triggers retain their old guards.
        con.execute('PRAGMA recursive_triggers=ON')
        for table, columns in self.columns.items():
            for event in ('INSERT', 'UPDATE', 'DELETE'):
                name = f'__vault_{table}_{event.lower()}'
                steps = []
                for alias, sign in (('OLD', -1), ('NEW', 1)):
                    if (alias == 'OLD' and event == 'INSERT') or (alias == 'NEW' and event == 'DELETE'):
                        continue
                    values = ','.join(alias + '.' + _quoted(column) for column in columns)
                    steps.append(f"SELECT __vault_delta('{table}',{sign},{values});")
                con.execute(f'CREATE TEMP TRIGGER {_quoted(name)} AFTER {event} '
                            f'ON main.{_quoted(table)} BEGIN ' + ' '.join(steps) + ' END')
                self.observers.append(name)

    def allowed(self, identity, deleting):
        # All direct transfer statements are UPDATE or INSERT. Nested explicit
        # DELETE statements are marked by their enclosing original trigger.
        explicit_delete = self.stack and self.stack[-1][1]
        return identity not in self.active and (not deleting or bool(explicit_delete))

    def enter(self, identity):
        if identity in self.active:
            return 0
        self.active.add(identity)
        self.stack.append([identity, False])
        return 1

    def leave(self, identity):
        if not self.stack or self.stack[-1][0] != identity:
            raise sqlite3.IntegrityError('invalid trigger exit')
        self.stack.pop()
        self.active.remove(identity)
        return 1

    def step(self, deleting):
        self.stack[-1][1] = bool(deleting)

    def observe(self, table, sign, *values):
        row = (table, values)
        self.effects[row] += sign
        if not self.effects[row]:
            del self.effects[row]

    def finish(self, expected):
        if self.effects != expected or self.active:
            raise sqlite3.IntegrityError('unexpected transfer effects')
        for name in self.observers:
            self.con.execute('DROP TRIGGER temp.' + _quoted(name))
        # DDL is transactional too: failures roll back the original definitions;
        # success restores the same SQL in the same trigger creation order.
        for name, _ in self.originals:
            self.con.execute('DROP TRIGGER main.' + _quoted(name))
        for _, sql in self.originals:
            self.con.execute(sql)
        if not self.recursive:
            self.con.execute('PRAGMA recursive_triggers=OFF')


def transfer(path, tenant, source, target, amount, key):
    _require_strings(tenant, source, target, key)
    if source == target or isinstance(amount, bool) or not isinstance(amount, int) or amount <= 0:
        raise ValueError('invalid request')

    receipt = dict(tenant=tenant, key=key, source=source, target=target, amount=amount)
    values = (tenant, key, source, target, amount)
    with closing(sqlite3.connect(path, timeout=30)) as con, con:
        # Reserve the writer before reading receipts or funds. Other writers must
        # see this transaction's receipt and balances before deciding what to do.
        con.execute('BEGIN IMMEDIATE')
        funds = _balance(con, tenant, source)
        credit = _balance(con, tenant, target)
        old = con.execute(
            'SELECT tenant,key,source,target,amount FROM transfers WHERE tenant=? AND key=?',
            (tenant, key),
        ).fetchone()
        if old is not None:
            if old != values:
                raise ValueError('key conflict')
            return dict(zip(receipt, old))
        if funds < amount:
            raise ValueError('insufficient funds')

        guard = _WriteGuard(con)
        expected = Counter({
            ('accounts', (tenant, source, funds)): -1,
            ('accounts', (tenant, source, funds - amount)): 1,
            ('accounts', (tenant, target, credit)): -1,
            ('accounts', (tenant, target, credit + amount)): 1,
            ('transfers', values): 1,
            ('audit', values): 1,
        })
        con.execute('UPDATE accounts SET balance=? WHERE tenant=? AND name=?',
                    (funds - amount, tenant, source))
        con.execute('UPDATE accounts SET balance=? WHERE tenant=? AND name=?',
                    (credit + amount, tenant, target))
        con.execute('INSERT INTO transfers (tenant,key,source,target,amount) VALUES (?,?,?,?,?)', values)
        con.execute('INSERT INTO audit (tenant,key,source,target,amount) VALUES (?,?,?,?,?)', values)
        guard.finish(expected)
        return receipt
