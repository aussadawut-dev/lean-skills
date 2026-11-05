"""Transaction-local verification of the logical effects of a transfer.

The stdlib sqlite binding has no pre-update hook. AFTER triggers therefore
collect OLD/NEW deltas inside SQLite, including REPLACE victims. Enabling those
delete notifications requires recursive_triggers; existing triggers retain
their original recursion and implicit-delete behavior through instrumentation.
No stored row values are passed to Python by the observers.
"""

from contextlib import contextmanager
import sqlite3
import uuid


def _quote(name):
    return '"' + name.replace('"', '""') + '"'


def _tokens(sql):
    """Significant SQLite tokens, retaining source spans and quoted identifiers."""
    result = []
    i = 0
    while i < len(sql):
        start = i
        char = sql[i]
        # SQLite accepts VT and a token-boundary BOM, but not Unicode \s.
        if char in ' \t\n\r\f\v\ufeff':
            i += 1
            continue
        if sql.startswith('--', i):
            end = sql.find('\n', i + 2)
            i = len(sql) if end < 0 else end + 1
            continue
        if sql.startswith('/*', i):
            end = sql.find('*/', i + 2)
            i = len(sql) if end < 0 else end + 2
            continue
        if char in "'\"`[":
            close = ']' if char == '[' else char
            i += 1
            while i < len(sql):
                if sql[i] == close:
                    i += 1
                    if char != '[' and i < len(sql) and sql[i] == close:
                        i += 1
                        continue
                    break
                i += 1
            value = sql[start + 1:i - 1].replace(close * 2, close)
            kind = 'string' if char == "'" else 'identifier'
        elif char.isascii() and (char.isalnum() or char in '_$') or ord(char) >= 128:
            i += 1
            while i < len(sql) and (
                sql[i].isascii() and (sql[i].isalnum() or sql[i] in '_$')
                or ord(sql[i]) >= 128
            ):
                i += 1
            value, kind = sql[start:i], 'word'
        else:
            i += 1
            value, kind = char, 'symbol'
        result.append((start, i, value, kind))
    return result


def _is(token, word):
    return token[3] == 'word' and token[2].upper() == word


def _event(header):
    tokens = _tokens(header)
    i = next(i for i, token in enumerate(tokens) if _is(token, 'TRIGGER')) + 1
    if _is(tokens[i], 'IF'):
        i += 3
    i += 1  # Trigger name, possibly schema-qualified.
    if tokens[i][2] == '.':
        i += 2
    if _is(tokens[i], 'BEFORE') or _is(tokens[i], 'AFTER'):
        i += 1
    elif _is(tokens[i], 'INSTEAD'):
        i += 2
    return tokens[i][2].upper()


def _valid_header(con, sql):
    tokens = _tokens(sql)
    trigger = next(i for i, token in enumerate(tokens) if _is(token, 'TRIGGER'))
    if not _is(tokens[trigger + 1], 'IF'):
        end = tokens[trigger][1]
        sql = sql[:end] + ' IF NOT EXISTS ' + sql[end:]
    try:
        con.execute('EXPLAIN ' + sql).close()
    except sqlite3.Error:
        return False
    return True


def _parts(con, sql):
    tokens = _tokens(sql)
    # BEGIN/END can be unquoted identifiers. Let SQLite validate the header.
    begin = next((token for token in tokens if _is(token, 'BEGIN') and
                  _valid_header(con, sql[:token[1]] + '\nSELECT 1; END')), None)
    if begin is None:
        raise sqlite3.DatabaseError('cannot observe trigger')
    end = tokens[-2] if tokens[-1][2] == ';' else tokens[-1]
    if not _is(end, 'END'):
        raise sqlite3.DatabaseError('cannot observe trigger')
    when = next((token for token in tokens if token[0] < begin[0] and
                 _is(token, 'WHEN') and _valid_header(
                     con, sql[:token[0]] + 'WHEN 1 BEGIN SELECT 1; END')), None)
    header = sql[:when[0] if when else begin[0]]
    condition = sql[when[1]:begin[0]] if when else '1'
    return header, condition, sql[begin[1]:end[0]], sql[end[0]:]


