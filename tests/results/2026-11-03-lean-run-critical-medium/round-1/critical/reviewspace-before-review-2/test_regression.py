"""Public-interface regression checks using real files, connections and CLI calls."""

from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import threading
import unittest

import vault


ROOT = Path(__file__).resolve().parent
TABLES = ("accounts", "transfers", "audit")


class DatabaseCase(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix=".vault-test-", dir=ROOT)
        self.addCleanup(self.temp.cleanup)
        self.serial = 0
        self.path = self.make_db()

    def make_db(self):
        self.serial += 1
        path = Path(self.temp.name) / f"{self.serial}.sqlite"
        vault.init_db(path)
        with closing(sqlite3.connect(path)) as con, con:
            con.executemany("INSERT INTO accounts VALUES (?,?,?)", [
                ("one", "a", 100), ("one", "b", 0), ("one", "spare", 40),
                ("two", "a", 700), ("two", "b", 30), ("two", "private", 456),
            ])
        return path

    def sql(self, statement, parameters=(), path=None):
        with closing(sqlite3.connect(path or self.path)) as con, con:
            return con.execute(statement, parameters).fetchall()

    def snapshot(self, path=None):
        with closing(sqlite3.connect(path or self.path)) as con:
            # Inspect all fixture rows, including invalid UTF-8 and duplicates.
            # This test oracle is deliberately broader than application reads.
            con.text_factory = bytes
            return {
                table: Counter(con.execute(f"SELECT * FROM {table}").fetchall())
                for table in TABLES
            }

    def perform(self, path=None, **changes):
        request = dict(tenant="one", source="a", target="b", amount=10, key="new")
        request.update(changes)
        return vault.transfer(path or self.path, **request)

    def seed_history(self, path):
        own = self.perform(path, source="spare", amount=3, key="old")
        other = self.perform(path, tenant="two", amount=7, key="old")
        return own, other

    def assert_history_replays(self, path, receipts):
        before = self.snapshot(path)
        vault.init_db(path)
        for receipt in receipts:
            self.assertEqual(vault.transfer(path, **receipt), receipt)
        self.assertEqual(self.snapshot(path), before)

    def cli(self, request, path=None):
        raw = request if isinstance(request, str) else json.dumps(request)
        return subprocess.run(
            [sys.executable, "-B", str(ROOT / "app.py"), str(path or self.path), raw],
            cwd=ROOT, capture_output=True, text=True, timeout=15,
        )

    def assert_cli_success(self, result, expected):
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stderr, "")
        self.assertEqual(len(result.stdout.splitlines()), 1)
        self.assertEqual(json.loads(result.stdout), expected)

    def assert_cli_failure(self, result):
        self.assertEqual(result.returncode, 2)
        self.assertEqual(result.stdout, "")
        self.assertEqual(len(result.stderr.splitlines()), 1)
        error = json.loads(result.stderr)
        self.assertIsInstance(error, dict)
        self.assertIsInstance(error.get("error"), str)
        self.assertNotIn("Traceback", result.stderr)
        return error


