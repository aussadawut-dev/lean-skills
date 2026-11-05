"""Transaction-local observation of SQLite row effects.

Only SQL touches the observed row images. Python receives a boolean verdict,
never another tenant's accounts or receipts. Physical slots reconcile event
order; the final comparison uses typed logical rows, including multiplicity.
"""

import sqlite3
import uuid


def _quote(name):
    return '"' + name.replace('"', '""') + '"'


def _tokens(sql):
    """SQLite tokens with original spans, not Python's Unicode whitespace."""
    result = []
    pos = 0
    while pos < len(sql):
        start = pos
        char = sql[pos]
        if char in ' \t\n\r\f':
            pos += 1
            while pos < len(sql) and sql[pos] in ' \t\n\r\f\v':
                pos += 1
            continue
        if char == '\ufeff':
            pos += 1
            continue
        if sql.startswith('--', pos):
            end = sql.find('\n', pos + 2)
            pos = len(sql) if end < 0 else end + 1
            continue
        if sql.startswith('/*', pos):
            end = sql.find('*/', pos + 2)
            pos = len(sql) if end < 0 else end + 2
            continue
        if char in "'\"`[":
            close = ']' if char == '[' else char
            pos += 1
            while pos < len(sql):
                if sql[pos] == close:
                    pos += 1
                    if close != ']' and pos < len(sql) and sql[pos] == close:
                        pos += 1
                        continue
                    break
                pos += 1
        elif char.isascii() and (char.isalnum() or char == '_') or ord(char) >= 128:
            pos += 1
            while pos < len(sql):
                char = sql[pos]
                if char.isascii() and (char.isalnum() or char in '_$') or ord(char) >= 128:
                    pos += 1
                else:
                    break
        else:
            pos += 1
        result.append((sql[start:pos], start, pos))
    return result


def _name(token):
    if token[0] in "'\"`[":
        close = ']' if token[0] == '[' else token[0]
        return token[1:-1].replace(close * 2, close)
    return token


