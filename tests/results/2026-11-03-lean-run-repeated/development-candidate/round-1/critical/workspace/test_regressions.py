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
        self.tmp = tempfile.TemporaryDirectory(dir=WORKSPACE)
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "vault.sqlite"
        vault.init_db(self.path)
        self.execute(
            "INSERT INTO accounts VALUES (?, ?, ?)",
            [
                ("red", "source", 100),
                ("red", "target", 20),
                ("blue", "source", 500),
                ("blue", "target", 50),
                ("blue", "private", 77),
            ],
            many=True,
        )

    def execute(self, sql, parameters=(), *, many=False):
        with closing(sqlite3.connect(self.path)) as con, con:
            if many:
                con.executemany(sql, parameters)
            else:
                con.execute(sql, parameters)

    def rows(self, sql, parameters=()):
        with closing(sqlite3.connect(self.path)) as con:
            return con.execute(sql, parameters).fetchall()

    def snapshot(self):
        return {
            table: self.rows(f"SELECT * FROM {table} ORDER BY rowid")
            for table in ("accounts", "transfers", "audit")
        }

    def request(self, **changes):
        fields = dict(
            tenant="red", source="source", target="target", amount=10, key="k"
        )
        fields.update(changes)
        return fields

    def send(self, **changes):
        return vault.transfer(self.path, **self.request(**changes))

    def assert_rejected(self, call, exception=ValueError):
        before = self.snapshot()
        try:
            with self.assertRaises(exception) as caught:
                call()
        finally:
            self.assertEqual(self.snapshot(), before)
        return str(caught.exception)

    def assert_single_transfer(self, receipt, source_balance, target_balance):
        self.assertEqual(
            vault.balance(self.path, receipt["tenant"], receipt["source"]),
            source_balance,
        )
        self.assertEqual(
            vault.balance(self.path, receipt["tenant"], receipt["target"]),
            target_balance,
        )
        expected = [tuple(receipt[name] for name in
                          ("tenant", "key", "source", "target", "amount"))]
        for table in ("transfers", "audit"):
            self.assertEqual(
                self.rows(
                    f"SELECT * FROM {table} WHERE tenant=? AND key=?",
                    (receipt["tenant"], receipt["key"]),
                ),
                expected,
            )

    def test_balance_is_tenant_scoped(self):
        self.assertEqual(vault.balance(self.path, "blue", "source"), 500)
        self.assertEqual(vault.balance(self.path, "red", "source"), 100)

    def test_missing_and_inaccessible_accounts_have_same_generic_error(self):
        errors = []
        for tenant, account in (
            ("red", "private"), ("red", "absent"), ("absent", "source")
        ):
            with self.subTest(tenant=tenant, account=account):
                errors.append(self.assert_rejected(
                    lambda: vault.balance(self.path, tenant, account)
                ))
        for source, target in (
            ("private", "target"), ("absent", "target"),
            ("source", "private"), ("source", "absent"),
        ):
            with self.subTest(source=source, target=target):
                errors.append(self.assert_rejected(
                    lambda: self.send(source=source, target=target)
                ))
        self.assertEqual(len(set(errors)), 1)
        for detail in ("red", "blue", "private", "absent", "77", "500"):
            self.assertNotIn(detail, errors[0])

    def test_balance_rejects_invalid_identifiers(self):
        for field in ("tenant", "account"):
            for value in (None, "", 1, True, b"red", [], {}):
                with self.subTest(field=field, value=value):
                    fields = dict(tenant="red", account="source")
                    fields[field] = value
                    self.assert_rejected(lambda: vault.balance(self.path, **fields))

    def test_transfer_rejects_invalid_fields_without_writes(self):
        invalid = {
            field: (None, "", 1, True, b"x", [], {})
            for field in ("tenant", "source", "target", "key")
        }
        invalid["amount"] = (0, -1, True, False, 1.0, "10", None, [], {})
        for field, values in invalid.items():
            for value in values:
                with self.subTest(field=field, value=value):
                    self.assert_rejected(lambda: self.send(**{field: value}))

    def test_transfer_requires_distinct_accounts_and_sufficient_funds(self):
        for changes in (
            dict(target="source"), dict(amount=101), dict(amount=2**100),
            dict(tenant="absent"),
        ):
            with self.subTest(changes=changes):
                self.assert_rejected(lambda: self.send(**changes))

    def test_transfer_changes_only_its_tenant_and_records_all_effects(self):
        blue_before = self.rows("SELECT * FROM accounts WHERE tenant='blue'")
        receipt = self.send(amount=100)
        self.assertEqual(receipt, self.request(amount=100))
        self.assert_single_transfer(receipt, 0, 120)
        self.assertEqual(
            self.rows("SELECT * FROM accounts WHERE tenant='blue'"), blue_before
        )

    def test_identifiers_are_opaque_nonempty_strings(self):
        tenant, source, target, key = "t' OR 1=1 --", " α ", " ", "k'--"
        self.execute(
            "INSERT INTO accounts VALUES (?, ?, ?)",
            [(tenant, source, 12), (tenant, target, 0)], many=True,
        )
        before = self.rows("SELECT * FROM accounts WHERE tenant != ?", (tenant,))
        receipt = self.send(
            tenant=tenant, source=source, target=target, key=key, amount=7
        )
        self.assert_single_transfer(receipt, 5, 7)
        self.assertEqual(
            self.rows("SELECT * FROM accounts WHERE tenant != ?", (tenant,)), before
        )

    def test_exact_replay_survives_reopening_and_changed_funds(self):
        original = self.send(amount=80)
        self.send(amount=20, key="drain")
        self.execute("""
            CREATE TRIGGER fail_audit BEFORE INSERT ON audit
            BEGIN SELECT RAISE(ABORT, 'audit unavailable'); END
        """)
        before = self.snapshot()
        vault.init_db(self.path)
        self.assertEqual(self.send(amount=80), original)
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(len(self.rows(
            "SELECT name FROM sqlite_master WHERE type='trigger' AND name='fail_audit'"
        )), 1)

    def test_same_key_conflicts_on_any_changed_payload(self):
        self.send()
        for changes in (
            dict(amount=11), dict(source="target", target="source"),
            dict(source="private"), dict(target="private"),
        ):
            with self.subTest(changes=changes):
                self.assert_rejected(lambda: self.send(**changes))

    def test_cached_replay_still_rejects_bool_and_float_amounts(self):
        self.send(amount=1)
        for amount in (True, 1.0):
            with self.subTest(amount=amount):
                self.assert_rejected(lambda: self.send(amount=amount))

    def test_key_and_receipt_are_scoped_to_tenant(self):
        blue = self.send(tenant="blue", amount=35)
        red = self.send(amount=10)
        self.assertEqual(blue, self.request(tenant="blue", amount=35))
        self.assertEqual(red, self.request(amount=10))
        self.assert_single_transfer(blue, 465, 85)
        self.assert_single_transfer(red, 90, 30)
        self.assertEqual(self.send(tenant="blue", amount=35), blue)
        self.assertEqual(self.send(amount=10), red)

    def test_cached_receipt_cannot_authorize_another_tenants_missing_accounts(self):
        self.send(tenant="blue", source="private", amount=5)
        self.assert_rejected(lambda: self.send(source="private", amount=5))

    def test_init_preserves_schema_rows_and_triggers(self):
        self.send()
        self.execute("""
            CREATE TRIGGER retained BEFORE INSERT ON audit
            BEGIN SELECT RAISE(ABORT, 'retained'); END
        """)
        before = self.snapshot()
        schema = self.rows("SELECT type, name, sql FROM sqlite_master ORDER BY name")
        vault.init_db(self.path)
        vault.init_db(self.path)
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(
            self.rows("SELECT type, name, sql FROM sqlite_master ORDER BY name"), schema
        )

    def test_storage_failures_roll_back_all_four_effects(self):
        phases = (
            "UPDATE ON accounts WHEN OLD.tenant='red' AND OLD.name='source'",
            "UPDATE ON accounts WHEN OLD.tenant='red' AND OLD.name='target'",
            "INSERT ON transfers", "INSERT ON audit",
        )
        for action in ("ABORT", "FAIL", "ROLLBACK", "IGNORE"):
            statement = (
                "SELECT RAISE(IGNORE)" if action == "IGNORE"
                else f"SELECT RAISE({action}, 'storage failure')"
            )
            for phase in phases:
                with self.subTest(action=action, phase=phase):
                    self.execute(f"""
                        CREATE TRIGGER fault BEFORE {phase}
                        BEGIN {statement}; END
                    """)
                    try:
                        message = self.assert_rejected(self.send, sqlite3.DatabaseError)
                        if action != "IGNORE":
                            self.assertEqual(message, "storage failure")
                        self.assertEqual(len(self.rows(
                            "SELECT name FROM sqlite_master WHERE name='fault'"
                        )), 1)
                    finally:
                        self.execute("DROP TRIGGER fault")
        receipt = self.send()
        self.assert_single_transfer(receipt, 90, 30)

    def test_silent_trigger_side_effects_cannot_leave_partial_transfers(self):
        bodies = (
            ("UPDATE ON accounts WHEN NEW.tenant='red' AND NEW.name='source'", """
                UPDATE accounts SET balance=OLD.balance
                WHERE tenant=OLD.tenant AND name=OLD.name;
            """),
            ("UPDATE ON accounts WHEN NEW.tenant='red' AND NEW.name='target'", """
                UPDATE accounts SET balance=OLD.balance
                WHERE tenant=OLD.tenant AND name=OLD.name;
            """),
            ("INSERT ON transfers", "DELETE FROM transfers WHERE rowid=NEW.rowid;"),
            ("INSERT ON audit", "DELETE FROM audit WHERE rowid=NEW.rowid;"),
        )
        for phase, body in bodies:
            with self.subTest(phase=phase):
                self.execute(f"CREATE TRIGGER fault AFTER {phase} BEGIN {body} END")
                try:
                    self.assert_rejected(self.send, sqlite3.DatabaseError)
                finally:
                    self.execute("DROP TRIGGER fault")

    def test_partial_trigger_writes_roll_back_with_ignored_audit(self):
        self.execute("""
            CREATE TRIGGER fault BEFORE INSERT ON audit WHEN NEW.key='k' BEGIN
                UPDATE accounts SET balance=999 WHERE tenant='red' AND name='target';
                INSERT INTO audit VALUES ('red', 'side-effect', 'source', 'target', 1);
                SELECT RAISE(IGNORE);
            END
        """)
        self.assert_rejected(self.send, sqlite3.DatabaseError)

    def test_sqlite_integer_boundary_remains_exact(self):
        maximum = 2**63 - 1
        self.execute(
            "UPDATE accounts SET balance=? WHERE tenant='red' AND name='target'",
            (maximum - 1,),
        )
        receipt = self.send(amount=1)
        self.assert_single_transfer(receipt, 99, maximum)
        self.assertIsInstance(vault.balance(self.path, "red", "target"), int)
        self.assert_rejected(lambda: self.send(amount=1, key="overflow"))

    def concurrently(self, requests):
        start = threading.Barrier(len(requests))

        def run(request):
            start.wait(timeout=10)
            try:
                return vault.transfer(self.path, **request)
            except ValueError as error:
                return error

        with ThreadPoolExecutor(max_workers=len(requests)) as pool:
            return list(pool.map(run, requests))

    def test_concurrent_duplicate_requests_execute_once(self):
        request = self.request(amount=75)
        receipts = self.concurrently([request] * 8)
        self.assertEqual(receipts, [request] * 8)
        self.assert_single_transfer(request, 25, 95)
        before = self.snapshot()
        self.assertEqual(self.send(amount=75), request)
        self.assertEqual(self.snapshot(), before)

    def test_concurrent_conflicting_payloads_have_only_one_winner(self):
        requests = [self.request(amount=20), self.request(amount=30)] * 4
        results = self.concurrently(requests)
        successes = [result for result in results if isinstance(result, dict)]
        self.assertEqual(len(successes), 4)
        winner = successes[0]
        for request, result in zip(requests, results):
            if request == winner:
                self.assertEqual(result, winner)
            else:
                self.assertIsInstance(result, ValueError)
        self.assert_single_transfer(winner, 100 - winner["amount"], 20 + winner["amount"])

    def test_concurrent_distinct_keys_never_overspend_or_lose_credits(self):
        results = self.concurrently([
            self.request(amount=30, key=f"k{index}") for index in range(8)
        ])
        receipts = [result for result in results if isinstance(result, dict)]
        failures = [result for result in results if isinstance(result, ValueError)]
        self.assertEqual(len(receipts), 3)
        self.assertEqual(len(failures), 5)
        self.assertEqual(vault.balance(self.path, "red", "source"), 10)
        self.assertEqual(vault.balance(self.path, "red", "target"), 110)
        expected = sorted(tuple(receipt[field] for field in
                                ("tenant", "key", "source", "target", "amount"))
                          for receipt in receipts)
        self.assertEqual(sorted(self.snapshot()["transfers"]), expected)
        self.assertEqual(sorted(self.snapshot()["audit"]), expected)
        self.assertEqual(vault.balance(self.path, "blue", "source"), 500)
        self.assertEqual(vault.balance(self.path, "blue", "target"), 50)

    def test_concurrent_credits_from_distinct_sources_are_all_retained(self):
        self.execute(
            "INSERT INTO accounts VALUES (?, ?, ?)",
            [("red", f"payer{index}", 100) for index in range(8)], many=True,
        )
        requests = [self.request(source=f"payer{i}", amount=10, key=f"k{i}")
                    for i in range(8)]
        self.assertEqual(self.concurrently(requests), requests)
        self.assertEqual(vault.balance(self.path, "red", "target"), 100)
        for request in requests:
            self.assertEqual(vault.balance(self.path, "red", request["source"]), 90)
        self.assertEqual(len(self.snapshot()["transfers"]), 8)
        self.assertEqual(len(self.snapshot()["audit"]), 8)

    def test_concurrent_same_key_is_independent_for_each_tenant(self):
        requests = [self.request(tenant="red", amount=40),
                    self.request(tenant="blue", amount=60)] * 4
        self.assertEqual(self.concurrently(requests), requests)
        self.assert_single_transfer(requests[0], 60, 60)
        self.assert_single_transfer(requests[1], 440, 110)

    def cli(self, request, *, path=None):
        raw = request if isinstance(request, str) else json.dumps(request)
        return subprocess.run(
            [sys.executable, "-B", str(WORKSPACE / "app.py"),
             str(self.path if path is None else path), raw],
            cwd=WORKSPACE, capture_output=True, text=True, timeout=15,
        )

    def assert_cli_success(self, result, expected):
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stderr, "")
        self.assertEqual(len(result.stdout.splitlines()), 1)
        self.assertEqual(json.loads(result.stdout), expected)

    def assert_cli_error(self, result):
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertEqual(result.stdout, "")
        self.assertEqual(len(result.stderr.splitlines()), 1)
        error = json.loads(result.stderr)
        self.assertEqual(set(error), {"error"})
        self.assertIsInstance(error["error"], str)
        self.assertTrue(error["error"])
        return error

    def test_cli_integrated_transfer_replay_conflict_and_tenant_journey(self):
        self.assert_cli_success(
            self.cli(dict(op="balance", tenant="blue", account="source")), 500
        )
        request = self.request(amount=25)
        self.assert_cli_success(self.cli(dict(op="transfer", **request)), request)
        self.assert_single_transfer(request, 75, 45)
        before_replay = self.snapshot()
        self.assert_cli_success(self.cli(dict(op="transfer", **request)), request)
        self.assertEqual(self.snapshot(), before_replay)
        self.assert_cli_error(self.cli(dict(op="transfer", **self.request(amount=26))))
        self.assertEqual(self.snapshot(), before_replay)
        blue = self.request(tenant="blue", amount=60)
        self.assert_cli_success(self.cli(dict(op="transfer", **blue)), blue)
        self.assert_single_transfer(blue, 440, 110)
        self.assert_cli_success(
            self.cli(dict(op="balance", tenant="red", account="target")), 45
        )
        self.assert_cli_success(
            self.cli(dict(op="balance", tenant="blue", account="target")), 110
        )

    def test_cli_invalid_requests_have_one_generic_error_and_no_writes(self):
        cases = (
            "{", "null", "[]", "42", '"balance"', {},
            dict(op="init_db"), dict(op="connect"), dict(op="__dict__"),
            dict(op=[]), dict(op="balance", tenant="red"),
            dict(op="balance", tenant="red", account="source", extra="secret"),
            dict(op="balance", tenant="red", account="private"),
            dict(op="balance", tenant="red", account="absent"),
            dict(op="balance", tenant="", account="source"),
            dict(op="transfer", **self.request(amount=True)),
            dict(op="transfer", **self.request(amount=101)),
            dict(op="transfer", **self.request(target="private")),
            dict(op="transfer", **self.request(target="source")),
        )
        errors = []
        before = self.snapshot()
        for request in cases:
            with self.subTest(request=request):
                errors.append(self.assert_cli_error(self.cli(request)))
                self.assertEqual(self.snapshot(), before)
        self.assertTrue(all(error == errors[0] for error in errors))
        for detail in ("blue", "private", "source", "77", "SELECT", "Traceback"):
            self.assertNotIn(detail, json.dumps(errors[0]))

    def test_cli_argument_errors_are_generic(self):
        requests = [[], [str(self.path)],
                    [str(self.path), '{}', 'unexpected']]
        for arguments in requests:
            with self.subTest(arguments=arguments):
                result = subprocess.run(
                    [sys.executable, "-B", str(WORKSPACE / "app.py"), *arguments],
                    cwd=WORKSPACE, capture_output=True, text=True, timeout=15,
                )
                self.assert_cli_error(result)

    def test_cli_storage_failure_rolls_back_and_recovery_reuses_key(self):
        self.execute("""
            CREATE TRIGGER fault BEFORE INSERT ON audit
            BEGIN SELECT RAISE(ABORT, 'private blue SQL INSERT secret'); END
        """)
        request = dict(op="transfer", **self.request())
        before = self.snapshot()
        error = self.assert_cli_error(self.cli(request))
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(error, self.assert_cli_error(self.cli("{")))
        self.assertEqual(len(self.rows(
            "SELECT name FROM sqlite_master WHERE name='fault'"
        )), 1)
        self.execute("DROP TRIGGER fault")
        self.assert_cli_success(self.cli(request), self.request())
        self.assert_single_transfer(self.request(), 90, 30)

    def test_cli_unavailable_database_is_generic(self):
        self.assert_cli_error(self.cli(
            dict(op="balance", tenant="red", account="source"),
            path=Path(self.tmp.name) / "absent" / "vault.sqlite",
        ))


if __name__ == "__main__":
    unittest.main()