class ValidationAndIsolationTests(DatabaseCase):
    def test_balances_and_transfer_are_tenant_scoped(self):
        self.assertEqual(vault.balance(self.path, "one", "a"), 100)
        self.assertEqual(vault.balance(self.path, "two", "a"), 700)
        receipt = self.perform()
        self.assertEqual(receipt, dict(
            tenant="one", key="new", source="a", target="b", amount=10,
        ))
        self.assertEqual(self.sql("SELECT * FROM accounts ORDER BY tenant,name"), [
            ("one", "a", 90), ("one", "b", 10), ("one", "spare", 40),
            ("two", "a", 700), ("two", "b", 30), ("two", "private", 456),
        ])
        expected = [("one", "new", "a", "b", 10)]
        self.assertEqual(self.sql("SELECT * FROM transfers"), expected)
        self.assertEqual(self.sql("SELECT * FROM audit"), expected)

    def test_missing_and_inaccessible_accounts_have_identical_errors(self):
        messages = []
        before = self.snapshot()
        for account in ("missing", "private"):
            with self.assertRaises(ValueError) as caught:
                vault.balance(self.path, "one", account)
            messages.append(str(caught.exception))
            for endpoint in ("source", "target"):
                with self.assertRaises(ValueError) as caught:
                    self.perform(**{endpoint: account})
                messages.append(str(caught.exception))
        self.assertEqual(len(set(messages)), 1)
        self.assertNotIn("private", messages[0])
        self.assertNotIn("two", messages[0])
        self.assertEqual(self.snapshot(), before)

    def test_invalid_names_and_amounts_never_write(self):
        before = self.snapshot()
        bad_strings = ("", None, 1, 1.0, True, b"one", [], {})
        for field in ("tenant", "source", "target", "key"):
            for value in bad_strings:
                with self.subTest(field=field, value=value):
                    with self.assertRaises(ValueError):
                        self.perform(**{field: value})
                    self.assertEqual(self.snapshot(), before)
        for amount in (True, False, 0, -1, 1.0, float("nan"), "10", None, [], {}, 2**100):
            with self.subTest(amount=amount):
                with self.assertRaises(ValueError):
                    self.perform(amount=amount)
                self.assertEqual(self.snapshot(), before)
        for change in ({"target": "a"}, {"tenant": "absent"}, {"amount": 101}):
            with self.subTest(change=change):
                with self.assertRaises(ValueError):
                    self.perform(**change)
                self.assertEqual(self.snapshot(), before)

    def test_balance_validates_both_names(self):
        for bad in ("", None, 1, False, [], {}):
            for tenant, account in ((bad, "a"), ("one", bad)):
                with self.subTest(tenant=tenant, account=account):
                    with self.assertRaises(ValueError):
                        vault.balance(self.path, tenant, account)

    def test_full_spend_and_durable_exact_replay(self):
        receipt = self.perform(amount=100)
        self.assertEqual(vault.balance(self.path, "one", "a"), 0)
        self.assertEqual(vault.balance(self.path, "one", "b"), 100)
        self.assert_history_replays(self.path, [receipt])
        before = self.snapshot()
        with self.assertRaises(ValueError):
            self.perform(amount=1, key="another")
        self.assertEqual(self.snapshot(), before)

    def test_replay_payload_conflicts_and_keys_are_tenant_scoped(self):
        receipt = self.perform()
        before = self.snapshot()
        for change in ({"amount": 11}, {"source": "spare"}, {"target": "spare"}):
            with self.subTest(change=change):
                with self.assertRaises(ValueError):
                    self.perform(**change)
                self.assertEqual(self.snapshot(), before)
        other = self.perform(tenant="two", amount=23)
        self.assertEqual(other["tenant"], "two")
        self.assertEqual(other["amount"], 23)
        self.assertEqual(vault.balance(self.path, "two", "a"), 677)
        self.assert_history_replays(self.path, [receipt, other])

    def test_nonempty_names_are_literal_including_whitespace_and_sql(self):
        tenant = "租户' OR 1=1--"
        source, target, key = " ", "target\x00name", "'; DELETE FROM accounts; --"
        self.sql("INSERT INTO accounts VALUES (?,?,?)", (tenant, source, 12))
        self.sql("INSERT INTO accounts VALUES (?,?,?)", (tenant, target, 0))
        receipt = vault.transfer(self.path, tenant, source, target, 1, key)
        self.assertEqual(vault.balance(self.path, tenant, source), 11)
        self.assertEqual(vault.balance(self.path, tenant, target), 1)
        self.assertEqual(vault.balance(self.path, "one", "a"), 100)
        self.assert_history_replays(self.path, [receipt])

    def test_malformed_other_tenant_rows_do_not_affect_valid_work(self):
        self.sql("INSERT INTO accounts VALUES ('two',CAST(x'80' AS TEXT),'bad balance')")
        for table in ("transfers", "audit"):
            self.sql(f"INSERT INTO {table} VALUES "
                     "('two','new',CAST(x'80' AS TEXT),'b','bad amount')")
        before = self.snapshot()
        self.assertEqual(vault.balance(self.path, "one", "a"), 100)
        receipt = self.perform()
        self.assertEqual(receipt["tenant"], "one")
        after = self.snapshot()
        for table in TABLES:
            self.assertEqual(
                Counter({row: count for row, count in before[table].items() if row[0] == b"two"}),
                Counter({row: count for row, count in after[table].items() if row[0] == b"two"}),
            )

    def test_init_preserves_existing_schema_rows_and_triggers(self):
        self.seed_history(self.path)
        self.sql("CREATE TRIGGER preserved AFTER INSERT ON audit BEGIN SELECT 1; END")
        before = self.snapshot()
        schema = self.sql("SELECT type,name,tbl_name,sql FROM sqlite_master ORDER BY name")
        vault.init_db(self.path)
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(
            self.sql("SELECT type,name,tbl_name,sql FROM sqlite_master ORDER BY name"), schema,
        )

    def test_integer_storage_overflow_does_not_round_or_debit(self):
        self.sql("UPDATE accounts SET balance=? WHERE tenant='one' AND name='b'", (2**63 - 1,))
        before = self.snapshot()
        with self.assertRaises(sqlite3.Error):
            self.perform(amount=1)
        self.assertEqual(self.snapshot(), before)


