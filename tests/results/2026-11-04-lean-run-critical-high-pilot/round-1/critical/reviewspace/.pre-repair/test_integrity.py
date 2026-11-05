from contextlib import closing
from pathlib import Path
import sqlite3
import tempfile
import unittest

import vault


WORKSPACE = Path(__file__).resolve().parent


class WriteIntegrityRegressions(unittest.TestCase):
    def database(self, setup='', encoding='UTF-8'):
        temporary = tempfile.TemporaryDirectory(dir=WORKSPACE)
        self.addCleanup(temporary.cleanup)
        path = Path(temporary.name) / 'vault.sqlite'
        with closing(sqlite3.connect(path)) as con:
            con.execute("PRAGMA encoding='" + encoding + "'")
            con.execute('CREATE TABLE observations(c,t,l)')
        vault.init_db(path)
        with closing(sqlite3.connect(path)) as con, con:
            con.executemany('INSERT INTO accounts VALUES (?,?,?)', [
                ('red', 'a', 100), ('red', 'b', 20), ('blue', 'private', 77),
                ('blue', 'other', 88),
            ])
            for table in ('transfers', 'audit'):
                con.executemany(f'INSERT INTO {table} VALUES (?,?,?,?,?)', [
                    ('red', 'previous', 'a', 'b', 1),
                    ('blue', 'previous', 'private', 'other', 1),
                ])
            con.executescript(setup)
        return path

    def snapshot(self, path):
        with closing(sqlite3.connect(path)) as con:
            result = {}
            for table, columns in (
                ('accounts', ('tenant', 'name', 'balance')),
                ('transfers', ('tenant', 'key', 'source', 'target', 'amount')),
                ('audit', ('tenant', 'key', 'source', 'target', 'amount')),
            ):
                # Include storage classes and bytes; malformed TEXT stays in
                # SQLite, and duplicate audit rows stay duplicated.
                fields = ','.join(f'typeof({col}),hex(CAST({col} AS BLOB))' for col in columns)
                result[table] = sorted(con.execute(f'SELECT {fields} FROM {table}').fetchall())
            result['schema'] = con.execute(
                'SELECT type,name,tbl_name,sql FROM sqlite_schema ORDER BY type,name'
            ).fetchall()
            result['observations'] = con.execute('SELECT * FROM observations').fetchall()
            return result

    def send(self, path):
        return vault.transfer(path, 'red', 'a', 'b', 10, 'new')

    def native_transfer(self, path):
        # Same public operation's four statements on a fresh native connection,
        # used only as a reference for trigger semantics and SQL-visible state.
        with closing(sqlite3.connect(path)) as con, con:
            con.execute('BEGIN IMMEDIATE')
            con.execute("UPDATE accounts SET balance=90 WHERE tenant='red' AND name='a'")
            con.execute("UPDATE accounts SET balance=30 WHERE tenant='red' AND name='b'")
            con.execute("INSERT INTO transfers VALUES ('red','new','a','b',10)")
            con.execute("INSERT INTO audit VALUES ('red','new','a','b',10)")

    def assert_native_control(self, setup, encoding='UTF-8'):
        native = self.database(setup, encoding)
        observed = self.database(setup, encoding)
        self.native_transfer(native)
        receipt = self.send(observed)
        self.assertEqual(receipt, dict(tenant='red', key='new', source='a', target='b', amount=10))
        self.assertEqual(self.snapshot(observed), self.snapshot(native))
        committed = self.snapshot(observed)
        self.assertEqual(self.send(observed), receipt)
        self.assertEqual(self.snapshot(observed), committed)

    def assert_rollback(self, setup):
        path = self.database(setup)
        before = self.snapshot(path)
        with self.assertRaises(sqlite3.IntegrityError):
            self.send(path)
        self.assertEqual(self.snapshot(path), before)
        self.assertEqual(vault.balance(path, 'red', 'a'), 100)
        return path

    def test_final_effects_history_multiplicity_and_storage_classes(self):
        cases = (
            "DELETE FROM audit WHERE key='new';",
            "UPDATE accounts SET balance=20 WHERE tenant='red' AND name='b';",
            "UPDATE accounts SET balance=100 WHERE tenant='red' AND name='a';",
            "DELETE FROM transfers WHERE tenant='blue';",
            "DELETE FROM audit WHERE tenant='blue';",
            "INSERT OR REPLACE INTO transfers VALUES ('blue','previous','private','other',2);",
            "UPDATE audit SET amount=2 WHERE tenant='blue';",
            "INSERT INTO audit VALUES (NEW.tenant,NEW.key,NEW.source,NEW.target,NEW.amount);",
            "UPDATE accounts SET balance=78 WHERE tenant='blue' AND name='private';",
            "UPDATE accounts SET name=CAST(name AS BLOB) WHERE tenant='blue' AND name='private';",
            "UPDATE transfers SET target=CAST(target AS BLOB) WHERE tenant='blue';",
            "UPDATE audit SET source=CAST(source AS BLOB) WHERE tenant='blue';",
        )
        for body in cases:
            with self.subTest(body=body):
                self.assert_rollback('CREATE TRIGGER effect AFTER INSERT ON audit BEGIN ' + body + ' END;')
        self.assert_rollback('''
            INSERT INTO audit SELECT * FROM audit WHERE tenant='blue';
            CREATE TRIGGER remove_one AFTER INSERT ON audit BEGIN
              DELETE FROM audit WHERE rowid=(SELECT min(rowid) FROM audit WHERE tenant='blue');
            END;
        ''')

    def test_stale_old_images_reconcile_latest_slot_and_control(self):
        setup = '''
            CREATE TRIGGER early_restore BEFORE UPDATE ON accounts
            WHEN OLD.tenant='blue' AND OLD.name='private' AND OLD.balance=78 AND NEW.balance=77
            BEGIN UPDATE accounts SET balance=77 WHERE tenant=OLD.tenant AND name=OLD.name; END;
            CREATE TRIGGER touch_foreign AFTER INSERT ON audit BEGIN
              UPDATE accounts SET balance=78 WHERE tenant='blue' AND name='private';
              UPDATE accounts SET balance=77 WHERE tenant='blue' AND name='private';
              %s
            END;
        '''
        self.assert_rollback(setup % "UPDATE accounts SET balance=78 WHERE tenant='blue' AND name='private';")
        self.assert_native_control(setup % '')

    def test_before_endpoint_changes_followed_by_audit_restoration(self):
        for endpoint, initial, final in (('a', 100, 90), ('b', 20, 30)):
            with self.subTest(endpoint=endpoint):
                setup = f'''
                    CREATE TRIGGER before_endpoint BEFORE UPDATE ON accounts
                    WHEN OLD.tenant='red' AND OLD.name='{endpoint}' AND OLD.balance={initial}
                    BEGIN UPDATE accounts SET balance={final} WHERE tenant='red' AND name='{endpoint}'; END;
                    CREATE TRIGGER restore_endpoint AFTER INSERT ON audit BEGIN
                      UPDATE accounts SET balance=%s WHERE tenant='red' AND name='{endpoint}';
                    END;
                '''
                self.assert_rollback(setup % initial)
                self.assert_native_control(setup % final)

    def test_replace_victims_from_unique_expression_and_partial_indexes(self):
        indexes = (
            'CREATE UNIQUE INDEX extra_unique ON accounts(balance);',
            'CREATE UNIQUE INDEX extra_unique ON accounts(abs(balance));',
            "CREATE UNIQUE INDEX extra_unique ON accounts(balance) WHERE tenant='blue';",
        )
        for index in indexes:
            for mutation in (
                "INSERT OR REPLACE INTO accounts VALUES ('blue','intruder',77); DELETE FROM accounts WHERE name='intruder';",
                "UPDATE OR REPLACE accounts SET balance=77 WHERE tenant='blue' AND name='other'; UPDATE accounts SET balance=88 WHERE tenant='blue' AND name='other';",
            ):
                with self.subTest(index=index, mutation=mutation):
                    self.assert_rollback(index + 'CREATE TRIGGER replacement AFTER INSERT ON audit BEGIN ' + mutation + ' END;')
        for table in ('transfers', 'audit'):
            self.assert_rollback(f'''
                CREATE UNIQUE INDEX extra_unique ON {table}(lower(key)) WHERE tenant='blue';
                CREATE TRIGGER replacement AFTER INSERT ON audit BEGIN
                  INSERT OR REPLACE INTO {table} VALUES ('blue','PREVIOUS','x','y',2);
                  DELETE FROM {table} WHERE tenant='blue' AND key='PREVIOUS';
                END;
            ''')

    def test_ignored_conflicts_row_moves_and_identical_replacements(self):
        for body in (
            "INSERT OR IGNORE INTO accounts VALUES ('blue','private',999);",
            "UPDATE OR IGNORE accounts SET name='private' WHERE tenant='blue' AND name='other';",
            "UPDATE accounts SET balance=balance WHERE tenant='blue';",
            "UPDATE accounts SET rowid=rowid+100 WHERE tenant='blue';",
            "UPDATE transfers SET rowid=rowid+100 WHERE tenant='blue';",
            "UPDATE audit SET rowid=rowid+100 WHERE tenant='blue';",
            "INSERT OR REPLACE INTO accounts VALUES ('blue','private',77);",
            "INSERT OR REPLACE INTO transfers VALUES ('blue','previous','private','other',1);",
            "DELETE FROM audit WHERE tenant='blue'; INSERT INTO audit VALUES ('blue','previous','private','other',1);",
        ):
            with self.subTest(body=body):
                self.assert_native_control('CREATE TRIGGER valid_effect AFTER INSERT ON audit BEGIN ' + body + ' END;')
        self.assert_native_control('''
            CREATE UNIQUE INDEX extra_unique ON accounts(abs(balance)) WHERE tenant='blue';
            CREATE TRIGGER ignored AFTER INSERT ON audit BEGIN
              INSERT OR IGNORE INTO accounts VALUES ('blue','ignored',77);
              UPDATE OR IGNORE accounts SET balance=77 WHERE tenant='blue' AND name='other';
            END;
        ''')

    def test_user_delete_triggers_do_not_start_firing_for_replace(self):
        self.assert_native_control('''
            CREATE TRIGGER delete_guard BEFORE DELETE ON accounts
            BEGIN SELECT RAISE(ABORT,'native replace does not fire this'); END;
            CREATE TRIGGER replace_same AFTER INSERT ON audit BEGIN
              INSERT OR REPLACE INTO accounts VALUES ('blue','private',77);
            END;
        ''')
        self.assert_rollback('''
            CREATE TRIGGER delete_guard BEFORE DELETE ON accounts
            BEGIN SELECT RAISE(ABORT,'explicit delete does fire this'); END;
            CREATE TRIGGER explicit_delete AFTER INSERT ON audit BEGIN
              DELETE FROM accounts WHERE tenant='blue' AND name='private';
              INSERT INTO accounts VALUES ('blue','private',77);
            END;
        ''')

    def test_native_recursion_guards_direct_and_through_views(self):
        sources = (
            'pragma_recursive_triggers', 'pragma_recursive_triggers()',
            "'pragma_recursive_triggers'()", 'main.pragma_recursive_triggers()',
            "'main'.'pragma_recursive_triggers'() AS mode",
        )
        for source in sources:
            for expected in (0, 1):
                for through_view in (False, True):
                    with self.subTest(source=source, expected=expected, view=through_view):
                        setup = f'CREATE VIEW saved_mode AS SELECT recursive_triggers FROM {source};' if through_view else ''
                        query_source = 'saved_mode' if through_view else source
                        setup += f'''
                            CREATE TRIGGER native_guard BEFORE INSERT ON audit
                            WHEN (SELECT recursive_triggers FROM {query_source})={expected}
                            BEGIN SELECT RAISE(ABORT,'native guard'); END;
                        '''
                        if expected == 0:
                            self.assert_rollback(setup)
                        else:
                            self.assert_native_control(setup)

    def test_pragma_literals_aliases_and_table_name_resolution(self):
        self.assert_native_control('''
            CREATE VIEW saved_mode AS SELECT recursive_triggers, 'pragma_recursive_triggers' AS literal
            FROM 'pragma_recursive_triggers'();
            CREATE TRIGGER guard BEFORE INSERT ON audit
            WHEN (SELECT recursive_triggers FROM saved_mode)<>0
              OR (SELECT literal FROM saved_mode)<>'pragma_recursive_triggers'
            BEGIN SELECT RAISE(ABORT,'changed literal or mode'); END;
        ''')
        self.assert_native_control('''
            CREATE TABLE pragma_recursive_triggers(recursive_triggers);
            INSERT INTO pragma_recursive_triggers VALUES (7);
            CREATE VIEW saved_mode AS SELECT p.recursive_triggers FROM 'pragma_recursive_triggers' AS p;
            CREATE TRIGGER guard BEFORE INSERT ON audit WHEN (SELECT recursive_triggers FROM saved_mode)<>7
            BEGIN SELECT RAISE(ABORT,'shadowed table'); END;
        ''')

    def test_counters_and_last_insert_state_match_native_execution(self):
        self.assert_native_control('''
            CREATE TABLE scratch(value);
            INSERT INTO scratch(rowid,value) VALUES (100,0);
            CREATE TRIGGER before_account BEFORE UPDATE ON accounts BEGIN
              INSERT INTO observations VALUES (changes(),total_changes(),last_insert_rowid());
            END;
            CREATE TRIGGER after_account AFTER UPDATE ON accounts BEGIN
              INSERT INTO observations VALUES (changes(),total_changes(),last_insert_rowid());
            END;
            CREATE TRIGGER nested AFTER INSERT ON scratch BEGIN
              INSERT INTO observations VALUES (changes(),total_changes(),last_insert_rowid());
            END;
            CREATE TRIGGER counters AFTER INSERT ON audit BEGIN
              INSERT INTO observations VALUES (changes(),total_changes(),last_insert_rowid());
              INSERT INTO scratch VALUES (1);
              INSERT INTO observations VALUES (changes(),total_changes(),last_insert_rowid());
              UPDATE accounts SET balance=balance WHERE tenant='blue';
              INSERT INTO observations VALUES (changes(),total_changes(),last_insert_rowid());
            END;
        ''')

    def test_nested_raise_ignore_resumes_parent_statement_scope(self):
        self.assert_native_control('''
            CREATE TABLE scratch(value);
            CREATE TRIGGER skip BEFORE INSERT ON scratch WHEN NEW.value=1
            BEGIN SELECT RAISE(IGNORE); END;
            CREATE TRIGGER parent AFTER INSERT ON audit BEGIN
              INSERT INTO scratch VALUES (1);
              INSERT INTO scratch VALUES (2);
              INSERT INTO scratch VALUES (1);
              INSERT INTO observations SELECT value,changes(),total_changes() FROM scratch;
            END;
        ''')
        self.assert_native_control('''
            CREATE TABLE scratch(value);
            CREATE TRIGGER child AFTER INSERT ON scratch WHEN NEW.value=1 BEGIN
              INSERT INTO scratch VALUES (2);
              SELECT RAISE(IGNORE);
            END;
            CREATE TRIGGER parent AFTER INSERT ON audit BEGIN
              INSERT INTO scratch VALUES (1);
              INSERT INTO scratch VALUES (1);
              INSERT INTO observations SELECT value,changes(),total_changes() FROM scratch;
            END;
        ''')

    def test_keyword_unicode_names_conditional_bodies_and_separators(self):
        names = ('begin', 'end', 'λ', 'dollar$name', 'a\u00a0b', 'a\ufeffb', '"name with spaces"', "'single quoted'")
        bodies = (
            'SELECT 1;',
            'VALUES(1);',
            'WITH vals(v) AS (VALUES(1)) SELECT v FROM vals;',
            "SELECT CASE WHEN 1 THEN 'END; BEGIN' ELSE 'x' END;",
        )
        for name in names:
            for body in bodies:
                with self.subTest(name=name, body=body):
                    self.assert_native_control(f'CREATE TRIGGER {name} AFTER INSERT ON audit WHEN NEW.amount=10 BEGIN {body} END;')
        for separator in (' \v', ' \ufeff', '\n', '\t', '\r\f'):
            with self.subTest(separator=repr(separator)):
                self.assert_native_control('CREATE TRIGGER separator AFTER INSERT ON audit BEGIN' + separator + 'DELETE FROM audit WHERE 0; SELECT' + separator + '1; END;')

    def test_malformed_foreign_text_and_database_encodings(self):
        for encoding in ('UTF-8', 'UTF-16le', 'UTF-16be'):
            with self.subTest(encoding=encoding):
                self.assert_native_control('''
                    UPDATE accounts SET balance=CAST(X'80FF' AS TEXT) WHERE tenant='blue' AND name='private';
                    UPDATE transfers SET amount=CAST(X'80FF' AS TEXT) WHERE tenant='blue';
                    UPDATE audit SET source=CAST(X'80FF' AS TEXT) WHERE tenant='blue';
                    CREATE TRIGGER harmless AFTER INSERT ON audit BEGIN
                      UPDATE accounts SET balance=balance WHERE tenant='blue';
                      UPDATE transfers SET amount=amount WHERE tenant='blue';
                      UPDATE audit SET source=source WHERE tenant='blue';
                    END;
                ''', encoding)


if __name__ == '__main__':
    unittest.main()
