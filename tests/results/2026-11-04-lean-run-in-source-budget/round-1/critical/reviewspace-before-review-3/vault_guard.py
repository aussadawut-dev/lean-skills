"""Connection-local observation of ledger effects, without exporting stored rows.

The TEMP journal records each physical slot's first and latest image. Validation
compares typed logical multisets, so row moves and restored writes are permitted.
Recursive triggers expose implicit REPLACE deletions; user triggers retain their
original recursion semantics and their definitions are restored transactionally.
"""

import sqlite3
import uuid


def _quote(name):
    return '"' + name.replace('"', '""') + '"'


def _tokens(sql):
    """SQLite token boundaries, retaining original spans and quoted contents."""
    result = []
    i = 0
    while i < len(sql):
        start = i
        char = sql[i]
        if char in ' \t\n\r\f\v\ufeff':
            i += 1
            continue
        if sql.startswith('--', i):
            end = sql.find('\n', i)
            i = len(sql) if end < 0 else end + 1
            continue
        if sql.startswith('/*', i):
            end = sql.find('*/', i + 2)
            i = len(sql) if end < 0 else end + 2
            continue
        if char in "'\"`[":
            endchar = ']' if char == '[' else char
            i += 1
            value = ''
            while i < len(sql):
                if sql[i] == endchar:
                    if endchar != ']' and i + 1 < len(sql) and sql[i + 1] == endchar:
                        value += endchar
                        i += 2
                        continue
                    i += 1
                    break
                value += sql[i]
                i += 1
            result.append((start, i, value.lower(), True))
        elif char.isalnum() or char == '_' or ord(char) >= 128:
            i += 1
            while i < len(sql) and (sql[i].isalnum() or sql[i] in '_$' or ord(sql[i]) >= 128):
                i += 1
            result.append((start, i, sql[start:i].lower(), False))
        else:
            i += 1
            result.append((start, i, char, False))
    return result


def _edits(sql, edits):
    for start, end, replacement in sorted(edits, reverse=True):
        sql = sql[:start] + replacement + sql[end:]
    return sql


