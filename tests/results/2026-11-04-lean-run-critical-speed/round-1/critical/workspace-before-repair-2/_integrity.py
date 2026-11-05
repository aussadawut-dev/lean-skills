"""Observe a transaction's logical row delta without selecting foreign rows."""

import re
import sqlite3
import uuid


_TOKENS = re.compile(
    r"(?P<skip>\s+|--[^\n]*|/\*.*?\*/)"
    r"|'(?:''|[^'])*'|\"(?:\"\"|[^\"])*\"|`(?:``|[^`])*`|\[[^\]]*\]"
    r"|[A-Za-z_\u0080-\U0010ffff][A-Za-z_0-9$\u0080-\U0010ffff]*|.",
    re.DOTALL,
)


def _quote(identifier):
    return '"' + identifier.replace('"', '""') + '"'


def _header(tokens):
    """Locate WHEN/BEGIN after the fixed CREATE TRIGGER header grammar."""
    words = [token.group().upper() for token in tokens]

    def name_end(index):
        index += 1
        if words[index] == '.':
            index += 2
        return index

    index = 1  # CREATE
    if words[index] in ('TEMP', 'TEMPORARY'):
        index += 1
    if words[index] != 'TRIGGER':
        raise sqlite3.DatabaseError('unsupported trigger definition')
    index += 1
    if words[index:index + 3] == ['IF', 'NOT', 'EXISTS']:
        index += 3
    index = name_end(index)
    if words[index] in ('BEFORE', 'AFTER'):
        index += 1
    elif words[index:index + 2] == ['INSTEAD', 'OF']:
        index += 2
    event = words[index]
    index += 1
    if event == 'UPDATE' and words[index] == 'OF':
        index += 1
        while True:
            index = name_end(index)
            if words[index] != ',':
                break
            index += 1
    if words[index] != 'ON':
        raise sqlite3.DatabaseError('unsupported trigger definition')
    index = name_end(index + 1)
    if words[index:index + 3] == ['FOR', 'EACH', 'ROW']:
        index += 3
    if words[index] == 'WHEN':
        return event, index, [i for i in range(index + 1, len(words)) if words[i] == 'BEGIN']
    return event, None, [index] if words[index] == 'BEGIN' else []


def _guarded_definitions(sql, number, prefix):
    tokens = [match for match in _TOKENS.finditer(sql) if match.lastgroup != 'skip']
    event, when, candidates = _header(tokens)
    last = len(tokens) - 1
    if tokens[last].group() == ';':
        last -= 1
    if tokens[last].group().upper() != 'END':
        raise sqlite3.DatabaseError('unsupported trigger definition')
    end = tokens[last].start()

    def fragment(start, stop):
        # RAISE(IGNORE) skips the remainder of a trigger. Unwind its guard at
        # that expression, so the caller's next trigger statement can run it.
        pieces = []
        position = start
        for index in range(len(tokens) - 3):
            group = tokens[index:index + 4]
            if (group[0].start() >= start and group[-1].end() <= stop
                    and [part.group().upper() for part in group]
                    == ['RAISE', '(', 'IGNORE', ')']):
                pieces.append(sql[position:group[0].start()])
                pieces.append(f'CASE WHEN {prefix}_ignore({number}) '
                              'THEN RAISE(IGNORE) END')
                position = group[-1].end()
        pieces.append(sql[position:stop])
        return ''.join(pieces)

    for begin in candidates:
        if tokens[begin].start() >= end:
            continue
        header_end = tokens[when].start() if when is not None else tokens[begin].start()
        condition = (fragment(tokens[when].end(), tokens[begin].start())
                     if when is not None else '1')
        # Trigger statements end in semicolons. Quoted strings/identifiers and
        # comments are already single tokens or skipped, so their semicolons
        # do not split statements. Preserve every original SQL span.
        body = []
        position = tokens[begin].end()
        statement = begin + 1
        for index in range(statement, last):
            if tokens[index].group() == ';':
                deleting = int(tokens[statement].group().upper() == 'DELETE')
                body.append(f'\nSELECT {prefix}_statement({deleting});\n' +
                            fragment(position, tokens[index].end()))
                position = tokens[index].end()
                statement = index + 1
        body.append(fragment(position, end))
        yield (sql[:header_end] +
               f'WHEN CASE WHEN {prefix}_allowed({number},{int(event == "DELETE")}) '
               f'THEN ({condition}) ELSE 0 END\nBEGIN\n'
               f'SELECT {prefix}_enter({number});\n' + ''.join(body) +
               f'\nSELECT {prefix}_leave({number});\n' + sql[end:])