class WriteIntegrity:
    _columns = {
        'accounts': ('tenant', 'name', 'balance'),
        'transfers': ('tenant', 'key', 'source', 'target', 'amount'),
        'audit': ('tenant', 'key', 'source', 'target', 'amount'),
    }

    def __init__(self, con):
        self.con = con
        self.prefix = '_vault_' + uuid.uuid4().hex
        self.journal = _quote(self.prefix + '_rows')
        self.mode_view = 'main.' + _quote(self.prefix + '_mode')
        self.hidden_changes = 0
        self.stack = []
        self.operation = None
        self.mode = con.execute('PRAGMA recursive_triggers').fetchone()[0]
        self.triggers = [tuple(row) for row in con.execute(
            "SELECT name,sql FROM main.sqlite_schema WHERE type='trigger' ORDER BY rowid"
        )]
        views = [tuple(row) for row in con.execute(
            "SELECT name,sql FROM main.sqlite_schema WHERE type='view' ORDER BY rowid"
        )]
        self.objects = {
            (schema, row[0].lower())
            for schema in ('main', 'temp')
            for row in con.execute(
                f"SELECT name FROM {schema}.sqlite_schema WHERE type IN ('table','view')"
            )
        }
        self.views = []
        for name, sql in views:
            rewritten = self._native_mode(sql)
            if rewritten != sql:
                self.views.append((name, sql, rewritten))

    def _function(self, suffix):
        return _quote(self.prefix + '_' + suffix)

    @staticmethod
    def _cte_scopes(tokens):
        """Ranges where an unqualified pragma name resolves to a CTE.

        WITH names are visible throughout their query, including forward CTE
        references and nested queries, but not outside the enclosing query.
        Schema-qualified sources bypass CTE lookup.
        """
        pairs = {}
        enclosing = {}
        stack = []
        for i, (token, _, _) in enumerate(tokens):
            enclosing[i] = stack[-1] if stack else None
            if token == '(':
                stack.append(i)
            elif token == ')' and stack:
                pairs[stack.pop()] = i
        scopes = []
        for start, (token, _, _) in enumerate(tokens):
            if token.upper() != 'WITH':
                continue
            i = start + 1
            if i < len(tokens) and tokens[i][0].upper() == 'RECURSIVE':
                i += 1
            names = []
            while i < len(tokens):
                name = _name(tokens[i][0]).lower()
                i += 1
                if i in pairs:  # optional CTE column names
                    i = pairs[i] + 1
                if i >= len(tokens) or tokens[i][0].upper() != 'AS':
                    break
                i += 1
                if i < len(tokens) and tokens[i][0].upper() == 'NOT':
                    i += 1
                if i < len(tokens) and tokens[i][0].upper() == 'MATERIALIZED':
                    i += 1
                if i not in pairs:
                    break
                names.append(name)
                i = pairs[i] + 1
                if i >= len(tokens) or tokens[i][0] != ',':
                    break
                i += 1
            if 'pragma_recursive_triggers' in names:
                end = pairs.get(enclosing[start], len(tokens))
                end = next((i for i in range(start, end)
                            if tokens[i][0] == ';'), end)
                scopes.append((start, end))
        return scopes

    def _native_mode(self, sql):
        """Normalize pragma *table sources*, leaving strings/expressions alone."""
        if self.mode:
            return sql
        tokens = _tokens(sql)
        cte_scopes = self._cte_scopes(tokens)
        edits = []
        # Each parenthesis has its own FROM-list state. A comma in a function
        # call or a SELECT list is not a table-reference boundary.
        contexts = [[False, False]]
        i = 0
        while i < len(tokens):
            token, start, end = tokens[i]
            upper = token.upper()
            context = contexts[-1]
            if token == '(':
                # A parenthesized table/join source keeps its FROM context;
                # scalar expressions and subqueries start their own context.
                table_group = context[1]
                context[1] = False
                contexts.append([table_group, table_group])
            elif token == ')':
                if len(contexts) > 1:
                    contexts.pop()
            elif upper == 'SELECT' or token == ';':
                context[:] = [False, False]
            elif upper in ('FROM', 'JOIN'):
                context[:] = [True, True]
            elif upper in ('WHERE', 'GROUP', 'HAVING', 'ORDER', 'LIMIT', 'UNION', 'EXCEPT', 'INTERSECT', 'RETURNING', 'ON', 'USING'):
                context[1] = False
                if upper not in ('ON', 'USING'):
                    context[0] = False
            elif token == ',' and context[0]:
                context[1] = True
            elif context[1]:
                context[1] = False
                schema = None
                name_token = token
                last = i
                if i + 2 < len(tokens) and tokens[i + 1][0] == '.':
                    schema = _name(token).lower()
                    last = i + 2
                    name_token = tokens[last][0]
                if _name(name_token).lower() == 'pragma_recursive_triggers':
                    lookup = (schema,) if schema else ('temp', 'main')
                    shadowed = any((part, 'pragma_recursive_triggers') in self.objects for part in lookup)
                    if schema is None:
                        shadowed |= any(start <= i < end for start, end in cte_scopes)
                    if not shadowed and schema in (None, 'main', 'temp'):
                        if last + 1 < len(tokens) and tokens[last + 1][0] == '(':
                            if last + 2 >= len(tokens) or tokens[last + 2][0] != ')':
                                i += 1
                                continue
                            last += 2
                        next_token = tokens[last + 1][0].upper() if last + 1 < len(tokens) else ''
                        terminators = {'', ';', ')', ',', 'WHERE', 'GROUP', 'HAVING', 'ORDER', 'LIMIT', 'UNION', 'EXCEPT', 'INTERSECT', 'JOIN', 'LEFT', 'RIGHT', 'FULL', 'INNER', 'CROSS', 'NATURAL', 'ON', 'USING', 'END', 'BEGIN'}
                        alias = ' AS ' + _quote(_name(name_token)) if next_token in terminators else ''
                        # A real main-schema view retains SQLite's qualified
                        # column lookup (main.alias.column), unlike a derived
                        # SELECT. Built-in pragma tables resolve in main even
                        # when their source is explicitly qualified with temp.
                        edits.append((start, tokens[last][2], self.mode_view + alias))
                        i = last
            i += 1
        for start, end, replacement in reversed(edits):
            sql = sql[:start] + replacement + sql[end:]
        return sql

    def _allowed(self, identity, event):
        if any(frame[0] == identity for frame in self.stack):
            return False
        operation = self.stack[-1][1] if self.stack else self.operation
        # At native mode 0, REPLACE's implicit deletes do not run user DELETE
        # triggers. Our observers must still see those deletes.
        return event != 'DELETE' or operation == 'DELETE'

    def _enter(self, identity):
        operation = self.stack[-1][1] if self.stack else self.operation
        self.stack.append([identity, operation])

    def _step(self, identity, operation):
        index = next(i for i, frame in enumerate(self.stack) if frame[0] == identity)
        # A nested RAISE(IGNORE) can skip the child's exit. SQLite resumes at
        # this next parent statement, so discard only the abandoned frames.
        del self.stack[index + 1:]
        self.stack[index][1] = operation

    def _leave(self, identity):
        index = next(i for i, frame in enumerate(self.stack) if frame[0] == identity)
        del self.stack[index:]

    def _hide(self, count):
        self.hidden_changes += count

    def _unwind_ignore(self, sql, identity):
        tokens = _tokens(sql)
        for i in range(len(tokens) - 4, -1, -1):
            if [token.upper() for token, _, _ in tokens[i:i + 4]] == ['RAISE', '(', 'IGNORE', ')']:
                start, end = tokens[i][1], tokens[i + 3][2]
                # CASE evaluates only the chosen expression, so conditional
                # IGNORE unwinds exactly when SQLite abandons this invocation,
                # before another row in the same statement can call it again.
                sql = (sql[:start] + f"(CASE WHEN {self._function('leave')}({identity}) IS NULL THEN "
                       + sql[start:end] + ' END)' + sql[end:])
        return sql

    def _instrument(self, name, sql, identity):
        tokens = _tokens(sql)
        # BEGIN is also a legal name. Let SQLite validate candidate headers
        # instead of interpreting keyword-like identifiers as grammar.
        begin = None
        for i, (token, start, end) in enumerate(tokens):
            if token.upper() != 'BEGIN':
                continue
            try:
                self.con.execute(sql[:end] + ' SELECT 1; END')
            except sqlite3.Error:
                continue
            self.con.execute('DROP TRIGGER main.' + _quote(name))
            begin = i
            break
        if begin is None:
            raise sqlite3.IntegrityError('cannot observe transfer writes')

        # Skip CREATE [TEMP] TRIGGER [IF NOT EXISTS] [schema.]name.
        i = 1
        if tokens[i][0].upper() in ('TEMP', 'TEMPORARY'):
            i += 1
        i += 1
        if tokens[i][0].upper() == 'IF':
            i += 3
        i += 1
        if tokens[i][0] == '.':
            i += 2
        if tokens[i][0].upper() in ('BEFORE', 'AFTER'):
            i += 1
        elif tokens[i][0].upper() == 'INSTEAD':
            i += 2
        event = tokens[i][0].upper()
        i += 1
        while tokens[i][0].upper() != 'ON':
            i += 1
        i += 2  # ON table-name
        if tokens[i][0] == '.':
            i += 2
        if tokens[i][0].upper() == 'FOR':
            i += 3
        condition = ''
        if i < begin and tokens[i][0].upper() == 'WHEN':
            condition = ' AND (' + sql[tokens[i][2]:tokens[begin][1]] + ') '
            header = sql[:tokens[i][1]]
        else:
            header = sql[:tokens[begin][1]]
        header += f" WHEN {self._function('allowed')}({identity},'{event}')" + condition + ' BEGIN '

        statements = []
        start = tokens[begin][2]
        first = begin + 1
        for i in range(begin + 1, len(tokens)):
            if tokens[i][0] == ';':
                statements.append((tokens[first][0].upper(), sql[start:tokens[i][2]]))
                start = tokens[i][2]
                first = i + 1
        # The last token is END, optionally followed by the CREATE terminator.
        if statements and statements[-1][0] == 'END':
            statements.pop()
        body = f"SELECT {self._function('enter')}({identity});"
        for operation, statement in statements:
            body += f"SELECT {self._function('step')}({identity},'{operation}');" + self._unwind_ignore(statement, identity)
        body += f"SELECT {self._function('leave')}({identity}); END"
        return self._native_mode(header + body)

    def install(self):
        con = self.con
        for suffix, arity, function in (
            ('allowed', 2, self._allowed), ('enter', 1, self._enter),
            ('step', 2, self._step), ('leave', 1, self._leave),
            ('hide', 1, self._hide),
        ):
            con.create_function(self.prefix + '_' + suffix, arity, function)
        con.create_function('total_changes', 0, lambda: con.total_changes - self.hidden_changes)
        if not self.mode:
            con.execute(f'CREATE VIEW {self.mode_view} AS SELECT 0 AS recursive_triggers')
            for name, _ in self.triggers:
                con.execute('DROP TRIGGER main.' + _quote(name))
            for name, _, _ in self.views:
                con.execute('DROP VIEW main.' + _quote(name))
            for _, _, rewritten in self.views:
                con.execute(rewritten)
            for identity, (name, sql) in enumerate(self.triggers):
                con.execute(self._instrument(name, sql, identity))
        con.execute('PRAGMA recursive_triggers=ON')
        fields = ','.join('old' + str(i) for i in range(5))
        fields += ',' + ','.join('new' + str(i) for i in range(5))
        con.execute(f'CREATE TEMP TABLE {self.journal} (tab TEXT,slot INTEGER,was INTEGER,present INTEGER,{fields},PRIMARY KEY(tab,slot)) WITHOUT ROWID')
        self.observers = []
        for table, columns in self._columns.items():
            for event in ('INSERT', 'UPDATE', 'DELETE'):
                name = self.prefix + '_' + table + '_' + event
                self.observers.append(name)
                body = ''
                if event in ('UPDATE', 'DELETE'):
                    body += self._record(table, columns, 'OLD', False)
                if event in ('INSERT', 'UPDATE'):
                    body += self._record(table, columns, 'NEW', True)
                con.execute(f'CREATE TEMP TRIGGER {_quote(name)} AFTER {event} ON main.{table} BEGIN {body} END')

    def _record(self, table, columns, image, present):
        values = [image + '.' + _quote(column) for column in columns]
        values += ['NULL'] * (5 - len(values))
        missing = ['NULL'] * 5
        old_values, new_values = (missing, values) if present else (values, missing)
        values = ','.join(old_values + new_values)
        updates = ','.join(f'new{i}=excluded.new{i}' for i in range(5))
        return (
            f"INSERT INTO {self.journal} VALUES ('{table}',{image}.rowid,{int(not present)},{int(present)},{values}) "
            f'ON CONFLICT(tab,slot) DO UPDATE SET present=excluded.present,{updates};'
            f"SELECT {self._function('hide')}(changes());"
        )

    def statement(self, sql, values):
        self.stack.clear()
        self.operation = sql.split(None, 1)[0].upper()
        self.con.execute(sql, values)

    def verify(self, tenant, source, target, amount, key, accounts):
        expected = [
            ('accounts', tenant, source, accounts[source], None, None, 1),
            ('accounts', tenant, source, accounts[source] - amount, None, None, -1),
            ('accounts', tenant, target, accounts[target], None, None, 1),
            ('accounts', tenant, target, accounts[target] + amount, None, None, -1),
            ('transfers', tenant, key, source, target, amount, -1),
            ('audit', tenant, key, source, target, amount, -1),
        ]
        old = ','.join('old' + str(i) for i in range(5))
        new = ','.join('new' + str(i) for i in range(5))
        grouping = ','.join(f'typeof(old{i}),old{i} COLLATE BINARY' for i in range(5))
        values_sql = ','.join('(?,?,?,?,?,?,?)' for _ in expected)
        mismatch = self.con.execute(
            f'WITH effects AS (SELECT tab,{old},-1 AS delta FROM {self.journal} WHERE was=1 '
            f'UNION ALL SELECT tab,{new},1 FROM {self.journal} WHERE present=1 '
            f'UNION ALL SELECT * FROM (VALUES {values_sql})) '
            f'SELECT 1 FROM effects GROUP BY tab,{grouping} HAVING sum(delta)<>0 LIMIT 1',
            [value for row in expected for value in row],
        ).fetchone()
        # Re-read only the authorized endpoints. BEFORE-trigger NEW images can
        # describe an attempted update; the persisted endpoint is authoritative.
        endpoints = dict(self.con.execute(
            "SELECT name,balance FROM accounts WHERE tenant=? AND name IN (?,?) AND typeof(balance)='integer'",
            (tenant, source, target),
        ))
        if mismatch is not None or endpoints != {
            source: accounts[source] - amount, target: accounts[target] + amount,
        }:
            raise sqlite3.IntegrityError('transfer effects violated')

    def restore(self):
        for name in self.observers:
            self.con.execute('DROP TRIGGER temp.' + _quote(name))
        self.con.execute('DROP TABLE temp.' + self.journal)
        if not self.mode:
            for name, _ in self.triggers:
                self.con.execute('DROP TRIGGER main.' + _quote(name))
            for name, _, _ in self.views:
                self.con.execute('DROP VIEW main.' + _quote(name))
            for _, original, _ in self.views:
                self.con.execute(original)
            for _, original in self.triggers:
                self.con.execute(original)
            self.con.execute('DROP VIEW ' + self.mode_view)
        self.con.execute(f'PRAGMA recursive_triggers={self.mode}')
