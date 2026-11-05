import collections
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


ROOT = Path(__file__).resolve().parent


class VaultRegressionTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix='.vault-tests-', dir=ROOT)
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / 'vault.sqlite'
        vault.init_db(self.path)
        with sqlite3.connect(self.path) as con:
            con.executemany(
                'INSERT INTO accounts VALUES (?, ?, ?)',
                [('one', 'alice', 100), ('one', 'bob', 10),
                 ('one', 'carol', 0), ('two', 'alice', 300),
                 ('two', 'bob', 30), ('two', 'hidden', 70)],
            )
            con.execute("INSERT INTO transfers VALUES ('two', 'history', 'alice', 'bob', 3)")
            # Duplicate historical audit rows must also survive unchanged.
            con.executemany('INSERT INTO audit VALUES (?, ?, ?, ?, ?)',
                            [('two', 'history', 'alice', 'bob', 3)] * 2)

    def snapshot(self):
        with sqlite3.connect(self.path) as con:
            con.text_factory = bytes
            return {table: collections.Counter(con.execute('SELECT * FROM ' + table))
                    for table in ('accounts', 'transfers', 'audit')}

    def receipt(self, tenant='one', key='payment', amount=20,
                source='alice', target='bob'):
        return dict(tenant=tenant, key=key, source=source, target=target, amount=amount)

    def pay(self, **changes):
        request = self.receipt()
        request.update(changes)
        return vault.transfer(self.path, **request)

    def cli(self, request, path=None):
        return subprocess.run(
            [sys.executable, '-B', str(ROOT / 'app.py'), str(path or self.path),
             json.dumps(request)],
            cwd=ROOT, capture_output=True, text=True, timeout=15,
        )

    def assert_cli_error(self, result):
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertEqual(result.stdout, '')
        self.assertEqual(json.loads(result.stderr), {'error': 'invalid request'})
        self.assertEqual(len(result.stderr.splitlines()), 1)

    def concurrent(self, requests):
        barrier = threading.Barrier(len(requests))

        def run(request):
            barrier.wait(timeout=10)
            try:
                return self.pay(**request)
            except ValueError as error:
                return error

        with concurrent.futures.ThreadPoolExecutor(max_workers=len(requests)) as pool:
            futures = [pool.submit(run, request) for request in requests]
            return [future.result(timeout=30) for future in futures]

    def test_init_preserves_existing_schema_rows_and_triggers(self):
        with sqlite3.connect(self.path) as con:
            con.execute('CREATE TRIGGER keep_audit BEFORE DELETE ON audit '
                        "BEGIN SELECT RAISE(ABORT, 'retain history'); END")
            schema = con.execute('SELECT type, name, sql FROM sqlite_master ORDER BY name').fetchall()
        before = self.snapshot()
        vault.init_db(self.path)
        self.assertEqual(self.snapshot(), before)
        with sqlite3.connect(self.path) as con:
            self.assertEqual(con.execute('SELECT type, name, sql FROM sqlite_master ORDER BY name').fetchall(), schema)

    def test_balance_is_scoped_to_tenant(self):
        self.assertEqual(vault.balance(self.path, 'one', 'alice'), 100)
        self.assertEqual(vault.balance(self.path, 'two', 'alice'), 300)
        self.assertIs(type(vault.balance(self.path, 'one', 'carol')), int)

    def test_missing_and_inaccessible_accounts_have_same_generic_error(self):
        errors = []
        before = self.snapshot()
        for account in ('missing', 'hidden'):
            with self.assertRaises(ValueError) as caught:
                vault.balance(self.path, 'one', account)
            errors.append(str(caught.exception))
        self.assertEqual(errors[0], errors[1])
        self.assertNotIn('hidden', errors[1])
        self.assertEqual(self.snapshot(), before)

    def test_balance_rejects_invalid_identifiers(self):
        before = self.snapshot()
        for invalid in ('', None, 1, True, [], {}):
            for tenant, account in ((invalid, 'alice'), ('one', invalid)):
                with self.subTest(tenant=tenant, account=account):
                    with self.assertRaises(ValueError):
                        vault.balance(self.path, tenant, account)
                    self.assertEqual(self.snapshot(), before)

    def test_transfer_changes_only_the_two_tenant_accounts(self):
        before = self.snapshot()
        self.assertEqual(self.pay(), self.receipt())
        self.assertEqual(vault.balance(self.path, 'one', 'alice'), 80)
        self.assertEqual(vault.balance(self.path, 'one', 'bob'), 30)
        expected = {table: rows.copy() for table, rows in before.items()}
        expected['accounts'].subtract([(b'one', b'alice', 100), (b'one', b'bob', 10)])
        expected['accounts'].update([(b'one', b'alice', 80), (b'one', b'bob', 30)])
        row = (b'one', b'payment', b'alice', b'bob', 20)
        expected['transfers'].update([row])
        expected['audit'].update([row])
        self.assertEqual(self.snapshot(), expected)

    def test_transfer_rejects_malformed_requests_without_writes(self):
        invalid_requests = [
            {field: invalid}
            for field in ('tenant', 'source', 'target', 'key')
            for invalid in ('', None, 1, True, [], {})
        ]
        invalid_requests.extend({'amount': invalid} for invalid in
                                (0, -1, True, False, 1.5, '20', None, [], {}, float('inf'), float('nan')))
        invalid_requests.extend([{'target': 'alice'}, {'amount': 101}, {'amount': 10 ** 100}])
        before = self.snapshot()
        for request in invalid_requests:
            with self.subTest(request=request):
                with self.assertRaises(ValueError):
                    self.pay(**request)
                self.assertEqual(self.snapshot(), before)

    def test_both_transfer_endpoints_must_exist_in_the_tenant(self):
        errors = []
        before = self.snapshot()
        for endpoint in ('source', 'target'):
            for account in ('missing', 'hidden'):
                with self.subTest(endpoint=endpoint, account=account):
                    with self.assertRaises(ValueError) as caught:
                        self.pay(**{endpoint: account})
                    errors.append(str(caught.exception))
                    self.assertEqual(self.snapshot(), before)
        self.assertEqual(len(set(errors)), 1)

    def test_replay_is_durable_and_does_not_recheck_funds_or_write(self):
        original = self.pay(amount=100)
        before = self.snapshot()
        with sqlite3.connect(self.path) as con:
            con.execute('CREATE TRIGGER reject_new_audit BEFORE INSERT ON audit '
                        "BEGIN SELECT RAISE(ABORT, 'no more writes'); END")
        self.assertEqual(self.pay(amount=100), original)
        result = self.cli(dict(op='transfer', **self.receipt(amount=100)))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stderr, '')
        self.assertEqual(json.loads(result.stdout), original)
        self.assertEqual(self.snapshot(), before)

    def test_receipt_return_values_do_not_share_mutable_state(self):
        receipt = self.pay()
        receipt['tenant'] = 'tampered'
        receipt['amount'] = -20
        self.assertEqual(self.pay(), self.receipt())

    def test_replay_conflicts_and_invalid_replays_have_no_writes(self):
        self.pay()
        before = self.snapshot()
        for change in ({'amount': 21}, {'source': 'bob', 'target': 'alice'},
                       {'source': 'carol'}, {'target': 'carol'}, {'amount': True},
                       {'amount': 20.0}, {'source': ''}):
            with self.subTest(change=change):
                with self.assertRaises(ValueError):
                    self.pay(**change)
                self.assertEqual(self.snapshot(), before)

    def test_key_can_be_reused_independently_by_another_tenant(self):
        self.assertEqual(self.pay(), self.receipt())
        self.assertEqual(self.pay(tenant='two', amount=40), self.receipt(tenant='two', amount=40))
        self.assertEqual(vault.balance(self.path, 'one', 'alice'), 80)
        self.assertEqual(vault.balance(self.path, 'two', 'alice'), 260)
        self.assertEqual(self.pay(), self.receipt())
        self.assertEqual(self.pay(tenant='two', amount=40), self.receipt(tenant='two', amount=40))

    def test_actor_scoped_history_replays_without_current_endpoints(self):
        with sqlite3.connect(self.path) as con:
            con.execute("INSERT INTO transfers VALUES ('one', 'legacy', 'hidden', 'bob', 20)")
        before = self.snapshot()
        self.assertEqual(self.pay(key='legacy', source='hidden'),
                         self.receipt(key='legacy', source='hidden'))
        with self.assertRaises(ValueError):
            self.pay(key='fresh', source='hidden')
        self.assertEqual(self.snapshot(), before)

    def test_foreign_cached_receipt_and_malformed_rows_are_not_read(self):
        with sqlite3.connect(self.path) as con:
            con.execute("INSERT INTO transfers VALUES ('two', 'payment', CAST(X'FF' AS TEXT), 'bob', 9)")
            con.execute("INSERT INTO accounts VALUES ('two', 'foreign-only', CAST(X'FF' AS TEXT))")
        before = self.snapshot()
        self.assertEqual(self.pay(), self.receipt())
        with self.assertRaises(ValueError):
            vault.balance(self.path, 'one', 'foreign-only')
        with self.assertRaises(ValueError):
            self.pay(source='foreign-only', key='other')
        after = self.snapshot()
        for table in before:
            foreign_before = collections.Counter({row: n for row, n in before[table].items()
                                                  if row[0] == b'two'})
            foreign_after = collections.Counter({row: n for row, n in after[table].items()
                                                 if row[0] == b'two'})
            self.assertEqual(foreign_after, foreign_before)

    def test_complete_balance_can_be_transferred(self):
        self.assertEqual(self.pay(amount=100), self.receipt(amount=100))
        self.assertEqual(vault.balance(self.path, 'one', 'alice'), 0)
        self.assertEqual(vault.balance(self.path, 'one', 'bob'), 110)

    def test_sql_parameters_accept_unicode_and_literal_sql_characters(self):
        tenant, source, target, key = "租户 ' OR 1=1 --", 'α', 'β', "'; DROP TABLE audit; --"
        with sqlite3.connect(self.path) as con:
            con.executemany('INSERT INTO accounts VALUES (?, ?, ?)',
                            [(tenant, source, 10), (tenant, target, 0)])
        expected = self.receipt(tenant=tenant, source=source, target=target, key=key, amount=4)
        self.assertEqual(self.pay(**expected), expected)
        self.assertEqual(vault.balance(self.path, tenant, source), 6)
        self.assertEqual(vault.balance(self.path, 'one', 'alice'), 100)

    def test_storage_failure_at_credit_receipt_or_audit_rolls_back_everything(self):
        triggers = [
            "AFTER UPDATE ON accounts WHEN NEW.tenant = 'one' AND NEW.name = 'bob'",
            'BEFORE INSERT ON transfers',
            'BEFORE INSERT ON audit',
            'AFTER INSERT ON audit',
        ]
        for trigger in triggers:
            with self.subTest(trigger=trigger):
                before = self.snapshot()
                with sqlite3.connect(self.path) as con:
                    con.execute('CREATE TRIGGER fail_write ' + trigger +
                                " BEGIN SELECT RAISE(ABORT, 'private storage failure'); END")
                try:
                    with self.assertRaises(sqlite3.Error):
                        self.pay()
                    self.assertEqual(self.snapshot(), before)
                    with sqlite3.connect(self.path) as con:
                        self.assertIsNotNone(con.execute(
                            "SELECT name FROM sqlite_master WHERE type='trigger' AND name='fail_write'"
                        ).fetchone())
                finally:
                    with sqlite3.connect(self.path) as con:
                        con.execute('DROP TRIGGER fail_write')

    def test_audit_fail_and_rollback_actions_are_atomic_and_retryable(self):
        for action in ('FAIL', 'ROLLBACK'):
            with self.subTest(action=action):
                before = self.snapshot()
                with sqlite3.connect(self.path) as con:
                    con.execute('CREATE TRIGGER fail_audit BEFORE INSERT ON audit '
                                "BEGIN SELECT RAISE(" + action + ", 'storage failure'); END")
                with self.assertRaises(sqlite3.Error):
                    self.pay(key=action)
                self.assertEqual(self.snapshot(), before)
                with sqlite3.connect(self.path) as con:
                    con.execute('DROP TRIGGER fail_audit')
                self.assertEqual(self.pay(key=action), self.receipt(key=action))

    def test_existing_unique_constraint_failure_does_not_lose_money_or_history(self):
        with sqlite3.connect(self.path) as con:
            con.execute('CREATE UNIQUE INDEX audit_amount ON audit(tenant, amount) WHERE tenant = \'one\'')
        self.pay()
        before = self.snapshot()
        with self.assertRaises(sqlite3.IntegrityError):
            self.pay(key='different')
        self.assertEqual(self.snapshot(), before)

    def test_ignored_required_write_rolls_back_everything(self):
        triggers = [
            "BEFORE UPDATE ON accounts WHEN OLD.tenant='one' AND OLD.name='alice'",
            "BEFORE UPDATE ON accounts WHEN OLD.tenant='one' AND OLD.name='bob'",
            'BEFORE INSERT ON transfers',
            'BEFORE INSERT ON audit',
        ]
        for trigger in triggers:
            with self.subTest(trigger=trigger):
                before = self.snapshot()
                with sqlite3.connect(self.path) as con:
                    con.execute('CREATE TRIGGER ignore_write ' + trigger +
                                ' BEGIN SELECT RAISE(IGNORE); END')
                try:
                    with self.assertRaises(sqlite3.Error):
                        self.pay()
                    self.assertEqual(self.snapshot(), before)
                finally:
                    with sqlite3.connect(self.path) as con:
                        con.execute('DROP TRIGGER ignore_write')

    def test_large_integer_balances_remain_exact_and_overflow_is_atomic(self):
        maximum = 2 ** 63 - 1
        with sqlite3.connect(self.path) as con:
            con.execute("UPDATE accounts SET balance=? WHERE tenant='one' AND name='alice'", (maximum,))
            con.execute("UPDATE accounts SET balance=0 WHERE tenant='one' AND name='bob'")
        self.assertEqual(self.pay(amount=maximum), self.receipt(amount=maximum))
        self.assertEqual(vault.balance(self.path, 'one', 'bob'), maximum)
        with sqlite3.connect(self.path) as con:
            con.execute("UPDATE accounts SET balance=1 WHERE tenant='one' AND name='alice'")
        before = self.snapshot()
        with self.assertRaises((ValueError, OverflowError, sqlite3.Error)):
            self.pay(amount=1, key='overflow')
        self.assertEqual(self.snapshot(), before)

    def test_simultaneous_duplicate_keys_execute_once(self):
        results = self.concurrent([{} for _ in range(8)])
        self.assertEqual(results, [self.receipt()] * 8)
        self.assertEqual(vault.balance(self.path, 'one', 'alice'), 80)
        self.assertEqual(vault.balance(self.path, 'one', 'bob'), 30)
        with sqlite3.connect(self.path) as con:
            for table in ('transfers', 'audit'):
                self.assertEqual(con.execute('SELECT COUNT(*) FROM ' + table +
                                             " WHERE tenant='one'").fetchone()[0], 1)

    def test_simultaneous_distinct_keys_cannot_overspend(self):
        results = self.concurrent([{'key': 'payment-' + str(i)} for i in range(8)])
        successes = [result for result in results if isinstance(result, dict)]
        failures = [result for result in results if isinstance(result, ValueError)]
        self.assertEqual(len(successes), 5)
        self.assertEqual(len(failures), 3)
        self.assertEqual(vault.balance(self.path, 'one', 'alice'), 0)
        self.assertEqual(vault.balance(self.path, 'one', 'bob'), 110)
        with sqlite3.connect(self.path) as con:
            for table in ('transfers', 'audit'):
                self.assertEqual(con.execute('SELECT COUNT(*) FROM ' + table +
                                             " WHERE tenant='one'").fetchone()[0], 5)

    def test_simultaneous_opposing_transfers_preserve_all_credits(self):
        with sqlite3.connect(self.path) as con:
            con.execute("UPDATE accounts SET balance=100 WHERE tenant='one' AND name='bob'")
        requests = [{'key': 'forward-' + str(i), 'amount': 7} for i in range(4)]
        requests += [{'key': 'reverse-' + str(i), 'source': 'bob', 'target': 'alice', 'amount': 5}
                     for i in range(4)]
        results = self.concurrent(requests)
        self.assertTrue(all(isinstance(result, dict) for result in results), results)
        self.assertEqual(vault.balance(self.path, 'one', 'alice'), 92)
        self.assertEqual(vault.balance(self.path, 'one', 'bob'), 108)

    def test_simultaneous_tenants_can_share_a_key(self):
        requests = [{'tenant': 'one'}] * 4 + [{'tenant': 'two'}] * 4
        self.assertEqual(self.concurrent(requests),
                         [self.receipt()] * 4 + [self.receipt(tenant='two')] * 4)
        self.assertEqual(vault.balance(self.path, 'one', 'alice'), 80)
        self.assertEqual(vault.balance(self.path, 'two', 'alice'), 280)

    def test_cli_integrated_transfer_replay_conflict_and_balance(self):
        request = dict(op='transfer', **self.receipt())
        first = self.cli(request)
        self.assertEqual(first.returncode, 0, first.stderr)
        self.assertEqual(json.loads(first.stdout), self.receipt())
        self.assertEqual(first.stderr, '')
        self.assertEqual(len(first.stdout.splitlines()), 1)
        before = self.snapshot()
        replay = self.cli(request)
        self.assertEqual(replay.returncode, 0, replay.stderr)
        self.assertEqual(replay.stdout, first.stdout)
        self.assertEqual(self.snapshot(), before)
        self.assert_cli_error(self.cli(dict(request, amount=21)))
        self.assert_cli_error(self.cli(dict(request, target='hidden', key='blocked')))
        self.assertEqual(self.snapshot(), before)
        result = self.cli(dict(op='balance', tenant='one', account='alice'))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout), 80)
        self.assertEqual(result.stderr, '')

    def test_cli_rejects_invalid_json_shape_operation_and_fields(self):
        invalid = [None, [], 1, True, 'request', {},
                   {'op': 'init_db'}, {'op': '__dict__'}, {'op': 'unknown'},
                   {'op': []}, {'op': 'balance'},
                   {'op': 'balance', 'tenant': 'one', 'account': 'hidden'},
                   {'op': 'balance', 'tenant': 'one', 'account': 'alice', 'extra': 1},
                   dict(op='transfer', **self.receipt(amount=True))]
        before = self.snapshot()
        for request in invalid:
            with self.subTest(request=request):
                self.assert_cli_error(self.cli(request))
                self.assertEqual(self.snapshot(), before)
        for arguments in ([], [str(self.path)], [str(self.path), '{bad json'],
                          [str(self.path), '[' * 1100 + ']' * 1100],
                          [str(self.path), '{}', 'extra']):
            with self.subTest(arguments=arguments):
                result = subprocess.run([sys.executable, '-B', str(ROOT / 'app.py'), *arguments],
                                        cwd=ROOT, capture_output=True, text=True, timeout=15)
                self.assert_cli_error(result)

    def test_cli_storage_failure_is_generic_and_atomic_then_recovers(self):
        before = self.snapshot()
        with sqlite3.connect(self.path) as con:
            con.execute('CREATE TRIGGER fail_cli BEFORE INSERT ON audit '
                        "BEGIN SELECT RAISE(ABORT, 'secret other-tenant SQL details'); END")
        request = dict(op='transfer', **self.receipt())
        self.assert_cli_error(self.cli(request))
        self.assertEqual(self.snapshot(), before)
        with sqlite3.connect(self.path) as con:
            con.execute('DROP TRIGGER fail_cli')
        result = self.cli(request)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout), self.receipt())
        self.assert_cli_error(self.cli(dict(op='balance', tenant='one', account='alice'),
                                       path=Path(self.directory.name)))


if __name__ == '__main__':
    unittest.main()
