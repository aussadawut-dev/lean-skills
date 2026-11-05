"""Regression checks for the bounded observer, lexer, and durable replay repair."""

from contextlib import closing
import json
import sqlite3
import subprocess
import sys

import test_regressions as fixtures
import vault


class RepairRegressionTests(fixtures.VaultFixture):
    def raw_rows(self, table, where=''):
        # Include storage classes: text_factory alone conflates TEXT and BLOB.
        columns = {
            'accounts': ('tenant', 'name', 'balance'),
            'transfers': ('tenant', 'key', 'source', 'target', 'amount'),
            'audit': ('tenant', 'key', 'source', 'target', 'amount'),
        }[table]
        fields = ','.join(f'typeof("{column}"),"{column}"' for column in columns)
        with closing(sqlite3.connect(self.path)) as con:
            con.text_factory = bytes
            return sorted(con.execute(f'SELECT {fields} FROM {table} {where}').fetchall(), key=repr)

    def schema(self):
        with closing(sqlite3.connect(self.path)) as con:
            return con.execute('SELECT type,name,sql FROM sqlite_master ORDER BY type,name').fetchall()

    def raw_snapshot(self):
        return ([self.raw_rows(table) for table in fixtures.TABLES], self.schema())

    def test_foreign_text_noop_preserves_data_and_triggers(self):
        self.execute("CREATE TRIGGER benign AFTER INSERT ON audit BEGIN "
                     "UPDATE accounts SET balance=balance WHERE tenant='other'; END")
        definitions = self.schema()
        for index, value in enumerate((b'ordinary text', b'\x80\xff')):
            with self.subTest(value=value):
                self.execute("UPDATE accounts SET balance=CAST(? AS TEXT) "
                             "WHERE tenant='other' AND name='secret'", (value,))
                before = self.raw_rows('accounts', "WHERE tenant='other'")
                request = self.request(amount=1, key=f'noop-{index}')
                self.assertEqual(vault.transfer(self.path, **request), request)
                self.assertEqual(before, self.raw_rows('accounts', "WHERE tenant='other'"))
                self.assertEqual(definitions, self.schema())
                self.assertEqual(vault.balance(self.path, 'one', 'a'), 99 - index)
                self.assertEqual(vault.balance(self.path, 'one', 'b'), index + 1)
                self.assertEqual(len(self.rows('audit')), index + 1)
                self.assertCountEqual(self.rows('transfers'), self.rows('audit'))

    def test_foreign_raw_storage_changes_are_rolled_back(self):
        cases = [
            ("CAST(x'80ff' AS TEXT)", "CAST(x'80fe' AS TEXT)"),
            ("CAST(x'80ff' AS TEXT)", "x'80ff'"),
            ("x'80ff'", "CAST(x'80ff' AS TEXT)"),
            ('NULL', "x''"),
            ('0.5', '0.5000000000000001'),
        ]
        for original, replacement in cases:
            self.execute(f"UPDATE accounts SET balance={original} "
                         "WHERE tenant='other' AND name='secret'")
            self.execute("CREATE TRIGGER side_effect AFTER INSERT ON audit BEGIN "
                         f"UPDATE accounts SET balance={replacement} "
                         "WHERE tenant='other' AND name='secret'; END")
            before = self.raw_snapshot()
            with self.subTest(original=original, replacement=replacement):
                with self.assertRaises(sqlite3.IntegrityError):
                    vault.transfer(self.path, **self.request())
                self.assertEqual(before, self.raw_snapshot())
            self.execute('DROP TRIGGER side_effect')

    def test_malformed_foreign_history_noops_preserve_rows(self):
        for table in ('transfers', 'audit'):
            self.execute(f"INSERT INTO {table} VALUES "
                         "('other','history',CAST(x'80ff' AS TEXT),'b',1)")
        self.execute("CREATE TRIGGER history_noop AFTER INSERT ON audit BEGIN "
                     "UPDATE transfers SET source=source WHERE tenant='other'; "
                     "UPDATE audit SET source=source WHERE tenant='other'; END")
        before = [self.raw_rows(table, "WHERE tenant='other'")
                  for table in ('transfers', 'audit')]
        definitions = self.schema()
        self.assertEqual(vault.transfer(self.path, **self.request()), self.request())
        self.assertEqual(before, [self.raw_rows(table, "WHERE tenant='other'")
                                  for table in ('transfers', 'audit')])
        self.assertEqual(definitions, self.schema())

    def test_observation_preserves_trigger_visible_total_changes(self):
        self.execute('CREATE TABLE notes (stage TEXT, changes INTEGER)')
        for table, event in (('accounts', 'UPDATE'), ('transfers', 'INSERT'), ('audit', 'INSERT')):
            self.execute(f'CREATE TRIGGER count_{table} AFTER {event} ON {table} '
                         f"BEGIN INSERT INTO notes VALUES ('{table}',total_changes()); END")
        # Native SQLite on a fresh connection supplies the trigger-visible control.
        with closing(sqlite3.connect(self.path)) as con:
            con.execute('BEGIN')
            con.execute("UPDATE accounts SET balance=90 WHERE tenant='one' AND name='a'")
            con.execute("UPDATE accounts SET balance=10 WHERE tenant='one' AND name='b'")
            con.execute("INSERT INTO transfers VALUES ('one','k','a','b',10)")
            con.execute("INSERT INTO audit VALUES ('one','k','a','b',10)")
            expected = con.execute('SELECT * FROM notes').fetchall()
            con.rollback()
        self.assertEqual(vault.transfer(self.path, **self.request()), self.request())
        self.assertEqual(self.rows('notes'), expected)

    def test_observation_uses_the_existing_database_text_encoding(self):
        for encoding in ('UTF-16le', 'UTF-16be'):
            with self.subTest(encoding=encoding):
                path = self.path.with_name(encoding + '.sqlite')
                with closing(sqlite3.connect(path)) as con, con:
                    con.execute(f"PRAGMA encoding='{encoding}'")
                    con.execute('CREATE TABLE notes (value TEXT)')
                    con.execute("INSERT INTO notes VALUES ('保留')")
                vault.init_db(path)
                with closing(sqlite3.connect(path)) as con, con:
                    con.executemany('INSERT INTO accounts VALUES (?,?,?)',
                                    [('租户', '来源', 10), ('租户', '收款', 0),
                                     ('other', 'secret', 'foreign text')])
                    con.execute('CREATE TRIGGER benign AFTER INSERT ON audit BEGIN '
                                "UPDATE accounts SET balance=balance WHERE tenant='other'; END")
                request = dict(tenant='租户', source='来源', target='收款', amount=2, key='凭据')
                self.assertEqual(vault.transfer(path, **request), request)
                self.assertEqual(vault.balance(path, '租户', '来源'), 8)
                self.assertEqual(vault.balance(path, '租户', '收款'), 2)
                with closing(sqlite3.connect(path)) as con:
                    self.assertEqual(con.execute('PRAGMA encoding').fetchone()[0], encoding)
                    self.assertEqual(con.execute('SELECT * FROM notes').fetchall(), [('保留',)])
                    self.assertEqual(con.execute("SELECT balance,typeof(balance) FROM accounts "
                                                 "WHERE tenant='other'").fetchall(),
                                     [('foreign text', 'text')])

    def test_sqlite_token_boundary_separators_are_accepted(self):
        for index, separator in enumerate((' ', '\v', '\ufeff')):
            self.execute('CREATE TRIGGER harmless ' + separator +
                         ' AFTER INSERT ON audit BEGIN SELECT 1; END')
            definitions = self.schema()
            with self.subTest(separator=repr(separator)):
                request = self.request(amount=1, key=f'separator-{index}')
                self.assertEqual(vault.transfer(self.path, **request), request)
                self.assertEqual(definitions, self.schema())
            self.execute('DROP TRIGGER harmless')

    def test_sqlite_identifier_characters_remain_identifiers(self):
        for index, name in enumerate(('\u00a0harmless', 'with\u00a0space', 'cash$flow', 'inside\ufeffname')):
            self.execute(f'CREATE TRIGGER {name} AFTER INSERT ON audit BEGIN SELECT 1; END')
            definitions = self.schema()
            with self.subTest(name=name):
                request = self.request(amount=1, key=f'identifier-{index}')
                self.assertEqual(vault.transfer(self.path, **request), request)
                self.assertEqual(definitions, self.schema())
            self.execute(f'DROP TRIGGER "{name}"')

    def test_durable_receipt_precedes_endpoint_reads_but_not_validation(self):
        request = self.request(amount=1)
        receipt = vault.transfer(self.path, **request)
        self.execute("INSERT INTO transfers VALUES ('other','k',CAST(x'80ff' AS TEXT),'b',1)")
        self.execute("CREATE TRIGGER no_new_audit BEFORE INSERT ON audit "
                     "BEGIN SELECT RAISE(FAIL, 'unexpected replay effect'); END")
        for endpoint in ('b', 'a'):
            # Fixture mutation and every public invocation use separate connections.
            self.execute("DELETE FROM accounts WHERE tenant='one' AND name=?", (endpoint,))
            before = self.raw_snapshot()
            with self.subTest(endpoint=endpoint):
                self.assertEqual(vault.transfer(self.path, **request), receipt)
                with self.assertRaisesRegex(ValueError, 'key conflict'):
                    vault.transfer(self.path, **self.request(amount=2))
                with self.assertRaisesRegex(ValueError, 'account not found'):
                    vault.transfer(self.path, **self.request(key='new'))
                with self.assertRaisesRegex(ValueError, 'invalid request'):
                    vault.transfer(self.path, **self.request(amount=True))
                self.assertEqual(before, self.raw_snapshot())

    def test_cli_repair_and_durable_replay_journey(self):
        def invoke(request):
            return subprocess.run(
                [sys.executable, '-B', str(fixtures.ROOT / 'app.py'), str(self.path),
                 json.dumps(dict(op='transfer', **request))],
                cwd=fixtures.ROOT, capture_output=True, text=True, timeout=15,
            )

        self.execute("UPDATE accounts SET balance=CAST(x'80ff' AS TEXT) "
                     "WHERE tenant='other' AND name='secret'")
        self.execute('CREATE TRIGGER benign \ufeff AFTER INSERT ON audit BEGIN '
                     "UPDATE accounts SET balance=balance WHERE tenant='other'; END")
        request = self.request()
        created = invoke(request)
        self.assertEqual(created.returncode, 0, created.stderr)
        self.assertEqual(created.stderr, '')
        self.assertEqual(json.loads(created.stdout), request)
        self.assertEqual(len(created.stdout.splitlines()), 1)
        self.execute("DELETE FROM accounts WHERE tenant='one' AND name='b'")
        before = self.raw_snapshot()
        replay = invoke(request)
        self.assertEqual(replay.returncode, 0, replay.stderr)
        self.assertEqual(replay.stderr, '')
        self.assertEqual(json.loads(replay.stdout), request)
        self.assertEqual(len(replay.stdout.splitlines()), 1)
        for invalid in (self.request(key='new'), self.request(amount=11)):
            result = invoke(invalid)
            self.assertEqual(result.returncode, 2)
            self.assertEqual(result.stdout, '')
            self.assertEqual(json.loads(result.stderr), {'error': 'invalid request'})
            self.assertEqual(len(result.stderr.splitlines()), 1)
        self.assertEqual(before, self.raw_snapshot())
