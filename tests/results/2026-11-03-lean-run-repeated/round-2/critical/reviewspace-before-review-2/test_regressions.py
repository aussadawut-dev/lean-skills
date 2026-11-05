import json
import sqlite3
import subprocess
import sys
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing, contextmanager
from pathlib import Path

import vault


ROOT = Path(__file__).resolve().parent


class VaultRegressionTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(dir=ROOT, prefix=".vault-test-")
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / "vault.sqlite"
        vault.init_db(self.path)
        with self.connection() as con:
            con.executemany(
                "INSERT INTO accounts VALUES (?, ?, ?)",
                [
                    ("alpha", "source", 100),
                    ("alpha", "target", 20),
                    ("beta", "source", 1000),
                    ("beta", "target", 200),
                    ("beta", "private", 700),
                ],
            )

    @contextmanager
    def connection(self):
        with closing(sqlite3.connect(self.path)) as con, con:
            yield con

    def snapshot(self):
        with self.connection() as con:
            return {
                table: con.execute(f"SELECT * FROM {table} ORDER BY 1, 2, 3").fetchall()
                for table in ("accounts", "transfers", "audit")
            }

    def send(self, **overrides):
        request = dict(
            tenant="alpha", source="source", target="target", amount=10, key="payment"
        )
        request.update(overrides)
        return vault.transfer(self.path, **request)

    def cli(self, *args):
        return subprocess.run(
            [sys.executable, "-B", str(ROOT / "app.py"), *map(str, args)],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=15,
        )

    def cli_request(self, request):
        return self.cli(self.path, json.dumps(request))

    def assert_cli_error(self, result):
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertEqual(result.stdout, "")
        error = json.loads(result.stderr)
        self.assertEqual(set(error), {"error"})
        self.assertIsInstance(error["error"], str)
        self.assertTrue(error["error"])
        return result.stderr

    def concurrent(self, requests):
        barrier = threading.Barrier(len(requests))

        def run(request):
            barrier.wait(timeout=10)
            try:
                return self.send(**request)
            except ValueError as error:
                return error

        with ThreadPoolExecutor(max_workers=len(requests)) as pool:
            futures = [pool.submit(run, request) for request in requests]
            return [future.result(timeout=20) for future in futures]

    def test_balance_is_scoped_to_tenant(self):
        self.assertEqual(vault.balance(self.path, "beta", "source"), 1000)
        self.assertEqual(vault.balance(self.path, "alpha", "source"), 100)

    def test_missing_and_inaccessible_accounts_have_same_error(self):
        before = self.snapshot()
        errors = []
        for account in ("private", "missing"):
            with self.assertRaises(ValueError) as caught:
                vault.balance(self.path, "alpha", account)
            errors.append(str(caught.exception))
        self.assertEqual(errors[0], errors[1])
        for endpoint in ("source", "target"):
            errors = []
            for account in ("private", "missing"):
                with self.assertRaises(ValueError) as caught:
                    self.send(**{endpoint: account})
                errors.append(str(caught.exception))
            self.assertEqual(errors[0], errors[1])
        self.assertEqual(self.snapshot(), before)

    def test_transfer_changes_only_its_tenant_and_records_all_effects(self):
        receipt = self.send(tenant="beta")
        self.assertEqual(
            receipt,
            dict(tenant="beta", key="payment", source="source", target="target", amount=10),
        )
        state = self.snapshot()
        self.assertEqual(
            state["accounts"],
            [
                ("alpha", "source", 100), ("alpha", "target", 20),
                ("beta", "private", 700), ("beta", "source", 990),
                ("beta", "target", 210),
            ],
        )
        expected = [("beta", "payment", "source", "target", 10)]
        self.assertEqual(state["transfers"], expected)
        self.assertEqual(state["audit"], expected)

    def test_replay_survives_reopening_and_init_preserves_rows(self):
        receipt = self.send(amount=100)
        before = self.snapshot()
        vault.init_db(self.path)
        self.assertEqual(self.send(amount=100), receipt)
        self.assertEqual(self.snapshot(), before)
        receipt["amount"] = -1
        self.assertEqual(self.send(amount=100)["amount"], 100)

    def test_key_conflicts_reject_every_changed_payload_without_writes(self):
        self.send()
        with self.connection() as con:
            con.execute("INSERT INTO accounts VALUES ('alpha', 'third', 50)")
        before = self.snapshot()
        for change in ({"amount": 11}, {"source": "third"}, {"target": "third"}):
            with self.subTest(change=change):
                with self.assertRaises(ValueError):
                    self.send(**change)
                self.assertEqual(self.snapshot(), before)

    def test_receipts_and_same_keys_are_isolated_by_tenant(self):
        first = self.send()
        second = self.send(tenant="beta", amount=25)
        self.assertEqual(first["tenant"], "alpha")
        self.assertEqual(second["tenant"], "beta")
        self.assertEqual(second["amount"], 25)
        before = self.snapshot()
        self.assertEqual(self.send(), first)
        self.assertEqual(self.send(tenant="beta", amount=25), second)
        with self.assertRaises(ValueError):
            self.send(tenant="absent")
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(len(before["transfers"]), 2)
        self.assertEqual(len(before["audit"]), 2)

    def test_malformed_fields_are_rejected_without_writes(self):
        before = self.snapshot()
        bad_strings = (None, "", 1, True, [], {})
        for field in ("tenant", "source", "target", "key"):
            for value in bad_strings:
                with self.subTest(field=field, value=value):
                    with self.assertRaises(ValueError):
                        self.send(**{field: value})
                    self.assertEqual(self.snapshot(), before)
        for amount in (True, False, 0, -1, 1.0, 1.5, "10", None, [], {}, float("nan"), float("inf")):
            with self.subTest(amount=amount):
                with self.assertRaises(ValueError):
                    self.send(amount=amount)
                self.assertEqual(self.snapshot(), before)
        for field in ("tenant", "account"):
            for value in bad_strings:
                request = dict(tenant="alpha", account="source")
                request[field] = value
                with self.subTest(balance=request):
                    with self.assertRaises(ValueError):
                        vault.balance(self.path, **request)
        self.assertEqual(self.snapshot(), before)

    def test_boolean_amount_is_rejected_without_writes(self):
        before = self.snapshot()
        with self.assertRaises(ValueError):
            self.send(amount=True)
        self.assertEqual(self.snapshot(), before)

    def test_self_transfer_and_insufficient_funds_leave_no_effects(self):
        before = self.snapshot()
        for request in ({"target": "source"}, {"amount": 101}, {"amount": 10**100}):
            with self.subTest(request=request):
                with self.assertRaises(ValueError):
                    self.send(**request)
                self.assertEqual(self.snapshot(), before)

    def test_credit_overflow_rolls_back_instead_of_storing_a_float(self):
        with self.connection() as con:
            con.execute(
                "UPDATE accounts SET balance = ? WHERE tenant = 'alpha' AND name = 'target'",
                (2**63 - 1,),
            )
        before = self.snapshot()
        with self.assertRaises((OverflowError, sqlite3.Error)):
            self.send()
        self.assertEqual(self.snapshot(), before)
        self.assertIsInstance(vault.balance(self.path, "alpha", "target"), int)

    def test_sql_metacharacters_and_unicode_are_literal_identifiers(self):
        tenant, source, target, key = "tenant ' 世界", "a' OR 1=1 --", "b 雪", "key'; --"
        with self.connection() as con:
            con.executemany(
                "INSERT INTO accounts VALUES (?, ?, ?)",
                [(tenant, source, 5), (tenant, target, 1)],
            )
        before = self.snapshot()["accounts"][:5]
        receipt = vault.transfer(self.path, tenant, source, target, 5, key)
        self.assertEqual(receipt["key"], key)
        self.assertEqual(vault.balance(self.path, tenant, source), 0)
        self.assertEqual(vault.balance(self.path, tenant, target), 6)
        self.assertEqual(self.snapshot()["accounts"][:5], before)

    def test_audit_exception_rolls_back_and_retry_survives_reopening(self):
        with self.connection() as con:
            con.execute("""CREATE TRIGGER audit_failure BEFORE INSERT ON audit
                           BEGIN SELECT RAISE(ABORT, 'private storage detail'); END""")
        before = self.snapshot()
        with self.assertRaises(sqlite3.Error):
            self.send()
        self.assertEqual(self.snapshot(), before)
        vault.init_db(self.path)
        with self.assertRaises(sqlite3.Error):
            self.send()
        self.assertEqual(self.snapshot(), before)
        with self.connection() as con:
            con.execute("DROP TRIGGER audit_failure")
        receipt = self.send()
        self.assertEqual(self.send(), receipt)
        state = self.snapshot()
        self.assertEqual(len(state["transfers"]), 1)
        self.assertEqual(len(state["audit"]), 1)
        self.assertEqual(vault.balance(self.path, "alpha", "source"), 90)
        self.assertEqual(vault.balance(self.path, "alpha", "target"), 30)

    def test_silently_ignored_writes_fail_atomically(self):
        cases = (
            ("accounts", "UPDATE", "NEW.tenant = 'alpha' AND NEW.name = 'source'"),
            ("accounts", "UPDATE", "NEW.tenant = 'alpha' AND NEW.name = 'target'"),
            ("transfers", "INSERT", "1"),
            ("audit", "INSERT", "1"),
        )
        for index, (table, operation, condition) in enumerate(cases):
            with self.subTest(table=table, condition=condition):
                with self.connection() as con:
                    con.execute(
                        f"CREATE TRIGGER ignored_write BEFORE {operation} ON {table} "
                        f"WHEN {condition} BEGIN SELECT RAISE(IGNORE); END"
                    )
                before = self.snapshot()
                try:
                    with self.assertRaises(sqlite3.Error):
                        self.send(key=f"ignored-{index}")
                    self.assertEqual(self.snapshot(), before)
                finally:
                    with self.connection() as con:
                        con.execute("DROP TRIGGER ignored_write")

    def test_after_trigger_cannot_erase_required_effects(self):
        cases = (
            ("UPDATE ON accounts WHEN NEW.tenant = 'alpha' AND NEW.name = 'target'",
             "UPDATE accounts SET balance = OLD.balance WHERE tenant = NEW.tenant AND name = NEW.name;"),
            ("INSERT ON transfers", "DELETE FROM transfers WHERE tenant = NEW.tenant AND key = NEW.key;"),
            ("INSERT ON audit", "DELETE FROM audit WHERE rowid = NEW.rowid;"),
            ("INSERT ON audit", "INSERT INTO audit VALUES (NEW.tenant, NEW.key, NEW.source, NEW.target, NEW.amount);"),
        )
        for index, (event, action) in enumerate(cases):
            with self.subTest(event=event):
                with self.connection() as con:
                    con.execute(f"CREATE TRIGGER erase_effect AFTER {event} BEGIN {action} END")
                before = self.snapshot()
                try:
                    with self.assertRaises(sqlite3.Error):
                        self.send(key=f"erased-{index}")
                    self.assertEqual(self.snapshot(), before)
                finally:
                    with self.connection() as con:
                        con.execute("DROP TRIGGER erase_effect")

    def test_concurrent_duplicate_requests_execute_once(self):
        results = self.concurrent([{} for _ in range(8)])
        self.assertTrue(all(isinstance(result, dict) for result in results), results)
        self.assertTrue(all(result == results[0] for result in results))
        self.assertEqual(vault.balance(self.path, "alpha", "source"), 90)
        self.assertEqual(vault.balance(self.path, "alpha", "target"), 30)
        state = self.snapshot()
        self.assertEqual(len(state["transfers"]), 1)
        self.assertEqual(len(state["audit"]), 1)
        vault.init_db(self.path)
        self.assertEqual(self.send(), results[0])
        self.assertEqual(self.snapshot(), state)

    def test_concurrent_distinct_keys_never_overspend_or_lose_credits(self):
        results = self.concurrent([dict(amount=30, key=f"key-{i}") for i in range(8)])
        receipts = [result for result in results if isinstance(result, dict)]
        failures = [result for result in results if isinstance(result, ValueError)]
        self.assertEqual(len(receipts), 3)
        self.assertEqual(len(failures), 5)
        self.assertEqual(vault.balance(self.path, "alpha", "source"), 10)
        self.assertEqual(vault.balance(self.path, "alpha", "target"), 110)
        state = self.snapshot()
        self.assertEqual(len(state["transfers"]), 3)
        self.assertEqual(state["audit"], state["transfers"])

    def test_concurrent_senders_do_not_lose_shared_target_credits(self):
        with self.connection() as con:
            con.executemany(
                "INSERT INTO accounts VALUES ('alpha', ?, 10)",
                [(f"sender-{i}",) for i in range(6)],
            )
        results = self.concurrent(
            [dict(source=f"sender-{i}", key=f"key-{i}") for i in range(6)]
        )
        self.assertTrue(all(isinstance(result, dict) for result in results), results)
        self.assertEqual(vault.balance(self.path, "alpha", "target"), 80)
        for i in range(6):
            self.assertEqual(vault.balance(self.path, "alpha", f"sender-{i}"), 0)
        state = self.snapshot()
        self.assertEqual(len(state["transfers"]), 6)
        self.assertEqual(state["audit"], state["transfers"])

    def test_concurrent_conflicting_payloads_have_one_winner(self):
        results = self.concurrent([dict(amount=amount) for amount in (10, 20, 10, 20)])
        receipts = [result for result in results if isinstance(result, dict)]
        self.assertEqual(len(receipts), 2)
        self.assertTrue(all(receipt == receipts[0] for receipt in receipts))
        self.assertEqual(sum(isinstance(result, ValueError) for result in results), 2)
        amount = receipts[0]["amount"]
        self.assertEqual(vault.balance(self.path, "alpha", "source"), 100 - amount)
        self.assertEqual(vault.balance(self.path, "alpha", "target"), 20 + amount)
        state = self.snapshot()
        self.assertEqual(len(state["transfers"]), 1)
        self.assertEqual(state["audit"], state["transfers"])

    def test_cli_integrated_transfer_replay_conflict_and_tenant_isolation(self):
        request = dict(op="transfer", tenant="alpha", source="source", target="target", amount=100, key="cli")
        first = self.cli_request(request)
        self.assertEqual(first.returncode, 0, first.stderr)
        self.assertEqual(first.stderr, "")
        self.assertEqual(len(first.stdout.splitlines()), 1)
        expected = {name: value for name, value in request.items() if name != "op"}
        self.assertEqual(json.loads(first.stdout), expected)
        before = self.snapshot()
        replay = self.cli_request(request)
        self.assertEqual(replay.returncode, 0, replay.stderr)
        self.assertEqual(replay.stdout, first.stdout)
        self.assertEqual(self.snapshot(), before)
        self.assert_cli_error(self.cli_request(dict(request, amount=99)))
        self.assertEqual(self.snapshot(), before)
        other = self.cli_request(dict(request, tenant="beta", amount=40))
        self.assertEqual(other.returncode, 0, other.stderr)
        self.assertEqual(json.loads(other.stdout)["tenant"], "beta")
        for tenant, account, amount in (
            ("alpha", "source", 0), ("alpha", "target", 120),
            ("beta", "source", 960), ("beta", "target", 240),
        ):
            result = self.cli_request(dict(op="balance", tenant=tenant, account=account))
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stderr, "")
            self.assertEqual(json.loads(result.stdout), amount)
        state = self.snapshot()
        self.assertEqual(len(state["transfers"]), 2)
        self.assertEqual(state["audit"], state["transfers"])

    def test_cli_errors_are_generic_and_leave_no_writes(self):
        before = self.snapshot()
        arguments = [
            (), (self.path,), (self.path, "{}", "extra"), (self.path, "{"),
            (self.path, "null"), (self.path, "[]"), (self.path, "{}"),
            (self.path, '{"op": "init_db"}'), (self.path, '{"op": []}'),
        ]
        requests = [
            dict(op="balance", tenant="alpha", account="private"),
            dict(op="balance", tenant="alpha", account="missing"),
            dict(op="balance", account="source"),
            dict(op="balance", tenant="alpha", account="source", extra=True),
            dict(op="transfer", tenant="alpha", source="source", target="target", amount=True, key="cli"),
            dict(op="transfer", tenant="alpha", source="source", target="private", amount=10, key="cli"),
            dict(op="transfer", tenant="alpha", source="source", target="target", amount=101, key="cli"),
        ]
        arguments.extend((self.path, json.dumps(request)) for request in requests)
        errors = []
        for args in arguments:
            with self.subTest(args=args):
                errors.append(self.assert_cli_error(self.cli(*args)))
                self.assertEqual(self.snapshot(), before)
        self.assertEqual(len(set(errors)), 1)

    def test_cli_storage_failure_is_generic_and_atomic(self):
        invalid = self.assert_cli_error(self.cli(self.path, "{}"))
        with self.connection() as con:
            con.execute("""CREATE TRIGGER audit_failure BEFORE INSERT ON audit
                           BEGIN SELECT RAISE(ABORT, 'SELECT private FROM beta'); END""")
        before = self.snapshot()
        result = self.cli_request(dict(
            op="transfer", tenant="alpha", source="source", target="target", amount=10, key="cli"
        ))
        self.assertEqual(self.assert_cli_error(result), invalid)
        self.assertEqual(self.snapshot(), before)

    def test_cli_deep_json_is_a_generic_error(self):
        before = self.snapshot()
        invalid = self.assert_cli_error(self.cli(self.path, "{}"))
        nested = "[" * 2000 + "0" + "]" * 2000
        self.assertEqual(self.assert_cli_error(self.cli(self.path, nested)), invalid)
        self.assertEqual(self.snapshot(), before)


if __name__ == "__main__":
    unittest.main()
