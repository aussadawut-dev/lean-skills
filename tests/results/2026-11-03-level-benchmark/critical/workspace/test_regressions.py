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


WORKSPACE = Path(__file__).resolve().parent


class VaultRegressionTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(dir=WORKSPACE)
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / "vault.sqlite"
        vault.init_db(self.path)
        with closing(sqlite3.connect(self.path)) as con, con:
            con.executemany(
                "INSERT INTO accounts VALUES (?, ?, ?)",
                [
                    ("alpha", "source", 100),
                    ("alpha", "target", 0),
                    ("alpha", "reserve", 50),
                    ("beta", "source", 200),
                    ("beta", "target", 10),
                    ("beta", "private-account", 77),
                ],
            )

    def snapshot(self):
        with closing(sqlite3.connect(self.path)) as con:
            return {
                table: con.execute(
                    "SELECT * FROM " + table + " ORDER BY rowid"
                ).fetchall()
                for table in ("accounts", "transfers", "audit")
            }

    def request(self, **changes):
        request = dict(
            tenant="alpha", source="source", target="target", amount=10, key="key"
        )
        request.update(changes)
        return request

    def run_cli(self, request=None, *, raw=None, arguments=None):
        if arguments is None:
            if raw is None:
                raw = json.dumps(request)
            arguments = [str(self.path), raw]
        return subprocess.run(
            [sys.executable, "-B", str(WORKSPACE / "app.py"), *arguments],
            cwd=WORKSPACE,
            capture_output=True,
            text=True,
            timeout=15,
        )

    def cli_success(self, request):
        result = self.run_cli(request)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stderr, "")
        self.assertEqual(len(result.stdout.splitlines()), 1)
        return json.loads(result.stdout)

    def cli_error(self, result):
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertEqual(result.stdout, "")
        self.assertEqual(len(result.stderr.splitlines()), 1)
        error = json.loads(result.stderr)
        self.assertEqual(set(error), {"error"})
        self.assertIsInstance(error["error"], str)
        self.assertTrue(error["error"])
        for private_detail in (
            "Traceback", "SELECT", "INSERT", "UPDATE", "beta", "private-account"
        ):
            self.assertNotIn(private_detail, result.stderr)
        return error

    def simultaneously(self, requests):
        barrier = threading.Barrier(len(requests))

        def submit(request):
            barrier.wait(timeout=10)
            try:
                return vault.transfer(self.path, **request)
            except ValueError as exc:
                return exc

        with ThreadPoolExecutor(max_workers=len(requests)) as executor:
            futures = [executor.submit(submit, request) for request in requests]
            return [future.result(timeout=20) for future in futures]

    def test_init_preserves_existing_schema_rows_and_triggers(self):
        vault.transfer(self.path, **self.request())
        with closing(sqlite3.connect(self.path)) as con, con:
            con.execute(
                "CREATE TRIGGER audit_guard BEFORE INSERT ON audit "
                "BEGIN SELECT RAISE(ABORT, 'audit blocked'); END"
            )
            schema = con.execute(
                "SELECT type, name, sql FROM sqlite_master ORDER BY name"
            ).fetchall()
        before = self.snapshot()
        vault.init_db(self.path)
        vault.init_db(self.path)
        self.assertEqual(self.snapshot(), before)
        with closing(sqlite3.connect(self.path)) as con:
            self.assertEqual(
                con.execute(
                    "SELECT type, name, sql FROM sqlite_master ORDER BY name"
                ).fetchall(),
                schema,
            )
            self.assertEqual(
                [row[1] for row in con.execute("PRAGMA table_info(accounts)")],
                ["tenant", "name", "balance"],
            )
            for table in ("transfers", "audit"):
                self.assertEqual(
                    [row[1] for row in con.execute("PRAGMA table_info(" + table + ")")],
                    ["tenant", "key", "source", "target", "amount"],
                )
        with self.assertRaises(sqlite3.IntegrityError):
            vault.transfer(self.path, **self.request(key="new"))
        self.assertEqual(self.snapshot(), before)

    def test_balance_uses_tenant_and_returns_integer(self):
        self.assertEqual(vault.balance(self.path, "alpha", "source"), 100)
        amount = vault.balance(self.path, "beta", "source")
        self.assertEqual(amount, 200)
        self.assertIs(type(amount), int)

    def test_balance_missing_and_inaccessible_have_same_error(self):
        before = self.snapshot()
        messages = []
        for tenant, account in (
            ("alpha", "missing"),
            ("alpha", "private-account"),
            ("missing-tenant", "source"),
        ):
            with self.subTest(tenant=tenant, account=account):
                with self.assertRaises(ValueError) as caught:
                    vault.balance(self.path, tenant, account)
                messages.append(str(caught.exception))
        self.assertEqual(len(set(messages)), 1)
        self.assertNotIn("private-account", messages[0])
        self.assertEqual(self.snapshot(), before)

    def test_balance_rejects_malformed_identifiers_without_writes(self):
        before = self.snapshot()
        for invalid in (None, "", 1, True, [], {}, b"source"):
            for tenant, account in ((invalid, "source"), ("alpha", invalid)):
                with self.subTest(tenant=tenant, account=account):
                    with self.assertRaises(ValueError):
                        vault.balance(self.path, tenant, account)
                    self.assertEqual(self.snapshot(), before)

    def test_transfer_changes_only_the_authenticated_tenant(self):
        receipt = vault.transfer(self.path, **self.request())
        self.assertEqual(receipt, self.request())
        self.assertEqual(vault.balance(self.path, "alpha", "source"), 90)
        self.assertEqual(vault.balance(self.path, "alpha", "target"), 10)
        self.assertEqual(vault.balance(self.path, "beta", "source"), 200)
        self.assertEqual(vault.balance(self.path, "beta", "target"), 10)
        expected = [("alpha", "key", "source", "target", 10)]
        state = self.snapshot()
        self.assertEqual(state["transfers"], expected)
        self.assertEqual(state["audit"], expected)

    def test_transfer_rejects_malformed_fields_without_writes(self):
        before = self.snapshot()
        for field in ("tenant", "source", "target", "key"):
            for invalid in (None, "", 1, True, [], {}, b"source"):
                with self.subTest(field=field, invalid=invalid):
                    with self.assertRaises(ValueError):
                        vault.transfer(self.path, **self.request(**{field: invalid}))
                    self.assertEqual(self.snapshot(), before)
        for invalid in (None, 0, -1, True, False, "10", 1.5, [], {}, float("nan"), float("inf")):
            with self.subTest(amount=invalid):
                with self.assertRaises(ValueError):
                    vault.transfer(self.path, **self.request(amount=invalid))
                self.assertEqual(self.snapshot(), before)

    def test_transfer_requires_distinct_existing_accessible_accounts(self):
        before = self.snapshot()
        with self.assertRaises(ValueError):
            vault.transfer(self.path, **self.request(target="source"))
        self.assertEqual(self.snapshot(), before)
        messages = []
        for field in ("source", "target"):
            for account in ("missing", "private-account"):
                with self.subTest(field=field, account=account):
                    with self.assertRaises(ValueError) as caught:
                        vault.transfer(self.path, **self.request(**{field: account}))
                    messages.append(str(caught.exception))
                    self.assertEqual(self.snapshot(), before)
        self.assertEqual(len(set(messages)), 1)
        self.assertNotIn("private-account", messages[0])

    def test_insufficient_funds_and_huge_amount_do_not_write(self):
        before = self.snapshot()
        for amount in (101, 2**100):
            with self.subTest(amount=amount):
                with self.assertRaises(ValueError):
                    vault.transfer(self.path, **self.request(amount=amount))
                self.assertEqual(self.snapshot(), before)

    def test_integer_balances_stay_exact_at_sqlite_limit(self):
        maximum = 2**63 - 1
        with closing(sqlite3.connect(self.path)) as con, con:
            con.execute(
                "UPDATE accounts SET balance = ? WHERE tenant = ? AND name = ?",
                (maximum - 1, "alpha", "target"),
            )
        vault.transfer(self.path, **self.request(amount=1))
        amount = vault.balance(self.path, "alpha", "target")
        self.assertEqual(amount, maximum)
        self.assertIs(type(amount), int)
        self.assertEqual(vault.balance(self.path, "alpha", "source"), 99)

    def test_unrepresentable_credit_rolls_back_without_losing_precision(self):
        with closing(sqlite3.connect(self.path)) as con, con:
            con.execute(
                "UPDATE accounts SET balance = ? WHERE tenant = ? AND name = ?",
                (2**63 - 1, "alpha", "target"),
            )
        before = self.snapshot()
        with self.assertRaises(OverflowError):
            vault.transfer(self.path, **self.request(amount=1))
        self.assertEqual(self.snapshot(), before)

    def test_exact_replay_survives_reopening_and_exhausted_funds(self):
        request = self.request(amount=100)
        original = vault.transfer(self.path, **request)
        before = self.snapshot()
        vault.init_db(self.path)
        self.assertEqual(vault.transfer(self.path, **request), original)
        self.assertEqual(self.snapshot(), before)
        original["amount"] = 999
        self.assertEqual(vault.transfer(self.path, **request), request)
        self.assertEqual(self.snapshot(), before)

    def test_same_key_with_different_payload_conflicts_without_writes(self):
        vault.transfer(self.path, **self.request())
        before = self.snapshot()
        for change in ({"amount": 11}, {"source": "reserve"}, {"target": "reserve"}):
            with self.subTest(change=change):
                with self.assertRaises(ValueError):
                    vault.transfer(self.path, **self.request(**change))
                self.assertEqual(self.snapshot(), before)

    def test_cached_receipt_does_not_bypass_input_validation(self):
        vault.transfer(self.path, **self.request(amount=1))
        before = self.snapshot()
        for change in ({"amount": True}, {"amount": 1.0}, {"source": ""}, {"target": "source"}):
            with self.subTest(change=change):
                with self.assertRaises(ValueError):
                    vault.transfer(self.path, **self.request(**change))
                self.assertEqual(self.snapshot(), before)

    def assert_cached_receipt_requires_account(self, account):
        vault.transfer(self.path, **self.request())
        with closing(sqlite3.connect(self.path)) as con, con:
            con.execute(
                "DELETE FROM accounts WHERE tenant = ? AND name = ?", ("alpha", account)
            )
        before = self.snapshot()
        with self.assertRaises(ValueError) as transfer_error:
            vault.transfer(self.path, **self.request())
        with self.assertRaises(ValueError) as balance_error:
            vault.balance(self.path, "alpha", account)
        self.assertEqual(str(transfer_error.exception), str(balance_error.exception))
        self.assertEqual(self.snapshot(), before)

    def test_cached_receipt_still_requires_existing_source_in_tenant(self):
        self.assert_cached_receipt_requires_account("source")

    def test_cached_receipt_still_requires_existing_target_in_tenant(self):
        self.assert_cached_receipt_requires_account("target")

    def test_receipts_and_keys_are_tenant_scoped(self):
        first = self.request(amount=40)
        second = self.request(tenant="beta", amount=15)
        self.assertEqual(vault.transfer(self.path, **first), first)
        self.assertEqual(vault.transfer(self.path, **second), second)
        before = self.snapshot()
        self.assertEqual(vault.transfer(self.path, **first), first)
        self.assertEqual(vault.transfer(self.path, **second), second)
        with self.assertRaises(ValueError) as caught:
            vault.transfer(self.path, **self.request(tenant="missing-tenant"))
        self.assertNotIn("alpha", str(caught.exception))
        self.assertNotIn("beta", str(caught.exception))
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(len(before["transfers"]), 2)
        self.assertEqual(len(before["audit"]), 2)
        self.assertEqual(vault.balance(self.path, "alpha", "source"), 60)
        self.assertEqual(vault.balance(self.path, "beta", "source"), 185)

    def test_identifiers_are_literal_strings(self):
        tenant = "tenant' OR 1=1 --"
        source = "source'; DROP TABLE accounts; --"
        target = " "
        key = "key' OR 1=1 --"
        with closing(sqlite3.connect(self.path)) as con, con:
            con.executemany(
                "INSERT INTO accounts VALUES (?, ?, ?)",
                [(tenant, source, 5), (tenant, target, 0)],
            )
        before = self.snapshot()["accounts"][:6]
        request = dict(tenant=tenant, source=source, target=target, amount=2, key=key)
        self.assertEqual(vault.transfer(self.path, **request), request)
        self.assertEqual(vault.balance(self.path, tenant, source), 3)
        self.assertEqual(vault.balance(self.path, tenant, target), 2)
        self.assertEqual(self.snapshot()["accounts"][:6], before)

    def assert_storage_failure_is_atomic(self, event, condition):
        vault.transfer(self.path, **self.request(key="earlier"))
        with closing(sqlite3.connect(self.path)) as con, con:
            con.execute(
                "CREATE TRIGGER reject_storage " + event + " WHEN " + condition
                + " BEGIN SELECT RAISE(FAIL, 'private storage failure'); END"
            )
        before = self.snapshot()
        with self.assertRaises(sqlite3.IntegrityError):
            vault.transfer(self.path, **self.request())
        self.assertEqual(self.snapshot(), before)
        # The trigger remains installed; an allowed tenant can still transact.
        recovery = self.request(tenant="beta", key="recovery", amount=1)
        self.assertEqual(vault.transfer(self.path, **recovery), recovery)
        self.assertEqual(vault.balance(self.path, "alpha", "source"), 90)
        self.assertEqual(vault.balance(self.path, "beta", "source"), 199)

    def test_debit_storage_failure_rolls_back_everything(self):
        self.assert_storage_failure_is_atomic(
            "AFTER UPDATE ON accounts", "NEW.tenant = 'alpha' AND NEW.name = 'source'"
        )

    def test_credit_storage_failure_rolls_back_debit(self):
        self.assert_storage_failure_is_atomic(
            "AFTER UPDATE ON accounts", "NEW.tenant = 'alpha' AND NEW.name = 'target'"
        )

    def test_receipt_storage_failure_rolls_back_both_balances(self):
        self.assert_storage_failure_is_atomic(
            "AFTER INSERT ON transfers", "NEW.tenant = 'alpha'"
        )

    def test_audit_storage_failure_rolls_back_balances_receipt_and_audit(self):
        self.assert_storage_failure_is_atomic(
            "AFTER INSERT ON audit", "NEW.tenant = 'alpha'"
        )

    def test_simultaneous_duplicate_requests_execute_once(self):
        request = self.request()
        results = self.simultaneously([request.copy() for _ in range(8)])
        self.assertEqual(results, [request] * 8)
        self.assertEqual(vault.balance(self.path, "alpha", "source"), 90)
        self.assertEqual(vault.balance(self.path, "alpha", "target"), 10)
        state = self.snapshot()
        self.assertEqual(len(state["transfers"]), 1)
        self.assertEqual(state["audit"], state["transfers"])
        self.assertEqual(vault.transfer(self.path, **request), request)
        self.assertEqual(self.snapshot(), state)

    def test_simultaneous_different_payloads_with_same_key_conflict(self):
        requests = [self.request(amount=amount) for amount in range(1, 9)]
        results = self.simultaneously(requests)
        successes = [result for result in results if isinstance(result, dict)]
        conflicts = [result for result in results if isinstance(result, ValueError)]
        self.assertEqual(len(successes), 1)
        self.assertEqual(len(conflicts), 7)
        amount = successes[0]["amount"]
        self.assertEqual(vault.balance(self.path, "alpha", "source"), 100 - amount)
        self.assertEqual(vault.balance(self.path, "alpha", "target"), amount)
        state = self.snapshot()
        self.assertEqual(len(state["transfers"]), 1)
        self.assertEqual(state["audit"], state["transfers"])

    def test_simultaneous_distinct_keys_never_overspend(self):
        results = self.simultaneously([
            self.request(amount=30, key="key-" + str(index)) for index in range(8)
        ])
        self.assertEqual(sum(isinstance(result, dict) for result in results), 3)
        self.assertEqual(sum(isinstance(result, ValueError) for result in results), 5)
        self.assertEqual(vault.balance(self.path, "alpha", "source"), 10)
        self.assertEqual(vault.balance(self.path, "alpha", "target"), 90)
        self.assertEqual(vault.balance(self.path, "beta", "source"), 200)
        state = self.snapshot()
        self.assertEqual(len(state["transfers"]), 3)
        self.assertEqual(state["audit"], state["transfers"])

    def test_simultaneous_credits_from_distinct_sources_are_preserved(self):
        names = ["payer-" + str(index) for index in range(8)]
        with closing(sqlite3.connect(self.path)) as con, con:
            con.executemany(
                "INSERT INTO accounts VALUES (?, ?, ?)",
                [("alpha", name, 100) for name in names],
            )
        requests = [self.request(source=name, amount=30, key=name) for name in names]
        self.assertEqual(self.simultaneously(requests), requests)
        for name in names:
            self.assertEqual(vault.balance(self.path, "alpha", name), 70)
        self.assertEqual(vault.balance(self.path, "alpha", "target"), 240)
        state = self.snapshot()
        self.assertEqual(len(state["transfers"]), 8)
        self.assertEqual(state["audit"], state["transfers"])

    def test_cli_integrated_journey_and_reopening(self):
        self.assertEqual(self.cli_success(dict(op="balance", tenant="alpha", account="source")), 100)
        first = self.request(amount=100)
        self.assertEqual(self.cli_success(dict(op="transfer", **first)), first)
        self.assertEqual(self.cli_success(dict(op="balance", tenant="alpha", account="source")), 0)
        self.assertEqual(self.cli_success(dict(op="balance", tenant="alpha", account="target")), 100)
        before = self.snapshot()
        self.assertEqual(self.cli_success(dict(op="transfer", **first)), first)
        self.assertEqual(self.snapshot(), before)
        conflict = self.cli_error(self.run_cli(dict(op="transfer", **self.request(amount=99))))
        inaccessible = self.cli_error(self.run_cli(dict(op="balance", tenant="alpha", account="private-account")))
        missing = self.cli_error(self.run_cli(dict(op="balance", tenant="alpha", account="missing")))
        insufficient = self.cli_error(self.run_cli(dict(op="transfer", **self.request(key="new"))))
        self.assertEqual(conflict, inaccessible)
        self.assertEqual(inaccessible, missing)
        self.assertEqual(missing, insufficient)
        self.assertEqual(self.snapshot(), before)
        second = self.request(tenant="beta", amount=15)
        self.assertEqual(self.cli_success(dict(op="transfer", **second)), second)
        self.assertEqual(self.cli_success(dict(op="balance", tenant="beta", account="source")), 185)
        self.assertEqual(self.cli_success(dict(op="balance", tenant="beta", account="target")), 25)
        state = self.snapshot()
        self.assertEqual(len(state["transfers"]), 2)
        self.assertEqual(state["audit"], state["transfers"])

    def test_cli_rejects_bad_json_envelopes_and_dispatch_without_writes(self):
        before = self.snapshot()
        invalid = [
            "{", "null", "[]", '"text"', "1", "true", "{}",
            '{"op": []}', '{"op": {}}', '{"op": 1}',
            '{"op": "init_db"}', '{"op": "__dict__"}', '{"op": "connect"}',
            '{"op": "balance", "tenant": "alpha"}',
            '{"op": "balance", "tenant": "alpha", "account": "source", "extra": 1}',
            '{"op": "balance", "tenant": "alpha", "account": "source", "path": "elsewhere"}',
            json.dumps(dict(op="transfer", **self.request(amount=True))),
            json.dumps(dict(op="transfer", **self.request(amount="10"))),
            json.dumps(dict(op="transfer", **self.request(tenant=[]))),
            json.dumps(dict(op="transfer", **self.request(key=""))),
        ]
        errors = []
        for raw in invalid:
            with self.subTest(raw=raw):
                errors.append(self.cli_error(self.run_cli(raw=raw)))
                self.assertEqual(self.snapshot(), before)
        for arguments in ([], [str(self.path)], [str(self.path), "{}", "extra"]):
            with self.subTest(arguments=arguments):
                errors.append(self.cli_error(self.run_cli(arguments=arguments)))
                self.assertEqual(self.snapshot(), before)
        self.assertTrue(all(error == errors[0] for error in errors))

    def test_cli_storage_failure_is_generic_and_atomic(self):
        with closing(sqlite3.connect(self.path)) as con, con:
            con.execute(
                "CREATE TRIGGER reject_audit AFTER INSERT ON audit "
                "BEGIN SELECT RAISE(FAIL, 'beta private-account SELECT secret'); END"
            )
        before = self.snapshot()
        self.cli_error(self.run_cli(dict(op="transfer", **self.request())))
        self.assertEqual(self.snapshot(), before)


if __name__ == "__main__":
    unittest.main()