def _replace_spans(sql, replacements):
    for start, end, value in sorted(replacements, reverse=True):
        sql = sql[:start] + value + sql[end:]
    return sql


def _pragma_view_calls(sql):
    # The snapshot view has the same name/column as the eponymous pragma table.
    # SQLite's optional empty argument list is not legal on an ordinary view.
    tokens = _tokens(sql)
    replacements = []
    for i, token in enumerate(tokens[:-2]):
        if (token[3] in ('word', 'identifier') and
                token[2].lower() == 'pragma_recursive_triggers' and
                tokens[i + 1][2] == '(' and tokens[i + 2][2] == ')'):
            replacements.extend((t[0], t[1], '') for t in tokens[i + 1:i + 3])
    return _replace_spans(sql, replacements)


def _instrument(con, sql, ident, event, prefix, snapshot_pragma):
    header, condition, body, end = _parts(con, sql)
    tokens = _tokens(body)
    replacements = []
    for i, token in enumerate(tokens[:-3]):
        if (_is(token, 'RAISE') and tokens[i + 1][2] == '(' and
                _is(tokens[i + 2], 'IGNORE') and tokens[i + 3][2] == ')'):
            # IGNORE can skip a row, leaving no epilogue to clear recursion state.
            replacements.append((token[0], tokens[i + 3][1],
                f'(CASE WHEN {prefix}_leave({ident}) THEN '
                + body[token[0]:tokens[i + 3][1]] + ' END)'))
    body = _replace_spans(body, replacements)
    statements = []
    start = 0
    for token in _tokens(body):
        if token[2] == ';' and token[3] == 'symbol':
            statement = body[start:token[1]]
            # Trigger DML starts with its verb; WITH/VALUES introduce SELECTs.
            operation = _tokens(statement)[0][2].upper()
            statements.append(f"\nSELECT {prefix}_statement({ident}, "
                              f"'{operation if operation == 'DELETE' else 'OTHER'}');\n"
                              + statement)
            start = token[1]
    instrumented = (header + f'\nWHEN CASE WHEN {prefix}_allowed({ident}, '
                    f"'{event}') THEN CASE WHEN (\n{condition}\n) THEN "
                    f'{prefix}_enter({ident}) END END\nBEGIN\n'
                    + ''.join(statements) + body[start:]
                    + f'\nSELECT {prefix}_leave({ident});\n' + end)
    return _pragma_view_calls(instrumented) if snapshot_pragma else instrumented


