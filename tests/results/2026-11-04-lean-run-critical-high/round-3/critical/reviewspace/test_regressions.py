from contextlib import closing
from concurrent.futures import ThreadPoolExecutor
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
        self.directory = tempfile.TemporaryDirectory(dir=ROOT)
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / 'vault.sqlite'
        vault.init_db(self.path)
        with closing(sqlite3.connect(self.path)) as con, con:
            con.executemany('INSERT INTO accounts VALUES (?, ?, ?)', [
                ('red', 'a', 100), ('red', 'b', 20), ('red', 'c', 0),
                ('blue', 'a', 250), ('blue', 'b', 30),
                ('blue', 'private', 77), ('blue', 'broken', 'not-a-number'),
            ])
            history = [
                ('red', 'historic', 'a', 'b', 1),
                ('blue', 'historic', 'private', 'b', 2),
            ]
            con.executemany('INSERT INTO transfers VALUES (?, ?, ?, ?, ?)', history)
            con.executemany('INSERT INTO audit VALUES (?, ?, ?, ?, ?)', history)

    def snapshot(self):
        with closing(sqlite3.connect(self.path)) as con:
            return {
                'accounts': con.execute(
                    'SELECT tenant, name, balance FROM accounts ORDER BY tenant, name'
                ).fetchall(),
                'transfers': con.execute(
                    'SELECT tenant, key, source, target, amount FROM transfers '
                    'ORDER BY tenant, key, source, target, amount'
                ).fetchall(),
                'audit': con.execute(
                    'SELECT tenant, key, source, target, amount FROM audit '
                    'ORDER BY tenant, key, source, target, amount'
                ).fetchall(),
            }

    def test_balance_is_scoped_to_tenant(self):
        self.assertEqual(vault.balance(self.path, 'blue', 'a'), 250)
        self.assertEqual(vault.balance(self.path, 'red', 'a'), 100)

    def test_missing_and_foreign_accounts_have_identical_errors(self):
        before = self.snapshot()
        errors = []
        for account in ('private', 'missing'):
            with self.subTest(account=account):
                with self.assertRaises(ValueError) as caught:
                    vault.balance(self.path, 'red', account)
                errors.append(str(caught.exception))
        self.assertEqual(len(errors), 2)
        self.assertEqual(errors[0], errors[1])
        self.assertEqual(self.snapshot(), before)

    def test_transfer_changes_only_authorized_rows(self):
        before = self.snapshot()
        with closing(sqlite3.connect(self.path)) as con, con:
            con.executescript('''
                CREATE TABLE effects (operation, old_tenant, old_name, old_balance,
                                      new_tenant, new_name, new_balance);
                CREATE TRIGGER observe_update AFTER UPDATE ON accounts BEGIN
                    INSERT INTO effects VALUES ('update', OLD.tenant, OLD.name,
                        OLD.balance, NEW.tenant, NEW.name, NEW.balance);
                END;
                CREATE TRIGGER observe_delete AFTER DELETE ON accounts BEGIN
                    INSERT INTO effects VALUES ('delete', OLD.tenant, OLD.name,
                        OLD.balance, NULL, NULL, NULL);
                END;
                CREATE TRIGGER observe_insert AFTER INSERT ON accounts BEGIN
                    INSERT INTO effects VALUES ('insert', NULL, NULL, NULL,
                        NEW.tenant, NEW.name, NEW.balance);
                END;
            ''')
        receipt = vault.transfer(self.path, 'red', 'a', 'b', 10, 'new')
        self.assertEqual(receipt, {
            'tenant': 'red', 'key': 'new', 'source': 'a', 'target': 'b', 'amount': 10,
        })
        expected = {table: rows[:] for table, rows in before.items()}
        expected['accounts'].remove(('red', 'a', 100))
        expected['accounts'].remove(('red', 'b', 20))
        expected['accounts'].extend([('red', 'a', 90), ('red', 'b', 30)])
        expected['accounts'].sort()
        for table in ('transfers', 'audit'):
            expected[table].append(('red', 'new', 'a', 'b', 10))
            expected[table].sort()
        self.assertEqual(self.snapshot(), expected)
        with closing(sqlite3.connect(self.path)) as con:
            self.assertCountEqual(con.execute('SELECT * FROM effects').fetchall(), [
                ('update', 'red', 'a', 100, 'red', 'a', 90),
                ('update', 'red', 'b', 20, 'red', 'b', 30),
            ])

    def test_foreign_transfer_endpoints_are_rejected_without_changes(self):
        before = self.snapshot()
        errors = []
        for source, target in (
            ('private', 'b'), ('a', 'private'), ('missing', 'b'), ('a', 'missing'),
        ):
            with self.subTest(source=source, target=target):
                with self.assertRaises(ValueError) as caught:
                    vault.transfer(self.path, 'red', source, target, 5, 'foreign')
                errors.append(str(caught.exception))
                self.assertEqual(self.snapshot(), before)
        self.assertEqual(len(errors), 4)
        self.assertEqual(len(set(errors)), 1)

    def test_audit_failure_rolls_back_every_effect(self):
        with closing(sqlite3.connect(self.path)) as con, con:
            con.execute('''CREATE TRIGGER reject_audit BEFORE INSERT ON audit
                BEGIN SELECT RAISE(ABORT, 'private storage details'); END''')
        before = self.snapshot()
        with self.assertRaises(sqlite3.IntegrityError):
            vault.transfer(self.path, 'red', 'a', 'b', 10, 'failed')
        self.assertEqual(self.snapshot(), before)
        vault.init_db(self.path)
        self.assertEqual(self.snapshot(), before)
        with closing(sqlite3.connect(self.path)) as con:
            self.assertIsNotNone(con.execute(
                "SELECT sql FROM sqlite_master WHERE type='trigger' AND name='reject_audit'"
            ).fetchone())

    def test_receipt_lookup_is_tenant_scoped(self):
        receipt = vault.transfer(self.path, 'red', 'a', 'b', 1, 'historic')
        self.assertEqual(receipt, {
            'tenant': 'red', 'key': 'historic', 'source': 'a', 'target': 'b', 'amount': 1,
        })
        other = vault.transfer(self.path, 'blue', 'private', 'b', 2, 'historic')
        self.assertEqual(other, {
            'tenant': 'blue', 'key': 'historic', 'source': 'private', 'target': 'b',
            'amount': 2,
        })

    def test_existing_key_with_changed_payload_conflicts(self):
        before = self.snapshot()
        for source, target, amount in (('a', 'b', 2), ('c', 'b', 1), ('a', 'c', 1)):
            with self.subTest(source=source, target=target, amount=amount):
                with self.assertRaises(ValueError):
                    vault.transfer(self.path, 'red', source, target, amount, 'historic')
                self.assertEqual(self.snapshot(), before)

    def test_negative_amount_is_rejected_without_changes(self):
        before = self.snapshot()
        with self.assertRaises(ValueError):
            vault.transfer(self.path, 'red', 'a', 'b', -10, 'negative')
        self.assertEqual(self.snapshot(), before)

    def test_nonempty_text_is_required_for_every_identity(self):
        before = self.snapshot()
        invalid = ('', None, 0, True, [], {}, b'red', 1.5)
        valid = dict(tenant='red', source='a', target='b', amount=1, key='new')
        for field in ('tenant', 'source', 'target', 'key'):
            for value in invalid:
                with self.subTest(operation='transfer', field=field, value=value):
                    request = dict(valid, **{field: value})
                    with self.assertRaises(ValueError):
                        vault.transfer(self.path, **request)
                    self.assertEqual(self.snapshot(), before)
        for field in ('tenant', 'account'):
            for value in invalid:
                with self.subTest(operation='balance', field=field, value=value):
                    request = dict(tenant='red', account='a')
                    request[field] = value
                    with self.assertRaises(ValueError):
                        vault.balance(self.path, **request)
                    self.assertEqual(self.snapshot(), before)

    def test_only_positive_nonboolean_integer_amounts_are_accepted(self):
        before = self.snapshot()
        for amount in (0, -1, True, False, 1.0, 1.5, '1', None, [], {},
                       float('nan'), float('inf')):
            with self.subTest(amount=amount):
                with self.assertRaises(ValueError):
                    vault.transfer(self.path, 'red', 'a', 'b', amount, 'invalid')
                self.assertEqual(self.snapshot(), before)

    def test_self_transfer_and_insufficient_funds_do_not_write(self):
        before = self.snapshot()
        for source, target, amount in (('a', 'a', 1), ('a', 'b', 101),
                                       ('c', 'b', 1), ('a', 'b', 2**100)):
            with self.subTest(source=source, target=target, amount=amount):
                with self.assertRaises(ValueError):
                    vault.transfer(self.path, 'red', source, target, amount, 'invalid')
                self.assertEqual(self.snapshot(), before)

    def test_unknown_tenant_cannot_read_or_transfer_existing_accounts(self):
        before = self.snapshot()
        with self.assertRaises(ValueError) as read_error:
            vault.balance(self.path, 'absent', 'a')
        with self.assertRaises(ValueError) as transfer_error:
            vault.transfer(self.path, 'absent', 'a', 'b', 1, 'historic')
        self.assertEqual(str(read_error.exception), str(transfer_error.exception))
        self.assertEqual(self.snapshot(), before)

    def test_text_identifiers_are_literal_and_not_normalized(self):
        tenant = 'tenant\x00租户'
        source = "a' OR 1=1 --"
        target = ' '
        key = "k'; DROP TABLE audit; --"
        before = self.snapshot()
        with closing(sqlite3.connect(self.path)) as con, con:
            con.executemany('INSERT INTO accounts VALUES (?, ?, ?)', [
                (tenant, source, 4), (tenant, target, 0),
            ])
        result = vault.transfer(self.path, tenant, source, target, 4, key)
        self.assertEqual(result, dict(tenant=tenant, source=source, target=target,
                                      amount=4, key=key))
        self.assertEqual(vault.balance(self.path, tenant, source), 0)
        self.assertEqual(vault.balance(self.path, tenant, target), 4)
        after = self.snapshot()
        for table, rows in before.items():
            self.assertEqual([row for row in after[table] if row[0] != tenant], rows)

    def test_replay_is_durable_even_when_source_is_now_empty(self):
        original = vault.transfer(self.path, 'red', 'a', 'b', 100, 'drain')
        expected = dict(original)
        before_replay = self.snapshot()
        original['amount'] = 999
        vault.init_db(self.path)
        self.assertEqual(vault.transfer(self.path, 'red', 'a', 'b', 100, 'drain'), expected)
        self.assertEqual(self.snapshot(), before_replay)
        self.assertEqual(vault.balance(self.path, 'red', 'a'), 0)

    def test_tenants_can_independently_create_the_same_key(self):
        first = vault.transfer(self.path, 'red', 'a', 'b', 7, 'shared')
        second = vault.transfer(self.path, 'blue', 'a', 'b', 9, 'shared')
        self.assertEqual(first['tenant'], 'red')
        self.assertEqual(second['tenant'], 'blue')
        self.assertEqual(vault.balance(self.path, 'red', 'a'), 93)
        self.assertEqual(vault.balance(self.path, 'blue', 'a'), 241)
        before = self.snapshot()
        self.assertEqual(vault.transfer(self.path, 'red', 'a', 'b', 7, 'shared'), first)
        self.assertEqual(vault.transfer(self.path, 'blue', 'a', 'b', 9, 'shared'), second)
        self.assertEqual(self.snapshot(), before)
        for table in ('transfers', 'audit'):
            self.assertEqual(len([row for row in before[table] if row[1] == 'shared']), 2)

    def test_initialization_preserves_schema_rows_and_audit_multiplicity(self):
        with closing(sqlite3.connect(self.path)) as con, con:
            con.execute("INSERT INTO audit VALUES ('red', 'historic', 'a', 'b', 1)")
            schema = con.execute(
                'SELECT type, name, tbl_name, sql FROM sqlite_master ORDER BY type, name'
            ).fetchall()
        before = self.snapshot()
        vault.init_db(self.path)
        self.assertEqual(self.snapshot(), before)
        with closing(sqlite3.connect(self.path)) as con:
            self.assertEqual(con.execute(
                'SELECT type, name, tbl_name, sql FROM sqlite_master ORDER BY type, name'
            ).fetchall(), schema)

    def test_after_audit_fail_trigger_rolls_back_trigger_writes_too(self):
        with closing(sqlite3.connect(self.path)) as con, con:
            con.execute('''CREATE TRIGGER reject_audit AFTER INSERT ON audit BEGIN
                UPDATE accounts SET balance=999 WHERE tenant='red' AND name='c';
                SELECT RAISE(FAIL, 'private storage details'); END''')
        before = self.snapshot()
        with self.assertRaises(sqlite3.IntegrityError):
            vault.transfer(self.path, 'red', 'a', 'b', 10, 'failed')
        self.assertEqual(self.snapshot(), before)

    def test_audit_rollback_trigger_propagates_without_partial_state(self):
        with closing(sqlite3.connect(self.path)) as con, con:
            con.execute('''CREATE TRIGGER reject_audit AFTER INSERT ON audit
                BEGIN SELECT RAISE(ROLLBACK, 'private storage details'); END''')
        before = self.snapshot()
        with self.assertRaises(sqlite3.IntegrityError):
            vault.transfer(self.path, 'red', 'a', 'b', 10, 'failed')
        self.assertEqual(self.snapshot(), before)

    def test_ignored_audit_insert_is_not_a_successful_transfer(self):
        with closing(sqlite3.connect(self.path)) as con, con:
            con.execute('''CREATE TRIGGER reject_audit BEFORE INSERT ON audit
                BEGIN SELECT RAISE(IGNORE); END''')
        before = self.snapshot()
        with self.assertRaises(sqlite3.IntegrityError):
            vault.transfer(self.path, 'red', 'a', 'b', 10, 'failed')
        self.assertEqual(self.snapshot(), before)

    def test_ignored_credit_rolls_back_debit(self):
        with closing(sqlite3.connect(self.path)) as con, con:
            con.execute('''CREATE TRIGGER reject_credit BEFORE UPDATE ON accounts
                WHEN OLD.tenant='red' AND OLD.name='b'
                BEGIN SELECT RAISE(IGNORE); END''')
        before = self.snapshot()
        with self.assertRaises(sqlite3.IntegrityError):
            vault.transfer(self.path, 'red', 'a', 'b', 10, 'failed')
        self.assertEqual(self.snapshot(), before)

    def test_unique_constraint_failure_preserves_existing_history(self):
        with closing(sqlite3.connect(self.path)) as con, con:
            con.execute('CREATE UNIQUE INDEX unique_payload '
                        'ON transfers (tenant, source, target, amount)')
        before = self.snapshot()
        with self.assertRaises(sqlite3.IntegrityError):
            vault.transfer(self.path, 'red', 'a', 'b', 1, 'new-key')
        self.assertEqual(self.snapshot(), before)

    def test_failed_key_can_succeed_after_storage_recovers(self):
        with closing(sqlite3.connect(self.path)) as con, con:
            con.executescript('''
                CREATE TABLE availability (available INTEGER);
                INSERT INTO availability VALUES (0);
                CREATE TRIGGER require_available BEFORE INSERT ON audit
                WHEN (SELECT available FROM availability)=0
                BEGIN SELECT RAISE(ABORT, 'storage unavailable'); END;
            ''')
        before = self.snapshot()
        with self.assertRaises(sqlite3.IntegrityError):
            vault.transfer(self.path, 'red', 'a', 'b', 10, 'retry')
        self.assertEqual(self.snapshot(), before)
        vault.init_db(self.path)
        with closing(sqlite3.connect(self.path)) as con, con:
            con.execute('UPDATE availability SET available=1')
        result = vault.transfer(self.path, 'red', 'a', 'b', 10, 'retry')
        self.assertEqual(result['amount'], 10)
        self.assertEqual(vault.balance(self.path, 'red', 'a'), 90)
        self.assertEqual(vault.balance(self.path, 'red', 'b'), 30)
        for table in ('transfers', 'audit'):
            self.assertEqual(self.snapshot()[table].count(('red', 'retry', 'a', 'b', 10)), 1)
        with closing(sqlite3.connect(self.path)) as con:
            self.assertIsNotNone(con.execute(
                "SELECT sql FROM sqlite_master WHERE name='require_available'"
            ).fetchone())

    def test_maximum_sqlite_integer_transfers_exactly(self):
        maximum = 2**63 - 1
        with closing(sqlite3.connect(self.path)) as con, con:
            con.execute("UPDATE accounts SET balance=? WHERE tenant='red' AND name='a'",
                        (maximum,))
            con.execute("UPDATE accounts SET balance=0 WHERE tenant='red' AND name='b'")
        result = vault.transfer(self.path, 'red', 'a', 'b', maximum, 'maximum')
        self.assertEqual(result['amount'], maximum)
        self.assertEqual(vault.balance(self.path, 'red', 'a'), 0)
        self.assertEqual(vault.balance(self.path, 'red', 'b'), maximum)
        self.assertIsInstance(vault.balance(self.path, 'red', 'b'), int)

    def test_unrepresentable_credit_rolls_back_without_float_conversion(self):
        with closing(sqlite3.connect(self.path)) as con, con:
            con.execute("UPDATE accounts SET balance=? WHERE tenant='red' AND name='b'",
                        (2**63 - 1,))
        before = self.snapshot()
        with self.assertRaises(OverflowError):
            vault.transfer(self.path, 'red', 'a', 'b', 1, 'overflow')
        self.assertEqual(self.snapshot(), before)

    def simultaneous(self, requests):
        barrier = threading.Barrier(len(requests))

        def call(request):
            barrier.wait(timeout=10)
            try:
                return vault.transfer(self.path, **request)
            except ValueError as error:
                return error

        with ThreadPoolExecutor(max_workers=len(requests)) as pool:
            return list(pool.map(call, requests, timeout=35))

    def test_concurrent_duplicates_execute_once_and_remain_replayable(self):
        request = dict(tenant='red', source='a', target='b', amount=10, key='duplicate')
        expected = dict(request)
        results = self.simultaneous([dict(request) for _ in range(8)])
        self.assertEqual(results, [expected] * 8)
        self.assertEqual(vault.balance(self.path, 'red', 'a'), 90)
        self.assertEqual(vault.balance(self.path, 'red', 'b'), 30)
        before = self.snapshot()
        for table in ('transfers', 'audit'):
            self.assertEqual(before[table].count(('red', 'duplicate', 'a', 'b', 10)), 1)
        vault.init_db(self.path)
        self.assertEqual(vault.transfer(self.path, **request), expected)
        self.assertEqual(self.snapshot(), before)

    def test_concurrent_distinct_keys_cannot_overspend(self):
        before = self.snapshot()
        requests = [dict(tenant='red', source='a', target='b', amount=30, key=f'race-{i}')
                    for i in range(8)]
        results = self.simultaneous(requests)
        receipts = [result for result in results if isinstance(result, dict)]
        rejections = [result for result in results if isinstance(result, ValueError)]
        self.assertEqual(len(receipts), 3)
        self.assertEqual(len(rejections), 5)
        self.assertEqual(vault.balance(self.path, 'red', 'a'), 10)
        self.assertEqual(vault.balance(self.path, 'red', 'b'), 110)
        after = self.snapshot()
        for table in ('transfers', 'audit'):
            expected = before[table] + [
                ('red', receipt['key'], 'a', 'b', 30) for receipt in receipts
            ]
            self.assertCountEqual(after[table], expected)
        self.assertEqual([row for row in after['accounts'] if row[0] == 'blue'],
                         [row for row in before['accounts'] if row[0] == 'blue'])

    def test_concurrent_sources_do_not_lose_shared_target_credits(self):
        with closing(sqlite3.connect(self.path)) as con, con:
            con.executemany('INSERT INTO accounts VALUES (?, ?, ?)',
                            [('red', f'source-{i}', 10) for i in range(8)])
        requests = [dict(tenant='red', source=f'source-{i}', target='c', amount=7,
                         key=f'credit-{i}') for i in range(8)]
        self.assertEqual(self.simultaneous(requests), requests)
        self.assertEqual(vault.balance(self.path, 'red', 'c'), 56)
        for i in range(8):
            self.assertEqual(vault.balance(self.path, 'red', f'source-{i}'), 3)
        for table in ('transfers', 'audit'):
            self.assertEqual(len([row for row in self.snapshot()[table]
                                  if row[1].startswith('credit-')]), 8)

    def test_concurrent_conflicting_payloads_choose_one_complete_transfer(self):
        requests = [dict(tenant='red', source='a', target='b', amount=i, key='conflict')
                    for i in range(1, 9)]
        results = self.simultaneous(requests)
        receipts = [result for result in results if isinstance(result, dict)]
        self.assertEqual(len(receipts), 1)
        self.assertEqual(sum(isinstance(result, ValueError) for result in results), 7)
        amount = receipts[0]['amount']
        self.assertEqual(vault.balance(self.path, 'red', 'a'), 100 - amount)
        self.assertEqual(vault.balance(self.path, 'red', 'b'), 20 + amount)
        for table in ('transfers', 'audit'):
            self.assertEqual([row for row in self.snapshot()[table] if row[1] == 'conflict'],
                             [('red', 'conflict', 'a', 'b', amount)])

    def command(self, *args):
        return subprocess.run([sys.executable, '-B', str(ROOT / 'app.py'), *args],
                              cwd=ROOT, text=True, capture_output=True, timeout=10)

    def cli(self, request):
        return self.command(str(self.path), json.dumps(request))

    def assert_cli_success(self, result, expected):
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stderr, '')
        self.assertEqual(len(result.stdout.splitlines()), 1)
        self.assertEqual(json.loads(result.stdout), expected)

    def assert_cli_error(self, result):
        self.assertEqual(result.returncode, 2)
        self.assertEqual(result.stdout, '')
        self.assertEqual(len(result.stderr.splitlines()), 1)
        self.assertEqual(json.loads(result.stderr), {'error': 'invalid request'})

    def test_cli_integrated_journey_across_process_restarts(self):
        self.assert_cli_success(self.cli(dict(op='balance', tenant='red', account='a')), 100)
        self.assert_cli_success(self.cli(dict(op='balance', tenant='blue', account='a')), 250)
        request = dict(op='transfer', tenant='red', source='a', target='b', amount=40,
                       key='journey')
        expected = {key: value for key, value in request.items() if key != 'op'}
        self.assert_cli_success(self.cli(request), expected)
        self.assert_cli_success(self.cli(dict(op='balance', tenant='red', account='a')), 60)
        self.assert_cli_success(self.cli(dict(op='balance', tenant='red', account='b')), 60)
        before_replay = self.snapshot()
        self.assert_cli_success(self.cli(request), expected)
        self.assertEqual(self.snapshot(), before_replay)

        other_request = dict(request, tenant='blue', amount=20)
        self.assert_cli_success(self.cli(other_request), dict(expected, tenant='blue', amount=20))
        self.assert_cli_success(self.cli(dict(op='balance', tenant='blue', account='a')), 230)
        self.assert_cli_success(self.cli(dict(op='balance', tenant='blue', account='b')), 50)
        with closing(sqlite3.connect(self.path)) as con, con:
            con.execute('''CREATE TRIGGER offline_audit BEFORE INSERT ON audit
                WHEN NEW.key='offline'
                BEGIN SELECT RAISE(ABORT, 'SELECT private information FROM blue'); END''')
        before_errors = self.snapshot()
        for rejected in (
            dict(request, amount=41),
            dict(request, key='insufficient', amount=61),
            dict(request, key='foreign', target='private'),
            dict(request, key='offline', amount=1),
            dict(op='balance', tenant='red', account='private'),
            dict(op='balance', tenant='red', account='missing'),
        ):
            with self.subTest(rejected=rejected):
                self.assert_cli_error(self.cli(rejected))
                self.assertEqual(self.snapshot(), before_errors)
        vault.init_db(self.path)
        self.assert_cli_success(self.cli(request), expected)
        self.assertEqual(self.snapshot(), before_errors)
        for table in ('transfers', 'audit'):
            self.assertEqual(len([row for row in before_errors[table]
                                  if row[1] == 'journey']), 2)

    def test_cli_malformed_requests_have_one_generic_error_and_no_changes(self):
        before = self.snapshot()
        malformed = [
            '', '{', 'null', '[]', '1', '"transfer"', '{}',
            '{"op": "init_db"}', '{"op": "__dict__"}', '{"op": []}',
            '{"op": "balance", "tenant": "red"}',
            '{"op": "balance", "tenant": "red", "account": "a", "extra": 1}',
            '{"op": "balance", "tenant": "blue", "tenant": "red", "account": "a"}',
            '{"op": "transfer", "tenant": "red", "source": "a", "target": "b", '
            '"amount": true, "key": "invalid"}',
            '{"op": "transfer", "tenant": "red", "source": "a", "target": "b", '
            '"amount": NaN, "key": "invalid"}',
            '[' * 1100 + '0' + ']' * 1100,
        ]
        for payload in malformed:
            with self.subTest(payload=payload[:80]):
                self.assert_cli_error(self.command(str(self.path), payload))
                self.assertEqual(self.snapshot(), before)
        for args in ((), (str(self.path),), (str(self.path), '{}', 'extra')):
            with self.subTest(args=args):
                self.assert_cli_error(self.command(*args))
                self.assertEqual(self.snapshot(), before)

    def test_cli_storage_open_error_is_generic(self):
        self.assert_cli_error(self.command(self.directory.name,
                                          '{"op":"balance","tenant":"red","account":"a"}'))


if __name__ == '__main__':
    unittest.main()
