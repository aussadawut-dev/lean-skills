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


class DatabaseTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(dir=ROOT)
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "vault.sqlite"
        vault.init_db(self.path)
        with closing(sqlite3.connect(self.path)) as con, con:
            con.executemany(
                "INSERT INTO accounts VALUES (?, ?, ?)",
                [("alpha", "shared", 100), ("alpha", "savings", 10),
                 ("beta", "shared", 1000), ("beta", "savings", 20),
                 ("beta", "private", 500)],
            )

    def snapshot(self):
        with closing(sqlite3.connect(self.path)) as con:
            return {
                table: con.execute(f"SELECT * FROM {table} ORDER BY 1, 2").fetchall()
                for table in ("accounts", "transfers", "audit")
            }

    def request(self, **changes):
        request = dict(tenant="alpha", source="shared", target="savings",
                       amount=10, key="key")
        request.update(changes)
        return request

    def make_trigger(self, name, statement):
        with closing(sqlite3.connect(self.path)) as con, con:
            con.execute(f"CREATE TRIGGER {name} {statement}")

    def drop_trigger(self, name):
        with closing(sqlite3.connect(self.path)) as con, con:
            con.execute(f"DROP TRIGGER {name}")

    def run_concurrently(self, requests):
        barrier = threading.Barrier(len(requests))

        def call(request):
            barrier.wait(timeout=10)
            try:
                return vault.transfer(self.path, **request)
            except ValueError as error:
                return error

        with ThreadPoolExecutor(max_workers=len(requests)) as executor:
            futures = [executor.submit(call, request) for request in requests]
            return [future.result(timeout=35) for future in futures]

    def test_balance_is_tenant_scoped(self):
        self.assertEqual(vault.balance(self.path, "alpha", "shared"), 100)
        self.assertEqual(vault.balance(self.path, "beta", "shared"), 1000)
        messages = []
        before = self.snapshot()
        for tenant, account in [("alpha", "private"), ("alpha", "missing"),
                                ("missing", "shared")]:
            with self.subTest(tenant=tenant, account=account):
                with self.assertRaises(ValueError) as error:
                    vault.balance(self.path, tenant, account)
                messages.append(str(error.exception))
        self.assertEqual(len(set(messages)), 1)
        self.assertNotIn("beta", messages[0])
        self.assertNotIn("private", messages[0])
        self.assertEqual(self.snapshot(), before)

    def test_transfer_and_receipts_are_tenant_scoped(self):
        beta = self.request(tenant="beta", amount=7)
        alpha = self.request(amount=11)
        self.assertEqual(vault.transfer(self.path, **beta), beta)
        self.assertEqual(vault.transfer(self.path, **alpha), alpha)
        self.assertEqual(vault.transfer(self.path, **beta), beta)
        self.assertEqual(vault.transfer(self.path, **alpha), alpha)
        self.assertEqual(self.snapshot(), {
            "accounts": [("alpha", "savings", 21), ("alpha", "shared", 89),
                         ("beta", "private", 500), ("beta", "savings", 27),
                         ("beta", "shared", 993)],
            "transfers": [("alpha", "key", "shared", "savings", 11),
                          ("beta", "key", "shared", "savings", 7)],
            "audit": [("alpha", "key", "shared", "savings", 11),
                      ("beta", "key", "shared", "savings", 7)],
        })

    def test_missing_transfer_endpoints_are_generic_and_leave_no_writes(self):
        before = self.snapshot()
        messages = []
        for endpoint in ("source", "target"):
            for name in ("private", "missing"):
                with self.subTest(endpoint=endpoint, name=name):
                    with self.assertRaises(ValueError) as error:
                        vault.transfer(self.path, **self.request(**{endpoint: name}))
                    messages.append(str(error.exception))
                    self.assertEqual(self.snapshot(), before)
        with self.assertRaises(ValueError) as error:
            vault.balance(self.path, "alpha", "private")
        self.assertEqual(set(messages), {str(error.exception)})

    def test_invalid_inputs_leave_no_writes(self):
        before = self.snapshot()
        for field in ("tenant", "source", "target", "key"):
            for invalid in (None, "", True, 1, 1.5, [], {}, b"name"):
                with self.subTest(field=field, invalid=invalid):
                    with self.assertRaises(ValueError):
                        vault.transfer(self.path, **self.request(**{field: invalid}))
                    self.assertEqual(self.snapshot(), before)
        for amount in (None, True, False, 0, -1, 1.5, "1", [], {}, 2**100):
            with self.subTest(amount=amount):
                with self.assertRaises(ValueError):
                    vault.transfer(self.path, **self.request(amount=amount))
                self.assertEqual(self.snapshot(), before)
        for changes in ({"target": "shared"}, {"amount": 101}):
            with self.subTest(changes=changes):
                with self.assertRaises(ValueError):
                    vault.transfer(self.path, **self.request(**changes))
                self.assertEqual(self.snapshot(), before)

    def test_invalid_balance_arguments(self):
        before = self.snapshot()
        for field in ("tenant", "account"):
            for invalid in (None, "", True, 1, 1.5, [], {}, b"name"):
                request = dict(tenant="alpha", account="shared")
                request[field] = invalid
                with self.subTest(field=field, invalid=invalid):
                    with self.assertRaises(ValueError):
                        vault.balance(self.path, **request)
                    self.assertEqual(self.snapshot(), before)

    def test_exact_replay_after_funds_change_and_key_conflicts(self):
        request = self.request(amount=100)
        receipt = vault.transfer(self.path, **request)
        before = self.snapshot()
        self.assertEqual(vault.balance(self.path, "alpha", "shared"), 0)
        self.assertEqual(vault.transfer(self.path, **request), receipt)
        for changes in ({"amount": 99}, {"source": "savings", "target": "shared"},
                        {"target": "private"}):
            with self.subTest(changes=changes):
                with self.assertRaises(ValueError):
                    vault.transfer(self.path, **dict(request, **changes))
                self.assertEqual(self.snapshot(), before)

    def test_init_preserves_existing_rows_schema_and_triggers(self):
        vault.transfer(self.path, **self.request())
        self.make_trigger("existing_audit", "BEFORE INSERT ON audit BEGIN SELECT 1; END")
        before = self.snapshot()
        with closing(sqlite3.connect(self.path)) as con:
            schema = con.execute("SELECT name, sql FROM sqlite_master ORDER BY name").fetchall()
        vault.init_db(self.path)
        self.assertEqual(self.snapshot(), before)
        with closing(sqlite3.connect(self.path)) as con:
            self.assertEqual(con.execute(
                "SELECT name, sql FROM sqlite_master ORDER BY name").fetchall(), schema)
        self.assertEqual(vault.transfer(self.path, **self.request()), self.request())
        self.assertEqual(self.snapshot(), before)

    def test_storage_failures_and_silent_skips_roll_back_every_effect(self):
        stages = {
            "debit": "BEFORE UPDATE ON accounts WHEN OLD.tenant='alpha' AND OLD.name='shared'",
            "credit": "BEFORE UPDATE ON accounts WHEN OLD.tenant='alpha' AND OLD.name='savings'",
            "receipt": "BEFORE INSERT ON transfers",
            "audit": "BEFORE INSERT ON audit",
        }
        for stage, event in stages.items():
            for failure in ("RAISE(ABORT, 'private storage detail')", "RAISE(IGNORE)"):
                with self.subTest(stage=stage, failure=failure):
                    before = self.snapshot()
                    self.make_trigger("failure", f"{event} BEGIN SELECT {failure}; END")
                    try:
                        with self.assertRaises(sqlite3.Error):
                            vault.transfer(self.path, **self.request(key=f"{stage}-{failure}"))
                        self.assertEqual(self.snapshot(), before)
                        with closing(sqlite3.connect(self.path)) as con:
                            self.assertIsNotNone(con.execute(
                                "SELECT name FROM sqlite_master WHERE name='failure'"
                            ).fetchone())
                    finally:
                        self.drop_trigger("failure")
        self.assertEqual(vault.transfer(self.path, **self.request()), self.request())
        self.assertEqual(vault.balance(self.path, "alpha", "shared"), 90)
        self.assertEqual(vault.balance(self.path, "alpha", "savings"), 20)
        self.assertEqual(len(self.snapshot()["audit"]), 1)

    def test_sqlite_integer_boundary_keeps_balances_exact(self):
        maximum = 2**63 - 1
        with closing(sqlite3.connect(self.path)) as con, con:
            con.execute("UPDATE accounts SET balance=? WHERE tenant=? AND name=?",
                        (maximum, "alpha", "shared"))
            con.execute("UPDATE accounts SET balance=0 WHERE tenant=? AND name=?",
                        ("alpha", "savings"))
        request = self.request(amount=maximum)
        self.assertEqual(vault.transfer(self.path, **request), request)
        self.assertEqual(vault.balance(self.path, "alpha", "shared"), 0)
        self.assertEqual(vault.balance(self.path, "alpha", "savings"), maximum)
        with closing(sqlite3.connect(self.path)) as con, con:
            con.execute("UPDATE accounts SET balance=1 WHERE tenant=? AND name=?",
                        ("alpha", "shared"))
        before = self.snapshot()
        with self.assertRaises(ValueError):
            vault.transfer(self.path, **self.request(amount=1, key="overflow"))
        self.assertEqual(self.snapshot(), before)

    def test_simultaneous_duplicate_requests_execute_once(self):
        request = self.request(amount=60)
        results = self.run_concurrently([request] * 12)
        self.assertEqual(results, [request] * 12)
        self.assertEqual(vault.balance(self.path, "alpha", "shared"), 40)
        self.assertEqual(vault.balance(self.path, "alpha", "savings"), 70)
        before = self.snapshot()
        self.assertEqual(len(before["transfers"]), 1)
        self.assertEqual(before["transfers"], before["audit"])
        self.assertEqual(vault.transfer(self.path, **request), request)
        self.assertEqual(self.snapshot(), before)

    def test_simultaneous_key_conflict_has_one_winner(self):
        requests = [self.request(amount=amount) for amount in (30, 40)]
        results = self.run_concurrently(requests)
        receipts = [result for result in results if isinstance(result, dict)]
        self.assertEqual(len(receipts), 1)
        self.assertEqual(sum(isinstance(result, ValueError) for result in results), 1)
        amount = receipts[0]["amount"]
        self.assertEqual(vault.balance(self.path, "alpha", "shared"), 100 - amount)
        self.assertEqual(vault.balance(self.path, "alpha", "savings"), 10 + amount)
        self.assertEqual(len(self.snapshot()["transfers"]), 1)
        self.assertEqual(self.snapshot()["transfers"], self.snapshot()["audit"])

    def test_simultaneous_distinct_keys_never_overspend(self):
        requests = [self.request(amount=30, key=f"key-{i}") for i in range(12)]
        results = self.run_concurrently(requests)
        self.assertEqual(sum(isinstance(result, dict) for result in results), 3)
        self.assertEqual(sum(isinstance(result, ValueError) for result in results), 9)
        self.assertEqual(vault.balance(self.path, "alpha", "shared"), 10)
        self.assertEqual(vault.balance(self.path, "alpha", "savings"), 100)
        snapshot = self.snapshot()
        self.assertEqual(len(snapshot["transfers"]), 3)
        self.assertEqual(snapshot["transfers"], snapshot["audit"])
        self.assertEqual(vault.balance(self.path, "beta", "shared"), 1000)

    def test_simultaneous_credits_from_different_sources_are_not_lost(self):
        with closing(sqlite3.connect(self.path)) as con, con:
            con.executemany("INSERT INTO accounts VALUES (?, ?, ?)",
                            [("alpha", f"source-{i}", 5) for i in range(8)])
        requests = [self.request(source=f"source-{i}", amount=5, key=f"key-{i}")
                    for i in range(8)]
        self.assertEqual(self.run_concurrently(requests), requests)
        self.assertEqual(vault.balance(self.path, "alpha", "savings"), 50)
        for request in requests:
            self.assertEqual(vault.balance(self.path, "alpha", request["source"]), 0)
        self.assertEqual(len(self.snapshot()["transfers"]), 8)
        self.assertEqual(self.snapshot()["transfers"], self.snapshot()["audit"])

    def test_names_and_keys_are_literal_nonempty_strings(self):
        tenant = "tenant' OR 1=1 --"
        source, target, key = " ", "target\u2603", "'; DROP TABLE accounts; --"
        with closing(sqlite3.connect(self.path)) as con, con:
            con.executemany("INSERT INTO accounts VALUES (?, ?, ?)",
                            [(tenant, source, 2), (tenant, target, 0)])
        request = self.request(tenant=tenant, source=source, target=target, amount=1, key=key)
        self.assertEqual(vault.transfer(self.path, **request), request)
        self.assertEqual(vault.balance(self.path, tenant, source), 1)
        self.assertEqual(vault.balance(self.path, "alpha", "shared"), 100)