class TransactionIntegrityTests(DatabaseCase):
    def test_failure_at_each_write_rolls_back_every_effect(self):
        stages = (
            "BEFORE UPDATE ON accounts WHEN NEW.tenant='one' AND NEW.name='a'",
            "BEFORE UPDATE ON accounts WHEN NEW.tenant='one' AND NEW.name='b'",
            "BEFORE INSERT ON transfers", "BEFORE INSERT ON audit",
        )
        for stage in stages:
            with self.subTest(stage=stage):
                path = self.make_db()
                history = self.seed_history(path)
                self.sql(f"CREATE TRIGGER failure {stage} BEGIN "
                         "SELECT RAISE(ABORT,'storage unavailable'); END", path=path)
                before = self.snapshot(path)
                with self.assertRaises(sqlite3.Error) as caught:
                    self.perform(path)
                self.assertIn("storage unavailable", str(caught.exception))
                self.assertEqual(self.snapshot(path), before)
                self.assert_history_replays(path, history)

    def test_all_sqlite_audit_failure_modes_roll_back(self):
        for mode in ("ABORT", "FAIL", "ROLLBACK"):
            with self.subTest(mode=mode):
                path = self.make_db()
                self.sql("CREATE TRIGGER failure BEFORE INSERT ON audit BEGIN "
                         f"SELECT RAISE({mode},'audit unavailable'); END", path=path)
                before = self.snapshot(path)
                with self.assertRaises(sqlite3.Error) as caught:
                    self.perform(path)
                self.assertIn("audit unavailable", str(caught.exception))
                self.assertEqual(self.snapshot(path), before)
                self.assertEqual(self.sql(
                    "SELECT name FROM sqlite_master WHERE type='trigger'", path=path,
                ), [("failure",)])

    def test_silently_ignored_required_writes_are_rejected(self):
        stages = (
            "BEFORE UPDATE ON accounts WHEN NEW.tenant='one' AND NEW.name='a'",
            "BEFORE UPDATE ON accounts WHEN NEW.tenant='one' AND NEW.name='b'",
            "BEFORE INSERT ON transfers", "BEFORE INSERT ON audit",
        )
        for stage in stages:
            with self.subTest(stage=stage):
                path = self.make_db()
                self.sql(f"CREATE TRIGGER ignore_write {stage} BEGIN "
                         "SELECT RAISE(IGNORE); END", path=path)
                before = self.snapshot(path)
                with self.assertRaises(sqlite3.Error):
                    self.perform(path)
                self.assertEqual(self.snapshot(path), before)

    def test_undone_debit_and_duplicate_audit_are_rejected(self):
        triggers = (
            "CREATE TRIGGER undo AFTER UPDATE ON accounts "
            "WHEN NEW.tenant='one' AND NEW.name='a' BEGIN "
            "UPDATE accounts SET balance=OLD.balance WHERE tenant=NEW.tenant AND name=NEW.name; END",
            "CREATE TRIGGER duplicate AFTER INSERT ON audit BEGIN "
            "INSERT INTO audit VALUES (NEW.tenant,NEW.key,NEW.source,NEW.target,NEW.amount); END",
        )
        for trigger in triggers:
            with self.subTest(trigger=trigger):
                path = self.make_db()
                self.sql(trigger, path=path)
                before = self.snapshot(path)
                with self.assertRaises(sqlite3.Error):
                    self.perform(path)
                self.assertEqual(self.snapshot(path), before)

    def test_unrelated_rows_and_history_cannot_be_changed_or_deleted(self):
        effects = (
            "UPDATE accounts SET balance=balance+1 WHERE tenant='one' AND name='spare';",
            "UPDATE accounts SET balance=balance+1 WHERE tenant='two' AND name='private';",
            "UPDATE transfers SET amount=amount+1 WHERE tenant='one' AND key='old';",
            "UPDATE transfers SET amount=amount+1 WHERE tenant='two' AND key='old';",
            "DELETE FROM transfers WHERE tenant='one' AND key='old';",
            "DELETE FROM audit WHERE tenant='two' AND key='old';",
            "DELETE FROM transfers WHERE tenant='one' AND key='old'; "
            "INSERT INTO transfers VALUES ('one','impostor','spare','b',3);",
            "DELETE FROM audit WHERE tenant='one' AND key='old'; "
            "INSERT INTO audit VALUES ('one','impostor','spare','b',3);",
            "UPDATE accounts SET tenant='two',name='stolen' WHERE tenant='one' AND name='spare';",
            "INSERT INTO accounts VALUES ('two','unexpected',1);",
        )
        for effect in effects:
            with self.subTest(effect=effect):
                path = self.make_db()
                history = self.seed_history(path)
                self.sql("CREATE TRIGGER corrupt AFTER INSERT ON audit "
                         f"WHEN NEW.key='new' BEGIN {effect} END", path=path)
                before = self.snapshot(path)
                with self.assertRaises(sqlite3.Error):
                    self.perform(path)
                self.assertEqual(self.snapshot(path), before)
                self.assert_history_replays(path, history)

    def test_replacement_rowid_collisions_cannot_erase_existing_rows(self):
        for victim_tenant in ("one", "two"):
            for table in TABLES:
                with self.subTest(table=table, victim_tenant=victim_tenant):
                    path = self.make_db()
                    history = self.seed_history(path)
                    if table == "accounts":
                        victim = "spare" if victim_tenant == "one" else "private"
                        selector, active, old = "name", "a", victim
                    else:
                        selector, active, old = "key", "new", "old"
                    self.sql(
                        "CREATE TRIGGER replace_row AFTER INSERT ON audit WHEN NEW.key='new' BEGIN "
                        f"UPDATE OR REPLACE {table} SET rowid=(SELECT rowid FROM {table} "
                        f"WHERE tenant='{victim_tenant}' AND {selector}='{old}') "
                        f"WHERE tenant='one' AND {selector}='{active}'; END", path=path,
                    )
                    before = self.snapshot(path)
                    with self.assertRaises(sqlite3.Error):
                        self.perform(path)
                    self.assertEqual(self.snapshot(path), before)
                    self.assert_history_replays(path, history)

    def test_insert_replace_cannot_steal_another_tenants_row(self):
        for table, columns, values, victim in (
            ("accounts", "tenant,name,balance", "'one','a',90", "name='private'"),
            ("transfers", "tenant,key,source,target,amount", "'one','new','a','b',10", "key='old'"),
            ("audit", "tenant,key,source,target,amount", "'one','new','a','b',10", "key='old'"),
        ):
            with self.subTest(table=table):
                path = self.make_db()
                history = self.seed_history(path)
                self.sql(
                    "CREATE TRIGGER replace_row AFTER INSERT ON audit WHEN NEW.key='new' BEGIN "
                    f"INSERT OR REPLACE INTO {table} (rowid,{columns}) "
                    f"SELECT rowid,{values} FROM {table} WHERE tenant='two' AND {victim}; END",
                    path=path,
                )
                before = self.snapshot(path)
                with self.assertRaises(sqlite3.Error):
                    self.perform(path)
                self.assertEqual(self.snapshot(path), before)
                self.assert_history_replays(path, history)

    def test_benign_noops_ignored_conflicts_and_rowid_moves_succeed(self):
        path = self.path
        history = self.seed_history(path)
        before = self.snapshot(path)
        self.sql("""
            CREATE TRIGGER benign AFTER INSERT ON audit WHEN NEW.key='new' BEGIN
                UPDATE accounts SET balance=balance;
                UPDATE transfers SET amount=amount;
                UPDATE audit SET amount=amount;
                INSERT OR IGNORE INTO accounts VALUES ('two','private',999);
                INSERT OR IGNORE INTO transfers VALUES ('two','old','bad','bad',999);
                UPDATE OR IGNORE accounts SET name='a' WHERE tenant='two' AND name='private';
                UPDATE OR IGNORE transfers SET key='new' WHERE tenant='one' AND key='old';
                UPDATE OR IGNORE audit SET rowid=(SELECT rowid FROM audit WHERE tenant='two' AND key='old')
                    WHERE tenant='one' AND key='new';
                UPDATE accounts SET rowid=rowid+1000 WHERE tenant='two' AND name='private';
                UPDATE transfers SET rowid=rowid+1000 WHERE tenant='one' AND key='old';
                UPDATE audit SET rowid=rowid+1000 WHERE tenant='two' AND key='old';
                INSERT OR REPLACE INTO accounts VALUES ('one','spare',37);
                INSERT OR REPLACE INTO transfers VALUES ('one','old','spare','b',3);
                INSERT OR REPLACE INTO audit (rowid,tenant,key,source,target,amount)
                    SELECT rowid,tenant,key,source,target,amount FROM audit WHERE tenant='one' AND key='old';
            END
        """)
        receipt = self.perform(path)
        self.assertEqual(vault.balance(path, "one", "a"), 90)
        self.assertEqual(vault.balance(path, "one", "b"), 13)
        after = self.snapshot(path)
        for table in TABLES:
            self.assertEqual(
                Counter({row: count for row, count in before[table].items() if row[0] == b"two"}),
                Counter({row: count for row, count in after[table].items() if row[0] == b"two"}),
            )
        self.assert_history_replays(path, [*history, receipt])

    def test_benign_self_update_trigger_keeps_sqlite_recursion_behavior(self):
        self.sql("""
            CREATE TRIGGER normalize AFTER UPDATE ON accounts BEGIN
                UPDATE accounts SET balance=balance WHERE tenant=NEW.tenant AND name=NEW.name;
            END
        """)
        self.perform()
        self.assertEqual(vault.balance(self.path, "one", "a"), 90)
        self.assertEqual(vault.balance(self.path, "one", "b"), 10)

    def test_existing_duplicate_audit_multiplicity_is_preserved(self):
        history = self.seed_history(self.path)
        self.sql("INSERT INTO audit SELECT * FROM audit WHERE tenant='one' AND key='old'")
        self.perform()
        self.assertEqual(self.sql(
            "SELECT count(*) FROM audit WHERE tenant='one' AND key='old'",
        ), [(2,)])
        self.assert_history_replays(self.path, history)


