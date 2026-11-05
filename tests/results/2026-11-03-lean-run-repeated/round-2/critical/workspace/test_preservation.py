import json
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from collections import Counter
from contextlib import closing, contextmanager
from pathlib import Path

import vault


ROOT = Path(__file__).resolve().parent
COLUMNS = "tenant, key, source, target, amount"
REQUEST = dict(tenant="alpha", key="payment", source="source", target="target", amount=10)


class PreservationTests(unittest.TestCase):
    @contextmanager
    def database(self):
        with tempfile.TemporaryDirectory(dir=ROOT, prefix=".preservation-test-") as directory:
            path = Path(directory) / "vault.sqlite"
            vault.init_db(path)
            with closing(sqlite3.connect(path)) as con, con:
                con.executemany(
                    "INSERT INTO accounts VALUES (?, ?, ?)",
                    [(tenant, name, funds) for tenant in ("alpha", "beta")
                     for name, funds in (("source", 100), ("target", 20), ("reserve", 50))],
                )
            for tenant in ("alpha", "beta"):
                vault.transfer(path, tenant, "source", "target", 7, "history")
            with closing(sqlite3.connect(path)) as con, con:
                # Replacing one copy of 3 with another copy of 7 preserves both
                # the row count and the set of rows, but corrupts multiplicity.
                con.executemany(
                    "INSERT INTO audit VALUES ('beta', 'legacy', 'source', 'target', ?)",
                    [(3,), (3,), (7,)],
                )
            yield path

    def snapshot(self, path):
        with closing(sqlite3.connect(path)) as con:
            return {
                table: Counter(con.execute(f"SELECT {columns} FROM {table}"))
                for table, columns in (
                    ("accounts", "tenant, name, balance"),
                    ("transfers", COLUMNS), ("audit", COLUMNS),
                    ("sqlite_master", "type, name, tbl_name, sql"),
                )
            }

    def trigger(self, path, action, event="INSERT ON audit"):
        with closing(sqlite3.connect(path)) as con, con:
            con.execute(
                f"CREATE TRIGGER preservation_probe AFTER {event} "
                f"BEGIN {action} END"
            )

    def cli(self, path, **request):
        return subprocess.run(
            [sys.executable, "-B", str(ROOT / "app.py"), str(path),
             json.dumps(dict(op="transfer", **request))],
            cwd=ROOT, text=True, capture_output=True, timeout=15,
        )

    def assert_replays_preserved(self, path, before):
        vault.init_db(path)
        for tenant in ("alpha", "beta"):
            request = dict(REQUEST, tenant=tenant, key="history", amount=7)
            self.assertEqual(vault.transfer(path, **request), request)
            replay = self.cli(path, **request)
            self.assertEqual(replay.returncode, 0, replay.stderr)
            self.assertEqual(replay.stderr, "")
            self.assertEqual(json.loads(replay.stdout), request)
        self.assertEqual(self.snapshot(path), before)

    def assert_rejected(self, action, event="INSERT ON audit", cli=False):
        with self.database() as path:
            self.trigger(path, action, event)
            before = self.snapshot(path)
            if cli:
                result = self.cli(path, **REQUEST)
                self.assertEqual(result.returncode, 2, result.stderr)
                self.assertEqual(result.stdout, "")
                self.assertEqual(json.loads(result.stderr), {"error": "invalid request"})
            else:
                with self.assertRaises(sqlite3.Error):
                    vault.transfer(path, **REQUEST)
            # A fresh connection observes rollback of all rows and retained schema.
            self.assertEqual(self.snapshot(path), before)
            self.assert_replays_preserved(path, before)

    def test_audit_history_and_duplicate_multiplicity_are_preserved(self):
        actions = (
            "UPDATE audit SET amount = amount + 1 WHERE tenant = 'beta' AND key = 'history';",
            "DELETE FROM audit WHERE rowid = (SELECT rowid FROM audit "
            "WHERE tenant = 'beta' AND key = 'legacy' AND amount = 3 LIMIT 1); "
            "INSERT INTO audit VALUES ('beta', 'legacy', 'source', 'target', 7);",
            "INSERT INTO audit VALUES ('beta', 'unexpected', 'source', 'target', 1);",
        )
        for action in actions:
            with self.subTest(action=action):
                self.assert_rejected(action)

    def test_existing_receipts_cannot_be_deleted_rewritten_or_replaced(self):
        actions = (
            "DELETE FROM transfers WHERE tenant = 'alpha' AND key = 'history';",
            "UPDATE transfers SET amount = 99 WHERE tenant = 'beta' AND key = 'history';",
            "INSERT INTO transfers VALUES ('beta', 'unexpected', 'source', 'target', 1);",
            # SQLite REPLACE can delete a conflicting row without firing DELETE
            # triggers, even when the inserted receipt has the expected values.
            "INSERT OR REPLACE INTO transfers (rowid, tenant, key, source, target, amount) "
            "SELECT rowid, NEW.tenant, NEW.key, NEW.source, NEW.target, NEW.amount "
            "FROM transfers WHERE tenant = 'beta' AND key = 'history';",
        )
        for action in actions:
            with self.subTest(action=action):
                self.assert_rejected(action)

    def test_accounts_outside_the_authorized_pair_are_preserved(self):
        actions = (
            "UPDATE accounts SET balance = balance + 50 WHERE tenant = 'beta' AND name = 'source';",
            "UPDATE accounts SET balance = balance + 50 WHERE tenant = 'alpha' AND name = 'reserve';",
            "DELETE FROM accounts WHERE tenant = 'beta' AND name = 'reserve';",
            "INSERT INTO accounts VALUES ('alpha', 'unexpected', 50);",
            "UPDATE OR REPLACE accounts SET rowid = (SELECT rowid FROM accounts "
            "WHERE tenant = 'beta' AND name = 'reserve') "
            "WHERE tenant = 'alpha' AND name = 'source';",
        )
        for action in actions:
            with self.subTest(action=action):
                self.assert_rejected(action)

    def test_preservation_checks_cover_triggers_before_the_final_audit_insert(self):
        cases = (
            ("UPDATE ON accounts WHEN NEW.tenant = 'alpha' AND NEW.name = 'source'",
             "DELETE FROM transfers WHERE tenant = 'alpha' AND key = 'history';"),
            ("INSERT ON transfers",
             "UPDATE audit SET target = 'reserve' WHERE tenant = 'beta' AND key = 'history';"),
        )
        for event, action in cases:
            with self.subTest(event=event):
                self.assert_rejected(action, event)

    def test_cli_preservation_failures_are_atomic_and_historical_replay_is_unchanged(self):
        for action in (
            "DELETE FROM transfers WHERE tenant = 'alpha' AND key = 'history';",
            "UPDATE accounts SET balance = balance + 50 WHERE tenant = 'beta' AND name = 'source';",
            "UPDATE audit SET amount = 99 WHERE tenant = 'beta' AND key = 'history';",
        ):
            with self.subTest(action=action):
                self.assert_rejected(action, cli=True)

    def assert_success(self, path, before, cli=False):
        if cli:
            result = self.cli(path, **REQUEST)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stderr, "")
            self.assertEqual(len(result.stdout.splitlines()), 1)
            self.assertEqual(json.loads(result.stdout), REQUEST)
        else:
            self.assertEqual(vault.transfer(path, **REQUEST), REQUEST)
        expected = {table: rows.copy() for table, rows in before.items()}
        for name, old_balance, new_balance in (("source", 93, 83), ("target", 27, 37)):
            del expected["accounts"][("alpha", name, old_balance)]
            expected["accounts"][("alpha", name, new_balance)] += 1
            self.assertEqual(vault.balance(path, "alpha", name), new_balance)
        for table in ("transfers", "audit"):
            expected[table][tuple(REQUEST[column] for column in COLUMNS.split(", "))] += 1
        self.assertEqual(self.snapshot(path), expected)
        vault.init_db(path)
        self.assertEqual(vault.transfer(path, **REQUEST), REQUEST)
        replay = self.cli(path, **REQUEST)
        self.assertEqual(replay.returncode, 0, replay.stderr)
        self.assertEqual(replay.stderr, "")
        self.assertEqual(len(replay.stdout.splitlines()), 1)
        self.assertEqual(json.loads(replay.stdout), REQUEST)
        self.assertEqual(self.snapshot(path), expected)

    def test_audit_rowid_relocation_succeeds_and_replays(self):
        with self.database() as path:
            self.trigger(path, "UPDATE audit SET rowid = NEW.rowid + 1000 WHERE rowid = NEW.rowid;")
            self.assert_success(path, self.snapshot(path))
            with closing(sqlite3.connect(path)) as con:
                rowid = con.execute(
                    "SELECT rowid FROM audit WHERE tenant = 'alpha' AND key = 'payment'"
                ).fetchone()[0]
            self.assertGreater(rowid, 1000)

    def test_preexisting_matching_audits_and_duplicates_are_retained(self):
        with self.database() as path:
            with closing(sqlite3.connect(path)) as con, con:
                con.executemany(
                    "INSERT INTO audit VALUES (?, ?, ?, ?, ?)",
                    [tuple(REQUEST[column] for column in COLUMNS.split(", "))] * 2,
                )
            self.assert_success(path, self.snapshot(path))

    def test_noop_and_rowid_only_account_and_receipt_triggers_remain_valid(self):
        with self.database() as path:
            self.trigger(path,
                "UPDATE accounts SET balance = balance WHERE tenant = 'beta'; "
                "UPDATE accounts SET rowid = rowid + 1000 WHERE tenant = 'alpha' AND name = 'source'; "
                "UPDATE transfers SET rowid = rowid + 1000 WHERE tenant = 'beta' AND key = 'history';"
            )
            self.assert_success(path, self.snapshot(path))

    def test_conflict_ignored_inserts_succeed_through_api_and_cli(self):
        actions = (
            "INSERT OR IGNORE INTO accounts(tenant, name, balance) "
            "VALUES (NEW.tenant, NEW.target, 0);",
            "INSERT OR IGNORE INTO transfers VALUES ('beta', 'history', 'source', 'reserve', 99);",
            "INSERT INTO accounts VALUES (NEW.tenant, NEW.target, 0) "
            "ON CONFLICT(tenant, name) DO NOTHING;",
        )
        for action in actions:
            for cli in (False, True):
                with self.subTest(action=action, cli=cli), self.database() as path:
                    self.trigger(path, action)
                    self.assert_success(path, self.snapshot(path), cli=cli)

    def test_actual_inserts_and_replacements_still_roll_back_through_api_and_cli(self):
        actions = (
            "INSERT OR IGNORE INTO accounts VALUES ('alpha', 'unexpected', 50);",
            "INSERT OR IGNORE INTO transfers VALUES ('beta', 'unexpected', 'source', 'target', 1);",
            # REPLACE changes a stored row despite leaving cardinality unchanged.
            "INSERT OR REPLACE INTO accounts VALUES ('beta', 'reserve', 999);",
            "INSERT OR REPLACE INTO transfers VALUES ('beta', 'history', 'source', 'target', 99);",
        )
        for action in actions:
            for cli in (False, True):
                with self.subTest(action=action, cli=cli):
                    self.assert_rejected(action, cli=cli)


if __name__ == "__main__":
    unittest.main()
