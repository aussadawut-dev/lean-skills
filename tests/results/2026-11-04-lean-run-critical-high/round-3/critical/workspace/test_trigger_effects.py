from contextlib import closing
from pathlib import Path
import json
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import vault


ROOT = Path(__file__).resolve().parent


class TriggerEffectTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(dir=ROOT)
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / 'vault.sqlite'
        vault.init_db(self.path)
        with closing(sqlite3.connect(self.path)) as con, con:
            con.executemany('INSERT INTO accounts VALUES (?,?,?)', [
                ('red', 'a', 100), ('red', 'b', 20), ('blue', 'private', 77),
            ])
            for table in ('transfers', 'audit'):
                con.execute(f'INSERT INTO {table} VALUES (?,?,?,?,?)',
                            ('blue', 'historic', 'private', 'b', 2))

    def install(self, sql):
        with closing(sqlite3.connect(self.path)) as con, con:
            con.executescript(sql)

    def snapshot(self):
        with closing(sqlite3.connect(self.path)) as con:
            return [con.execute(f'SELECT * FROM {table} ORDER BY rowid').fetchall()
                    for table in ('accounts', 'transfers', 'audit', 'sqlite_schema')]

    def transfer(self):
        return vault.transfer(self.path, 'red', 'a', 'b', 10, 'new')

    def assert_rejected(self):
        before = self.snapshot()
        with self.assertRaises(sqlite3.IntegrityError):
            self.transfer()
        self.assertEqual(self.snapshot(), before)

    def assert_matches_native(self, side_tables=()):
        """Compare the public transfer with SQLite's original trigger semantics."""
        native = Path(self.directory.name) / 'native.sqlite'
        with closing(sqlite3.connect(self.path)) as original:
            with closing(sqlite3.connect(native)) as copy:
                original.backup(copy)
        with closing(sqlite3.connect(native)) as con, con:
            con.execute('BEGIN IMMEDIATE')
            con.execute("UPDATE accounts SET balance=90 WHERE tenant='red' AND name='a'")
            con.execute("UPDATE accounts SET balance=30 WHERE tenant='red' AND name='b'")
            for table in ('transfers', 'audit'):
                con.execute(f'INSERT INTO {table} VALUES (?,?,?,?,?)',
                            ('red', 'new', 'a', 'b', 10))
        schema = self.snapshot()[3]
        self.transfer()
        self.assertEqual(self.snapshot()[3], schema)
        for table in ('accounts', 'transfers', 'audit', *side_tables):
            with closing(sqlite3.connect(native)) as con:
                expected = con.execute(f'SELECT * FROM "{table}"').fetchall()
            with closing(sqlite3.connect(self.path)) as con:
                actual = con.execute(f'SELECT * FROM "{table}"').fetchall()
            self.assertCountEqual(actual, expected, table)

    def test_cancel_credit_rolls_back_all_rows_and_preserves_trigger(self):
        self.install('''CREATE TRIGGER undo_credit AFTER INSERT ON audit BEGIN
            UPDATE accounts SET balance=balance-NEW.amount
                WHERE tenant=NEW.tenant AND name=NEW.target;
        END;''')
        self.assert_rejected()

    def install_early_update(self, account, original, updated, restore=True):
        self.install(f'''CREATE TRIGGER early_{account} BEFORE UPDATE ON accounts
            WHEN OLD.tenant='red' AND OLD.name='{account}'
                AND OLD.balance={original} AND NEW.balance={updated} BEGIN
                UPDATE accounts SET balance={updated}
                    WHERE tenant=OLD.tenant AND name=OLD.name;
            END;''')
        if restore:
            self.install(f'''CREATE TRIGGER restore_{account} AFTER INSERT ON audit BEGIN
                UPDATE accounts SET balance={original}
                    WHERE tenant=NEW.tenant AND name='{account}';
            END;''')

    def test_before_debit_and_audit_restore_roll_back(self):
        self.install_early_update('a', 100, 90)
        self.assert_rejected()
        # Reopening and reusing the key must still reject, with no cached receipt.
        self.assert_rejected()

    def test_before_credit_and_audit_restore_roll_back(self):
        self.install_early_update('b', 20, 30)
        self.assert_rejected()

    def test_before_updates_with_correct_final_balances_match_native(self):
        self.install_early_update('a', 100, 90, restore=False)
        self.install_early_update('b', 20, 30, restore=False)
        self.assert_matches_native()
        before_replay = self.snapshot()
        self.assertEqual(self.transfer(), dict(tenant='red', key='new', source='a',
                                              target='b', amount=10))
        self.assertEqual(self.snapshot(), before_replay)

    def test_final_balance_check_retains_unrelated_null_identity_observation(self):
        self.install('''
            INSERT INTO accounts VALUES (NULL,'a',75), ('red',NULL,85);
            CREATE TRIGGER alter_unrelated AFTER INSERT ON audit BEGIN
                UPDATE accounts SET balance=balance+1 WHERE tenant IS NULL OR name IS NULL;
            END;
        ''')
        self.assert_rejected()

    def test_cli_before_debit_and_audit_restore_reject_without_changes(self):
        self.install_early_update('a', 100, 90)
        request = dict(op='transfer', tenant='red', source='a', target='b', amount=10, key='new')
        command = [sys.executable, '-B', str(ROOT / 'app.py'), str(self.path), json.dumps(request)]
        before = self.snapshot()
        for attempt in range(2):
            with self.subTest(attempt=attempt):
                result = subprocess.run(command, cwd=ROOT, text=True, capture_output=True, timeout=10)
                self.assertEqual(result.returncode, 2)
                self.assertEqual(result.stdout, '')
                self.assertEqual(result.stderr, '{"error": "invalid request"}\n')
                self.assertEqual(self.snapshot(), before)

    def test_replace_victim_is_observed_even_when_insert_is_undone(self):
        self.install('''
            CREATE UNIQUE INDEX unique_balance ON accounts(balance);
            CREATE TRIGGER replace_foreign AFTER INSERT ON audit BEGIN
                INSERT OR REPLACE INTO accounts VALUES ('red','temporary',77);
                DELETE FROM accounts WHERE tenant='red' AND name='temporary';
            END;
        ''')
        self.assert_rejected()

    def test_ignored_conflict_is_a_valid_transfer(self):
        self.install('''
            CREATE UNIQUE INDEX unique_balance ON accounts(balance);
            CREATE TRIGGER ignored_conflict AFTER INSERT ON audit BEGIN
                INSERT OR IGNORE INTO accounts VALUES ('red','temporary',77);
            END;
        ''')
        before_schema = self.snapshot()[3]
        self.assertEqual(self.transfer()['amount'], 10)
        self.assertEqual(vault.balance(self.path, 'red', 'a'), 90)
        self.assertEqual(vault.balance(self.path, 'red', 'b'), 30)
        self.assertEqual(vault.balance(self.path, 'blue', 'private'), 77)
        self.assertEqual(self.snapshot()[3], before_schema)
        before_replay = self.snapshot()
        self.assertEqual(self.transfer()['amount'], 10)
        self.assertEqual(self.snapshot(), before_replay)

    def test_duplicate_audit_and_removed_history_are_rejected(self):
        for body in (
            'INSERT INTO audit VALUES (NEW.tenant,NEW.key,NEW.source,NEW.target,NEW.amount);',
            "DELETE FROM audit WHERE tenant='blue';",
            "DELETE FROM transfers WHERE tenant='blue';",
            "DELETE FROM accounts WHERE tenant='blue';",
        ):
            with self.subTest(body=body):
                self.install('CREATE TRIGGER extra AFTER INSERT ON audit BEGIN ' + body + ' END;')
                self.assert_rejected()
                self.install('DROP TRIGGER extra;')

    def test_replace_victims_for_rowid_and_expression_unique_indexes(self):
        for index, insert in (
            ('', "INSERT OR REPLACE INTO accounts(rowid,tenant,name,balance) "
                 "VALUES (3,'red','temporary',77);"),
            ('CREATE UNIQUE INDEX expression_identity ON accounts(lower(name));',
             "INSERT OR REPLACE INTO accounts VALUES ('red','PRIVATE',77);"),
            ('CREATE UNIQUE INDEX partial_balance ON accounts(balance) WHERE balance>50;',
             "INSERT OR REPLACE INTO accounts VALUES ('red','temporary',77);"),
        ):
            with self.subTest(index=index):
                self.install(index + '''CREATE TRIGGER extra AFTER INSERT ON audit BEGIN
                    ''' + insert + '''
                    DELETE FROM accounts WHERE tenant='red' AND name NOT IN ('a','b');
                END;''')
                self.assert_rejected()
                self.install('DROP TRIGGER extra;')
                if index:
                    self.install('DROP INDEX ' + index.split()[3] + ';')

    def test_update_replace_victim_cannot_hide_behind_restored_update(self):
        self.install('''
            CREATE UNIQUE INDEX unique_balance ON accounts(balance);
            INSERT INTO accounts VALUES ('blue','other',88);
            CREATE TRIGGER extra AFTER INSERT ON audit BEGIN
                UPDATE OR REPLACE accounts SET balance=77 WHERE tenant='blue' AND name='other';
                UPDATE accounts SET balance=88 WHERE tenant='blue' AND name='other';
            END;
        ''')
        self.assert_rejected()

    def test_noops_row_moves_and_restored_duplicate_history_are_allowed(self):
        self.install('''
            INSERT INTO audit VALUES ('blue','historic','private','b',2);
            CREATE TRIGGER harmless AFTER INSERT ON audit BEGIN
                UPDATE accounts SET balance=balance, rowid=rowid+100 WHERE tenant='blue';
                DELETE FROM audit WHERE tenant='blue';
                INSERT INTO audit VALUES ('blue','historic','private','b',2),
                                         ('blue','historic','private','b',2);
            END;
        ''')
        self.assert_matches_native()

    def test_native_keyword_unicode_and_compound_statement_semantics(self):
        self.install('''
            CREATE TABLE "end" ("begin", "\u00a0name", "a\ufeffb");
            CREATE TRIGGER begin AFTER INSERT ON audit WHEN NEW.amount=10 BEGIN
                VALUES ('BEGIN; END; --'), ('/*;*/') UNION ALL SELECT 'WITH';
                WITH x(v) AS (VALUES (1),(2)) SELECT CASE WHEN v=1 THEN 'END' END FROM x;
                INSERT INTO "end" SELECT 'begin', 2, 3;
                UPDATE "end" SET \u00a0name=\u00a0name+1, a\ufeffb=a\ufeffb+1;
            END;
        ''')
        self.assert_matches_native(('end',))

    def test_vt_and_boundary_bom_explicit_deletes_keep_native_guards(self):
        for separator in ('\v', '\ufeff'):
            for timing in ('', 'BEFORE', 'AFTER'):
                with self.subTest(separator=repr(separator), timing=timing):
                    self.install(f'''
                        CREATE TABLE effects(kind);
                        CREATE TRIGGER deletion {timing} DELETE ON accounts BEGIN
                            INSERT INTO effects VALUES ('explicit');
                        END;
                        CREATE TRIGGER harmless AFTER INSERT ON audit BEGIN
                            INSERT OR REPLACE INTO accounts VALUES ('blue','private',77);
                            {separator}DELETE FROM accounts WHERE tenant='blue' AND name='private';
                            INSERT INTO accounts VALUES ('blue','private',77);
                        END;
                    ''')
                    self.assert_matches_native(('effects',))
                    with closing(sqlite3.connect(self.path)) as con:
                        self.assertEqual(con.execute('SELECT * FROM effects').fetchall(),
                                         [('explicit',)])
                    self.install('''DROP TRIGGER harmless; DROP TRIGGER deletion;
                        DROP TABLE effects; DELETE FROM transfers WHERE tenant='red';
                        DELETE FROM audit WHERE tenant='red';
                        UPDATE accounts SET balance=100 WHERE tenant='red' AND name='a';
                        UPDATE accounts SET balance=20 WHERE tenant='red' AND name='b';''')

    def test_ignore_across_rows_and_recursive_noops_match_native(self):
        self.install('''
            CREATE TABLE work(value);
            CREATE TABLE effects(kind,value);
            CREATE TRIGGER guarded BEFORE INSERT ON work BEGIN
                INSERT INTO effects VALUES ('checked',NEW.value);
                SELECT CASE WHEN NEW.value IN (1,3) THEN RAISE(IGNORE) END;
                INSERT INTO effects VALUES ('accepted',NEW.value);
            END;
            CREATE TRIGGER noop AFTER UPDATE ON accounts WHEN NEW.tenant='red' BEGIN
                UPDATE accounts SET balance=balance WHERE tenant=NEW.tenant AND name=NEW.name;
                INSERT INTO effects VALUES ('updated',NEW.name);
            END;
            CREATE TRIGGER work_items AFTER INSERT ON audit BEGIN
                INSERT INTO work VALUES (1),(2),(3),(4);
                INSERT INTO effects VALUES ('finished',0);
            END;
        ''')
        self.assert_matches_native(('work', 'effects'))

    def test_changes_total_changes_and_last_insert_rowid_match_native(self):
        self.install('''
            CREATE TABLE counters(event,changed,total,last);
            CREATE TRIGGER counts_update AFTER UPDATE ON accounts BEGIN
                INSERT INTO counters VALUES ('update', changes(), total_changes(), last_insert_rowid());
                SELECT 1;
                INSERT INTO counters VALUES ('second', changes(), total_changes(), last_insert_rowid());
            END;
            CREATE TRIGGER counts_audit AFTER INSERT ON audit BEGIN
                INSERT INTO counters VALUES ('audit', changes(), total_changes(), last_insert_rowid());
                INSERT OR IGNORE INTO accounts VALUES ('red','a',123);
                INSERT INTO counters VALUES ('ignored', changes(), total_changes(), last_insert_rowid());
            END;
        ''')
        self.assert_matches_native(('counters',))

    def test_original_recursive_pragma_aborting_guard_and_harmless_control(self):
        for table in ('pragma_recursive_triggers', 'pragma_recursive_triggers()',
                      'main."pragma_recursive_triggers"()', '[pragma_recursive_triggers]'):
            for rejects in (True, False):
                with self.subTest(table=table, rejects=rejects):
                    self.install(f'''CREATE TRIGGER pragma_guard BEFORE INSERT ON audit
                        WHEN (SELECT recursive_triggers FROM {table})={0 if rejects else 1}
                        BEGIN SELECT RAISE(ABORT,'original pragma guard'); END;''')
                    if rejects:
                        before = self.snapshot()
                        with self.assertRaisesRegex(sqlite3.IntegrityError, 'original pragma guard'):
                            self.transfer()
                        self.assertEqual(self.snapshot(), before)
                    else:
                        self.assert_matches_native()
                    self.install('''DROP TRIGGER pragma_guard;
                        DELETE FROM transfers WHERE tenant='red'; DELETE FROM audit WHERE tenant='red';
                        UPDATE accounts SET balance=100 WHERE tenant='red' AND name='a';
                        UPDATE accounts SET balance=20 WHERE tenant='red' AND name='b';''')

    def test_recursive_pragma_through_views_matches_native_and_restores_sql(self):
        for table in ('pragma_recursive_triggers()',
                      'main."pragma_recursive_triggers"(/* keep comment */)',
                      '[pragma_recursive_triggers]()', '`pragma_recursive_triggers`()',
                      'pragma_recursive_triggers'):
            for rejects in (False, True):
                with self.subTest(table=table, rejects=rejects):
                    # Create the indirect view first to also exercise a forward reference.
                    guard_view = '"saved mode"' if table == 'pragma_recursive_triggers()' else 'indirect_mode'
                    self.install(f'''
                        CREATE VIEW indirect_mode AS SELECT recursive_triggers FROM "saved mode";
                        CREATE VIEW "saved mode" AS SELECT recursive_triggers FROM {table};
                        CREATE TRIGGER pragma_guard BEFORE INSERT ON audit
                        WHEN (SELECT recursive_triggers FROM {guard_view})={0 if rejects else 1}
                        BEGIN SELECT RAISE(ABORT,'original pragma guard'); END;
                    ''')
                    try:
                        if rejects:
                            before = self.snapshot()
                            with self.assertRaisesRegex(sqlite3.IntegrityError, 'original pragma guard'):
                                self.transfer()
                            self.assertEqual(self.snapshot(), before)
                        else:
                            self.assert_matches_native()
                            before_replay = self.snapshot()
                            self.assertEqual(self.transfer()['amount'], 10)
                            self.assertEqual(self.snapshot(), before_replay)
                        with closing(sqlite3.connect(self.path)) as con:
                            self.assertEqual(con.execute('SELECT * FROM indirect_mode').fetchall(), [(0,)])
                    finally:
                        self.install('''DROP TRIGGER pragma_guard;
                            DROP VIEW "saved mode"; DROP VIEW indirect_mode;
                            DELETE FROM transfers WHERE tenant='red'; DELETE FROM audit WHERE tenant='red';
                            UPDATE accounts SET balance=100 WHERE tenant='red' AND name='a';
                            UPDATE accounts SET balance=20 WHERE tenant='red' AND name='b';''')

    def test_pragma_view_normalization_preserves_ctes_literals_and_view_triggers(self):
        self.install('''
            CREATE TABLE effects(mode,literal);
            CREATE VIEW shadowed_mode AS
                WITH "pragma_recursive_triggers"(recursive_triggers) AS (VALUES(7))
                SELECT recursive_triggers FROM "pragma_recursive_triggers";
            CREATE VIEW saved_mode AS
                SELECT recursive_triggers, 'pragma_recursive_triggers()' AS literal
                FROM pragma_recursive_triggers();
            CREATE TRIGGER save_mode INSTEAD OF INSERT ON saved_mode BEGIN
                INSERT INTO effects VALUES (NEW.recursive_triggers,NEW.literal);
            END;
            CREATE TRIGGER pragma_guard BEFORE INSERT ON audit
            WHEN (SELECT recursive_triggers FROM shadowed_mode)!=7
                OR (SELECT recursive_triggers FROM saved_mode)!=0
            BEGIN SELECT RAISE(ABORT,'original pragma guard'); END;
            CREATE TRIGGER record_mode AFTER INSERT ON audit BEGIN
                INSERT INTO saved_mode SELECT * FROM saved_mode;
            END;
        ''')
        self.assert_matches_native(('effects',))
        with closing(sqlite3.connect(self.path)) as con:
            self.assertEqual(con.execute('SELECT * FROM effects').fetchall(),
                             [(0, 'pragma_recursive_triggers()')])

    def test_recursive_pragma_real_table_shadowing_matches_native(self):
        self.install('''
            CREATE TABLE "pragma_recursive_triggers"(recursive_triggers);
            INSERT INTO "pragma_recursive_triggers" VALUES (7);
            CREATE VIEW saved_mode AS SELECT recursive_triggers FROM "pragma_recursive_triggers";
            CREATE TRIGGER pragma_guard BEFORE INSERT ON audit
            WHEN (SELECT recursive_triggers FROM saved_mode)!=7
            BEGIN SELECT RAISE(ABORT,'original pragma guard'); END;
        ''')
        self.assert_matches_native(('pragma_recursive_triggers',))

    def test_original_enabled_recursion_is_preserved(self):
        self.install('''
            CREATE TABLE effects(kind);
            CREATE TRIGGER deletion AFTER DELETE ON accounts BEGIN
                INSERT INTO effects VALUES ('implicit');
            END;
            CREATE TRIGGER replace_same AFTER INSERT ON audit BEGIN
                INSERT OR REPLACE INTO accounts VALUES ('blue','private',77);
                SELECT CASE WHEN (SELECT recursive_triggers FROM pragma_recursive_triggers())!=1
                    THEN RAISE(ABORT,'original pragma guard') END;
            END;
        ''')
        connect = sqlite3.connect

        def configured(*args, **kwargs):
            con = connect(*args, **kwargs)
            con.execute('PRAGMA recursive_triggers=ON')
            return con

        with patch.object(sqlite3, 'connect', configured):
            self.assert_matches_native(('effects',))
        with closing(sqlite3.connect(self.path)) as con:
            self.assertEqual(con.execute('SELECT * FROM effects').fetchall(), [('implicit',)])

    def test_type_only_history_changes_are_rejected(self):
        self.install('''
            DROP TABLE audit;
            CREATE TABLE audit (tenant, key, source, target, amount);
            INSERT INTO audit VALUES ('blue','historic','private','b',2);
        ''')
        for change in ("key=CAST(key AS BLOB)", "amount=CAST(amount AS REAL)"):
            with self.subTest(change=change):
                self.install('CREATE TRIGGER type_change AFTER INSERT ON audit BEGIN '
                             f"UPDATE audit SET {change} WHERE tenant='blue'; END;")
                self.assert_rejected()
                self.install('DROP TRIGGER type_change;')

    def test_storage_types_encodings_and_unreadable_foreign_text_are_preserved(self):
        for encoding in ('UTF-8', 'UTF-16le', 'UTF-16be'):
            with self.subTest(encoding=encoding):
                path = Path(self.directory.name) / (encoding + '.sqlite')
                with closing(sqlite3.connect(path)) as con:
                    con.execute(f"PRAGMA encoding='{encoding}'")
                    con.execute('CREATE TABLE marker(value)')
                vault.init_db(path)
                with closing(sqlite3.connect(path)) as con, con:
                    con.executemany('INSERT INTO accounts VALUES (?,?,?)', [
                        ('租户\x00', 'α', 100), ('租户\x00', 'β', 20),
                        ('blue', 'text', 'not an integer'), ('blue', 'real', 1.5),
                        ('blue', 'blob', b'\x00\xff'), ('blue', 'null', None),
                    ])
                    con.execute("INSERT INTO accounts VALUES ('blue','invalid',CAST(X'80' AS TEXT))")
                    con.executescript('''
                        CREATE TABLE counts(value);
                        CREATE TRIGGER harmless AFTER INSERT ON audit BEGIN
                            UPDATE accounts SET balance=balance WHERE tenant='blue';
                            INSERT INTO counts VALUES (total_changes());
                        END;
                    ''')
                    original = con.execute("SELECT name, typeof(balance), hex(CAST(balance AS BLOB)) "
                                           "FROM accounts WHERE tenant='blue' ORDER BY name").fetchall()
                receipt = vault.transfer(path, '租户\x00', 'α', 'β', 10, '鍵\x00')
                self.assertEqual(receipt, dict(tenant='租户\x00', source='α', target='β',
                                               amount=10, key='鍵\x00'))
                self.assertEqual(vault.balance(path, '租户\x00', 'α'), 90)
                self.assertEqual(vault.balance(path, '租户\x00', 'β'), 30)
                with closing(sqlite3.connect(path)) as con:
                    self.assertEqual(con.execute('PRAGMA encoding').fetchone()[0].lower(),
                                     encoding.lower())
                    self.assertEqual(con.execute("SELECT name, typeof(balance), hex(CAST(balance AS BLOB)) "
                                                 "FROM accounts WHERE tenant='blue' ORDER BY name").fetchall(),
                                     original)
                    count = con.execute('SELECT * FROM counts').fetchall()
                self.assertEqual(vault.transfer(path, '租户\x00', 'α', 'β', 10, '鍵\x00'), receipt)
                with closing(sqlite3.connect(path)) as con:
                    self.assertEqual(con.execute('SELECT * FROM counts').fetchall(), count)

    def test_cli_effect_failure_recovery_and_replay(self):
        self.install('''
            CREATE TABLE corruption(enabled);
            INSERT INTO corruption VALUES (1);
            CREATE TRIGGER undo_credit AFTER INSERT ON audit
            WHEN (SELECT enabled FROM corruption)=1 BEGIN
                UPDATE accounts SET balance=balance-NEW.amount
                    WHERE tenant=NEW.tenant AND name=NEW.target;
            END;
        ''')
        request = dict(op='transfer', tenant='red', source='a', target='b', amount=10, key='new')
        command = [sys.executable, '-B', str(ROOT / 'app.py'), str(self.path), json.dumps(request)]
        before = self.snapshot()
        failed = subprocess.run(command, cwd=ROOT, text=True, capture_output=True, timeout=10)
        self.assertEqual(failed.returncode, 2)
        self.assertEqual(failed.stdout, '')
        self.assertEqual(failed.stderr, '{"error": "invalid request"}\n')
        self.assertEqual(self.snapshot(), before)
        self.install('UPDATE corruption SET enabled=0;')
        succeeded = subprocess.run(command, cwd=ROOT, text=True, capture_output=True, timeout=10)
        self.assertEqual(succeeded.returncode, 0, succeeded.stderr)
        self.assertEqual(succeeded.stderr, '')
        self.assertEqual(json.loads(succeeded.stdout),
                         {key: value for key, value in request.items() if key != 'op'})
        self.install('UPDATE corruption SET enabled=1;')
        before_replay = self.snapshot()
        replay = subprocess.run(command, cwd=ROOT, text=True, capture_output=True, timeout=10)
        self.assertEqual((replay.returncode, replay.stdout, replay.stderr),
                         (succeeded.returncode, succeeded.stdout, succeeded.stderr))
        self.assertEqual(self.snapshot(), before_replay)


if __name__ == '__main__':
    unittest.main()
