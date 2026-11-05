import collections
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


class RepairTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory(prefix='.repair-tests-', dir=ROOT)
        self.addCleanup(directory.cleanup)
        self.path = Path(directory.name) / 'vault.sqlite'
        vault.init_db(self.path)
        self.sql("""
            INSERT INTO accounts VALUES ('one','a',100), ('one','b',0),
                                        ('two','foreign',777);
            INSERT INTO audit VALUES ('two','history','old','target',7);
        """)

    def sql(self, statements):
        with sqlite3.connect(self.path) as con:
            con.executescript(statements)

    def pay(self, **changes):
        request = dict(tenant='one', source='a', target='b', amount=10, key='k')
        request.update(changes)
        return vault.transfer(self.path, **request)

    def snapshot(self):
        with sqlite3.connect(self.path) as con:
            con.text_factory = bytes
            # Include storage classes: Python considers 7 == 7.0 and a bytes
            # text_factory alone conflates SQL TEXT and BLOB.
            return {table: collections.Counter(con.execute(
                'SELECT ' + ', '.join('typeof(' + c + '), ' + c for c in columns)
                + ' FROM ' + table)) for table, columns in COLUMNS.items()}

    def schema(self):
        with sqlite3.connect(self.path) as con:
            return con.execute('SELECT type, name, sql FROM sqlite_master ORDER BY name').fetchall()

    def assert_rollback(self):
        before, schema = self.snapshot(), self.schema()
        with self.assertRaises(sqlite3.Error):
            self.pay()
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(self.schema(), schema)

    def cli(self, payload):
        return subprocess.run([sys.executable, '-B', str(ROOT / 'app.py'),
                               str(self.path), payload], cwd=ROOT,
                              capture_output=True, text=True, timeout=15)

    def test_erased_required_audit_is_rejected_and_retryable(self):
        self.sql('CREATE TRIGGER erase_audit AFTER INSERT ON audit '
                 'BEGIN DELETE FROM audit WHERE rowid=NEW.rowid; END;')
        self.assert_rollback()
        self.sql('DROP TRIGGER erase_audit;')
        original = self.pay()
        self.assertEqual(self.pay(), original)
        with sqlite3.connect(self.path) as con:
            self.assertEqual(con.execute("SELECT count(*) FROM audit WHERE tenant='one'").fetchone()[0], 1)

    def test_foreign_balance_change_is_rejected(self):
        self.sql("CREATE TRIGGER corrupt AFTER INSERT ON audit BEGIN "
                 "UPDATE accounts SET balance=0 WHERE tenant='two'; END;")
        self.assert_rollback()

    def test_storage_class_only_change_is_rejected(self):
        self.sql("CREATE TRIGGER corrupt AFTER INSERT ON audit BEGIN "
                 "UPDATE accounts SET name=CAST(name AS BLOB) WHERE tenant='two'; END;")
        self.assert_rollback()

    def test_replace_cannot_remove_history_via_extra_unique_indexes(self):
        self.sql("""
            INSERT INTO audit VALUES ('two','second','another','target',9);
            CREATE UNIQUE INDEX audit_key ON audit(key);
            CREATE UNIQUE INDEX audit_source ON audit(source);
            CREATE TRIGGER replace_history AFTER INSERT ON audit
            WHEN NEW.tenant='one' BEGIN
              INSERT OR REPLACE INTO audit VALUES ('two','history','another','target',7);
              UPDATE audit SET source='old' WHERE key='history';
            END;
        """)
        self.assert_rollback()

    def test_noops_ignored_conflicts_and_row_moves_preserve_raw_foreign_data(self):
        self.sql("""
            UPDATE accounts SET balance=CAST(X'FF' AS TEXT) WHERE tenant='two';
            CREATE TRIGGER harmless AFTER INSERT ON audit WHEN NEW.tenant='one' BEGIN
              UPDATE accounts SET balance=balance WHERE tenant='two';
              INSERT OR IGNORE INTO accounts VALUES ('two','foreign',0);
              UPDATE accounts SET rowid=rowid+100 WHERE tenant='two';
              DELETE FROM audit WHERE tenant='two';
              INSERT INTO audit VALUES ('two','history','old','target',7);
            END;
        """)
        before, schema = self.snapshot(), self.schema()
        self.pay()
        after = self.snapshot()
        for table in COLUMNS:
            self.assertEqual(collections.Counter({row: n for row, n in after[table].items()
                                                  if row[1] == b'two'}), before[table] if table != 'accounts'
                             else collections.Counter({row: n for row, n in before[table].items()
                                                       if row[1] == b'two'}))
        self.assertEqual(self.schema(), schema)

    def test_implicit_replace_delete_keeps_native_delete_trigger_behavior(self):
        self.sql("""
            CREATE UNIQUE INDEX audit_key ON audit(key);
            CREATE TRIGGER explicit_deletes_fail BEFORE DELETE ON audit BEGIN
              SELECT RAISE(ABORT, 'explicit deletion');
            END;
            CREATE TRIGGER harmless_replace AFTER INSERT ON audit WHEN NEW.tenant='one' BEGIN
              INSERT OR REPLACE INTO audit VALUES ('two','history','old','target',7);
              SELECT CASE WHEN total_changes()!=4 THEN RAISE(ABORT, 'changed counter') END;
            END;
        """)
        schema = self.schema()
        self.assertEqual(self.pay()['amount'], 10)
        self.assertEqual(self.schema(), schema)
        self.sql("""
            DROP TRIGGER harmless_replace;
            CREATE TRIGGER explicit_delete AFTER INSERT ON audit WHEN NEW.tenant='one' BEGIN
              DELETE FROM audit WHERE tenant='two';
              INSERT INTO audit VALUES ('two','history','old','target',7);
            END;
        """)
        before = self.snapshot()
        with self.assertRaisesRegex(sqlite3.IntegrityError, 'explicit deletion'):
            self.pay(key='explicit')
        self.assertEqual(self.snapshot(), before)

    def test_recursive_noop_and_after_ignore_keep_native_behavior(self):
        self.sql("""
            CREATE TRIGGER noop AFTER UPDATE ON accounts WHEN NEW.tenant='two' BEGIN
              UPDATE accounts SET balance=balance WHERE tenant=NEW.tenant AND name=NEW.name;
              SELECT RAISE(IGNORE);
            END;
            CREATE TRIGGER nested AFTER INSERT ON audit WHEN NEW.tenant='one' BEGIN
              UPDATE accounts SET balance=balance WHERE tenant='two';
              UPDATE accounts SET balance=balance WHERE tenant='two';
              SELECT CASE WHEN total_changes()!=7 THEN RAISE(ABORT, 'changed counter') END;
            END;
        """)
        self.assertEqual(self.pay()['amount'], 10)
        self.assertEqual(vault.balance(self.path, 'two', 'foreign'), 777)

    def test_duplicate_decoded_json_keys_are_rejected_without_effects(self):
        before = self.snapshot()
        payloads = [
            '{"op":"balance","tenant":"two","tenant":"one","account":"a"}',
            '{"op":"transfer","tenant":"one","source":"a","target":"b",'
            '"key":"k","amount":1,"amount":10}',
            r'{"op":"transfer","tenant":"one","source":"a","target":"b",'
            r'"key":"k","amount":1,"\u0061mount":10}',
            r'{"op":"balance","\u006fp":"balance","tenant":"one","account":"a"}',
        ]
        for payload in payloads:
            with self.subTest(payload=payload):
                result = self.cli(payload)
                self.assertEqual(result.returncode, 2, result.stderr)
                self.assertEqual(result.stdout, '')
                self.assertEqual(result.stderr, '{"error": "invalid request"}\n')
                self.assertEqual(self.snapshot(), before)

    def test_durable_replay_survives_removed_endpoints_and_rejects_new_requests(self):
        original = self.pay()
        self.sql("DELETE FROM accounts WHERE tenant='one';")
        before = self.snapshot()
        self.assertEqual(self.pay(), original)
        result = self.cli(json.dumps(dict(op='transfer', **original)))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout), original)
        for changes in ({'key': 'new'}, {'amount': 11}, {'amount': True}, {'tenant': 'two'}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                self.pay(**changes)
        self.assertEqual(self.snapshot(), before)


if __name__ == '__main__':
    unittest.main()
