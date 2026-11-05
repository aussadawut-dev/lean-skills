from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
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
        self.tmp = tempfile.TemporaryDirectory(prefix='.vault-test-', dir=ROOT)
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / 'vault.sqlite'
        self.make_database(self.path)

    def make_database(self, path):
        vault.init_db(path)
        with closing(sqlite3.connect(path)) as con, con:
            # Insert the foreign names first to expose unscoped lookups.
            con.executemany('INSERT INTO accounts VALUES (?,?,?)', [
                ('other', 'a', 900), ('other', 'b', 20),
                ('other', 'private-account', 321),
                ('one', 'a', 100), ('one', 'b', 0), ('one', 'c', 100),
            ])

    def snapshot(self, path=None):
        with closing(sqlite3.connect(path or self.path)) as con:
            return {
                table: con.execute('SELECT * FROM ' + table + ' ORDER BY ' + order).fetchall()
                for table, order in (
                    ('accounts', 'tenant,name'),
                    ('transfers', 'tenant,key,source,target,amount'),
                    ('audit', 'tenant,key,source,target,amount'),
                )
            }

    def request(self, **changes):
        request = dict(tenant='one', source='a', target='b', amount=10, key='key')
        request.update(changes)
        return request

    def test_balance_isolation_and_generic_missing_account(self):
        before = self.snapshot()
        self.assertEqual(vault.balance(self.path, 'one', 'a'), 100)
        self.assertEqual(vault.balance(self.path, 'other', 'a'), 900)
        errors = []
        for tenant, account in (
            ('one', 'missing'), ('one', 'private-account'),
            ('missing', 'a'), ("one' OR 1=1 --", 'a'),
            ('one', "a' OR 1=1 --"),
        ):
            with self.subTest(tenant=tenant, account=account):
                with self.assertRaises(ValueError) as error:
                    vault.balance(self.path, tenant, account)
                errors.append(str(error.exception))
        self.assertEqual(len(set(errors)), 1)
        self.assertEqual(self.snapshot(), before)

    def test_invalid_names_are_rejected_without_writes(self):
        before = self.snapshot()
        for value in ('', None, 1, True, [], {}, b'name'):
            for field in ('tenant', 'source', 'target', 'key'):
                with self.subTest(field=field, value=value):
                    with self.assertRaises(ValueError):
                        vault.transfer(self.path, **self.request(**{field: value}))
            for args in ((value, 'a'), ('one', value)):
                with self.subTest(balance=args):
                    with self.assertRaises(ValueError):
                        vault.balance(self.path, *args)
            self.assertEqual(self.snapshot(), before)

    def test_invalid_amounts_and_endpoints_are_rejected_without_writes(self):
        before = self.snapshot()
        for amount in (0, -1, True, False, 1.0, '10', None, [], {},
                       float('nan'), float('inf'), 101, 10 ** 100):
            with self.subTest(amount=amount):
                with self.assertRaises(ValueError):
                    vault.transfer(self.path, **self.request(amount=amount))
                self.assertEqual(self.snapshot(), before)
        with self.assertRaises(ValueError):
            vault.transfer(self.path, **self.request(target='a'))
        errors = []
        for changes in ({'source': 'missing'}, {'target': 'missing'},
                        {'source': 'private-account'}, {'target': 'private-account'},
                        {'tenant': 'missing'}):
            with self.subTest(changes=changes):
                with self.assertRaises(ValueError) as error:
                    vault.transfer(self.path, **self.request(**changes))
                errors.append(str(error.exception))
                self.assertEqual(self.snapshot(), before)
        self.assertEqual(len(set(errors)), 1)

    def test_tenant_scoped_transfers_and_receipts(self):
        local = self.request(key='shared')
        other = self.request(tenant='other', amount=30, key='shared')
        self.assertEqual(vault.transfer(self.path, **local), local)
        self.assertEqual(vault.transfer(self.path, **other), other)
        self.assertEqual(vault.balance(self.path, 'one', 'a'), 90)
        self.assertEqual(vault.balance(self.path, 'one', 'b'), 10)
        self.assertEqual(vault.balance(self.path, 'other', 'a'), 870)
        self.assertEqual(vault.balance(self.path, 'other', 'b'), 50)
        self.assertEqual(vault.balance(self.path, 'other', 'private-account'), 321)
        before = self.snapshot()
        self.assertEqual(vault.transfer(self.path, **local), local)
        self.assertEqual(vault.transfer(self.path, **other), other)
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(len(before['transfers']), 2)
        self.assertEqual(before['audit'], before['transfers'])

    def test_replay_after_depletion_and_reopening_and_payload_conflicts(self):
        request = self.request(amount=100)
        receipt = vault.transfer(self.path, **request)
        self.assertEqual(receipt, request)
        before = self.snapshot()
        vault.init_db(self.path)
        receipt['amount'] = 999  # Returned dictionaries do not change stored receipts.
        self.assertEqual(vault.transfer(self.path, **request), request)
        self.assertEqual(self.snapshot(), before)
        for changes in ({'amount': 1}, {'source': 'c'}, {'target': 'c'},
                        {'source': 'b', 'target': 'a'}):
            with self.subTest(changes=changes):
                with self.assertRaises(ValueError):
                    vault.transfer(self.path, **dict(request, **changes))
                self.assertEqual(self.snapshot(), before)
        self.assertEqual(vault.balance(self.path, 'one', 'a'), 0)
        self.assertEqual(before['audit'], before['transfers'])
        self.assertEqual(len(before['audit']), 1)

    def test_existing_rows_and_malformed_foreign_data_are_preserved(self):
        with closing(sqlite3.connect(self.path)) as con, con:
            con.execute("UPDATE accounts SET balance='foreign-bad-data' WHERE tenant='other'")
            row = ('other', 'historic', 'a', 'b', 8)
            con.execute('INSERT INTO transfers VALUES (?,?,?,?,?)', row)
            con.execute('INSERT INTO audit VALUES (?,?,?,?,?)', row)
        before = self.snapshot()
        vault.init_db(self.path)
        self.assertEqual(self.snapshot(), before)
        vault.transfer(self.path, **self.request())
        after = self.snapshot()
        for table in before:
            self.assertEqual([row for row in after[table] if row[0] == 'other'],
                             [row for row in before[table] if row[0] == 'other'])
        self.assertEqual(vault.balance(self.path, 'one', 'a'), 90)

    def test_storage_and_audit_failures_roll_back_every_effect(self):
        cases = (
            ('BEFORE UPDATE', 'accounts', "NEW.tenant='one' AND NEW.name='a' AND NEW.balance=83", 'ABORT'),
            ('AFTER UPDATE', 'accounts', "NEW.tenant='one' AND NEW.name='b' AND NEW.balance=17", 'FAIL'),
            ('AFTER INSERT', 'transfers', "NEW.key='failure'", 'FAIL'),
            ('BEFORE INSERT', 'audit', "NEW.key='failure'", 'ABORT'),
            ('AFTER INSERT', 'audit', "NEW.key='failure'", 'FAIL'),
            ('BEFORE INSERT', 'audit', "NEW.key='failure'", 'ROLLBACK'),
            ('BEFORE UPDATE', 'accounts', "NEW.name='b' AND NEW.balance=17", 'IGNORE'),
            ('BEFORE INSERT', 'transfers', "NEW.key='failure'", 'IGNORE'),
            ('BEFORE INSERT', 'audit', "NEW.key='failure'", 'IGNORE'),
        )
        for index, (event, table, condition, action) in enumerate(cases):
            with self.subTest(event=event, table=table, action=action):
                path = Path(self.tmp.name) / ('failure-%s.sqlite' % index)
                self.make_database(path)
                vault.transfer(path, **self.request(key='historic'))
                error = action if action == 'IGNORE' else action + ", 'private storage detail'"
                with closing(sqlite3.connect(path)) as con:
                    con.execute('CREATE TRIGGER failure_gate ' + event + ' ON ' + table
                                + ' WHEN ' + condition + ' BEGIN SELECT RAISE(' + error + '); END')
                    trigger = con.execute("SELECT sql FROM sqlite_master WHERE type='trigger'").fetchall()
                before = self.snapshot(path)
                with self.assertRaises(sqlite3.Error):
                    vault.transfer(path, **self.request(amount=7, key='failure'))
                self.assertEqual(self.snapshot(path), before)
                # The conditional trigger stays installed; a valid control works.
                control = self.request(amount=3, key='control')
                self.assertEqual(vault.transfer(path, **control), control)
                with closing(sqlite3.connect(path)) as con:
                    self.assertEqual(con.execute("SELECT sql FROM sqlite_master WHERE type='trigger'").fetchall(), trigger)
                self.assertEqual(vault.balance(path, 'one', 'a'), 87)
                self.assertEqual(vault.balance(path, 'one', 'b'), 13)

    def test_credit_integer_overflow_rolls_back_debit(self):
        with closing(sqlite3.connect(self.path)) as con, con:
            con.execute("UPDATE accounts SET balance=? WHERE tenant='one' AND name='b'", (2 ** 63 - 1,))
        before = self.snapshot()
        with self.assertRaises(OverflowError):
            vault.transfer(self.path, **self.request())
        self.assertEqual(self.snapshot(), before)

    def run_concurrently(self, requests):
        barrier = threading.Barrier(len(requests))

        def run(request):
            barrier.wait(timeout=10)
            try:
                return vault.transfer(self.path, **request)
            except ValueError as error:
                return error

        with ThreadPoolExecutor(max_workers=len(requests)) as pool:
            return list(pool.map(run, requests))

    def test_simultaneous_duplicate_requests_execute_once(self):
        request = self.request(amount=7)
        receipts = self.run_concurrently([request] * 8)
        self.assertEqual(receipts, [request] * 8)
        self.assertEqual(vault.balance(self.path, 'one', 'a'), 93)
        self.assertEqual(vault.balance(self.path, 'one', 'b'), 7)
        before = self.snapshot()
        self.assertEqual(len(before['transfers']), 1)
        self.assertEqual(before['audit'], before['transfers'])
        vault.init_db(self.path)
        self.assertEqual(vault.transfer(self.path, **request), request)
        self.assertEqual(self.snapshot(), before)

    def test_simultaneous_key_conflict_has_one_winner(self):
        requests = [self.request(amount=7), self.request(amount=9)]
        results = self.run_concurrently(requests)
        successes = [result for result in results if isinstance(result, dict)]
        self.assertEqual(len(successes), 1)
        self.assertEqual(sum(isinstance(result, ValueError) for result in results), 1)
        amount = successes[0]['amount']
        self.assertEqual(vault.balance(self.path, 'one', 'a'), 100 - amount)
        self.assertEqual(vault.balance(self.path, 'one', 'b'), amount)
        state = self.snapshot()
        self.assertEqual(len(state['transfers']), 1)
        self.assertEqual(state['audit'], state['transfers'])

    def test_distinct_keys_cannot_overspend(self):
        requests = [self.request(amount=15, key='spend-%s' % index) for index in range(12)]
        results = self.run_concurrently(requests)
        successes = [result for result in results if isinstance(result, dict)]
        self.assertEqual(len(successes), 6)
        self.assertEqual(sum(isinstance(result, ValueError) for result in results), 6)
        self.assertEqual(vault.balance(self.path, 'one', 'a'), 10)
        self.assertEqual(vault.balance(self.path, 'one', 'b'), 90)
        state = self.snapshot()
        self.assertEqual({row[1] for row in state['transfers']}, {row['key'] for row in successes})
        self.assertEqual(state['audit'], state['transfers'])

    def test_concurrent_sources_do_not_lose_credits(self):
        requests = [self.request(source=source, amount=3, key=source + str(index))
                    for source in ('a', 'c') for index in range(5)]
        self.assertEqual(self.run_concurrently(requests), requests)
        self.assertEqual(vault.balance(self.path, 'one', 'a'), 85)
        self.assertEqual(vault.balance(self.path, 'one', 'c'), 85)
        self.assertEqual(vault.balance(self.path, 'one', 'b'), 30)
        state = self.snapshot()
        self.assertEqual(len(state['transfers']), 10)
        self.assertEqual(state['audit'], state['transfers'])

    def cli(self, *args):
        return subprocess.run([sys.executable, '-B', str(ROOT / 'app.py'), *args],
                              cwd=ROOT, text=True, capture_output=True, timeout=10)

    def cli_request(self, request):
        return self.cli(str(self.path), json.dumps(request))

    def assert_cli_success(self, process, expected):
        self.assertEqual(process.returncode, 0, process.stderr)
        self.assertEqual(process.stderr, '')
        self.assertEqual(len(process.stdout.splitlines()), 1)
        self.assertEqual(json.loads(process.stdout), expected)

    def assert_cli_error(self, process):
        self.assertEqual(process.returncode, 2, process.stderr)
        self.assertEqual(process.stdout, '')
        self.assertEqual(len(process.stderr.splitlines()), 1)
        self.assertEqual(json.loads(process.stderr), {'error': 'invalid request'})

    def test_cli_integrated_journey_with_reopen_replay_and_recovery(self):
        self.assert_cli_success(self.cli_request(dict(op='balance', tenant='one', account='a')), 100)
        request = self.request(key='journey')
        self.assert_cli_success(self.cli_request(dict(op='transfer', **request)), request)
        before = self.snapshot()
        self.assert_cli_success(self.cli_request(dict(op='transfer', **request)), request)
        self.assertEqual(self.snapshot(), before)
        self.assert_cli_error(self.cli_request(dict(op='transfer', **dict(request, amount=11))))
        self.assert_cli_error(self.cli_request(dict(op='balance', tenant='one', account='private-account')))
        self.assertEqual(self.snapshot(), before)
        other = dict(request, tenant='other', amount=20)
        self.assert_cli_success(self.cli_request(dict(op='transfer', **other)), other)
        with closing(sqlite3.connect(self.path)) as con:
            con.execute("CREATE TRIGGER audit_gate AFTER INSERT ON audit WHEN NEW.key='blocked' "
                        "BEGIN SELECT RAISE(FAIL, 'other private-account secret SQL INSERT'); END")
        before = self.snapshot()
        self.assert_cli_error(self.cli_request(dict(op='transfer', **dict(request, key='blocked'))))
        self.assertEqual(self.snapshot(), before)
        recovery = dict(request, key='recovery', amount=5)
        self.assert_cli_success(self.cli_request(dict(op='transfer', **recovery)), recovery)
        for tenant, account, expected in (('one', 'a', 85), ('one', 'b', 15),
                                          ('other', 'a', 880), ('other', 'b', 40)):
            self.assert_cli_success(self.cli_request(dict(op='balance', tenant=tenant, account=account)), expected)
        state = self.snapshot()
        self.assertEqual(len(state['audit']), 3)
        self.assertEqual(state['audit'], state['transfers'])

    def test_cli_rejects_invalid_shapes_operations_and_values(self):
        before = self.snapshot()
        requests = [None, [], 'balance', 1, {}, {'op': 'init_db'}, {'op': '__dict__'},
                    {'op': []}, {'op': 'balance', 'tenant': 'one'},
                    {'op': 'balance', 'tenant': 'one', 'account': 'a', 'extra': 1},
                    {'op': 'balance', 'tenant': None, 'account': 'a'},
                    dict(op='transfer', **self.request(amount=True)),
                    dict(op='transfer', **self.request(amount='10')),
                    dict(op='transfer', **self.request(amount=101)),
                    dict(op='transfer', **self.request(target='private-account'))]
        for request in requests:
            with self.subTest(request=request):
                self.assert_cli_error(self.cli_request(request))
        for args in ((), (str(self.path),), (str(self.path), '{}', 'extra'),
                     (str(self.path), '{'), (str(self.path), 'NaN'),
                     (str(self.path), '[' * 2000 + ']' * 2000),
                     (self.tmp.name, json.dumps(dict(op='balance', tenant='one', account='a')))):
            with self.subTest(argument_count=len(args)):
                self.assert_cli_error(self.cli(*args))
        self.assertEqual(self.snapshot(), before)


if __name__ == '__main__':
    unittest.main()