@contextmanager
def transfer_effects(con, tenant, source, funds, target, target_funds, amount, key):
    """Require precisely the expected logical multiset delta before committing."""
    prefix = '_vault_' + uuid.uuid4().hex
    delta = prefix + '_delta'
    recursive = con.execute('PRAGMA recursive_triggers').fetchone()[0]
    triggers = con.execute(
        "SELECT name, sql FROM main.sqlite_schema WHERE type='trigger' ORDER BY rowid"
    ).fetchall()
    shadowed = con.execute(
        "SELECT 1 FROM main.sqlite_schema WHERE name='pragma_recursive_triggers' COLLATE NOCASE"
    ).fetchone()
    snapshot_pragma = not recursive and not shadowed
    frames = []
    observation_changes = 0

    def enter(ident):
        frames.append([ident, 'OTHER'])
        return 1

    def trim(ident, leave=False):
        index = next(i for i, frame in enumerate(frames) if frame[0] == ident)
        del frames[index + (0 if leave else 1):]
        return 1

    def statement(ident, operation):
        trim(ident)
        frames[-1][1] = operation
        return 1

    def allowed(ident, event):
        if any(frame[0] == ident for frame in frames):
            return 0
        # With native recursion off, DELETE triggers do not run for REPLACE.
        return int(event != 'DELETE' or bool(frames and frames[-1][1] == 'DELETE'))

    def counted(count):
        nonlocal observation_changes
        observation_changes += count
        return 0

    con.create_function(prefix + '_enter', 1, enter)
    con.create_function(prefix + '_leave', 1, lambda ident: trim(ident, leave=True))
    con.create_function(prefix + '_statement', 2, statement)
    con.create_function(prefix + '_allowed', 2, allowed)
    con.create_function(prefix + '_counted', 1, counted)
    con.create_function('total_changes', 0, lambda: con.total_changes - observation_changes)

    # Change the pragma only between statements, never while a guard is running.
    con.execute('PRAGMA recursive_triggers=ON')
    if snapshot_pragma:
        con.execute('CREATE VIEW main.pragma_recursive_triggers AS '
                    'SELECT 0 AS recursive_triggers')
    rewritten = []
    if not recursive:
        for ident, (name, sql) in enumerate(triggers):
            header, _, _, _ = _parts(con, sql)
            rewritten.append((name, _instrument(
                con, sql, ident, _event(header), prefix, snapshot_pragma)))
        for name, _ in triggers:
            con.execute('DROP TRIGGER main.' + _quote(name))
        for _, sql in rewritten:
            con.execute(sql)

    con.execute(f'CREATE TEMP TABLE {delta} (tab, sign, v0, v1, v2, v3, v4)')
    values = (tenant, key, source, target, amount)
    expected = [
        ('accounts', 1, tenant, source, funds, None, None),
        ('accounts', -1, tenant, source, funds - amount, None, None),
        ('accounts', 1, tenant, target, target_funds, None, None),
        ('accounts', -1, tenant, target, target_funds + amount, None, None),
        ('transfers', -1, *values), ('audit', -1, *values),
    ]
    observers = []
    for table, columns in (
        ('accounts', ('tenant', 'name', 'balance')),
        ('transfers', ('tenant', 'key', 'source', 'target', 'amount')),
        ('audit', ('tenant', 'key', 'source', 'target', 'amount')),
    ):
        for event in ('INSERT', 'UPDATE', 'DELETE'):
            rows = []
            for alias, sign in (('OLD', -1), ('NEW', 1)):
                if event == 'INSERT' and alias == 'OLD' or event == 'DELETE' and alias == 'NEW':
                    continue
                fields = [f'{alias}.{_quote(column)}' for column in columns]
                fields += ['NULL'] * (5 - len(fields))
                rows.append(f"('{table}', {sign}, " + ', '.join(fields) + ')')
            name = f'{prefix}_{table}_{event}'
            observers.append(name)
            con.execute(f'CREATE TEMP TRIGGER {name} AFTER {event} ON main.{table} '
                        f'BEGIN INSERT INTO {delta} VALUES ' + ', '.join(rows)
                        + f'; SELECT {prefix}_counted(changes()); END')

    yield

    # Seed expectations only after user triggers finish: setup inserts would
    # otherwise change their initial changes() and last_insert_rowid().
    con.executemany(f'INSERT INTO {delta} VALUES (?,?,?,?,?,?,?)', expected)
    observation_changes += len(expected)
    # No affinity conversions or Python equality: distinguish INTEGER/REAL,
    # TEXT/BLOB, NULL, embedded NULs, and duplicate rows inside the storage engine.
    group = ', '.join(f'typeof(v{i}), v{i} COLLATE BINARY' for i in range(5))
    if con.execute(f'SELECT 1 FROM {delta} GROUP BY tab, {group} '
                   'HAVING sum(sign) != 0 LIMIT 1').fetchone() is not None:
        raise sqlite3.IntegrityError('unexpected transfer effects')

    for name in observers:
        con.execute('DROP TRIGGER temp.' + _quote(name))
    con.execute('DROP TABLE temp.' + _quote(delta))
    if not recursive:
        for name, _ in triggers:
            con.execute('DROP TRIGGER main.' + _quote(name))
        for _, sql in triggers:
            con.execute(sql)
    if snapshot_pragma:
        con.execute('DROP VIEW main.pragma_recursive_triggers')
    con.execute(f'PRAGMA recursive_triggers={recursive}')
