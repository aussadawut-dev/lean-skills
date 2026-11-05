"""Native SQLite controls for the scope and limits of resolution oracles."""
from contextlib import closing
import json
import sqlite3


def events_for(con, sql):
    events = []
    con.set_authorizer(lambda *event: (events.append(event), sqlite3.SQLITE_OK)[1])
    try:
        values = con.execute(sql).fetchall()
    finally:
        con.set_authorizer(None)
    return values, events


def error_for(con, sql):
    try:
        con.execute(sql).fetchall()
    except sqlite3.OperationalError as error:
        return str(error)
    raise AssertionError(f'Unexpected success: {sql}')


with closing(sqlite3.connect(':memory:', cached_statements=0)) as con:
    con.executescript("""
        PRAGMA recursive_triggers=OFF;
        CREATE TABLE audit(i);
        CREATE VIEW saved_mode AS SELECT 0 IN main.pragma_recursive_triggers AS mode;
        CREATE TRIGGER native_guard BEFORE INSERT ON audit
        WHEN (SELECT mode FROM saved_mode)=1
        BEGIN SELECT RAISE(ABORT,'native guard'); END;
    """)
    _, prepared = events_for(con, 'EXPLAIN INSERT INTO audit VALUES(1)')
    assert (sqlite3.SQLITE_READ, 'pragma_recursive_triggers', 'recursive_triggers',
            'main', 'saved_mode') in prepared
    assert con.execute('SELECT * FROM audit').fetchall() == []
    _, execution = events_for(con, 'SELECT * FROM saved_mode')
    assert (sqlite3.SQLITE_PRAGMA, 'recursive_triggers', None, None, None) in execution
    for query, expected in (
        ('SELECT 0 IN pragma_recursive_triggers', [(1,)]),
        ('SELECT 0 IN main.pragma_recursive_triggers', [(1,)]),
        ('SELECT p.recursive_triggers FROM pragma_recursive_triggers() AS p', [(0,)]),
        ('SELECT main.pragma_recursive_triggers.recursive_triggers '
         'FROM pragma_recursive_triggers NOT INDEXED', [(0,)]),
        ('SELECT recursive_triggers, rowid, _rowid_, oid FROM pragma_recursive_triggers()', [(0, 1, 1, 1)]),
        ("""SELECT 'pragma_recursive_triggers', "pragma_recursive_triggers" """,
         [('pragma_recursive_triggers', 'pragma_recursive_triggers')]),
        ('WITH pragma_recursive_triggers(recursive_triggers) AS (VALUES (7)) '
         'SELECT 7 IN pragma_recursive_triggers', [(1,)]),
        ('WITH pragma_recursive_triggers(recursive_triggers) AS (VALUES (7)) '
         'SELECT 0 IN main.pragma_recursive_triggers', [(1,)]),
    ):
        assert con.execute(query).fetchall() == expected, query
    _, shadowed_cte = events_for(con, 'WITH pragma_recursive_triggers(x) AS (VALUES (7)) '
                                    'SELECT * FROM pragma_recursive_triggers')
    assert all(event[0] != sqlite3.SQLITE_PRAGMA for event in shadowed_cte)
    nested = ('WITH pragma_recursive_triggers AS (SELECT recursive_triggers+7 AS recursive_triggers '
              'FROM main.pragma_recursive_triggers) SELECT recursive_triggers FROM ')
    con.execute('CREATE TABLE surrogate (recursive_triggers)')
    con.execute('INSERT INTO surrogate VALUES (0)')
    native, native_events = events_for(con, nested + 'pragma_recursive_triggers')
    edited, edited_events = events_for(con, nested + 'surrogate')
    assert native == [(7,)] and edited == [(0,)]
    assert any(event[0] == sqlite3.SQLITE_PRAGMA for event in native_events)
    assert all(event[0] != sqlite3.SQLITE_PRAGMA for event in edited_events)

    con.execute('CREATE VIEW mode_view AS SELECT 0 AS recursive_triggers')
    assert 'no such column: rowid' in error_for(con, 'SELECT rowid FROM mode_view')
    assert con.execute('SELECT rowid, _rowid_, oid FROM surrogate').fetchall() == [(1, 1, 1)]
    assert 'no such index' in error_for(
        con, 'SELECT * FROM pragma_recursive_triggers INDEXED BY absent')
    con.executescript("""
        CREATE TABLE pragma_recursive_triggers(recursive_triggers);
        INSERT INTO pragma_recursive_triggers VALUES(7);
        CREATE INDEX owned_index ON pragma_recursive_triggers(recursive_triggers);
    """)
    values, shadowed_table = events_for(
        con, 'SELECT recursive_triggers FROM pragma_recursive_triggers INDEXED BY owned_index')
    assert values == [(7,)]
    assert (sqlite3.SQLITE_READ, 'pragma_recursive_triggers', 'recursive_triggers',
            'main', None) in shadowed_table
    assert all(event[0] != sqlite3.SQLITE_PRAGMA for event in shadowed_table)
    assert 'is not a function' in error_for(con, 'SELECT * FROM pragma_recursive_triggers()')
    assert con.execute('SELECT * FROM temp.pragma_recursive_triggers()').fetchall() == [(0,)]
    options = [option for option, in con.execute('PRAGMA compile_options')]
    assert 'ENABLE_PREUPDATE_HOOK' not in options
print(json.dumps({
    'sqlite_version': sqlite3.sqlite_version,
    'status': 'PASS',
    'controls': [
        'EXPLAIN compiles top-level writes through stored trigger and view without writes',
        'runtime PRAGMA authorizer distinguishes actual built-in read from CTE and table',
        'equivalent native sources include IN plain/main and NOT INDEXED qualified',
        'disappearing PRAGMA event does not prove an edited span referenced the builtin',
        'view and same-name real table shadows have observable differences',
        'binding has no preupdate hook compiled',
    ],
}, indent=2))