class CommandLineTests(unittest.TestCase):
    setUp = DatabaseTests.setUp
    snapshot = DatabaseTests.snapshot
    request = DatabaseTests.request
    make_trigger = DatabaseTests.make_trigger
    drop_trigger = DatabaseTests.drop_trigger

    def cli(self, request):
        return self.cli_args(str(self.path), json.dumps(request))

    def cli_args(self, *args):
        return subprocess.run([sys.executable, "-B", str(ROOT / "app.py"), *args],
                              cwd=ROOT, text=True, capture_output=True, timeout=10)

    def success(self, result):
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stderr, "")
        self.assertEqual(len(result.stdout.splitlines()), 1)
        return json.loads(result.stdout)

    def failure(self, result):
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertEqual(result.stdout, "")
        self.assertEqual(len(result.stderr.splitlines()), 1)
        error = json.loads(result.stderr)
        self.assertIsInstance(error, dict)
        self.assertEqual(set(error), {"error"})
        self.assertIsInstance(error["error"], str)
        self.assertTrue(error["error"])
        return error

    def test_cli_integrated_journey_and_durable_replay(self):
        self.assertEqual(self.success(self.cli(
            dict(op="balance", tenant="alpha", account="shared"))), 100)
        request = self.request(amount=25)
        receipt = self.success(self.cli(dict(op="transfer", **request)))
        self.assertEqual(receipt, request)
        self.assertEqual(self.success(self.cli(
            dict(op="balance", tenant="alpha", account="shared"))), 75)
        self.assertEqual(self.success(self.cli(
            dict(op="balance", tenant="alpha", account="savings"))), 35)
        before = self.snapshot()
        self.assertEqual(self.success(self.cli(dict(op="transfer", **request))), receipt)
        self.assertEqual(self.snapshot(), before)
        self.failure(self.cli(dict(op="transfer", **dict(request, amount=26))))
        self.assertEqual(self.snapshot(), before)
        beta = self.request(tenant="beta", amount=7)
        self.assertEqual(self.success(self.cli(dict(op="transfer", **beta))), beta)
        before = self.snapshot()
        self.failure(self.cli(dict(op="transfer", **self.request(target="private", key="other"))))
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(len(before["transfers"]), 2)
        self.assertEqual(before["transfers"], before["audit"])

    def test_cli_invalid_calls_have_one_generic_error_and_no_writes(self):
        before = self.snapshot()
        invalid = [None, [], 1, "text", {}, {"op": []}, {"op": "unknown"},
                   {"op": "init_db"}, {"op": "balance", "tenant": "alpha"},
                   dict(op="balance", tenant="alpha", account="shared", extra=1),
                   dict(op="balance", tenant="alpha", account="private"),
                   dict(op="balance", tenant="alpha", account="missing"),
                   dict(op="balance", tenant="alpha", account=5),
                   dict(op="transfer", **self.request(amount=True)),
                   dict(op="transfer", **self.request(amount=101)),
                   dict(op="transfer", **self.request(target="shared")),
                   dict(op="transfer", **self.request(key=""))]
        errors = []
        for request in invalid:
            with self.subTest(request=request):
                errors.append(self.failure(self.cli(request)))
                self.assertEqual(self.snapshot(), before)
        for args in [(), (str(self.path),), (str(self.path), "{"),
                     (str(self.path), "{}", "extra")]:
            with self.subTest(args=args):
                errors.append(self.failure(self.cli_args(*args)))
                self.assertEqual(self.snapshot(), before)
        self.assertTrue(all(error == errors[0] for error in errors))

    def test_cli_storage_failure_is_generic_atomic_and_retryable(self):
        before = self.snapshot()
        self.make_trigger("fail_audit", "BEFORE INSERT ON audit BEGIN "
                          "SELECT RAISE(ABORT, 'beta secret SQL INSERT audit'); END")
        failed = self.failure(self.cli(dict(op="transfer", **self.request())))
        self.assertEqual(failed, self.failure(self.cli(dict(op="balance", tenant="alpha",
                                                         account="private"))))
        self.assertEqual(self.snapshot(), before)
        self.drop_trigger("fail_audit")
        self.assertEqual(self.success(self.cli(dict(op="transfer", **self.request()))),
                         self.request())
        self.assertEqual(len(self.snapshot()["audit"]), 1)


if __name__ == "__main__":
    unittest.main()