class TransferEffects:
    """Used inside the caller's transaction; any failure rolls back its DDL too.

    Recursive delete observation is needed for REPLACE victims. When recursion
    was off, guards retain each existing trigger's nonrecursive behavior and
    suppress its DELETE events unless the calling statement is DELETE. Only
    observers see implicit REPLACE deletions. Original definitions and creation
    order are restored before commit.
    """

    def __init__(self, con):
        self.con = con
        self.prefix = '_vault_' + uuid.uuid4().hex
        self.delta = _quote(self.prefix + '_delta')
        self.active = set()
        # Transfer's top-level statements are INSERT/UPDATE. Each nested
        # trigger saves this context and marks its own statements in turn.
        self.deleting = [False]
        self.recursive = con.execute('PRAGMA recursive_triggers').fetchone()[0]
        self.triggers = con.execute(
            "SELECT name, sql FROM main.sqlite_schema WHERE type='trigger' ORDER BY rowid"
        ).fetchall()
        con.execute('PRAGMA recursive_triggers=ON')
        if not self.recursive:
            con.create_function(self.prefix + '_allowed', 2, self._allowed)
            con.create_function(self.prefix + '_enter', 1, self._enter)
            con.create_function(self.prefix + '_leave', 1, self._leave)
            con.create_function(self.prefix + '_statement', 1, self._statement)
            con.create_function(self.prefix + '_ignore', 1, self._ignore)
            self._drop_originals()
            for number, (_, sql) in enumerate(self.triggers):
                for definition in _guarded_definitions(sql, number, self.prefix):
                    try:
                        con.execute(definition)
                    except sqlite3.OperationalError:
                        # BEGIN can also be an unquoted identifier in WHEN.
                        # Let SQLite validate the proposed grammar boundary.
                        continue
                    break
                else:
                    raise sqlite3.DatabaseError('unsupported trigger definition')

        con.execute(f'CREATE TEMP TABLE {self.delta} '
                    '(kind TEXT, tenant, identity, source, target, value, delta INTEGER)')
        for table, columns in (
                ('accounts', ('tenant', 'name', None, None, 'balance')),
                ('transfers', ('tenant', 'key', 'source', 'target', 'amount')),
                ('audit', ('tenant', 'key', 'source', 'target', 'amount'))):
            for event in ('INSERT', 'UPDATE', 'DELETE'):
                statements = []
                for alias, sign in (('OLD', -1), ('NEW', 1)):
                    if (alias == 'OLD' and event == 'INSERT'
                            or alias == 'NEW' and event == 'DELETE'):
                        continue
                    values = ','.join('NULL' if column is None else alias + '.' + column
                                      for column in columns)
                    statements.append(f'INSERT INTO {self.delta} '
                                      f"VALUES ('{table}',{values},{sign});")
                name = _quote(self.prefix + '_' + table + '_' + event)
                con.execute(f'CREATE TEMP TRIGGER {name} AFTER {event} ON main.{table} '
                            'BEGIN ' + ' '.join(statements) + ' END')

    def _drop_originals(self):
        for name, _ in self.triggers:
            self.con.execute('DROP TRIGGER main.' + _quote(name))

    def _ignore(self, number):
        self._leave(number)
        return 1

    def _allowed(self, number, deleting):
        return int(number not in self.active and (not deleting or self.deleting[-1]))

    def _enter(self, number):
        self.active.add(number)
        self.deleting.append(False)

    def _leave(self, number):
        # RAISE(IGNORE) in WHEN can run before this trigger has entered.
        if number in self.active:
            self.active.remove(number)
            self.deleting.pop()

    def _statement(self, deleting):
        self.deleting[-1] = bool(deleting)

    def execute(self, sql, parameters):
        try:
            return self.con.execute(sql, parameters)
        finally:
            self.active.clear()
            self.deleting[:] = [False]

    def finish(self, inverse_delta):
        self.con.executemany(f'INSERT INTO {self.delta} VALUES (?,?,?,?,?,?,?)',
                             inverse_delta)
        columns = ('kind', 'tenant', 'identity', 'source', 'target', 'value')
        group = ','.join(f'{column}, typeof({column})' for column in columns)
        unexpected = self.con.execute(
            f'SELECT EXISTS(SELECT 1 FROM {self.delta} GROUP BY {group} '
            'HAVING SUM(delta) <> 0)'
        ).fetchone()[0]
        if unexpected:
            raise sqlite3.IntegrityError('unexpected transfer effects')
        if not self.recursive:
            self._drop_originals()
            for _, sql in self.triggers:
                self.con.execute(sql)
            self.con.execute('PRAGMA recursive_triggers=OFF')
