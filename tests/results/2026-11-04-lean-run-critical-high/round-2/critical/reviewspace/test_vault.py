import json
import sqlite3
import subprocess
import sys
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from pathlib import Path

import vault


ROOT = Path(__file__).resolve().parent


class VaultTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(dir=ROOT)
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "vault.sqlite"
        vault.init_db(self.path)
        with closing(sqlite3.connect(self.path)) as con, con:
            con.executemany(
                "INSERT INTO accounts VALUES (?, ?, ?)",
                [
                    ("red", "a", 100),
                    ("red", "b", 0),
                    ("blue", "a", 700),
                    ("blue", "b", 50),
                    ("blue", "private", 80),
                ],
            )

    def snapshot(self):
        # Compare logical rows (including audit multiplicity) across fresh
        # connections, so transaction-local observations cannot hide a commit.
        with closing(sqlite3.connect(self.path)) as con:
            return {
                "accounts": con.execute(
                    "SELECT tenant, name, balance FROM accounts ORDER BY tenant, name"
                ).fetchall(),
                "transfers": con.execute(
                    'SELECT tenant, key, source, target, amount FROM transfers '
                    'ORDER BY tenant, key'
                ).fetchall(),
                "audit": con.execute(
                    'SELECT tenant, key, source, target, amount FROM audit '
                    'ORDER BY tenant, key, source, target, amount'
                ).fetchall(),
            }

    def cli(self, request):
        return self.cli_args(str(self.path), json.dumps(request))

    def cli_args(self, *args):
        return subprocess.run(
            [sys.executable, "-B", str(ROOT / "app.py"), *args],
            text=True,
            capture_output=True,
            cwd=ROOT,
            timeout=10,
        )

    def assert_cli_error(self, result):
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertEqual(result.stdout, "")
        self.assertEqual(len(result.stderr.splitlines()), 1)
        self.assertEqual(json.loads(result.stderr), {"error": "invalid request"})

    def assert_cli_result(self, request, expected):
        result = self.cli(request)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stderr, "")
        self.assertEqual(len(result.stdout.splitlines()), 1)
        self.assertEqual(json.loads(result.stdout), expected)

    def concurrent_transfers(self, requests):
        start = threading.Barrier(len(requests))

        def send(request):
            start.wait(timeout=10)
            try:
                # Each public call opens its own connection to the same file.
                return vault.transfer(self.path, **request)
            except ValueError as error:
                return error

        with ThreadPoolExecutor(max_workers=len(requests)) as pool:
            futures = [pool.submit(send, request) for request in requests]
            return [future.result(timeout=15) for future in futures]

    def test_balance_is_scoped_to_tenant(self):
        self.assertEqual(vault.balance(self.path, "blue", "a"), 700)

    def test_transfer_changes_only_its_two_accounts(self):
        before = self.snapshot()
        receipt = vault.transfer(self.path, "red", "a", "b", 25, "k")
        after = self.snapshot()
        self.assertEqual(receipt, dict(tenant="red", key="k", source="a", target="b", amount=25))
        self.assertEqual(vault.balance(self.path, "red", "a"), 75)
        self.assertEqual(vault.balance(self.path, "red", "b"), 25)
        self.assertEqual(
            [row for row in after["accounts"] if row[0] == "blue"],
            [row for row in before["accounts"] if row[0] == "blue"],
        )
        self.assertEqual(after["transfers"], [("red", "k", "a", "b", 25)])
        self.assertEqual(after["audit"], after["transfers"])

    def test_same_key_is_independent_for_each_tenant(self):
        vault.transfer(self.path, "red", "a", "b", 20, "shared")
        receipt = vault.transfer(self.path, "blue", "a", "b", 30, "shared")
        self.assertEqual(receipt, dict(tenant="blue", key="shared", source="a", target="b", amount=30))
        self.assertEqual(len(self.snapshot()["audit"]), 2)

    def test_conflicting_replay_has_no_writes(self):
        vault.transfer(self.path, "red", "a", "b", 20, "shared")
        before = self.snapshot()
        with self.assertRaises(ValueError):
            vault.transfer(self.path, "red", "a", "b", 21, "shared")
        self.assertEqual(self.snapshot(), before)

    def test_missing_and_inaccessible_accounts_are_generic(self):
        errors = []
        before = self.snapshot()
        for name in ("absent", "private"):
            with self.subTest(account=name):
                with self.assertRaises(ValueError) as caught:
                    vault.balance(self.path, "red", name)
                errors.append(str(caught.exception))
        self.assertEqual(len(errors), 2)
        self.assertEqual(errors[0], errors[1])
        self.assertTrue(errors[0])
        for sensitive in ("private", "absent", "blue", "red", "80"):
            self.assertNotIn(sensitive, errors[0])
        self.assertEqual(self.snapshot(), before)

    def test_negative_amount_has_no_writes(self):
        before = self.snapshot()
        with self.assertRaises(ValueError):
            vault.transfer(self.path, "red", "a", "b", -10, "negative")
        self.assertEqual(self.snapshot(), before)

    def test_audit_failure_rolls_back_all_four_effects(self):
        with closing(sqlite3.connect(self.path)) as con, con:
            con.execute("""
                CREATE TRIGGER fail_audit BEFORE INSERT ON audit
                BEGIN SELECT RAISE(ABORT, 'synthetic audit failure'); END
            """)
        before = self.snapshot()
        with self.assertRaises(sqlite3.DatabaseError):
            vault.transfer(self.path, "red", "a", "b", 10, "failed")
        self.assertEqual(self.snapshot(), before)

    def test_cli_invalid_call_is_generic_json(self):
        result = self.cli({"op": "balance", "tenant": "red", "account": "absent"})
        self.assert_cli_error(result)

    def test_invalid_identifiers_do_not_write(self):
        before = self.snapshot()
        bad_names = ("", None, False, 1, 1.5, b"red", [], {})
        for name in bad_names:
            for field in ("tenant", "source", "target", "key"):
                with self.subTest(field=field, value=name):
                    request = dict(tenant="red", source="a", target="b", amount=1, key="k")
                    request[field] = name
                    with self.assertRaises(ValueError):
                        vault.transfer(self.path, **request)
                    self.assertEqual(self.snapshot(), before)
            for field in ("tenant", "account"):
                with self.subTest(balance_field=field, value=name):
                    request = dict(tenant="red", account="a")
                    request[field] = name
                    with self.assertRaises(ValueError):
                        vault.balance(self.path, **request)
                    self.assertEqual(self.snapshot(), before)

    def test_invalid_amounts_do_not_write_even_on_replay(self):
        vault.transfer(self.path, "red", "a", "b", 1, "used")
        before = self.snapshot()
        amounts = (None, False, True, 0, -1, 1.0, "1", b"1", [], {}, float("inf"), float("nan"))
        for amount in amounts:
            for key in ("new", "used"):
                with self.subTest(amount=amount, key=key):
                    with self.assertRaises(ValueError):
                        vault.transfer(self.path, "red", "a", "b", amount, key)
                    self.assertEqual(self.snapshot(), before)

    def test_self_transfer_is_rejected(self):
        before = self.snapshot()
        with self.assertRaises(ValueError):
            vault.transfer(self.path, "red", "a", "a", 1, "same")
        self.assertEqual(self.snapshot(), before)

    def test_both_transfer_endpoints_require_tenant_ownership(self):
        before = self.snapshot()
        errors = []
        for source, target in (("absent", "b"), ("private", "b"), ("a", "absent"), ("a", "private")):
            with self.subTest(source=source, target=target):
                with self.assertRaises(ValueError) as caught:
                    vault.transfer(self.path, "red", source, target, 1, "inaccessible")
                errors.append(str(caught.exception))
                self.assertEqual(self.snapshot(), before)
        with self.assertRaises(ValueError) as caught:
            vault.transfer(self.path, "unknown", "a", "b", 1, "inaccessible")
        errors.append(str(caught.exception))
        with self.assertRaises(ValueError) as caught:
            vault.balance(self.path, "red", "private")
        errors.append(str(caught.exception))
        self.assertEqual(len(set(errors)), 1)
        self.assertEqual(self.snapshot(), before)

    def test_exact_replay_is_durable_and_returns_an_independent_receipt(self):
        expected = dict(tenant="red", key="replay", source="a", target="b", amount=80)
        receipt = vault.transfer(self.path, "red", "a", "b", 80, "replay")
        self.assertEqual(receipt, expected)
        before = self.snapshot()
        receipt["tenant"] = "blue"
        receipt["amount"] = 1
        vault.init_db(self.path)
        # The remaining balance is too small for a new transfer of 80, but an
        # exact replay must still succeed after all prior connections closed.
        replay = vault.transfer(self.path, "red", "a", "b", 80, "replay")
        self.assertEqual(replay, expected)
        self.assertIsNot(receipt, replay)
        self.assertEqual(self.snapshot(), before)

    def test_each_payload_field_participates_in_key_conflicts(self):
        vault.transfer(self.path, "red", "a", "b", 20, "used")
        with closing(sqlite3.connect(self.path)) as con, con:
            con.execute("INSERT INTO accounts VALUES ('red', 'c', 100)")
        before = self.snapshot()
        for source, target, amount in (("c", "b", 20), ("a", "c", 20), ("a", "b", 21)):
            with self.subTest(source=source, target=target, amount=amount):
                with self.assertRaises(ValueError):
                    vault.transfer(self.path, "red", source, target, amount, "used")
                self.assertEqual(self.snapshot(), before)

    def test_insufficient_funds_and_integer_boundaries(self):
        for amount in (101, 2**100):
            with self.subTest(amount=amount):
                before = self.snapshot()
                with self.assertRaises(ValueError):
                    vault.transfer(self.path, "red", "a", "b", amount, "too-much")
                self.assertEqual(self.snapshot(), before)
        vault.transfer(self.path, "red", "a", "b", 1, "one")
        vault.transfer(self.path, "red", "a", "b", 99, "rest")
        self.assertEqual(vault.balance(self.path, "red", "a"), 0)
        self.assertEqual(vault.balance(self.path, "red", "b"), 100)
        before = self.snapshot()
        with self.assertRaises(ValueError):
            vault.transfer(self.path, "red", "a", "b", 1, "empty")
        self.assertEqual(self.snapshot(), before)

    def test_large_integer_transfer_remains_exact(self):
        limit = 2**63 - 1
        with closing(sqlite3.connect(self.path)) as con, con:
            con.execute("UPDATE accounts SET balance=? WHERE tenant='red' AND name='a'", (limit,))
        receipt = vault.transfer(self.path, "red", "a", "b", limit, "large")
        self.assertEqual(receipt["amount"], limit)
        self.assertEqual(vault.balance(self.path, "red", "a"), 0)
        self.assertEqual(vault.balance(self.path, "red", "b"), limit)
        self.assertIs(type(vault.balance(self.path, "red", "b")), int)

    def test_integer_storage_overflow_rolls_back_debit(self):
        with closing(sqlite3.connect(self.path)) as con, con:
            con.execute("UPDATE accounts SET balance=? WHERE tenant='red' AND name='b'", (2**63 - 1,))
        before = self.snapshot()
        with self.assertRaises(OverflowError):
            vault.transfer(self.path, "red", "a", "b", 1, "overflow")
        self.assertEqual(self.snapshot(), before)

    def test_identifiers_are_literal_nonempty_strings(self):
        tenant = "tenant' OR 1=1 --"
        source, target, key = "账户'); DROP TABLE accounts; --", " ", "clé\x00'"
        with closing(sqlite3.connect(self.path)) as con, con:
            con.executemany(
                "INSERT INTO accounts VALUES (?, ?, ?)",
                [(tenant, source, 5), (tenant, target, 0)],
            )
        before = self.snapshot()
        receipt = vault.transfer(self.path, tenant, source, target, 5, key)
        self.assertEqual(receipt, dict(tenant=tenant, key=key, source=source, target=target, amount=5))
        self.assertEqual(vault.balance(self.path, tenant, source), 0)
        self.assertEqual(vault.balance(self.path, tenant, target), 5)
        self.assertEqual(
            [row for row in self.snapshot()["accounts"] if row[0] != tenant],
            [row for row in before["accounts"] if row[0] != tenant],
        )

    def test_malformed_foreign_rows_do_not_affect_authorized_requests(self):
        with closing(sqlite3.connect(self.path)) as con, con:
            con.execute("UPDATE accounts SET balance=NULL WHERE tenant='blue'")
            con.execute(
                "INSERT INTO transfers VALUES (?, ?, ?, ?, ?)",
                ("blue", "legacy", b"foreign private data", None, "malformed"),
            )
            con.executemany(
                "INSERT INTO audit VALUES (?, ?, ?, ?, ?)",
                [("blue", "legacy", None, None, None)] * 2,
            )
        before = self.snapshot()
        self.assertEqual(vault.balance(self.path, "red", "a"), 100)
        self.assertEqual(
            vault.transfer(self.path, "red", "a", "b", 5, "legacy"),
            dict(tenant="red", key="legacy", source="a", target="b", amount=5),
        )
        after = self.snapshot()
        for table in before:
            self.assertEqual(
                [row for row in after[table] if row[0] == "blue"],
                [row for row in before[table] if row[0] == "blue"],
            )

    def test_init_preserves_existing_rows_schema_indexes_and_triggers(self):
        vault.transfer(self.path, "red", "a", "b", 5, "history")
        with closing(sqlite3.connect(self.path)) as con, con:
            con.execute("INSERT INTO audit SELECT * FROM audit")
            con.execute("CREATE INDEX audit_keys ON audit (tenant, key)")
            con.execute("""
                CREATE TRIGGER keep_audit BEFORE INSERT ON audit
                WHEN NEW.key = 'blocked'
                BEGIN SELECT RAISE(ABORT, 'synthetic failure'); END
            """)
            schema = con.execute("SELECT type, name, tbl_name, sql FROM sqlite_master ORDER BY name").fetchall()
        before = self.snapshot()
        vault.init_db(self.path)
        vault.init_db(self.path)
        self.assertEqual(self.snapshot(), before)
        with closing(sqlite3.connect(self.path)) as con:
            self.assertEqual(
                con.execute("SELECT type, name, tbl_name, sql FROM sqlite_master ORDER BY name").fetchall(),
                schema,
            )
        vault.transfer(self.path, "red", "a", "b", 2, "new")
        after = self.snapshot()
        for table in ("transfers", "audit"):
            self.assertEqual([row for row in after[table] if row[1] == "history"], before[table])

    def test_credit_storage_failure_rolls_back_debit(self):
        with closing(sqlite3.connect(self.path)) as con, con:
            con.execute("""
                CREATE TRIGGER fail_credit BEFORE UPDATE ON accounts
                WHEN NEW.tenant = 'red' AND NEW.name = 'b'
                BEGIN SELECT RAISE(FAIL, 'credit storage failure'); END
            """)
        before = self.snapshot()
        with self.assertRaises(sqlite3.IntegrityError):
            vault.transfer(self.path, "red", "a", "b", 10, "failed")
        self.assertEqual(self.snapshot(), before)

    def test_receipt_storage_failure_rolls_back_balances(self):
        with closing(sqlite3.connect(self.path)) as con, con:
            con.execute("""
                CREATE TRIGGER fail_receipt BEFORE INSERT ON transfers
                BEGIN SELECT RAISE(ABORT, 'receipt storage failure'); END
            """)
        before = self.snapshot()
        with self.assertRaises(sqlite3.IntegrityError):
            vault.transfer(self.path, "red", "a", "b", 10, "failed")
        self.assertEqual(self.snapshot(), before)

    def test_failure_after_audit_insertion_rolls_back_and_preserves_history(self):
        vault.transfer(self.path, "red", "a", "b", 10, "history")
        with closing(sqlite3.connect(self.path)) as con, con:
            con.execute("""
                CREATE TRIGGER fail_after_audit AFTER INSERT ON audit
                BEGIN SELECT RAISE(FAIL, 'failure after audit insert'); END
            """)
        before = self.snapshot()
        with self.assertRaises(sqlite3.IntegrityError):
            vault.transfer(self.path, "red", "a", "b", 10, "failed")
        vault.init_db(self.path)
        self.assertEqual(self.snapshot(), before)
        # Replay must not attempt another audit insert, even with this trigger.
        vault.transfer(self.path, "red", "a", "b", 10, "history")
        self.assertEqual(self.snapshot(), before)

    def test_failed_key_can_be_retried_while_audit_trigger_is_retained(self):
        with closing(sqlite3.connect(self.path)) as con, con:
            con.execute("""
                CREATE TRIGGER conditional_failure BEFORE INSERT ON audit
                WHEN NEW.amount = 10
                BEGIN SELECT RAISE(ROLLBACK, 'synthetic audit failure'); END
            """)
            trigger = con.execute("SELECT sql FROM sqlite_master WHERE name='conditional_failure'").fetchone()
        before = self.snapshot()
        with self.assertRaises(sqlite3.IntegrityError):
            vault.transfer(self.path, "red", "a", "b", 10, "retry")
        self.assertEqual(self.snapshot(), before)
        receipt = vault.transfer(self.path, "red", "a", "b", 11, "retry")
        self.assertEqual(receipt["amount"], 11)
        self.assertEqual(vault.balance(self.path, "red", "a"), 89)
        self.assertEqual(vault.balance(self.path, "red", "b"), 11)
        after = self.snapshot()
        self.assertEqual(after["transfers"], [("red", "retry", "a", "b", 11)])
        self.assertEqual(after["audit"], after["transfers"])
        with closing(sqlite3.connect(self.path)) as con:
            self.assertEqual(
                con.execute("SELECT sql FROM sqlite_master WHERE name='conditional_failure'").fetchone(), trigger
            )

    def test_concurrent_duplicate_requests_execute_once_and_replay_after_reopen(self):
        request = dict(tenant="red", source="a", target="b", amount=80, key="once")
        results = self.concurrent_transfers([request] * 8)
        self.assertEqual(results, [request] * 8)
        self.assertEqual(vault.balance(self.path, "red", "a"), 20)
        self.assertEqual(vault.balance(self.path, "red", "b"), 80)
        before = self.snapshot()
        self.assertEqual(before["transfers"], [("red", "once", "a", "b", 80)])
        self.assertEqual(before["audit"], before["transfers"])
        vault.init_db(self.path)
        self.assertEqual(vault.transfer(self.path, **request), request)
        self.assertEqual(self.snapshot(), before)

    def test_concurrent_conflicting_key_has_one_winning_payload(self):
        requests = [dict(tenant="red", source="a", target="b", amount=amount, key="race") for amount in (10, 20) * 4]
        results = self.concurrent_transfers(requests)
        receipts = [result for result in results if isinstance(result, dict)]
        self.assertEqual(len(receipts), 4)
        self.assertEqual(len([result for result in results if isinstance(result, ValueError)]), 4)
        self.assertEqual(receipts, [receipts[0]] * 4)
        winning_amount = receipts[0]["amount"]
        self.assertEqual(vault.balance(self.path, "red", "a"), 100 - winning_amount)
        self.assertEqual(vault.balance(self.path, "red", "b"), winning_amount)
        state = self.snapshot()
        self.assertEqual(state["transfers"], [("red", "race", "a", "b", winning_amount)])
        self.assertEqual(state["audit"], state["transfers"])

    def test_concurrent_distinct_keys_never_overspend(self):
        requests = [dict(tenant="red", source="a", target="b", amount=30, key=f"spend-{i}") for i in range(8)]
        results = self.concurrent_transfers(requests)
        receipts = [result for result in results if isinstance(result, dict)]
        self.assertEqual(len(receipts), 3)
        self.assertEqual(len([result for result in results if isinstance(result, ValueError)]), 5)
        self.assertEqual(vault.balance(self.path, "red", "a"), 10)
        self.assertEqual(vault.balance(self.path, "red", "b"), 90)
        state = self.snapshot()
        self.assertEqual(
            state["transfers"],
            sorted(("red", result["key"], "a", "b", 30) for result in receipts),
        )
        self.assertEqual(state["audit"], state["transfers"])

    def test_concurrent_credits_from_distinct_sources_are_not_lost(self):
        with closing(sqlite3.connect(self.path)) as con, con:
            con.executemany("INSERT INTO accounts VALUES ('red', ?, 100)", [(f"source-{i}",) for i in range(8)])
        requests = [dict(tenant="red", source=f"source-{i}", target="b", amount=10, key=f"credit-{i}") for i in range(8)]
        results = self.concurrent_transfers(requests)
        self.assertEqual(results, requests)
        self.assertEqual(vault.balance(self.path, "red", "b"), 80)
        for request in requests:
            self.assertEqual(vault.balance(self.path, "red", request["source"]), 90)
        state = self.snapshot()
        self.assertEqual(len(state["transfers"]), 8)
        self.assertEqual(state["audit"], state["transfers"])

    def test_cli_rejects_malformed_requests_without_writes(self):
        before = self.snapshot()
        requests = [
            None, [], True, "balance", 42, {},
            {"op": "init_db"}, {"op": "__dict__"}, {"op": "unknown"}, {"op": []},
            {"op": "balance", "tenant": "red"},
            {"op": "balance", "tenant": "red", "account": "a", "extra": 1},
            {"op": "balance", "tenant": None, "account": "a"},
            {"op": "transfer", "tenant": "red", "source": "a", "target": "b", "amount": 1},
        ]
        for amount in (True, 0, -1, 1.5, "1", float("nan"), float("inf")):
            requests.append(dict(op="transfer", tenant="red", source="a", target="b", amount=amount, key="bad"))
        for request in requests:
            with self.subTest(request=request):
                self.assert_cli_error(self.cli(request))
                self.assertEqual(self.snapshot(), before)
        raw_inputs = [
            "{", "{} {}", "[" * 1100 + "]" * 1100,
            '{"op":"transfer","tenant":"red","tenant":"blue","source":"a","target":"b","amount":1,"key":"duplicate"}',
        ]
        for raw in raw_inputs:
            with self.subTest(raw=raw[:100]):
                self.assert_cli_error(self.cli_args(str(self.path), raw))
                self.assertEqual(self.snapshot(), before)
        for args in ((), (str(self.path),), (str(self.path), "{}", "extra")):
            with self.subTest(args=args):
                self.assert_cli_error(self.cli_args(*args))
                self.assertEqual(self.snapshot(), before)

    def test_cli_integrated_transfer_failure_and_recovery_journey(self):
        self.assert_cli_result(dict(op="balance", tenant="red", account="a"), 100)
        receipt = dict(tenant="red", source="a", target="b", amount=80, key="journey")
        self.assert_cli_result(dict(op="transfer", **receipt), receipt)
        self.assert_cli_result(dict(op="balance", tenant="red", account="a"), 20)
        self.assert_cli_result(dict(op="balance", tenant="red", account="b"), 80)
        before = self.snapshot()
        # Each invocation is a fresh process: replay cannot depend on memory.
        self.assert_cli_result(dict(op="transfer", **receipt), receipt)
        self.assertEqual(self.snapshot(), before)
        rejected = [
            dict(receipt, amount=1),
            dict(receipt, amount=21, key="insufficient"),
            dict(receipt, source="private", amount=1, key="inaccessible-source"),
            dict(receipt, target="private", amount=1, key="inaccessible-target"),
        ]
        for request in rejected:
            self.assert_cli_error(self.cli(dict(op="transfer", **request)))
            self.assertEqual(self.snapshot(), before)
        blue = dict(receipt, tenant="blue", amount=90)
        self.assert_cli_result(dict(op="transfer", **blue), blue)
        self.assert_cli_result(dict(op="balance", tenant="blue", account="a"), 610)
        self.assert_cli_result(dict(op="balance", tenant="blue", account="b"), 140)
        with closing(sqlite3.connect(self.path)) as con, con:
            con.execute("""
                CREATE TRIGGER cli_audit_failure BEFORE INSERT ON audit
                WHEN NEW.key = 'blocked'
                BEGIN SELECT RAISE(ABORT, 'SELECT secret FROM blue_private'); END
            """)
        before = self.snapshot()
        self.assert_cli_error(self.cli(dict(op="transfer", **dict(receipt, amount=5, key="blocked"))))
        self.assertEqual(self.snapshot(), before)
        recovered = dict(receipt, amount=5, key="recovered")
        self.assert_cli_result(dict(op="transfer", **recovered), recovered)
        self.assert_cli_result(dict(op="balance", tenant="red", account="a"), 15)
        self.assert_cli_result(dict(op="balance", tenant="red", account="b"), 85)
        state = self.snapshot()
        self.assertEqual(len(state["transfers"]), 3)
        self.assertEqual(state["audit"], state["transfers"])
        with closing(sqlite3.connect(self.path)) as con:
            self.assertIsNotNone(con.execute("SELECT sql FROM sqlite_master WHERE name='cli_audit_failure'").fetchone())


if __name__ == "__main__":
    unittest.main()
