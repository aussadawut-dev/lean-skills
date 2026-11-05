"""Public-interface regressions for trigger effects and durable preservation."""

import json
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from collections import Counter
from contextlib import closing
from pathlib import Path

import vault


ROOT = Path(__file__).resolve().parent


class TriggerEffectsTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(dir=ROOT)
        self.addCleanup(tmp.cleanup)
        self.directory = Path(tmp.name)
        self.database_number = 0
        self.new_database()

    def new_database(self):
        self.database_number += 1
        self.path = self.directory / f"vault-{self.database_number}.sqlite"
        vault.init_db(self.path)
        with closing(sqlite3.connect(self.path)) as con, con:
            con.executemany("INSERT INTO accounts VALUES (?, ?, ?)", [
                ("alpha", "source", 100), ("alpha", "target", 10),
                ("alpha", "unrelated", 40), ("beta", "source", 300),
                ("beta", "target", 20),
            ])
        self.history = [self.request(key="old-alpha", amount=3),
                        self.request(tenant="beta", key="old-beta", amount=5)]
        for request in self.history:
            self.assertEqual(vault.transfer(self.path, **request), request)
        # Audit has no unique key: preservation includes duplicate multiplicity.
        with closing(sqlite3.connect(self.path)) as con, con:
            con.execute("INSERT INTO audit SELECT * FROM audit WHERE tenant='beta'")

    def request(self, **changes):
        request = dict(tenant="alpha", key="new", source="source", target="target", amount=10)
        request.update(changes)
        return request

    def contents(self):
        with closing(sqlite3.connect(self.path)) as con:
            return {table: Counter(con.execute(f"SELECT * FROM {table}"))
                    for table in ("accounts", "transfers", "audit")}

    def schema(self):
        with closing(sqlite3.connect(self.path)) as con:
            return con.execute("SELECT type, name, tbl_name, sql FROM sqlite_master "
                               "ORDER BY type, name").fetchall()

    def trigger(self, event, body):
        with closing(sqlite3.connect(self.path)) as con, con:
            con.execute(f"CREATE TRIGGER probe {event} BEGIN {body} END")

    def drop_trigger(self):
        with closing(sqlite3.connect(self.path)) as con, con:
            con.execute("DROP TRIGGER probe")

    def assert_rejected_without_changes(self):
        before, schema = self.contents(), self.schema()
        with self.assertRaises(sqlite3.Error):
            vault.transfer(self.path, **self.request())
        self.assertEqual(self.contents(), before)
        self.assertEqual(self.schema(), schema)
        # Each public call opens a new connection. History must still deduplicate.
        for request in self.history:
            self.assertEqual(vault.transfer(self.path, **request), request)
        self.assertEqual(self.contents(), before)

    def assert_valid_transfer_and_replay(self):
        before, schema = self.contents(), self.schema()
        request = self.request()
        self.assertEqual(vault.transfer(self.path, **request), request)
        expected = {table: rows.copy() for table, rows in before.items()}
        for name, change in (("source", -10), ("target", 10)):
            old = next(row for row in before["accounts"] if row[:2] == ("alpha", name))
            expected["accounts"][old] -= 1
            expected["accounts"][("alpha", name, old[2] + change)] += 1
        row = tuple(request[field] for field in ("tenant", "key", "source", "target", "amount"))
        expected["transfers"][row] += 1
        expected["audit"][row] += 1
        self.assertEqual(self.contents(), expected)
        self.assertEqual(self.schema(), schema)
        self.assertEqual(vault.balance(self.path, "alpha", "source"), 87)
        self.assertEqual(vault.balance(self.path, "alpha", "target"), 23)
        self.assertEqual(vault.balance(self.path, "beta", "source"), 295)
        for replay in [request, *self.history]:
            self.assertEqual(vault.transfer(self.path, **replay), replay)
        self.assertEqual(self.contents(), expected)

    def test_after_triggers_cannot_erase_or_duplicate_required_effects(self):
        cases = {
            "missing debit": (
                "AFTER UPDATE ON accounts WHEN NEW.tenant='alpha' AND NEW.name='source'",
                "UPDATE accounts SET balance=OLD.balance WHERE tenant=NEW.tenant AND name=NEW.name;"),
            "missing credit": (
                "AFTER UPDATE ON accounts WHEN NEW.tenant='alpha' AND NEW.name='target'",
                "UPDATE accounts SET balance=OLD.balance WHERE tenant=NEW.tenant AND name=NEW.name;"),
            "missing receipt": (
                "AFTER INSERT ON transfers",
                "DELETE FROM transfers WHERE tenant=NEW.tenant AND key=NEW.key;"),
            "missing audit": (
                "AFTER INSERT ON audit", "DELETE FROM audit WHERE rowid=NEW.rowid;"),
            "duplicate audit": (
                "AFTER INSERT ON audit",
                "INSERT INTO audit VALUES (NEW.tenant, NEW.key, NEW.source, NEW.target, NEW.amount);"),
            # Only the final check can catch a later write undoing an earlier one.
            "late missing credit": (
                "AFTER INSERT ON audit",
                "UPDATE accounts SET balance=balance-NEW.amount "
                "WHERE tenant=NEW.tenant AND name=NEW.target;"),
            "late missing receipt": (
                "AFTER INSERT ON audit",
                "DELETE FROM transfers WHERE tenant=NEW.tenant AND key=NEW.key;"),
        }
        for name, (event, body) in cases.items():
            with self.subTest(case=name):
                self.new_database()
                self.trigger(event, body)
                try:
                    self.assert_rejected_without_changes()
                finally:
                    self.drop_trigger()

    def test_existing_audit_contents_and_multiplicity_are_preserved(self):
        cases = {
            "other tenant rewrite": "UPDATE audit SET amount=amount+1 WHERE tenant='beta';",
            "equal counts with different duplicate multiplicity":
                "DELETE FROM audit WHERE rowid=(SELECT MIN(rowid) FROM audit WHERE tenant='beta'); "
                "INSERT INTO audit SELECT * FROM audit WHERE tenant='alpha' AND key='old-alpha';",
            "current row rewrite": "UPDATE audit SET amount=amount+1 WHERE rowid=NEW.rowid;",
        }
        for name, body in cases.items():
            with self.subTest(case=name):
                self.new_database()
                self.trigger("AFTER INSERT ON audit", body)
                try:
                    self.assert_rejected_without_changes()
                finally:
                    self.drop_trigger()

    def test_existing_receipts_and_unrelated_accounts_are_preserved(self):
        cases = {
            "same tenant receipt deletion": "DELETE FROM transfers WHERE tenant='alpha' AND key='old-alpha';",
            "other tenant receipt deletion": "DELETE FROM transfers WHERE tenant='beta' AND key='old-beta';",
            "other tenant receipt rewrite": "UPDATE transfers SET amount=99 WHERE tenant='beta';",
            "same tenant unrelated account": "UPDATE accounts SET balance=0 WHERE tenant='alpha' AND name='unrelated';",
            "other tenant account": "UPDATE accounts SET balance=0 WHERE tenant='beta' AND name='source';",
            "other tenant account deletion": "DELETE FROM accounts WHERE tenant='beta' AND name='target';",
            "other tenant account replacement": "INSERT OR REPLACE INTO accounts VALUES ('beta', 'source', 0);",
            "extra account": "INSERT INTO accounts VALUES ('beta', 'extra', 1);",
        }
        for name, body in cases.items():
            with self.subTest(case=name):
                self.new_database()
                self.trigger("AFTER INSERT ON audit", body)
                try:
                    self.assert_rejected_without_changes()
                finally:
                    self.drop_trigger()

    def test_rowid_relocation_preserves_valid_transfer_and_replay(self):
        self.trigger("AFTER INSERT ON audit",
                     "UPDATE accounts SET rowid=rowid+1000; "
                     "UPDATE transfers SET rowid=rowid+1000; "
                     "UPDATE audit SET rowid=rowid+1000;")
        self.assert_valid_transfer_and_replay()

    def test_valid_noop_triggers_preserve_transfer_and_replay(self):
        self.trigger("AFTER INSERT ON audit",
                     "INSERT OR IGNORE INTO accounts VALUES (NEW.tenant, NEW.target, -1); "
                     "UPDATE accounts SET balance=balance WHERE tenant='beta'; "
                     "UPDATE transfers SET amount=amount WHERE tenant='beta'; "
                     "UPDATE audit SET amount=amount WHERE tenant='beta';")
        self.assert_valid_transfer_and_replay()

    def cli(self, request):
        return subprocess.run([sys.executable, "-B", str(ROOT / "app.py"),
                               str(self.path), json.dumps(request)], cwd=ROOT,
                              text=True, capture_output=True, timeout=10)

    def test_cli_preservation_failures_are_atomic_and_history_still_replays(self):
        cases = {
            "historical receipt": "DELETE FROM transfers WHERE tenant='alpha' AND key='old-alpha';",
            "other tenant account": "UPDATE accounts SET balance=0 WHERE tenant='beta' AND name='source';",
            "audit history": "UPDATE audit SET amount=99 WHERE tenant='beta';",
        }
        for name, body in cases.items():
            with self.subTest(case=name):
                self.new_database()
                self.trigger("AFTER INSERT ON audit", body)
                try:
                    before, schema = self.contents(), self.schema()
                    failed = self.cli(dict(op="transfer", **self.request()))
                    self.assertEqual(failed.returncode, 2)
                    self.assertEqual(failed.stdout, "")
                    self.assertEqual(failed.stderr, '{"error": "request failed"}\n')
                    self.assertEqual(self.contents(), before)
                    self.assertEqual(self.schema(), schema)
                    for request in self.history:
                        replay = self.cli(dict(op="transfer", **request))
                        self.assertEqual(replay.returncode, 0, replay.stderr)
                        self.assertEqual(replay.stderr, "")
                        self.assertEqual(len(replay.stdout.splitlines()), 1)
                        self.assertEqual(json.loads(replay.stdout), request)
                    self.assertEqual(self.contents(), before)
                finally:
                    self.drop_trigger()
        self.new_database()
        self.assert_valid_transfer_and_replay()


if __name__ == "__main__":
    unittest.main()
