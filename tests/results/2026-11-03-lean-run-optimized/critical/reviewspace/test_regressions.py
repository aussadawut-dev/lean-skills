import concurrent.futures
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import threading
import unittest

import vault


WORKSPACE = Path(__file__).resolve().parent


class VaultTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(dir=WORKSPACE)
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "vault.sqlite"
        vault.init_db(self.path)
        self.sql(
            "INSERT INTO accounts VALUES (?, ?, ?)",
            [
                ("alpha", "source", 100),
                ("alpha", "target", 0),
                ("beta", "source", 1000),
                ("beta", "target", 50),
                ("beta", "private", 77),
            ],
        )

    def sql(self, statement, rows=None):
        con = sqlite3.connect(self.path)
        try:
            with con:
                if rows is not None:
                    con.executemany(statement, rows)
                    return []
                return con.execute(statement).fetchall()
        finally:
            con.close()

    def snapshot(self):
        return {
            table: self.sql(f"SELECT * FROM {table} ORDER BY 1, 2")
            for table in ("accounts", "transfers", "audit")
        }

    def transfer(self, **changes):
        request = dict(
            tenant="alpha", source="source", target="target", amount=10, key="key"
        )
        request.update(changes)
        return vault.transfer(self.path, **request)

    def cli(self, *arguments):
        return subprocess.run(
            [sys.executable, "-B", str(WORKSPACE / "app.py"), *arguments],
            cwd=WORKSPACE,
            capture_output=True,
            text=True,
            timeout=15,
        )

    def request(self, request):
        return self.cli(str(self.path), json.dumps(request))

    def assert_cli_success(self, completed, expected):
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(completed.stderr, "")
        self.assertEqual(len(completed.stdout.splitlines()), 1)
        self.assertEqual(json.loads(completed.stdout), expected)

    def assert_cli_error(self, completed):
        self.assertEqual(completed.returncode, 2)
        self.assertEqual(completed.stdout, "")
        self.assertEqual(len(completed.stderr.splitlines()), 1)
        error = json.loads(completed.stderr)
        self.assertEqual(set(error), {"error"})
        self.assertIsInstance(error["error"], str)
        self.assertTrue(error["error"])
        return error

    def test_balance_is_tenant_scoped(self):
        self.assertEqual(vault.balance(self.path, "alpha", "source"), 100)
        self.assertEqual(vault.balance(self.path, "beta", "source"), 1000)

    def test_missing_and_inaccessible_balance_share_error(self):
        errors = []
        for tenant, account in (
            ("alpha", "private"),
            ("alpha", "absent"),
            ("unknown", "source"),
            ("alpha", "' OR 1=1 --"),
        ):
            with self.assertRaises(ValueError) as caught:
                vault.balance(self.path, tenant, account)
            errors.append(str(caught.exception))
        self.assertTrue(errors[0])
        self.assertEqual(len(set(errors)), 1)
        self.assertNotIn("beta", errors[0])
        self.assertNotIn("private", errors[0])

    def test_balance_validates_strings(self):
        for value in ("", None, 1, True, [], {}, b"alpha"):
            for field in ("tenant", "account"):
                with self.subTest(field=field, value=value):
                    request = dict(tenant="alpha", account="source")
                    request[field] = value
                    with self.assertRaises(ValueError):
                        vault.balance(self.path, **request)

    def test_transfer_updates_only_authenticated_tenant(self):
        receipt = self.transfer()
        self.assertEqual(
            receipt,
            dict(tenant="alpha", key="key", source="source", target="target", amount=10),
        )
        self.assertEqual(
            self.snapshot(),
            {
                "accounts": [
                    ("alpha", "source", 90),
                    ("alpha", "target", 10),
                    ("beta", "private", 77),
                    ("beta", "source", 1000),
                    ("beta", "target", 50),
                ],
                "transfers": [("alpha", "key", "source", "target", 10)],
                "audit": [("alpha", "key", "source", "target", 10)],
            },
        )

    def test_transfer_validates_strings_without_writes(self):
        original = self.snapshot()
        for field in ("tenant", "source", "target", "key"):
            for value in ("", None, 1, True, [], {}, b"name"):
                with self.subTest(field=field, value=value):
                    with self.assertRaises(ValueError):
                        self.transfer(**{field: value})
                    self.assertEqual(self.snapshot(), original)

    def test_transfer_validates_amount_without_writes(self):
        original = self.snapshot()
        for amount in (0, -1, True, False, 1.0, "1", None, [], {}, float("nan"), float("inf")):
            with self.subTest(amount=amount):
                with self.assertRaises(ValueError):
                    self.transfer(amount=amount)
                self.assertEqual(self.snapshot(), original)

    def test_missing_and_inaccessible_transfer_accounts_share_error(self):
        original = self.snapshot()
        errors = []
        for field in ("source", "target"):
            for name in ("absent", "private"):
                with self.subTest(field=field, name=name):
                    with self.assertRaises(ValueError) as caught:
                        self.transfer(**{field: name})
                    errors.append(str(caught.exception))
                    self.assertEqual(self.snapshot(), original)
        self.assertEqual(len(set(errors)), 1)
        with self.assertRaises(ValueError) as caught:
            vault.balance(self.path, "alpha", "absent")
        self.assertEqual(errors[0], str(caught.exception))

    def test_self_transfer_and_insufficient_funds_do_not_write(self):
        original = self.snapshot()
        for changes in ({"target": "source"}, {"amount": 101}, {"amount": 2**80}):
            with self.subTest(changes=changes):
                with self.assertRaises(ValueError):
                    self.transfer(**changes)
                self.assertEqual(self.snapshot(), original)

    def test_exact_replay_is_durable_even_when_remaining_funds_are_lower(self):
        receipt = self.transfer(amount=80)
        after = self.snapshot()
        self.assertEqual(self.transfer(amount=80), receipt)
        self.assertEqual(self.snapshot(), after)
        request = dict(op="transfer", **receipt)
        self.assert_cli_success(self.request(request), receipt)
        self.assertEqual(self.snapshot(), after)

    def test_cached_receipt_does_not_bypass_amount_validation(self):
        self.transfer(amount=1)
        after = self.snapshot()
        for amount in (True, 1.0):
            with self.subTest(amount=amount):
                with self.assertRaises(ValueError):
                    self.transfer(amount=amount)
                self.assertEqual(self.snapshot(), after)

    def test_integer_limits_remain_exact_and_overflow_rolls_back(self):
        largest_integer = 2**63 - 1
        self.sql(
            "UPDATE accounts SET balance=? WHERE tenant='alpha' AND name='source'",
            [(largest_integer,)],
        )
        self.assertEqual(self.transfer(amount=largest_integer)["amount"], largest_integer)
        self.assertEqual(vault.balance(self.path, "alpha", "source"), 0)
        credited = vault.balance(self.path, "alpha", "target")
        self.assertIsInstance(credited, int)
        self.assertEqual(credited, largest_integer)
        self.sql("UPDATE accounts SET balance=1 WHERE tenant='alpha' AND name='source'")
        before = self.snapshot()
        with self.assertRaises(OverflowError):
            self.transfer(amount=1, key="overflow")
        self.assertEqual(self.snapshot(), before)

    def test_conflicting_key_payloads_do_not_write(self):
        self.transfer()
        self.sql("INSERT INTO accounts VALUES ('alpha', 'third', 100)")
        original = self.snapshot()
        for changes in ({"amount": 11}, {"source": "third"}, {"target": "third"}):
            with self.subTest(changes=changes):
                with self.assertRaises(ValueError):
                    self.transfer(**changes)
                self.assertEqual(self.snapshot(), original)

    def test_same_key_is_independent_between_tenants(self):
        alpha = self.transfer()
        beta = self.transfer(tenant="beta", amount=30)
        self.assertEqual(beta, dict(alpha, tenant="beta", amount=30))
        self.assertEqual(vault.balance(self.path, "beta", "source"), 970)
        self.assertEqual(vault.balance(self.path, "beta", "target"), 80)
        self.assertEqual(self.transfer(), alpha)
        self.assertEqual(self.transfer(tenant="beta", amount=30), beta)
        self.assertEqual(len(self.sql("SELECT * FROM transfers")), 2)
        self.assertEqual(len(self.sql("SELECT * FROM audit")), 2)

    def test_cached_receipt_does_not_grant_other_tenant_access(self):
        self.transfer()
        before = self.snapshot()
        with self.assertRaises(ValueError):
            self.transfer(tenant="unknown")
        self.assertEqual(self.snapshot(), before)

    def test_storage_failures_roll_back_all_four_changes(self):
        original = self.snapshot()
        failures = (
            ("BEFORE UPDATE OF balance ON accounts WHEN NEW.tenant='alpha' AND NEW.name='source'", "ABORT"),
            ("BEFORE UPDATE OF balance ON accounts WHEN NEW.tenant='alpha' AND NEW.name='target'", "ABORT"),
            ("BEFORE INSERT ON transfers", "ABORT"),
            ("BEFORE INSERT ON audit", "ABORT"),
            ("BEFORE INSERT ON audit", "FAIL"),
            ("BEFORE INSERT ON audit", "ROLLBACK"),
        )
        for event, action in failures:
            with self.subTest(event=event, action=action):
                self.sql(
                    f"CREATE TRIGGER storage_failure {event} "
                    f"BEGIN SELECT RAISE({action}, 'storage failure'); END"
                )
                try:
                    with self.assertRaises(sqlite3.DatabaseError):
                        self.transfer()
                    self.assertEqual(self.snapshot(), original)
                    self.assertEqual(
                        self.sql("SELECT name FROM sqlite_master WHERE type='trigger'"),
                        [("storage_failure",)],
                    )
                finally:
                    self.sql("DROP TRIGGER storage_failure")
        self.transfer()
        self.assertEqual(vault.balance(self.path, "alpha", "source"), 90)

    def test_existing_rows_schema_and_triggers_survive_initialization(self):
        self.sql("INSERT INTO transfers VALUES ('alpha', 'old', 'source', 'target', 1)")
        self.sql("INSERT INTO audit VALUES ('alpha', 'old', 'source', 'target', 1)")
        self.sql("CREATE TRIGGER keep_me BEFORE INSERT ON audit BEGIN SELECT RAISE(ABORT, 'keep'); END")
        original = self.snapshot()
        schema = self.sql("SELECT type, name, sql FROM sqlite_master ORDER BY type, name")
        vault.init_db(self.path)
        vault.init_db(self.path)
        self.assertEqual(self.snapshot(), original)
        self.assertEqual(
            self.sql("SELECT type, name, sql FROM sqlite_master ORDER BY type, name"),
            schema,
        )

    def assert_ignored_write_is_atomic(self, event):
        existing = self.transfer(key="existing")
        self.sql(
            f"CREATE TRIGGER block_write {event} "
            "BEGIN SELECT RAISE(IGNORE); END"
        )
        original = self.snapshot()
        trigger_query = "SELECT name, sql FROM sqlite_master WHERE type='trigger' ORDER BY name"
        triggers = self.sql(trigger_query)
        request = dict(
            op="transfer", tenant="alpha", source="source", target="target",
            amount=10, key="ignored",
        )
        generic_error = self.assert_cli_error(
            self.request(dict(op="balance", tenant="alpha", account="absent"))
        )

        # Each call opens a new connection/process. Retrying the same key must
        # neither accumulate partial changes nor reuse a phantom receipt.
        for attempt in range(2):
            with self.subTest(attempt=attempt):
                with self.assertRaises(sqlite3.DatabaseError):
                    self.transfer(key="ignored")
                self.assertEqual(self.snapshot(), original)
                self.assertEqual(self.sql(trigger_query), triggers)
                self.assertEqual(self.assert_cli_error(self.request(request)), generic_error)
                self.assertEqual(self.snapshot(), original)
                self.assertEqual(self.sql(trigger_query), triggers)

        # A committed receipt still replays without any writes, even with the
        # blocking trigger installed. Existing balances and rows stay intact.
        self.assertEqual(self.transfer(key="existing"), existing)
        self.assert_cli_success(self.request(dict(op="transfer", **existing)), existing)
        self.assertEqual(self.snapshot(), original)
        self.assertEqual(self.sql(trigger_query), triggers)

    def test_ignored_debit_rolls_back(self):
        self.assert_ignored_write_is_atomic(
            "BEFORE UPDATE OF balance ON accounts "
            "WHEN NEW.tenant='alpha' AND NEW.name='source'"
        )

    def test_ignored_credit_rolls_back(self):
        self.assert_ignored_write_is_atomic(
            "BEFORE UPDATE OF balance ON accounts "
            "WHEN NEW.tenant='alpha' AND NEW.name='target'"
        )

    def test_ignored_receipt_rolls_back(self):
        self.assert_ignored_write_is_atomic("BEFORE INSERT ON transfers")

    def test_ignored_audit_rolls_back(self):
        self.assert_ignored_write_is_atomic("BEFORE INSERT ON audit")

    def test_nonempty_names_are_preserved_as_literal_strings(self):
        tenant, source, target, key = "tenant' --", "source'; --", " ", "key' --"
        self.sql("INSERT INTO accounts VALUES (?, ?, ?)", [(tenant, source, 7), (tenant, target, 0)])
        expected = dict(tenant=tenant, source=source, target=target, amount=7, key=key)
        self.assertEqual(vault.transfer(self.path, **expected), expected)
        self.assertEqual(vault.balance(self.path, tenant, source), 0)
        self.assertEqual(vault.balance(self.path, tenant, target), 7)

    def concurrent_transfers(self, requests):
        start = threading.Barrier(len(requests))

        def run(request):
            start.wait(timeout=10)
            try:
                return self.transfer(**request)
            except Exception as error:
                return error

        with concurrent.futures.ThreadPoolExecutor(max_workers=len(requests)) as pool:
            return list(pool.map(run, requests))

    def test_concurrent_duplicate_key_executes_once(self):
        expected = dict(tenant="alpha", key="key", source="source", target="target", amount=80)
        results = self.concurrent_transfers([{"amount": 80} for _ in range(8)])
        self.assertEqual(results, [expected] * 8)
        self.assertEqual(vault.balance(self.path, "alpha", "source"), 20)
        self.assertEqual(vault.balance(self.path, "alpha", "target"), 80)
        self.assertEqual(self.sql("SELECT * FROM transfers"), [("alpha", "key", "source", "target", 80)])
        self.assertEqual(self.sql("SELECT * FROM audit"), [("alpha", "key", "source", "target", 80)])
        after = self.snapshot()
        self.assertEqual(self.transfer(amount=80), expected)
        self.assertEqual(self.snapshot(), after)

    def test_concurrent_distinct_keys_never_overspend(self):
        results = self.concurrent_transfers([{"amount": 30, "key": str(i)} for i in range(8)])
        receipts = [result for result in results if isinstance(result, dict)]
        failures = [result for result in results if isinstance(result, ValueError)]
        self.assertEqual(len(receipts), 3, repr(results))
        self.assertEqual(len(failures), 5, repr(results))
        self.assertEqual(vault.balance(self.path, "alpha", "source"), 10)
        self.assertEqual(vault.balance(self.path, "alpha", "target"), 90)
        self.assertEqual(len(self.sql("SELECT * FROM transfers")), 3)
        self.assertEqual(self.sql("SELECT * FROM transfers ORDER BY key"), self.sql("SELECT * FROM audit ORDER BY key"))

    def test_concurrent_credits_from_distinct_sources_are_not_lost(self):
        self.sql("INSERT INTO accounts VALUES (?, ?, ?)", [("alpha", f"source{i}", 10) for i in range(8)])
        results = self.concurrent_transfers(
            [{"source": f"source{i}", "amount": 10, "key": str(i)} for i in range(8)]
        )
        self.assertTrue(all(isinstance(result, dict) for result in results), repr(results))
        self.assertEqual(vault.balance(self.path, "alpha", "target"), 80)
        for i in range(8):
            self.assertEqual(vault.balance(self.path, "alpha", f"source{i}"), 0)
        self.assertEqual(len(self.sql("SELECT * FROM transfers")), 8)
        self.assertEqual(self.sql("SELECT * FROM transfers ORDER BY key"), self.sql("SELECT * FROM audit ORDER BY key"))

    def test_cli_integrated_journey_across_processes(self):
        self.assert_cli_success(self.request(dict(op="balance", tenant="alpha", account="source")), 100)
        receipt = dict(tenant="alpha", source="source", target="target", amount=80, key="journey")
        self.assert_cli_success(self.request(dict(op="transfer", **receipt)), receipt)
        after = self.snapshot()
        self.assert_cli_success(self.request(dict(op="transfer", **receipt)), receipt)
        self.assertEqual(self.snapshot(), after)
        error = self.assert_cli_error(self.request(dict(op="transfer", **dict(receipt, amount=81))))
        self.assertEqual(self.snapshot(), after)
        for account in ("private", "absent"):
            self.assertEqual(
                self.assert_cli_error(self.request(dict(op="balance", tenant="alpha", account=account))),
                error,
            )
        self.assertEqual(
            self.assert_cli_error(self.request(dict(op="transfer", **dict(receipt, key="too-much", amount=21)))),
            error,
        )
        self.assertEqual(self.snapshot(), after)
        beta = dict(receipt, tenant="beta", amount=30)
        self.assert_cli_success(self.request(dict(op="transfer", **beta)), beta)
        for tenant, account, expected in (
            ("alpha", "source", 20), ("alpha", "target", 80),
            ("beta", "source", 970), ("beta", "target", 80),
        ):
            self.assert_cli_success(self.request(dict(op="balance", tenant=tenant, account=account)), expected)
        self.assertEqual(len(self.sql("SELECT * FROM transfers")), 2)
        self.assertEqual(self.sql("SELECT * FROM transfers ORDER BY tenant"), self.sql("SELECT * FROM audit ORDER BY tenant"))

    def test_cli_rejects_malformed_requests_with_one_generic_error(self):
        original = self.snapshot()
        valid = dict(op="transfer", tenant="alpha", source="source", target="target", amount=10, key="key")
        calls = [
            (), (str(self.path),), (str(self.path), "{}", "extra"),
            (str(self.path), "{"), (str(self.path), "[]"), (str(self.path), "null"),
            (str(self.path), "true"), (str(self.path), "42"),
        ]
        malformed = [
            {}, {"op": "unknown"}, {"op": "init_db"}, {"op": "__dict__"},
            {"op": []}, {"op": None}, {"op": "balance", "tenant": "alpha"},
            dict(op="balance", tenant="alpha", account="source", extra=1),
            dict(valid, amount=True), dict(valid, amount=0), dict(valid, amount="10"),
            dict(valid, amount=1.5), dict(valid, tenant=""), dict(valid, target="private"),
            dict(valid, key=None), dict(valid, path=str(self.path)),
        ]
        calls.extend((str(self.path), json.dumps(request)) for request in malformed)
        errors = []
        for arguments in calls:
            with self.subTest(arguments=arguments):
                errors.append(self.assert_cli_error(self.cli(*arguments)))
                self.assertEqual(self.snapshot(), original)
        self.assertTrue(all(error == errors[0] for error in errors))

    def test_cli_storage_failure_is_generic_and_atomic(self):
        self.sql("CREATE TRIGGER audit_failure BEFORE INSERT ON audit BEGIN SELECT RAISE(ABORT, 'beta private SQL INSERT'); END")
        before = self.snapshot()
        request = dict(op="transfer", tenant="alpha", source="source", target="target", amount=10, key="key")
        failure = self.assert_cli_error(self.request(request))
        missing = self.assert_cli_error(self.request(dict(op="balance", tenant="alpha", account="absent")))
        self.assertEqual(failure, missing)
        self.assertNotIn("beta", json.dumps(failure))
        self.assertNotIn("SQL", json.dumps(failure))
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(self.sql("SELECT name FROM sqlite_master WHERE type='trigger'"), [("audit_failure",)])


if __name__ == "__main__":
    unittest.main()