class ConcurrencyTests(DatabaseCase):
    def race(self, path, requests):
        barrier = threading.Barrier(len(requests))

        def worker(request):
            barrier.wait(timeout=10)
            try:
                return self.perform(path, **request)
            except ValueError:
                return None

        with ThreadPoolExecutor(max_workers=len(requests)) as pool:
            futures = [pool.submit(worker, request) for request in requests]
            return [future.result(timeout=30) for future in futures]

    def test_simultaneous_duplicates_execute_once_in_both_journal_modes(self):
        for mode in ("DELETE", "WAL"):
            with self.subTest(mode=mode):
                path = self.make_db()
                self.sql(f"PRAGMA journal_mode={mode}", path=path)
                receipts = self.race(path, [{} for _ in range(8)])
                self.assertTrue(all(receipt == receipts[0] for receipt in receipts))
                self.assertIsNotNone(receipts[0])
                self.assertEqual(vault.balance(path, "one", "a"), 90)
                self.assertEqual(vault.balance(path, "one", "b"), 10)
                for table in ("transfers", "audit"):
                    self.assertEqual(self.sql(f"SELECT count(*) FROM {table}", path=path), [(1,)])
                self.assert_history_replays(path, [receipts[0]])

    def test_distinct_keys_never_overspend_in_both_journal_modes(self):
        for mode in ("DELETE", "WAL"):
            with self.subTest(mode=mode):
                path = self.make_db()
                self.sql(f"PRAGMA journal_mode={mode}", path=path)
                results = self.race(path, [dict(amount=30, key=f"k{i}") for i in range(8)])
                receipts = [result for result in results if result is not None]
                self.assertEqual(len(receipts), 3)
                self.assertEqual(vault.balance(path, "one", "a"), 10)
                self.assertEqual(vault.balance(path, "one", "b"), 90)
                for table in ("transfers", "audit"):
                    self.assertEqual(self.sql(f"SELECT count(*) FROM {table}", path=path), [(3,)])
                self.assert_history_replays(path, receipts)

    def test_concurrent_sources_do_not_lose_shared_target_credits(self):
        requests = [dict(source="a", amount=10, key=f"a{i}") for i in range(4)]
        requests += [dict(source="spare", amount=5, key=f"s{i}") for i in range(4)]
        receipts = self.race(self.path, requests)
        self.assertNotIn(None, receipts)
        self.assertEqual(vault.balance(self.path, "one", "a"), 60)
        self.assertEqual(vault.balance(self.path, "one", "spare"), 20)
        self.assertEqual(vault.balance(self.path, "one", "b"), 60)
        self.assert_history_replays(self.path, receipts)

    def test_conflicting_same_key_race_has_one_winner(self):
        results = self.race(self.path, [dict(amount=10), dict(amount=20)])
        receipts = [result for result in results if result is not None]
        self.assertEqual(len(receipts), 1)
        amount = receipts[0]["amount"]
        self.assertEqual(vault.balance(self.path, "one", "a"), 100 - amount)
        self.assertEqual(vault.balance(self.path, "one", "b"), amount)
        self.assertEqual(self.sql("SELECT count(*) FROM audit"), [(1,)])
        self.assert_history_replays(self.path, receipts)


