from collections import Counter
from contextlib import closing
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest

import vault


ROOT = Path(__file__).resolve().parent
COLUMNS = {
    'accounts': ('tenant', 'name', 'balance'),
    'transfers': ('tenant', 'key', 'source', 'target', 'amount'),
    'audit': ('tenant', 'key', 'source', 'target', 'amount'),
}


class FinalRepairTests(unittest.TestCase):
    def create_database(self, path, request, script, encoding):
        with closing(sqlite3.connect(path)) as con, con:
            # Persist the encoding before init_db creates the remaining tables.
            con.execute("PRAGMA encoding='" + encoding + "'")
            con.execute('CREATE TABLE accounts (tenant TEXT, name TEXT, balance INTEGER, '
                        'PRIMARY KEY(tenant,name))')
        vault.init_db(path)
        with closing(sqlite3.connect(path)) as con, con:
            self.assertEqual(con.execute('PRAGMA encoding').fetchone()[0], encoding)
            con.executemany('INSERT INTO accounts VALUES (?, ?, ?)', [
                (request['tenant'], request['source'], 100),
                (request['tenant'], request['target'], 0),
            ])
            con.execute("INSERT INTO accounts VALUES ('two', 'foreign', CAST(X'FF00FF' AS TEXT))")
            con.execute("INSERT INTO transfers VALUES ('two', 'history', 'old', 'target', 7)")
            con.executemany('INSERT INTO audit VALUES (?, ?, ?, ?, ?)',
                            [('two', 'history', 'old', 'target', 7)] * 2)
            con.executescript(script)

    def snapshot(self, path):
        with closing(sqlite3.connect(path)) as con:
            # Read raw database-encoding bytes, preserving malformed foreign
            # TEXT, storage classes, and duplicate historical rows.
            return {table: Counter(con.execute('SELECT ' + ', '.join(
                f"typeof({name}), CASE WHEN typeof({name})='text' "
                f'THEN CAST({name} AS BLOB) ELSE {name} END' for name in columns
            ) + ' FROM ' + table)) for table, columns in COLUMNS.items()}

    def schema(self, path):
        with closing(sqlite3.connect(path)) as con:
            return con.execute('SELECT type, name, sql FROM sqlite_master ORDER BY rowid').fetchall()

    def native_transfer(self, path, request):
        # Reference the four writes with SQLite's original trigger definitions
        # and default recursion semantics, on a fresh independent connection.
        with closing(sqlite3.connect(path)) as con, con:
            con.execute('PRAGMA recursive_triggers=OFF')
            con.execute('BEGIN IMMEDIATE')
            con.execute('UPDATE accounts SET balance=? WHERE tenant=? AND name=?',
                        (100 - request['amount'], request['tenant'], request['source']))
            con.execute('UPDATE accounts SET balance=? WHERE tenant=? AND name=?',
                        (request['amount'], request['tenant'], request['target']))
            values = tuple(request[name] for name in COLUMNS['transfers'])
            con.execute('INSERT INTO transfers VALUES (?, ?, ?, ?, ?)', values)
            con.execute('INSERT INTO audit VALUES (?, ?, ?, ?, ?)', values)

    def cli(self, path, request):
        return subprocess.run([sys.executable, '-B', str(ROOT / 'app.py'),
                               str(path), json.dumps(request)], cwd=ROOT,
                              capture_output=True, text=True, timeout=15)

    def assert_cli_success(self, result, expected):
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stderr, '')
        self.assertEqual(len(result.stdout.splitlines()), 1)
        self.assertEqual(json.loads(result.stdout), expected)

    def assert_native_behavior(self, script, *, failure=None, encoding='UTF-8', request=None):
        if request is None:
            request = dict(tenant='one', source='a', target='b', amount=10, key='k')
        with tempfile.TemporaryDirectory(prefix='.final-repair-tests-', dir=ROOT) as directory:
            native = Path(directory) / 'native.sqlite'
            self.create_database(native, request, script, encoding)
            before, schema = self.snapshot(native), self.schema(native)
            if failure:
                with self.assertRaisesRegex(sqlite3.IntegrityError, failure):
                    self.native_transfer(native, request)
                self.assertEqual(self.snapshot(native), before)
            else:
                self.native_transfer(native, request)
            expected = self.snapshot(native)
            self.assertEqual(self.schema(native), schema)

            for interface in ('api', 'cli'):
                with self.subTest(interface=interface):
                    path = Path(directory) / (interface + '.sqlite')
                    self.create_database(path, request, script, encoding)
                    self.assertEqual(self.snapshot(path), before)
                    self.assertEqual(self.schema(path), schema)
                    if interface == 'api':
                        if failure:
                            with self.assertRaisesRegex(sqlite3.IntegrityError, failure):
                                vault.transfer(path, **request)
                        else:
                            self.assertEqual(vault.transfer(path, **request), request)
                    else:
                        result = self.cli(path, dict(op='transfer', **request))
                        if failure:
                            self.assertEqual(result.returncode, 2, result.stderr)
                            self.assertEqual(result.stdout, '')
                            self.assertEqual(result.stderr, '{"error": "invalid request"}\n')
                        else:
                            self.assert_cli_success(result, request)
                    self.assertEqual(self.snapshot(path), expected)
                    self.assertEqual(self.schema(path), schema)
                    if not failure:
                        # Reopen for exact replay and balances through both
                        # public interfaces; replay must add no storage effects.
                        self.assertEqual(vault.transfer(path, **request), request)
                        self.assert_cli_success(self.cli(path, dict(op='transfer', **request)), request)
                        self.assertEqual(self.snapshot(path), expected)
                        self.assertEqual(self.schema(path), schema)
                        self.assertEqual(vault.balance(path, request['tenant'], request['source']), 90)
                        self.assert_cli_success(self.cli(path, dict(
                            op='balance', tenant=request['tenant'], account=request['target'])), 10)

    def test_multirow_ignore_and_null_controls_preserve_abort_and_rollback(self):
        for timing in ('BEFORE', 'AFTER'):
            for expression in ('RAISE(IGNORE)', 'NULL'):
                with self.subTest(timing=timing, expression=expression):
                    self.assert_native_behavior(f"""
                        CREATE TRIGGER guard {timing} UPDATE ON accounts
                        WHEN NEW.balance=OLD.balance BEGIN
                          SELECT CASE WHEN NEW.name='a' THEN {expression}
                                 ELSE RAISE(ABORT, 'blocked') END;
                        END;
                        CREATE TRIGGER audit_check AFTER INSERT ON audit BEGIN
                          UPDATE accounts SET balance=balance WHERE tenant=NEW.tenant;
                        END;
                    """, failure='blocked')

    def test_conditional_ignore_preserves_recursive_guards_and_change_counters(self):
        for timing in ('BEFORE', 'AFTER'):
            for ignore in (True, False):
                expression = 'RaIsE /* preserve this span */ ( IgNoRe )' if ignore else 'NULL'
                total = (7 if timing == 'BEFORE' else 8) if ignore else 9
                changed = 1 if ignore and timing == 'BEFORE' else 2
                with self.subTest(timing=timing, ignore=ignore):
                    self.assert_native_behavior(f"""
                        CREATE TRIGGER guard {timing} UPDATE ON accounts
                        WHEN NEW.balance=OLD.balance BEGIN
                          UPDATE accounts SET balance=balance
                            WHERE tenant=NEW.tenant AND name=NEW.name;
                          SELECT 'RAISE(IGNORE); is text',
                                 CASE WHEN NEW.name='a' THEN {expression} END;
                          UPDATE accounts SET balance=balance
                            WHERE tenant=NEW.tenant AND name=NEW.name;
                        END;
                        CREATE TRIGGER audit_check AFTER INSERT ON audit BEGIN
                          UPDATE accounts SET balance=balance WHERE tenant=NEW.tenant;
                          SELECT CASE WHEN changes()!={changed} OR total_changes()!={total}
                                 THEN RAISE(ABORT, 'changed counter') END;
                        END;
                    """)

    def test_values_and_with_select_keep_native_trigger_behavior(self):
        statements = (
            'VALUES(1);',
            'WITH c AS (SELECT 1) SELECT * FROM c;',
            "VALUES('RAISE(IGNORE);'), ('quoted text');",
            'WITH RECURSIVE c(n) AS (VALUES(1) UNION ALL SELECT n+1 FROM c WHERE n<3) '
            'SELECT n FROM c;',
        )
        for statement in statements:
            with self.subTest(statement=statement):
                self.assert_native_behavior('CREATE TRIGGER t AFTER INSERT ON audit BEGIN '
                                            + statement + """
                    SELECT CASE WHEN changes()!=1 OR total_changes()!=3
                           THEN RAISE(ABORT, 'changed counter') END;
                    END;
                """)

    def test_delete_event_separators_and_identifiers_preserve_delete_semantics(self):
        boundaries = [('gate', ' \v'), ('gate', ' \ufeff'),
                      ('gate\u00a0name', ' '), ('gate\ufeffname', ' '), ('\u00a0gate', ' ')]
        for name, separator in boundaries:
            for explicit in (False, True):
                delete = ('DELETE FROM transfers WHERE tenant=NEW.tenant AND key=NEW.key;'
                          if explicit else '')
                with self.subTest(name=name, separator=separator, explicit=explicit):
                    self.assert_native_behavior(f"""
                        CREATE TRIGGER {name}{separator}DELETE ON transfers BEGIN
                          SELECT RAISE(ABORT, 'explicit deletion');
                        END;
                        CREATE TRIGGER replace_receipt AFTER INSERT ON audit BEGIN
                          {delete}
                          INSERT OR REPLACE INTO transfers VALUES
                            (NEW.tenant, NEW.key, NEW.source, NEW.target, NEW.amount);
                          SELECT CASE WHEN changes()!=1 OR total_changes()!=4
                                 THEN RAISE(ABORT, 'changed counter') END;
                        END;
                    """, failure='explicit deletion' if explicit else None)

    def test_database_encoding_preserves_unicode_and_raw_foreign_rows(self):
        request = dict(tenant='租户🗝', source="源'α", target='目β', amount=10, key='鍵☃🗝')
        for encoding in ('UTF-8', 'UTF-16le', 'UTF-16be'):
            with self.subTest(encoding=encoding):
                self.assert_native_behavior("""
                    CREATE TRIGGER keep_raw AFTER INSERT ON audit BEGIN
                      UPDATE accounts SET balance=balance WHERE tenant='two';
                      SELECT CASE WHEN changes()!=1 OR total_changes()!=4
                             THEN RAISE(ABORT, 'changed counter') END;
                    END;
                """, encoding=encoding, request=request)


if __name__ == '__main__':
    unittest.main()
