from contextlib import closing
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
from threading import Barrier
import unittest

import vault


ROOT = Path(__file__).resolve().parent


class TransferRegressionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(dir=ROOT)
        self.addCleanup(self.tmp.cleanup)
        self.new_database("ledger")

    def new_database(self, name):
        self.path = Path(self.tmp.name) / (name + ".sqlite")
        vault.init_db(self.path)
        self.execute_many(
            "INSERT INTO accounts VALUES (?,?,?)",
            [
                ("alpha", "cash", 100),
                ("alpha", "savings", 0),
                ("beta", "cash", 900),
                ("beta", "savings", 200),
                ("beta", "private", 7),
            ],
        )

    def execute_many(self, sql, rows):
        with closing(sqlite3.connect(self.path)) as con, con:
            con.executemany(sql, rows)

    def execute(self, sql):
        with closing(sqlite3.connect(self.path)) as con, con:
            con.execute(sql)

    def snapshot(self):
        with closing(sqlite3.connect(self.path)) as con:
            return {
                table: sorted(con.execute("SELECT * FROM " + table).fetchall(), key=repr)
                for table in ("accounts", "transfers", "audit")
            }

    def run_cli(self, request):
        return self.run_cli_args([str(self.path), json.dumps(request)])

    def run_cli_args(self, args):
        return subprocess.run(
            [sys.executable, "-B", str(ROOT / "app.py"), *args],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
            timeout=15,
        )

    def assert_cli_error(self, result):
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertEqual(result.stdout, "")
        self.assertEqual(json.loads(result.stderr), {"error": "invalid request"})
        self.assertEqual(len(result.stderr.splitlines()), 1)

    def assert_cli_success(self, result, expected):
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stderr, "")
        self.assertEqual(json.loads(result.stdout), expected)
        self.assertEqual(len(result.stdout.splitlines()), 1)

    def assert_applied(self, before, receipts):
        """Check all balances, history and row multiplicities, including other tenants."""
        accounts = {(tenant, name): funds for tenant, name, funds in before["accounts"]}
        history = []
        for receipt in receipts:
            tenant = receipt["tenant"]
            accounts[tenant, receipt["source"]] -= receipt["amount"]
            accounts[tenant, receipt["target"]] += receipt["amount"]
            history.append(tuple(receipt[field] for field in ("tenant", "key", "source", "target", "amount")))
        expected = {
            "accounts": sorted([(tenant, name, funds) for (tenant, name), funds in accounts.items()], key=repr),
            "transfers": sorted(before["transfers"] + history, key=repr),
            "audit": sorted(before["audit"] + history, key=repr),
        }
        self.assertEqual(self.snapshot(), expected)

    def concurrent_transfers(self, requests):
        start = Barrier(len(requests))

        def run(request):
            start.wait(timeout=10)
            try:
                return vault.transfer(self.path, **request), None
            except ValueError as error:
                return None, str(error)

        with ThreadPoolExecutor(max_workers=len(requests)) as pool:
            return list(pool.map(run, requests, timeout=30))

    def request(self, **changes):
        request = dict(tenant="alpha", source="cash", target="savings", amount=10, key="key")
        request.update(changes)
        return request

    def test_balance_is_scoped_to_tenant(self):
        self.assertEqual(vault.balance(self.path, "beta", "cash"), 900)

    def test_receipts_are_scoped_to_tenant(self):
        first = vault.transfer(self.path, "alpha", "cash", "savings", 10, "shared")
        second = vault.transfer(self.path, "beta", "cash", "savings", 10, "shared")
        self.assertEqual(first["tenant"], "alpha")
        self.assertEqual(second["tenant"], "beta")
        self.assertEqual(vault.balance(self.path, "alpha", "cash"), 90)
        self.assertEqual(vault.balance(self.path, "beta", "cash"), 890)

    def test_audit_failure_rolls_back_every_effect(self):
        self.execute(
            "CREATE TRIGGER reject_audit BEFORE INSERT ON audit "
            "BEGIN SELECT RAISE(ABORT, 'audit unavailable'); END"
        )
        before = self.snapshot()
        with self.assertRaises(sqlite3.IntegrityError):
            vault.transfer(self.path, "alpha", "cash", "savings", 10, "audit-failure")
        self.assertEqual(self.snapshot(), before)

    def test_cli_missing_account_has_generic_json_error(self):
        result = self.run_cli({"op": "balance", "tenant": "alpha", "account": "missing"})
        self.assert_cli_error(result)

    def test_missing_and_foreign_accounts_have_identical_errors(self):
        before = self.snapshot()
        errors = []
        for account in ("missing", "private"):
            with self.subTest(account=account):
                with self.assertRaises(ValueError) as caught:
                    vault.balance(self.path, "alpha", account)
                errors.append(str(caught.exception))
                for field in ("source", "target"):
                    with self.assertRaises(ValueError) as caught:
                        vault.transfer(self.path, **self.request(**{field: account}))
                    errors.append(str(caught.exception))
                self.assertEqual(self.snapshot(), before)
        self.assertEqual(set(errors), {"account unavailable"})
        with self.assertRaisesRegex(ValueError, "^account unavailable$"):
            vault.balance(self.path, "unknown-tenant", "cash")

    def test_malformed_names_are_rejected_without_writes(self):
        before = self.snapshot()
        invalid = (None, "", 0, False, [], {}, b"alpha")
        for field in ("tenant", "source", "target", "key"):
            for value in invalid:
                with self.subTest(field=field, value=value):
                    with self.assertRaises(ValueError):
                        vault.transfer(self.path, **self.request(**{field: value}))
                    self.assertEqual(self.snapshot(), before)
        for field in ("tenant", "account"):
            for value in invalid:
                with self.subTest(field=field, value=value):
                    request = dict(tenant="alpha", account="cash")
                    request[field] = value
                    with self.assertRaises(ValueError):
                        vault.balance(self.path, **request)
                    self.assertEqual(self.snapshot(), before)

    def test_invalid_amounts_same_account_and_overdraft_do_not_write(self):
        before = self.snapshot()
        invalid = (0, -1, True, False, 1.0, "1", None, [], {}, float("nan"), float("inf"), 101, 2**100)
        requests = [self.request(amount=value) for value in invalid]
        requests.append(self.request(target="cash"))
        for request in requests:
            with self.subTest(request=request):
                with self.assertRaises(ValueError):
                    vault.transfer(self.path, **request)
                self.assertEqual(self.snapshot(), before)

    def test_valid_identifiers_are_bound_literally(self):
        for index, tenant in enumerate((" ", "租户'; SELECT * FROM accounts; --")):
            with self.subTest(tenant=tenant):
                source, target, key = "cash\x00'", "储蓄 ", "key'; DROP TABLE audit; --"
                self.execute_many("INSERT INTO accounts VALUES (?,?,?)", [(tenant, source, 10), (tenant, target, 0)])
                before = self.snapshot()
                receipt = vault.transfer(self.path, tenant, source, target, 1, key)
                self.assertEqual(receipt, dict(tenant=tenant, source=source, target=target, amount=1, key=key))
                self.assert_applied(before, [receipt])
                funds = vault.balance(self.path, tenant, source)
                self.assertIs(type(funds), int)
                self.assertEqual(funds, 9)

    def test_replay_survives_reopening_and_owns_its_receipt(self):
        request = self.request(amount=100)
        before = self.snapshot()
        first = vault.transfer(self.path, **request)
        self.assertEqual(first, request)
        self.assert_applied(before, [first])
        committed = self.snapshot()
        first.update(tenant="beta", amount=-1)
        vault.init_db(self.path)
        replay = vault.transfer(self.path, **request)
        self.assertEqual(replay, request)
        self.assertIsNot(replay, first)
        self.assertEqual(self.snapshot(), committed)

    def test_key_conflicts_reject_each_changed_payload_without_writes(self):
        self.execute_many("INSERT INTO accounts VALUES (?,?,?)", [("alpha", "third", 50)])
        vault.transfer(self.path, **self.request())
        before = self.snapshot()
        for change in ({"source": "third"}, {"target": "third"}, {"amount": 11}):
            with self.subTest(change=change):
                with self.assertRaisesRegex(ValueError, "^key conflict$"):
                    vault.transfer(self.path, **self.request(**change))
                self.assertEqual(self.snapshot(), before)
        # Validation still applies to an otherwise matching replay.
        with self.assertRaises(ValueError):
            vault.transfer(self.path, **self.request(amount=10.0))
        self.assertEqual(self.snapshot(), before)

    def test_foreign_malformed_data_does_not_affect_reads_or_writes(self):
        self.execute("UPDATE accounts SET balance='not a number' WHERE tenant='beta' AND name='cash'")
        self.execute_many(
            "INSERT INTO transfers VALUES (?,?,?,?,?)",
            [("beta", "key", "private", "cash", sqlite3.Binary(b"\xff"))],
        )
        before = self.snapshot()
        self.assertEqual(vault.balance(self.path, "alpha", "cash"), 100)
        receipt = vault.transfer(self.path, **self.request())
        self.assertEqual(receipt, self.request())
        self.assert_applied(before, [receipt])

    def test_init_preserves_existing_schema_rows_and_triggers(self):
        history = ("beta", "history", "cash", "savings", 4)
        self.execute_many("INSERT INTO transfers VALUES (?,?,?,?,?)", [history])
        self.execute_many("INSERT INTO audit VALUES (?,?,?,?,?)", [history, history])
        self.execute("CREATE INDEX audit_history ON audit(tenant,key)")
        self.execute(
            "CREATE TRIGGER existing_trigger BEFORE INSERT ON audit "
            "WHEN NEW.key='blocked' BEGIN SELECT RAISE(ABORT, 'existing rule'); END"
        )
        before = self.snapshot()
        with closing(sqlite3.connect(self.path)) as con:
            schema = con.execute("SELECT type,name,tbl_name,sql FROM sqlite_master ORDER BY name").fetchall()
        vault.init_db(self.path)
        vault.init_db(self.path)
        with closing(sqlite3.connect(self.path)) as con:
            self.assertEqual(con.execute("SELECT type,name,tbl_name,sql FROM sqlite_master ORDER BY name").fetchall(), schema)
        self.assertEqual(self.snapshot(), before)
        receipt = vault.transfer(self.path, **self.request())
        self.assert_applied(before, [receipt])
        committed = self.snapshot()
        with self.assertRaises(sqlite3.IntegrityError):
            vault.transfer(self.path, **self.request(key="blocked"))
        self.assertEqual(self.snapshot(), committed)

    def test_failures_at_each_write_boundary_roll_back_and_allow_valid_control(self):
        cases = (
            ("BEFORE", "UPDATE", "accounts", "NEW.name='cash' AND NEW.balance=90"),
            ("BEFORE", "UPDATE", "accounts", "NEW.name='savings' AND NEW.balance=10"),
            ("BEFORE", "INSERT", "transfers", "NEW.key='blocked'"),
            ("BEFORE", "INSERT", "audit", "NEW.key='blocked'"),
            ("AFTER", "INSERT", "audit", "NEW.key='blocked'"),
        )
        for index, (timing, event, table, condition) in enumerate(cases):
            with self.subTest(timing=timing, table=table, condition=condition):
                self.new_database("failure-" + str(index))
                trigger = (
                    f"CREATE TRIGGER reject_write {timing} {event} ON {table} "
                    f"WHEN {condition} BEGIN SELECT RAISE(ABORT, 'write unavailable'); END"
                )
                self.execute(trigger)
                before = self.snapshot()
                with self.assertRaises(sqlite3.IntegrityError):
                    vault.transfer(self.path, **self.request(key="blocked"))
                self.assertEqual(self.snapshot(), before)
                receipt = vault.transfer(self.path, **self.request(amount=1, key="control"))
                self.assert_applied(before, [receipt])
                with closing(sqlite3.connect(self.path)) as con:
                    self.assertEqual(con.execute("SELECT sql FROM sqlite_master WHERE name='reject_write'").fetchone()[0], trigger)

    def test_ignored_required_writes_roll_back(self):
        cases = (
            ("UPDATE", "accounts", "NEW.name='cash'"),
            ("UPDATE", "accounts", "NEW.name='savings'"),
            ("INSERT", "transfers", "1"),
            ("INSERT", "audit", "1"),
        )
        for index, (event, table, condition) in enumerate(cases):
            with self.subTest(table=table, condition=condition):
                self.new_database("ignored-" + str(index))
                self.execute(
                    f"CREATE TRIGGER ignore_write BEFORE {event} ON {table} "
                    f"WHEN {condition} BEGIN SELECT RAISE(IGNORE); END"
                )
                before = self.snapshot()
                with self.assertRaises(sqlite3.IntegrityError):
                    vault.transfer(self.path, **self.request())
                self.assertEqual(self.snapshot(), before)

    def test_storage_integer_limit_does_not_lose_credits(self):
        maximum = 2**63 - 1
        self.execute_many("UPDATE accounts SET balance=? WHERE tenant=? AND name=?", [(maximum, "alpha", "savings")])
        before = self.snapshot()
        with self.assertRaises(OverflowError):
            vault.transfer(self.path, **self.request(amount=1))
        self.assertEqual(self.snapshot(), before)
        self.execute_many(
            "UPDATE accounts SET balance=? WHERE tenant=? AND name=?",
            [(maximum, "alpha", "cash"), (0, "alpha", "savings")],
        )
        before = self.snapshot()
        receipt = vault.transfer(self.path, **self.request(amount=maximum))
        self.assert_applied(before, [receipt])
        funds = vault.balance(self.path, "alpha", "savings")
        self.assertIs(type(funds), int)
        self.assertEqual(funds, maximum)

    def test_simultaneous_duplicates_execute_once_in_both_journal_modes(self):
        for journal in ("DELETE", "WAL"):
            with self.subTest(journal=journal):
                self.new_database("duplicate-" + journal)
                self.execute("PRAGMA journal_mode=" + journal)
                before = self.snapshot()
                request = self.request(amount=100)
                outcomes = self.concurrent_transfers([request.copy() for _ in range(12)])
                self.assertEqual(outcomes, [(request, None)] * 12)
                self.assert_applied(before, [request])
                committed = self.snapshot()
                self.assertEqual(vault.transfer(self.path, **request), request)
                self.assertEqual(self.snapshot(), committed)

    def test_simultaneous_distinct_keys_never_overspend(self):
        before = self.snapshot()
        outcomes = self.concurrent_transfers([self.request(key=str(index)) for index in range(20)])
        receipts = [receipt for receipt, error in outcomes if receipt is not None]
        errors = [error for receipt, error in outcomes if error is not None]
        self.assertEqual(len(receipts), 10)
        self.assertEqual(errors, ["insufficient funds"] * 10)
        self.assert_applied(before, receipts)
        self.assertEqual(vault.balance(self.path, "alpha", "cash"), 0)
        self.assertEqual(vault.balance(self.path, "alpha", "savings"), 100)

    def test_simultaneous_credits_from_distinct_accounts_are_not_lost(self):
        self.execute_many("INSERT INTO accounts VALUES (?,?,?)", [("alpha", "donor-" + str(i), 20) for i in range(12)])
        before = self.snapshot()
        requests = [self.request(source="donor-" + str(i), amount=20, key=str(i)) for i in range(12)]
        outcomes = self.concurrent_transfers(requests)
        self.assertEqual(outcomes, [(request, None) for request in requests])
        self.assert_applied(before, requests)
        self.assertEqual(vault.balance(self.path, "alpha", "savings"), 240)

    def test_simultaneous_conflicting_key_has_one_winner(self):
        before = self.snapshot()
        requests = [self.request(amount=10), self.request(amount=20)]
        outcomes = self.concurrent_transfers(requests)
        receipts = [receipt for receipt, error in outcomes if receipt is not None]
        errors = [error for receipt, error in outcomes if error is not None]
        self.assertEqual(len(receipts), 1)
        self.assertIn(receipts[0], requests)
        self.assertEqual(errors, ["key conflict"])
        self.assert_applied(before, receipts)

    def test_simultaneous_tenants_can_use_the_same_key(self):
        before = self.snapshot()
        requests = [self.request(), self.request(tenant="beta")]
        outcomes = self.concurrent_transfers(requests)
        self.assertEqual(outcomes, [(request, None) for request in requests])
        self.assert_applied(before, requests)

    def test_cli_rejects_malformed_payloads_and_arguments_without_writes(self):
        before = self.snapshot()
        payloads = ["", "{", "null", "[]", "true", "12", '"text"']
        payloads += [json.dumps(request) for request in (
            {}, {"op": "init_db"}, {"op": "__dict__"}, {"op": []}, {"op": {}},
            {"op": "balance", "tenant": "alpha"},
            {"op": "balance", "tenant": "alpha", "account": "cash", "extra": 1},
            {"op": "balance", "tenant": "", "account": "cash"},
            {"op": "balance", "tenant": "alpha", "account": []},
            {"op": "transfer", **self.request(amount=True)},
            {"op": "transfer", **self.request(amount=1.0)},
            {"op": "transfer", **self.request(amount=101)},
            {"op": "transfer", **self.request(target="private")},
            {"op": "transfer", **self.request(key="")},
            {"op": "transfer", **self.request(), "extra": 1},
        )]
        arguments = [[], [str(self.path)], [str(self.path), "{}", "extra"]]
        arguments += [[str(self.path), payload] for payload in payloads]
        for args in arguments:
            with self.subTest(args=args):
                self.assert_cli_error(self.run_cli_args(args))
                self.assertEqual(self.snapshot(), before)

    def test_cli_hides_storage_errors(self):
        self.execute(
            "CREATE TRIGGER secret_failure BEFORE INSERT ON audit "
            "BEGIN SELECT RAISE(ABORT, 'SELECT secret FROM beta'); END"
        )
        before = self.snapshot()
        self.assert_cli_error(self.run_cli({"op": "transfer", **self.request()}))
        self.assertEqual(self.snapshot(), before)
        missing_path = Path(self.tmp.name) / "missing-directory" / "db.sqlite"
        result = self.run_cli_args([str(missing_path), json.dumps({"op": "balance", "tenant": "alpha", "account": "cash"})])
        self.assert_cli_error(result)

    def test_cli_integrated_journey_across_processes(self):
        self.assert_cli_success(self.run_cli({"op": "balance", "tenant": "alpha", "account": "cash"}), 100)
        self.assert_cli_success(self.run_cli({"op": "balance", "tenant": "beta", "account": "cash"}), 900)
        before = self.snapshot()
        first = self.request(amount=70, key="journey")
        self.assert_cli_success(self.run_cli({"op": "transfer", **first}), first)
        self.assert_applied(before, [first])
        committed = self.snapshot()
        vault.init_db(self.path)
        self.assert_cli_success(self.run_cli({"op": "transfer", **first}), first)
        self.assert_cli_error(self.run_cli({"op": "transfer", **dict(first, amount=71)}))
        for account in ("missing", "private"):
            self.assert_cli_error(self.run_cli({"op": "balance", "tenant": "alpha", "account": account}))
            self.assert_cli_error(self.run_cli({"op": "transfer", **self.request(target=account)}))
        self.assertEqual(self.snapshot(), committed)
        second = dict(first, tenant="beta")
        self.assert_cli_success(self.run_cli({"op": "transfer", **second}), second)
        self.assert_applied(before, [first, second])
        self.execute(
            "CREATE TRIGGER journey_failure BEFORE INSERT ON audit "
            "WHEN NEW.tenant='alpha' AND NEW.key='retry' AND NEW.amount=10 "
            "BEGIN SELECT RAISE(ABORT, 'audit unavailable'); END"
        )
        committed = self.snapshot()
        self.assert_cli_error(self.run_cli({"op": "transfer", **self.request(key="retry")}))
        self.assertEqual(self.snapshot(), committed)
        third = self.request(key="retry", amount=1)
        self.assert_cli_success(self.run_cli({"op": "transfer", **third}), third)
        self.assert_applied(before, [first, second, third])
        for tenant, account, expected in (("alpha", "cash", 29), ("alpha", "savings", 71), ("beta", "cash", 830)):
            self.assert_cli_success(self.run_cli({"op": "balance", "tenant": tenant, "account": account}), expected)


if __name__ == "__main__":
    unittest.main()