def _scoped_sql(sql, tenant_function, recursive_mode, pragma_shadowed=False):
    """Restrict SELECT sources, including views, CTEs and IN-table shorthand."""
    tokens = _tokens(sql)
    n = len(tokens)
    words = [t[2] for t in tokens]
    depths, matching, stack = [], {}, []
    for i, word in enumerate(words):
        depths.append(len(stack))
        if word == '(' and not tokens[i][3]:
            stack.append(i)
        elif word == ')' and not tokens[i][3] and stack:
            opening = stack.pop()
            matching[opening] = i
    ctes = []
    for i, word in enumerate(words):
        if word != 'with' or tokens[i][3]:
            continue
        end = next((j for j in range(i + 1, n)
                    if depths[j] < depths[i] or (depths[j] == depths[i] and words[j] == ';')), n)
        j = i + 1
        if j < n and words[j] == 'recursive' and not tokens[j][3]:
            j += 1
        names = set()
        while j < end:
            name = words[j]
            j += 1
            if j < end and words[j] == '(':
                j = matching.get(j, end) + 1
            if j >= end or words[j] != 'as':
                break
            j += 1
            while j < end and words[j] in ('not', 'materialized'):
                j += 1
            if j >= end or words[j] != '(':
                break
            names.add(name)
            j = matching.get(j, end) + 1
            if j >= end or words[j] != ',':
                break
            j += 1
        ctes.append((i, end, names))
    starts = {}
    from_depth = set()
    for i, word in enumerate(words):
        depth = depths[i]
        if word in ('where', 'group', 'order', 'limit', 'having', 'union', 'except', 'intersect', 'window', ';') and not tokens[i][3]:
            from_depth.discard(depth)
        if word == ')' and not tokens[i][3]:
            from_depth.discard(depth)
        if not tokens[i][3] and word in ('from', 'join', 'in'):
            if word == 'from' and i and words[i - 1] == 'delete':
                continue
            if word != 'in':
                from_depth.add(depth)
            starts[i + 1] = word == 'in'
            # Parenthesized join groups have their own comma-separated sources.
            j = i + 1
            while j + 1 < n and words[j] == '(' and words[j + 1] not in ('select', 'with', 'values'):
                from_depth.add(depths[j] + 1)
                j += 1
        elif word == ',' and depth in from_depth:
            starts[i + 1] = False
    edits = []
    qualifiers = set()
    for start, in_table in starts.items():
        j = start
        while j < n and words[j] == '(' and j + 1 < n and words[j + 1] not in ('select', 'with', 'values'):
            j += 1
        if j >= n:
            continue
        begin = j
        schema = None
        if j + 2 < n and words[j + 1] == '.':
            schema = words[j]
            j += 2
        name = words[j]
        if name not in ('accounts', 'transfers', 'pragma_recursive_triggers'):
            continue
        if name == 'pragma_recursive_triggers' and pragma_shadowed:
            continue
        if schema is None and any(a <= j < b and name in names for a, b, names in ctes):
            continue
        if schema not in (None, 'main'):
            continue
        finish = j + 1
        if finish < n and words[finish] == '(':
            if matching.get(finish) != finish + 1:
                # These sources take no arguments. Preserve native errors.
                continue
            finish = matching.get(finish, finish) + 1
        if name == 'pragma_recursive_triggers':
            select = f'SELECT {recursive_mode} AS recursive_triggers'
        else:
            select = f'SELECT * FROM main.{_quote(name)} WHERE tenant={tenant_function}()'
        # Index hints apply to tables, not derived tables. The restriction uses
        # the original table's indexes inside the derived source.
        if finish + 1 < n and words[finish:finish + 2] == ['not', 'indexed']:
            finish += 2
        elif finish + 2 < n and words[finish:finish + 2] == ['indexed', 'by']:
            finish += 3
        alias = ''
        if not in_table:
            reserved = {'where','join','left','right','inner','outer','cross','full','on','using','group','order','limit','having','union','except','intersect','window',';',')',',','end'}
            has_alias = finish < n and (words[finish] == 'as' or tokens[finish][3] or words[finish] not in reserved)
            if not has_alias:
                alias = ' AS ' + _quote(name)
                if schema:
                    qualifiers.add((schema, name))
            else:
                alias_end = finish + (2 if words[finish] == 'as' else 1)
                if words[alias_end:alias_end + 2] == ['not', 'indexed']:
                    edits.append((tokens[alias_end][0], tokens[alias_end + 1][1], ''))
                elif words[alias_end:alias_end + 2] == ['indexed', 'by'] and alias_end + 2 < n:
                    edits.append((tokens[alias_end][0], tokens[alias_end + 2][1], ''))
        edits.append((tokens[begin][0], tokens[finish - 1][1], '(' + select + ')' + alias))
    for i in range(n - 3):
        if (words[i], words[i + 2]) in qualifiers and words[i + 1] == words[i + 3] == '.':
            if not any(a <= tokens[i][0] < b for a, b, _ in edits):
                edits.append((tokens[i][0], tokens[i + 2][0], ''))
    return _edits(sql, edits)