class CliJourneyTests(DatabaseCase):
    def test_integrated_cli_journey_failure_recovery_and_durable_replay(self):
        request = dict(op="transfer", tenant="one", source="a", target="b", amount=20, key="journey")
        receipt = {key: value for key, value in request.items() if key != "op"}
        self.assert_cli_success(self.cli(dict(op="balance", tenant="one", account="a")), 100)
        self.assert_cli_success(self.cli(request), receipt)
        self.assert_cli_success(self.cli(dict(op="balance", tenant="one", account="a")), 80)
        before = self.snapshot()
        self.assert_cli_success(self.cli(request), receipt)
        self.assertEqual(self.snapshot(), before)
        generic = self.assert_cli_failure(self.cli({**request, "amount": 21}))
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(self.assert_cli_failure(self.cli({**request, "key": "large", "amount": 81})), generic)
        self.assertEqual(self.snapshot(), before)
        for account in ("private", "missing"):
            self.assertEqual(self.assert_cli_failure(self.cli(
                dict(op="balance", tenant="one", account=account),
            )), generic)
        other = {**request, "tenant": "two", "amount": 7}
        other_receipt = {key: value for key, value in other.items() if key != "op"}
        self.assert_cli_success(self.cli(other), other_receipt)

        self.sql("CREATE TABLE audit_availability (enabled INTEGER)")
        self.sql("INSERT INTO audit_availability VALUES (0)")
        self.sql("""
            CREATE TRIGGER unavailable BEFORE INSERT ON audit
            WHEN (SELECT enabled FROM audit_availability)=0 BEGIN
                SELECT RAISE(ABORT,'SELECT private details FROM tenant_two');
            END
        """)
        recovery = {**request, "amount": 3, "key": "recovery"}
        before = self.snapshot()
        self.assertEqual(self.assert_cli_failure(self.cli(recovery)), generic)
        self.assertEqual(self.snapshot(), before)
        # Restore the simulated storage dependency without removing its trigger.
        self.sql("UPDATE audit_availability SET enabled=1")
        recovery_receipt = {key: value for key, value in recovery.items() if key != "op"}
        self.assert_cli_success(self.cli(recovery), recovery_receipt)
        self.assert_history_replays(self.path, [receipt, other_receipt, recovery_receipt])
        self.assertEqual(self.sql("SELECT count(*) FROM audit"), [(3,)])
        self.assertEqual(vault.balance(self.path, "one", "a"), 77)
        self.assertEqual(vault.balance(self.path, "two", "a"), 693)

    def test_malformed_cli_inputs_share_one_generic_error_without_writes(self):
        before = self.snapshot()
        inputs = [
            "{bad json", "[]", "null", "1", '"balance"', "{}",
            '{"op":"balance","op":"transfer"}',
            {"op": "init_db"}, {"op": "__dict__"}, {"op": []},
            {"op": "balance", "tenant": "one"},
            {"op": "balance", "tenant": "one", "account": "a", "extra": 1},
            {"op": "balance", "tenant": None, "account": "a"},
            {"op": "transfer", "tenant": "one", "source": "a", "target": "b", "key": "k"},
        ]
        for amount in (True, 0, -1, 1.0, "10", None, float("nan"), float("inf")):
            inputs.append(dict(op="transfer", tenant="one", source="a", target="b", amount=amount, key="k"))
        errors = []
        for request in inputs:
            with self.subTest(request=request):
                errors.append(self.assert_cli_failure(self.cli(request)))
                self.assertEqual(self.snapshot(), before)
        self.assertTrue(all(error == errors[0] for error in errors))

    def test_cli_argument_count_errors_are_generic(self):
        for args in ([], [str(self.path)], [str(self.path), "{}", "extra"]):
            with self.subTest(args=args):
                result = subprocess.run(
                    [sys.executable, "-B", str(ROOT / "app.py"), *args],
                    cwd=ROOT, capture_output=True, text=True, timeout=15,
                )
                self.assert_cli_failure(result)


if __name__ == "__main__":
    unittest.main()
