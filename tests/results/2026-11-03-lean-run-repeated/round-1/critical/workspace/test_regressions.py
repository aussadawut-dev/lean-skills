import concurrent.futures
import contextlib
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


class VaultRegressionTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(dir=WORKSPACE)
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / "vault.sqlite"
        vault.init_db(self.path)
        with self.connection() as con:
            con.executemany(
                "INSERT INTO accounts VALUES (?, ?, ?)",
                [
                    ("alpha", "checking", 100),
                    ("alpha", "savings", 20),
                    ("alpha", "private-a", 60),
                    ("beta", "checking", 900),
                    ("beta", "savings", 80),
                    ("beta", "private-b", 700),
                ],
            )

    @contextlib.contextmanager
    def connection(self):
        with contextlib.closing(sqlite3.connect(self.path)) as con:
            with con:
                yield con

    def snapshot(self):
        with self.connection() as con:
            return {
                table: con.execute(f"SELECT * FROM {table} ORDER BY rowid").fetchall()
                for table in ("accounts", "transfers", "audit")
            }

    def receipt(self, tenant="alpha", source="checking", target="savings",
                amount=10, key="key"):
        return dict(tenant=tenant, key=key, source=source, target=target, amount=amount)

    def assert_recorded(self, receipt):
        values = tuple(receipt[field] for field in
                       ("tenant", "key", "source", "target", "amount"))
        with self.connection() as con:
            for table in ("transfers", "audit"):
                rows = con.execute(
                    f"SELECT * FROM {table} WHERE tenant=? AND key=?", values[:2]
                ).fetchall()
                self.assertEqual(rows, [values])

    def parallel(self, requests):
        barrier = threading.Barrier(len(requests))

        def run(request):
            barrier.wait(timeout=10)
            try:
                return vault.transfer(self.path, **request)
            except ValueError as error:
                return error

        with concurrent.futures.ThreadPoolExecutor(max_workers=len(requests)) as pool:
            return list(pool.map(run, requests))

    def test_init_preserves_existing_schema_rows_and_receipts(self):
        receipt = vault.transfer(self.path, **self.receipt())
        before = self.snapshot()
        with self.connection() as con:
            schema = con.execute("SELECT name, sql FROM sqlite_master ORDER BY name").fetchall()
        vault.init_db(self.path)
        vault.init_db(self.path)
        self.assertEqual(self.snapshot(), before)
        with self.connection() as con:
            self.assertEqual(
                con.execute("SELECT name, sql FROM sqlite_master ORDER BY name").fetchall(),
                schema,
            )
        self.assertEqual(vault.transfer(self.path, **self.receipt()), receipt)
        self.assertEqual(self.snapshot(), before)

    def test_balance_is_scoped_to_tenant(self):
        before = self.snapshot()
        self.assertEqual(vault.balance(self.path, "alpha", "checking"), 100)
        self.assertEqual(vault.balance(self.path, "beta", "checking"), 900)
        self.assertEqual(self.snapshot(), before)

    def test_missing_and_inaccessible_accounts_share_generic_error(self):
        before = self.snapshot()
        errors = []
        calls = [
            lambda: vault.balance(self.path, "alpha", "missing-secret"),
            lambda: vault.balance(self.path, "alpha", "private-b"),
            lambda: vault.balance(self.path, "unknown-tenant", "checking"),
            lambda: vault.transfer(self.path, "alpha", "missing-secret", "savings", 1, "k"),
            lambda: vault.transfer(self.path, "alpha", "private-b", "savings", 1, "k"),
            lambda: vault.transfer(self.path, "alpha", "checking", "missing-secret", 1, "k"),
            lambda: vault.transfer(self.path, "alpha", "checking", "private-b", 1, "k"),
        ]
        for call in calls:
            with self.subTest(call=calls.index(call)):
                with self.assertRaises(ValueError) as caught:
                    call()
                errors.append(str(caught.exception))
                self.assertEqual(self.snapshot(), before)
        self.assertEqual(len(set(errors)), 1)
        for secret in ("alpha", "beta", "private-b", "missing-secret", "unknown-tenant"):
            self.assertNotIn(secret, errors[0])

    def test_invalid_identifiers_are_rejected_without_writes(self):
        before = self.snapshot()
        for field in ("tenant", "source", "target", "key"):
            for value in ("", None, 3, False, [], {}):
                with self.subTest(field=field, value=value):
                    request = self.receipt()
                    request[field] = value
                    with self.assertRaises(ValueError):
                        vault.transfer(self.path, **request)
                    self.assertEqual(self.snapshot(), before)
        for field in ("tenant", "account"):
            for value in ("", None, 3, False, [], {}):
                with self.subTest(balance_field=field, value=value):
                    request = dict(tenant="alpha", account="checking")
                    request[field] = value
                    with self.assertRaises(ValueError):
                        vault.balance(self.path, **request)
                    self.assertEqual(self.snapshot(), before)

    def test_invalid_requests_do_not_create_database(self):
        absent = Path(self.directory.name) / "absent.sqlite"
        with self.assertRaises(ValueError):
            vault.transfer(absent, "alpha", "checking", "savings", True, "key")
        with self.assertRaises(ValueError):
            vault.balance(absent, "", "checking")
        self.assertFalse(absent.exists())

    def test_invalid_amounts_and_insufficient_funds_do_not_write(self):
        before = self.snapshot()
        for amount in (0, -1, True, False, 1.0, 1.5, "10", None, [], {},
                       float("nan"), float("inf"), 101, 10**100):
            with self.subTest(amount=amount):
                with self.assertRaises(ValueError):
                    vault.transfer(self.path, **self.receipt(amount=amount))
                self.assertEqual(self.snapshot(), before)

    def test_same_account_is_rejected_without_writes(self):
        before = self.snapshot()
        with self.assertRaises(ValueError):
            vault.transfer(self.path, **self.receipt(target="checking"))
        self.assertEqual(self.snapshot(), before)

    def test_integer_limit_is_exact_and_overflow_rolls_back(self):
        maximum = 2**63 - 1
        with self.connection() as con:
            con.execute("UPDATE accounts SET balance=? WHERE tenant=? AND name=?",
                        (maximum - 1, "alpha", "savings"))
        request = self.receipt(amount=1)
        self.assertEqual(vault.transfer(self.path, **request), request)
        credited = vault.balance(self.path, "alpha", "savings")
        self.assertIsInstance(credited, int)
        self.assertEqual(credited, maximum)
        self.assert_recorded(request)
        before = self.snapshot()
        with self.assertRaises((OverflowError, sqlite3.Error)):
            vault.transfer(self.path, **(request | dict(key="overflow")))
        self.assertEqual(self.snapshot(), before)

    def test_transfer_changes_only_current_tenant(self):
        expected = self.receipt(amount=25)
        self.assertEqual(vault.transfer(self.path, **expected), expected)
        self.assertEqual(self.snapshot()["accounts"], [
            ("alpha", "checking", 75), ("alpha", "savings", 45),
            ("alpha", "private-a", 60), ("beta", "checking", 900),
            ("beta", "savings", 80), ("beta", "private-b", 700),
        ])
        self.assert_recorded(expected)

    def test_identifiers_are_exact_and_parameterized(self):
        tenant = "tenant' OR 1=1 --"
        source = "账户'; DROP TABLE accounts; --"
        target = " "
        key = "key' AND tenant='beta"
        before = self.snapshot()
        with self.connection() as con:
            con.executemany("INSERT INTO accounts VALUES (?, ?, ?)",
                            [(tenant, source, 7), (tenant, target, 0)])
        request = self.receipt(tenant, source, target, 7, key)
        self.assertEqual(vault.transfer(self.path, **request), request)
        self.assertEqual(vault.balance(self.path, tenant, source), 0)
        self.assertEqual(vault.balance(self.path, tenant, target), 7)
        self.assertEqual(self.snapshot()["accounts"][:6], before["accounts"])
        self.assert_recorded(request)

    def test_exact_replay_returns_original_after_balance_changes(self):
        request = self.receipt(amount=60)
        original = vault.transfer(self.path, **request)
        before = self.snapshot()
        self.assertEqual(vault.transfer(self.path, **request), original)
        self.assertEqual(self.snapshot(), before)
        vault.transfer(self.path, **self.receipt(source="savings", target="checking",
                                               amount=5, key="later"))
        before = self.snapshot()
        original["amount"] = 999  # A caller cannot mutate the persisted receipt.
        self.assertEqual(vault.transfer(self.path, **request), request)
        self.assertEqual(self.snapshot(), before)

    def test_same_key_different_payload_conflicts(self):
        request = self.receipt()
        vault.transfer(self.path, **request)
        before = self.snapshot()
        for changed in (dict(amount=11), dict(source="private-a"),
                        dict(target="private-a"), dict(source="savings", target="checking")):
            with self.subTest(changed=changed):
                with self.assertRaises(ValueError):
                    vault.transfer(self.path, **(request | changed))
                self.assertEqual(self.snapshot(), before)

    def test_replay_still_validates_amount_type(self):
        request = self.receipt(amount=1)
        vault.transfer(self.path, **request)
        before = self.snapshot()
        for amount in (True, 1.0):
            with self.subTest(amount=amount):
                with self.assertRaises(ValueError):
                    vault.transfer(self.path, **(request | dict(amount=amount)))
                self.assertEqual(self.snapshot(), before)

    def test_keys_and_cached_receipts_are_scoped_to_tenant(self):
        first = self.receipt(amount=10)
        second = self.receipt(tenant="beta", amount=70)
        self.assertEqual(vault.transfer(self.path, **first), first)
        self.assertEqual(vault.transfer(self.path, **second), second)
        before = self.snapshot()
        self.assertEqual(vault.transfer(self.path, **first), first)
        self.assertEqual(vault.transfer(self.path, **second), second)
        with self.assertRaises(ValueError):
            vault.transfer(self.path, **(first | dict(tenant="outsider")))
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(vault.balance(self.path, "beta", "checking"), 830)
        self.assert_recorded(first)
        self.assert_recorded(second)

    def test_audit_failure_rolls_back_all_four_effects(self):
        with self.connection() as con:
            con.execute("""CREATE TRIGGER reject_audit BEFORE INSERT ON audit
                           BEGIN SELECT RAISE(ABORT, 'private storage failure'); END""")
        before = self.snapshot()
        with self.assertRaises(sqlite3.Error):
            vault.transfer(self.path, **self.receipt())
        self.assertEqual(self.snapshot(), before)
        with self.connection() as con:
            self.assertEqual(con.execute(
                "SELECT COUNT(*) FROM sqlite_master WHERE name='reject_audit'"
            ).fetchone()[0], 1)
            con.execute("DROP TRIGGER reject_audit")
        self.assertEqual(vault.transfer(self.path, **self.receipt()), self.receipt())
        self.assertEqual(vault.balance(self.path, "alpha", "checking"), 90)
        self.assertEqual(vault.balance(self.path, "alpha", "savings"), 30)
        self.assert_recorded(self.receipt())

    def test_failed_or_ignored_writes_roll_back_and_allow_retry(self):
        stages = (
            "BEFORE UPDATE ON accounts WHEN OLD.tenant='alpha' AND OLD.name='checking'",
            "BEFORE UPDATE ON accounts WHEN OLD.tenant='alpha' AND OLD.name='savings'",
            "BEFORE INSERT ON transfers",
            "BEFORE INSERT ON audit",
            "AFTER INSERT ON audit",
        )
        for index, stage in enumerate(stages):
            actions = ("ABORT", "FAIL", "ROLLBACK", "IGNORE")
            if stage.startswith("AFTER"):
                actions = actions[:-1]  # AFTER IGNORE does not suppress the row itself.
            for action in actions:
                with self.subTest(stage=stage, action=action):
                    request = self.receipt(amount=1, key=f"failure-{index}-{action}")
                    before = self.snapshot()
                    raised = "RAISE(IGNORE)" if action == "IGNORE" else f"RAISE({action}, 'failure')"
                    with self.connection() as con:
                        con.execute(f"CREATE TRIGGER reject_write {stage} BEGIN SELECT {raised}; END")
                    try:
                        with self.assertRaises(sqlite3.Error):
                            vault.transfer(self.path, **request)
                        self.assertEqual(self.snapshot(), before)
                        with self.connection() as con:
                            self.assertIsNotNone(con.execute(
                                "SELECT name FROM sqlite_master WHERE name='reject_write'"
                            ).fetchone())
                    finally:
                        with self.connection() as con:
                            con.execute("DROP TRIGGER reject_write")
                    self.assertEqual(vault.transfer(self.path, **request), request)
                    self.assert_recorded(request)
                    after = self.snapshot()
                    self.assertEqual(vault.transfer(self.path, **request), request)
                    self.assertEqual(self.snapshot(), after)

    def test_after_triggers_roll_back_changed_final_effects(self):
        cases = {
            "missing credit": """AFTER UPDATE OF balance ON accounts
                WHEN NEW.tenant='alpha' AND NEW.name='savings'
                BEGIN UPDATE accounts SET balance=OLD.balance
                    WHERE tenant=NEW.tenant AND name=NEW.name; END""",
            "missing receipt": """AFTER INSERT ON transfers
                BEGIN DELETE FROM transfers
                    WHERE tenant=NEW.tenant AND key=NEW.key; END""",
            "missing audit": """AFTER INSERT ON audit
                BEGIN DELETE FROM audit WHERE rowid=NEW.rowid; END""",
            "duplicate audit": """AFTER INSERT ON audit
                BEGIN INSERT INTO audit VALUES
                    (NEW.tenant, NEW.key, NEW.source, NEW.target, NEW.amount); END""",
            "late missing debit": """AFTER INSERT ON audit
                BEGIN UPDATE accounts SET balance=balance+NEW.amount
                    WHERE tenant=NEW.tenant AND name=NEW.source; END""",
            "late missing credit": """AFTER INSERT ON audit
                BEGIN UPDATE accounts SET balance=balance-NEW.amount
                    WHERE tenant=NEW.tenant AND name=NEW.target; END""",
            "late missing receipt": """AFTER INSERT ON audit
                BEGIN DELETE FROM transfers
                    WHERE tenant=NEW.tenant AND key=NEW.key; END""",
            "altered receipt": """AFTER INSERT ON audit
                BEGIN UPDATE transfers SET amount=NEW.amount+1
                    WHERE tenant=NEW.tenant AND key=NEW.key; END""",
            "altered audit": """AFTER INSERT ON audit
                BEGIN UPDATE audit SET amount=NEW.amount+1 WHERE rowid=NEW.rowid; END""",
            "missing account": """AFTER INSERT ON audit
                BEGIN DELETE FROM accounts
                    WHERE tenant=NEW.tenant AND name=NEW.source; END""",
            "duplicate audit under another key": """AFTER INSERT ON audit
                BEGIN INSERT INTO audit VALUES
                    (NEW.tenant, NEW.key || '-extra', NEW.source, NEW.target, NEW.amount); END""",
            "duplicate audit for another tenant": """AFTER INSERT ON audit
                BEGIN INSERT INTO audit VALUES
                    ('beta', NEW.key, NEW.source, NEW.target, NEW.amount); END""",
            "altered audit history": """AFTER INSERT ON audit
                BEGIN UPDATE audit SET amount=amount+1
                    WHERE tenant=NEW.tenant AND key='existing'; END""",
            "replaced audit history of another tenant": """AFTER INSERT ON audit
                WHEN NEW.tenant='alpha'
                BEGIN DELETE FROM audit WHERE tenant='beta' AND key='existing';
                    INSERT INTO audit VALUES
                    ('beta', NEW.key, NEW.source, NEW.target, NEW.amount); END""",
            "altered audit history of another tenant": """AFTER INSERT ON audit
                BEGIN UPDATE audit SET amount=amount+1
                    WHERE tenant='beta' AND key='existing'; END""",
            "changed audit history multiplicity": """AFTER INSERT ON audit
                WHEN NEW.tenant='alpha'
                BEGIN DELETE FROM audit WHERE rowid=(
                    SELECT rowid FROM audit WHERE tenant='beta' AND key='duplicate' LIMIT 1);
                    INSERT INTO audit SELECT tenant, key, source, target, amount
                    FROM audit WHERE tenant='beta' AND key='other' LIMIT 1; END""",
        }
        # Keep existing history in both tenants throughout each rollback/retry.
        vault.transfer(self.path, **self.receipt(key="existing"))
        vault.transfer(self.path, **self.receipt(tenant="beta", key="existing"))
        with self.connection() as con:
            # Changing these counts preserves both the total and distinct rows.
            con.executemany("INSERT INTO audit VALUES (?, ?, ?, ?, ?)", [
                ("beta", "duplicate", "checking", "savings", 2),
                ("beta", "duplicate", "checking", "savings", 2),
                ("beta", "other", "checking", "savings", 3),
            ])
        for name, definition in cases.items():
            with self.subTest(effect=name):
                request = self.receipt(amount=1, key=name)
                before = self.snapshot()
                with self.connection() as con:
                    con.execute(f"CREATE TRIGGER change_effect {definition}")
                    schema = con.execute(
                        "SELECT name, sql FROM sqlite_master ORDER BY name"
                    ).fetchall()
                try:
                    with self.assertRaises(sqlite3.Error):
                        vault.transfer(self.path, **request)
                    self.assertEqual(self.snapshot(), before)
                    self.assertEqual(
                        self.assert_cli_error(self.cli(dict(op="transfer", **request))),
                        {"error": "invalid request"},
                    )
                    self.assertEqual(self.snapshot(), before)
                    with self.connection() as con:
                        self.assertEqual(con.execute(
                            "SELECT name, sql FROM sqlite_master ORDER BY name"
                        ).fetchall(), schema)
                finally:
                    with self.connection() as con:
                        con.execute("DROP TRIGGER change_effect")
                self.assertEqual(vault.transfer(self.path, **request), request)
                self.assert_recorded(request)
                after = self.snapshot()
                self.assertEqual(vault.transfer(self.path, **request), request)
                self.assertEqual(self.snapshot(), after)

    def test_transfer_adds_one_audit_preserving_history_and_benign_trigger(self):
        request = self.receipt()
        values = ("alpha", "key", "checking", "savings", 10)
        with self.connection() as con:
            # Existing audit rows need not be unique or have a cached receipt.
            con.executemany("INSERT INTO audit VALUES (?, ?, ?, ?, ?)",
                            [values, values, ("beta", "key", "checking", "savings", 40)])
            con.execute("""CREATE TRIGGER keep_balance AFTER INSERT ON audit
                BEGIN UPDATE accounts SET balance=balance
                    WHERE tenant=NEW.tenant AND name=NEW.target; END""")
            schema = con.execute(
                "SELECT name, sql FROM sqlite_master ORDER BY name"
            ).fetchall()
        before = self.snapshot()
        self.assertEqual(vault.transfer(self.path, **request), request)
        self.assertEqual(vault.balance(self.path, "alpha", "checking"), 90)
        self.assertEqual(vault.balance(self.path, "alpha", "savings"), 30)
        after = self.snapshot()
        self.assertEqual(after["audit"], before["audit"] + [values])
        self.assertEqual(after["transfers"], before["transfers"] + [values])
        self.assertEqual(after["accounts"][2:], before["accounts"][2:])
        with self.connection() as con:
            self.assertEqual(con.execute(
                "SELECT name, sql FROM sqlite_master ORDER BY name"
            ).fetchall(), schema)
        self.assertEqual(vault.transfer(self.path, **request), request)
        self.assertEqual(self.snapshot(), after)

    def test_transfer_accepts_audit_rowid_relocation(self):
        with self.connection() as con:
            con.executemany("INSERT INTO audit VALUES (?, ?, ?, ?, ?)", [
                ("alpha", "API", "checking", "savings", 10),
                ("alpha", "API", "checking", "savings", 10),
                ("beta", "old", "checking", "savings", 2),
            ])
            con.execute("""CREATE TRIGGER relocate_audit AFTER INSERT ON audit
                BEGIN UPDATE audit SET rowid=NEW.rowid+1000
                    WHERE rowid=NEW.rowid; END""")
            schema = con.execute(
                "SELECT name, sql FROM sqlite_master ORDER BY name"
            ).fetchall()
        for index, interface in enumerate(("API", "CLI"), start=1):
            with self.subTest(interface=interface):
                request = self.receipt(key=interface)
                values = ("alpha", interface, "checking", "savings", 10)
                before = self.snapshot()
                with self.connection() as con:
                    previous_rowid = con.execute("SELECT MAX(rowid) FROM audit").fetchone()[0]
                if interface == "API":
                    self.assertEqual(vault.transfer(self.path, **request), request)
                else:
                    self.assert_cli_success(self.cli(dict(op="transfer", **request)), request)
                self.assertEqual(vault.balance(self.path, "alpha", "checking"), 100 - 10 * index)
                self.assertEqual(vault.balance(self.path, "alpha", "savings"), 20 + 10 * index)
                after = self.snapshot()
                self.assertCountEqual(after["audit"], before["audit"] + [values])
                self.assertEqual(after["transfers"], before["transfers"] + [values])
                self.assertEqual(after["accounts"][2:], before["accounts"][2:])
                with self.connection() as con:
                    # Confirm the trigger actually ran, including through the CLI.
                    self.assertEqual(con.execute("SELECT MAX(rowid) FROM audit").fetchone()[0],
                                     previous_rowid + 1001)
                    self.assertEqual(con.execute(
                        "SELECT name, sql FROM sqlite_master ORDER BY name"
                    ).fetchall(), schema)
                self.assertEqual(vault.transfer(self.path, **request), request)
                self.assert_cli_success(self.cli(dict(op="transfer", **request)), request)
                self.assertEqual(self.snapshot(), after)

    def test_concurrent_same_key_executes_once_and_survives_reopen(self):
        request = self.receipt(amount=30)
        results = self.parallel([request] * 8)
        self.assertEqual(results, [request] * 8)
        self.assertEqual(vault.balance(self.path, "alpha", "checking"), 70)
        self.assertEqual(vault.balance(self.path, "alpha", "savings"), 50)
        self.assert_recorded(request)
        before = self.snapshot()
        vault.init_db(self.path)
        self.assertEqual(vault.transfer(self.path, **request), request)
        self.assertEqual(self.snapshot(), before)

    def test_concurrent_conflicting_payloads_have_one_winner(self):
        requests = [self.receipt(amount=20 + 10 * (i % 2)) for i in range(8)]
        results = self.parallel(requests)
        successes = [result for result in results if not isinstance(result, ValueError)]
        self.assertEqual(len(successes), 4)
        winner = successes[0]
        for request, result in zip(requests, results):
            if request == winner:
                self.assertEqual(result, winner)
            else:
                self.assertIsInstance(result, ValueError)
        self.assertEqual(vault.balance(self.path, "alpha", "checking"), 100 - winner["amount"])
        self.assertEqual(vault.balance(self.path, "alpha", "savings"), 20 + winner["amount"])
        self.assert_recorded(winner)

    def test_concurrent_distinct_keys_do_not_overspend(self):
        requests = [self.receipt(amount=20, key=f"spend-{i}") for i in range(8)]
        results = self.parallel(requests)
        successes = [result for result in results if not isinstance(result, ValueError)]
        self.assertEqual(len(successes), 5)
        self.assertEqual(vault.balance(self.path, "alpha", "checking"), 0)
        self.assertEqual(vault.balance(self.path, "alpha", "savings"), 120)
        snapshot = self.snapshot()
        self.assertEqual(len(snapshot["transfers"]), 5)
        self.assertEqual(sorted(snapshot["transfers"]), sorted(snapshot["audit"]))
        for receipt in successes:
            self.assert_recorded(receipt)

    def test_concurrent_sources_do_not_lose_credits(self):
        with self.connection() as con:
            con.executemany("INSERT INTO accounts VALUES (?, ?, ?)",
                            [("alpha", f"donor-{i}", 100) for i in range(8)])
        requests = [self.receipt(source=f"donor-{i}", amount=25, key=f"credit-{i}")
                    for i in range(8)]
        self.assertEqual(self.parallel(requests), requests)
        self.assertEqual(vault.balance(self.path, "alpha", "savings"), 220)
        for request in requests:
            self.assertEqual(vault.balance(self.path, "alpha", request["source"]), 75)
            self.assert_recorded(request)

    def cli_raw(self, *args):
        return subprocess.run([sys.executable, "-B", str(WORKSPACE / "app.py"), *args],
                              cwd=WORKSPACE, capture_output=True, text=True, timeout=10)

    def cli(self, request):
        return self.cli_raw(str(self.path), json.dumps(request))

    def assert_cli_success(self, process, expected):
        self.assertEqual(process.returncode, 0, process.stderr)
        self.assertEqual(process.stderr, "")
        self.assertEqual(len(process.stdout.splitlines()), 1)
        self.assertEqual(json.loads(process.stdout), expected)

    def assert_cli_error(self, process):
        self.assertEqual(process.returncode, 2, process.stderr)
        self.assertEqual(process.stdout, "")
        self.assertEqual(len(process.stderr.splitlines()), 1)
        error = json.loads(process.stderr)
        self.assertEqual(set(error), {"error"})
        self.assertIsInstance(error["error"], str)
        self.assertTrue(error["error"])
        return error

    def test_cli_invalid_calls_have_one_generic_json_error(self):
        requests = [
            None, [], True, 1, "request", {}, {"op": "unknown"}, {"op": "init_db"},
            {"op": "__dict__"}, {"op": []}, {"op": "balance"},
            {"op": "balance", "tenant": "alpha", "account": "private-b"},
            {"op": "balance", "tenant": "alpha", "account": "missing-secret"},
            {"op": "balance", "tenant": "", "account": "checking"},
            {"op": "balance", "tenant": "alpha", "account": "checking", "extra": 1},
            {"op": "transfer", **self.receipt(amount=True)},
            {"op": "transfer", **self.receipt(amount=1.0)},
            {"op": "transfer", **self.receipt(amount=-1)},
            {"op": "transfer", **self.receipt(amount=101)},
            {"op": "transfer", **self.receipt(target="checking")},
            {"op": "transfer", **self.receipt(target="private-b")},
            {"op": "transfer", **self.receipt(key="")},
        ]
        before = self.snapshot()
        errors = []
        for request in requests:
            with self.subTest(request=request):
                errors.append(self.assert_cli_error(self.cli(request)))
                self.assertEqual(self.snapshot(), before)
        malformed = ["", "{", "{} {}", '{"op":"balance","op":"init_db"}',
                     '{"op":"balance","tenant":"alpha","account":"checking","x":NaN}']
        for raw in malformed:
            with self.subTest(raw=raw):
                errors.append(self.assert_cli_error(self.cli_raw(str(self.path), raw)))
                self.assertEqual(self.snapshot(), before)
        for args in ((), (str(self.path),), (str(self.path), "{}", "unexpected")):
            with self.subTest(args=args):
                errors.append(self.assert_cli_error(self.cli_raw(*args)))
        self.assertTrue(all(error == errors[0] for error in errors))

    def test_cli_journey_persistence_isolation_replay_and_recovery(self):
        self.assert_cli_success(self.cli(dict(op="balance", tenant="alpha", account="checking")), 100)
        self.assert_cli_success(self.cli(dict(op="balance", tenant="beta", account="checking")), 900)
        first = self.receipt(amount=60)
        self.assert_cli_success(self.cli(dict(op="transfer", **first)), first)
        before_replay = self.snapshot()
        self.assert_cli_success(self.cli(dict(op="transfer", **first)), first)
        self.assertEqual(self.snapshot(), before_replay)
        second = self.receipt(tenant="beta", amount=70)
        self.assert_cli_success(self.cli(dict(op="transfer", **second)), second)
        self.assert_recorded(first)
        self.assert_recorded(second)
        for tenant, account, expected in (("alpha", "checking", 40), ("alpha", "savings", 80),
                                          ("beta", "checking", 830), ("beta", "savings", 150)):
            self.assert_cli_success(self.cli(dict(op="balance", tenant=tenant, account=account)), expected)
        before = self.snapshot()
        conflict = dict(op="transfer", **(first | dict(amount=1)))
        generic = self.assert_cli_error(self.cli(conflict))
        self.assertEqual(self.snapshot(), before)
        with self.connection() as con:
            con.execute("""CREATE TRIGGER reject_audit BEFORE INSERT ON audit
                           BEGIN SELECT RAISE(ABORT, 'secret tenant beta SQL INSERT audit'); END""")
        retry = self.receipt(amount=5, key="retry")
        self.assertEqual(self.assert_cli_error(self.cli(dict(op="transfer", **retry))), generic)
        self.assertEqual(self.snapshot(), before)
        with self.connection() as con:
            self.assertIsNotNone(con.execute(
                "SELECT name FROM sqlite_master WHERE name='reject_audit'"
            ).fetchone())
            con.execute("DROP TRIGGER reject_audit")
        self.assert_cli_success(self.cli(dict(op="transfer", **retry)), retry)
        self.assert_cli_success(self.cli(dict(op="balance", tenant="alpha", account="checking")), 35)
        self.assert_cli_success(self.cli(dict(op="balance", tenant="alpha", account="savings")), 85)
        self.assert_recorded(retry)
        self.assertEqual(len(self.snapshot()["transfers"]), 3)
        self.assertEqual(sorted(self.snapshot()["transfers"]), sorted(self.snapshot()["audit"]))


if __name__ == "__main__":
    unittest.main()