class Effects:
    columns = {
        'accounts': ('tenant', 'name', 'balance'),
        'transfers': ('tenant', 'key', 'source', 'target', 'amount'),
        'audit': ('tenant', 'key', 'source', 'target', 'amount'),
    }

    def __init__(self, con, tenant):
        self.con = con
        self.prefix = '_vault_' + uuid.uuid4().hex
        self.journal = self.prefix + '_rows'
        self.expected = self.prefix + '_expected'
        self.stack = []
        self.internal_changes = 0
        self.mode = con.execute('PRAGMA recursive_triggers').fetchone()[0]
        self.definitions = con.execute(
            "SELECT type,name,sql FROM sqlite_schema WHERE type IN ('trigger','view') AND sql IS NOT NULL ORDER BY rowid"
        ).fetchall()
        pragma_shadowed = con.execute(
            "SELECT 1 FROM sqlite_schema WHERE name='pragma_recursive_triggers' COLLATE NOCASE AND type IN ('table','view')"
        ).fetchone() is not None
        con.create_function(self.prefix + '_tenant', 0, lambda: tenant)
        con.create_function(self.prefix + '_allow', 2, self._allow)
        con.create_function(self.prefix + '_enter', 1, self._enter)
        con.create_function(self.prefix + '_exit', 1, self._exit)
        con.create_function(self.prefix + '_ignore', 1, self._ignore)
        con.create_function(self.prefix + '_statement', 1, self._statement)
        con.create_function(self.prefix + '_count', 1, self._count)
        con.create_function('total_changes', 0, lambda: con.total_changes - self.internal_changes)
        fields = ','.join(f'{phase}{i}' for phase in ('a', 'b') for i in range(5))
        con.execute(f'CREATE TEMP TABLE {self.journal}(t,slot,a_exists,b_exists,{fields},PRIMARY KEY(t,slot))')
        con.execute(f'CREATE TEMP TABLE {self.expected}(t,sign,{",".join("v"+str(i) for i in range(5))})')
        # Recreate in schema order to retain native trigger ordering.
        self._drop_definitions()
        for kind, name, sql in self.definitions:
            scoped = _scoped_sql(sql, self.prefix + '_tenant', self.mode, pragma_shadowed)
            if kind == 'trigger':
                scoped = self._trigger(scoped, name)
            con.execute(scoped)
        con.execute('PRAGMA recursive_triggers=ON')
        for table, columns in self.columns.items():
            self._observe(table, columns)

    def _enter(self, name):
        self.stack.append([name, False])
        return 1

    def _allow(self, name, deleting):
        if self.mode:
            return 1
        # At native mode 0, implicit REPLACE victims do not invoke user DELETE
        # triggers. The TEMP observers must still see those physical deletions.
        if deleting and self.stack and self.stack[-1][1]:
            return 0
        return all(frame[0] != name for frame in self.stack)

    def _statement(self, replacing):
        if self.stack:
            self.stack[-1][1] = bool(replacing)
        return 1

    def _exit(self, name):
        if self.stack and self.stack[-1][0] == name:
            self.stack.pop()
        return 1

    def _ignore(self, name):
        self._exit(name)
        return 1

    def _count(self, count):
        self.internal_changes += count
        return 1

    def _trigger(self, sql, name):
        tokens = _tokens(sql)
        # Validate candidate BEGIN boundaries using SQLite's own parser. Trigger
        # names and column identifiers may themselves be keywords.
        begin = None
        for i, token in enumerate(tokens):
            if token[2] != 'begin' or token[3]:
                continue
            candidate = sql[:token[1]] + ' SELECT 1; END'
            try:
                self.con.execute('EXPLAIN ' + candidate).fetchall()
            except sqlite3.Error:
                continue
            begin = i
            break
        if begin is None:
            raise sqlite3.DatabaseError('unsupported trigger definition')
        end = next(i for i in range(len(tokens) - 1, begin, -1) if tokens[i][2] == 'end' and not tokens[i][3])
        literal = "'" + name.replace("'", "''") + "'"
        deleting = any(token[2] == 'delete' and not token[3] for token in tokens[:begin])
        gate = f'{self.prefix}_allow({literal},{int(deleting)})'
        when = None
        for i in range(begin):
            if tokens[i][2] != 'when' or tokens[i][3]:
                continue
            try:
                self.con.execute('EXPLAIN ' + sql[:tokens[i][0]] + ' WHEN 1 BEGIN SELECT 1; END').fetchall()
            except sqlite3.Error:
                continue
            when = i
            break
        edits = [(tokens[begin][1], tokens[begin][1], f' SELECT {self.prefix}_enter({literal}); '),
                 (tokens[end][0], tokens[end][0], f' SELECT {self.prefix}_exit({literal}); ')]
        if when is None:
            edits.append((tokens[begin][0], tokens[begin][0], ' WHEN ' + gate + ' '))
        else:
            condition = sql[tokens[when][1]:tokens[begin][0]]
            edits.append((tokens[when][1], tokens[begin][0], f' {gate} AND ({condition}) '))
        for i in range(begin + 1, end - 3):
            if [t[2] for t in tokens[i:i + 4]] == ['raise', '(', 'ignore', ')'] and not tokens[i][3]:
                edits.append((tokens[i][0], tokens[i + 3][1], f'CASE WHEN {self.prefix}_ignore({literal}) THEN RAISE(IGNORE) END'))
        statement_start = begin + 1
        for i in range(begin + 1, end):
            if tokens[i][2] != ';' or tokens[i][3]:
                continue
            words = [token[2] for token in tokens[statement_start:i]]
            replacing = bool(words) and (words[0] == 'replace' or words[:3] in
                                         (['insert', 'or', 'replace'], ['update', 'or', 'replace']))
            if words:
                position = tokens[statement_start][0]
                edits.append((position, position, f'SELECT {self.prefix}_statement({int(replacing)}); '))
            statement_start = i + 1
        return _edits(sql, edits)

    def _observe(self, table, columns):
        journal = self.journal
        def values(which):
            return ','.join([which + '.' + _quote(c) for c in columns] + ['NULL'] * (5 - len(columns)))
        def counted(statement):
            return statement + f'; SELECT {self.prefix}_count(changes()); '
        initial = counted(
            f"INSERT INTO {journal} VALUES ('{table}',OLD.rowid,1,1,{values('OLD')},{values('OLD')}) ON CONFLICT(t,slot) DO NOTHING"
        )
        absent = counted(
            f"INSERT INTO {journal}(t,slot,a_exists,b_exists) VALUES ('{table}',NEW.rowid,0,0) ON CONFLICT(t,slot) DO NOTHING"
        )
        remove = counted(f"UPDATE {journal} SET b_exists=0 WHERE t='{table}' AND slot=OLD.rowid")
        assignments = ','.join(f'b{i}={value}' for i, value in enumerate(
            [f'NEW.{_quote(c)}' for c in columns] + ['NULL'] * (5 - len(columns))))
        latest = counted(f"UPDATE {journal} SET b_exists=1,{assignments} WHERE t='{table}' AND slot=NEW.rowid")
        for timing, event, body in (
            ('BEFORE', 'UPDATE', initial), ('BEFORE', 'DELETE', initial),
            ('AFTER', 'UPDATE', remove + absent + latest),
            ('AFTER', 'DELETE', remove), ('AFTER', 'INSERT', absent + latest),
        ):
            name = f'{self.prefix}_{table}_{timing}_{event}'
            self.con.execute(f'CREATE TEMP TRIGGER {name} {timing} {event} ON main.{table} BEGIN {body} END')

    def verify(self, tenant, source, target, before, amount, key):
        expected = [
            ('accounts', 1, tenant, source, before[source], None, None),
            ('accounts', 1, tenant, target, before[target], None, None),
            ('accounts', -1, tenant, source, before[source] - amount, None, None),
            ('accounts', -1, tenant, target, before[target] + amount, None, None),
            ('transfers', -1, tenant, key, source, target, amount),
            ('audit', -1, tenant, key, source, target, amount),
        ]
        self.con.executemany(f'INSERT INTO {self.expected} VALUES (?,?,?,?,?,?,?)', expected)
        self.internal_changes += len(expected)
        a = ','.join('a' + str(i) for i in range(5))
        b = ','.join('b' + str(i) for i in range(5))
        v = ','.join('v' + str(i) for i in range(5))
        group = ','.join(f'typeof(v{i}),v{i} COLLATE BINARY' for i in range(5))
        mismatch = self.con.execute(
            f'WITH effects(t,sign,{v}) AS ('
            f'SELECT t,-1,{a} FROM {self.journal} WHERE a_exists=1 UNION ALL '
            f'SELECT t,1,{b} FROM {self.journal} WHERE b_exists=1 UNION ALL '
            f'SELECT * FROM {self.expected}) '
            f'SELECT 1 FROM effects GROUP BY t,{group} HAVING sum(sign)!=0 LIMIT 1'
        ).fetchone()
        # Read only authenticated endpoints to confirm the final values as well
        # as the journal's complete preservation equation.
        rows = self.con.execute(
            'SELECT name,balance,typeof(balance) FROM accounts WHERE tenant=? AND name IN (?,?)',
            (tenant, source, target),
        ).fetchall()
        final = {row[0]: (row[1], row[2]) for row in rows}
        if mismatch or final != {source: (before[source] - amount, 'integer'), target: (before[target] + amount, 'integer')}:
            raise sqlite3.IntegrityError('transaction effects rejected')

    def restore(self):
        self._drop_definitions()
        for kind, name, sql in self.definitions:
            self.con.execute(sql)
        self.con.execute(f'PRAGMA recursive_triggers={self.mode}')

    def _drop_definitions(self):
        # Dropping a view also drops its INSTEAD OF triggers.
        for object_type in ('trigger', 'view'):
            for kind, name, sql in self.definitions:
                if kind == object_type:
                    self.con.execute(f'DROP {kind} {_quote(name)}')
