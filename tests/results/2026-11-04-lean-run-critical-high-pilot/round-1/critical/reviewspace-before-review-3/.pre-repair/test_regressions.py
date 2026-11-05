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


WORKSPACE = Path(__file__).resolve().parent


class VaultRegressions(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(dir=WORKSPACE)
        self.addCleanup(temporary.cleanup)
        self.path = Path(temporary.name) / 'vault.sqlite'
        vault.init_db(self.path)
        with closing(sqlite3.connect(self.path)) as con, con:
            con.executemany('INSERT INTO accounts VALUES (?,?,?)', [
                ('alpha', 'source', 100), ('alpha', 'target', 0),
                ('alpha', 'other', 40),
                ('beta', 'source', 300), ('beta', 'target', 20),
                ('beta', 'private-account', 700),
            ])

    def snapshot(self):
        with closing(sqlite3.connect(self.path)) as con:
            return {
                'accounts': con.execute(
                    'SELECT tenant,name,balance FROM accounts ORDER BY tenant,name'
                ).fetchall(),
                'transfers': con.execute(
                    'SELECT tenant,key,source,target,amount FROM transfers '
                    'ORDER BY tenant,key,source,target,amount'
                ).fetchall(),
                'audit': con.execute(
                    'SELECT tenant,key,source,target,amount FROM audit '
                    'ORDER BY tenant,key,source,target,amount'
                ).fetchall(),
            }

    def send(self, **changes):
        request = dict(tenant='alpha', source='source', target='target', amount=10, key='key')
        request.update(changes)
        return vault.transfer(self.path, **request)

    def run_concurrently(self, requests):
        barrier = threading.Barrier(len(requests))

        def call(request):
            barrier.wait(timeout=10)
            try:
                return self.send(**request)
            except ValueError as exc:
                return exc

        with ThreadPoolExecutor(max_workers=len(requests)) as pool:
            return list(pool.map(call, requests))

    def cli(self, request):
        return self.raw_cli(str(self.path), json.dumps(request))

    def raw_cli(self, *args):
        return subprocess.run(
            [sys.executable, '-B', str(WORKSPACE / 'app.py'), *args],
            cwd=WORKSPACE, capture_output=True, text=True, timeout=15,
        )

    def assert_cli_error(self, result):
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertEqual(result.stdout, '')
        self.assertEqual(json.loads(result.stderr), {'error': 'invalid request'})
        self.assertEqual(len(result.stderr.splitlines()), 1)

    def test_balance_and_transfer_are_tenant_scoped(self):
        self.assertEqual(vault.balance(self.path, 'alpha', 'source'), 100)
        self.assertEqual(vault.balance(self.path, 'beta', 'source'), 300)
        before = self.snapshot()
        receipt = self.send()
        self.assertEqual(receipt, dict(
            tenant='alpha', key='key', source='source', target='target', amount=10,
        ))
        after = self.snapshot()
        self.assertEqual(vault.balance(self.path, 'alpha', 'source'), 90)
        self.assertEqual(vault.balance(self.path, 'alpha', 'target'), 10)
        self.assertEqual(
            [row for row in after['accounts'] if row[0] == 'beta'],
            [row for row in before['accounts'] if row[0] == 'beta'],
        )
        self.assertEqual(vault.balance(self.path, 'alpha', 'other'), 40)
        self.assertEqual(after['transfers'], [('alpha', 'key', 'source', 'target', 10)])
        self.assertEqual(after['audit'], after['transfers'])

    def test_missing_and_inaccessible_accounts_share_one_error(self):
        before = self.snapshot()
        errors = []
        for account in ('missing', 'private-account'):
            with self.assertRaises(ValueError) as caught:
                vault.balance(self.path, 'alpha', account)
            errors.append(caught.exception.args)
            for field in ('source', 'target'):
                with self.subTest(account=account, field=field):
                    with self.assertRaises(ValueError) as caught:
                        self.send(**{field: account})
                    errors.append(caught.exception.args)
        with self.assertRaises(ValueError) as caught:
            self.send(tenant='unknown')
        errors.append(caught.exception.args)
        self.assertEqual(len(set(errors)), 1)
        self.assertEqual(errors[0], ('account unavailable',))
        self.assertEqual(self.snapshot(), before)

    def test_invalid_requests_leave_database_unchanged(self):
        invalid_names = ('', None, True, 1, 1.5, b'source', [], {})
        before = self.snapshot()
        for value in invalid_names:
            for field in ('tenant', 'source', 'target', 'key'):
                with self.subTest(field=field, value=value):
                    with self.assertRaises(ValueError):
                        self.send(**{field: value})
            for tenant, account in ((value, 'source'), ('alpha', value)):
                with self.assertRaises(ValueError):
                    vault.balance(self.path, tenant, account)
        for amount in (0, -1, True, False, 1.0, '1', None, [], {}, float('inf'), float('nan')):
            with self.subTest(amount=amount):
                with self.assertRaises(ValueError):
                    self.send(amount=amount)
        for changes in ({'target': 'source'}, {'amount': 101}, {'amount': 2 ** 100}):
            with self.subTest(changes=changes):
                with self.assertRaises(ValueError):
                    self.send(**changes)
        self.assertEqual(self.snapshot(), before)

    def test_validation_precedes_database_creation(self):
        path = self.path.parent / 'must-not-exist.sqlite'
        with self.assertRaises(ValueError):
            vault.transfer(path, 'alpha', 'source', 'target', True, 'key')
        with self.assertRaises(ValueError):
            vault.balance(path, '', 'source')
        self.assertFalse(path.exists())

    def test_names_are_literal_nonempty_strings(self):
        tenant = "tenant' OR 1=1 -- λ"
        source = "source'; DROP TABLE accounts; --"
        with closing(sqlite3.connect(self.path)) as con, con:
            con.executemany('INSERT INTO accounts VALUES (?,?,?)', [
                (tenant, source, 9), (tenant, ' ', 0),
            ])
        receipt = vault.transfer(self.path, tenant, source, ' ', 9, "key' -- λ")
        self.assertEqual(receipt['tenant'], tenant)
        self.assertEqual(vault.balance(self.path, tenant, source), 0)
        self.assertEqual(vault.balance(self.path, tenant, ' '), 9)
        self.assertEqual(vault.balance(self.path, 'alpha', 'source'), 100)

    def test_foreign_malformed_storage_is_not_used(self):
        with closing(sqlite3.connect(self.path)) as con, con:
            con.execute(
                'UPDATE accounts SET balance=? WHERE tenant=? AND name=?',
                ('foreign-private-invalid-balance', 'beta', 'source'),
            )
            con.execute('INSERT INTO transfers VALUES (?,?,?,?,?)', (
                'beta', 'key', 'private-source', 'private-target', 'private-amount',
            ))
        before = self.snapshot()
        self.assertEqual(vault.balance(self.path, 'alpha', 'source'), 100)
        self.assertEqual(self.send()['tenant'], 'alpha')
        after = self.snapshot()
        for table in ('accounts', 'transfers', 'audit'):
            self.assertEqual(
                [row for row in before[table] if row[0] == 'beta'],
                [row for row in after[table] if row[0] == 'beta'],
            )

    def test_replay_survives_reopening_and_returns_detached_receipts(self):
        receipt = self.send(amount=100)
        expected = receipt.copy()
        before = self.snapshot()
        receipt['amount'] = 999
        receipt['tenant'] = 'beta'
        vault.init_db(self.path)
        replay = self.send(amount=100)
        self.assertEqual(replay, expected)
        replay.clear()
        self.assertEqual(self.send(amount=100), expected)
        self.assertEqual(self.snapshot(), before)

    def test_conflicts_reject_every_payload_change_without_writes(self):
        self.send()
        before = self.snapshot()
        for changes in ({'source': 'other'}, {'target': 'other'}, {'amount': 11}, {'amount': True}):
            with self.subTest(changes=changes):
                with self.assertRaises(ValueError):
                    self.send(**changes)
                self.assertEqual(self.snapshot(), before)

    def test_same_key_is_independent_for_each_tenant(self):
        first = self.send()
        second = self.send(tenant='beta', amount=25)
        self.assertEqual(first['tenant'], 'alpha')
        self.assertEqual(second['tenant'], 'beta')
        before = self.snapshot()
        self.assertEqual(self.send(), first)
        self.assertEqual(self.send(tenant='beta', amount=25), second)
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(vault.balance(self.path, 'beta', 'source'), 275)
        self.assertEqual(vault.balance(self.path, 'beta', 'target'), 45)
        self.assertEqual(len(before['audit']), 2)

    def test_init_preserves_existing_schema_history_and_trigger(self):
        self.send()
        with closing(sqlite3.connect(self.path)) as con, con:
            con.execute('''CREATE TRIGGER existing_guard BEFORE INSERT ON audit
                           WHEN NEW.amount < 0 BEGIN SELECT RAISE(ABORT, 'negative'); END''')
            schema = con.execute('SELECT type,name,sql FROM sqlite_master ORDER BY type,name').fetchall()
        before = self.snapshot()
        vault.init_db(self.path)
        self.assertEqual(self.snapshot(), before)
        with closing(sqlite3.connect(self.path)) as con:
            self.assertEqual(
                con.execute('SELECT type,name,sql FROM sqlite_master ORDER BY type,name').fetchall(),
                schema,
            )

    def test_failure_at_each_write_rolls_back_and_preserves_history(self):
        self.send(key='previous')
        self.send(tenant='beta', key='previous')
        cases = (
            ('accounts', 'UPDATE', "NEW.tenant='alpha' AND NEW.name='source'"),
            ('accounts', 'UPDATE', "NEW.tenant='alpha' AND NEW.name='target'"),
            ('transfers', 'INSERT', "NEW.key='fail'"),
            ('audit', 'INSERT', "NEW.key='fail'"),
        )
        for action in ('ABORT', 'FAIL', 'ROLLBACK'):
            for table, event, condition in cases:
                with self.subTest(action=action, table=table, condition=condition):
                    trigger = (
                        f'CREATE TRIGGER reject_write BEFORE {event} ON {table} '
                        f"WHEN {condition} BEGIN SELECT RAISE({action}, 'private-storage-error'); END"
                    )
                    with closing(sqlite3.connect(self.path)) as con, con:
                        con.execute(trigger)
                    before = self.snapshot()
                    with self.assertRaises(sqlite3.IntegrityError):
                        self.send(key='fail')
                    self.assertEqual(self.snapshot(), before)
                    with closing(sqlite3.connect(self.path)) as con, con:
                        self.assertEqual(con.execute(
                            "SELECT sql FROM sqlite_master WHERE name='reject_write'"
                        ).fetchone()[0], trigger)
                        con.execute('DROP TRIGGER reject_write')
        self.send(key='fail')
        self.assertEqual(len(self.snapshot()['audit']), 3)

    def test_balance_overflow_is_a_storage_failure_without_partial_debit(self):
        with closing(sqlite3.connect(self.path)) as con, con:
            con.execute(
                'UPDATE accounts SET balance=? WHERE tenant=? AND name=?',
                (2 ** 63 - 1, 'alpha', 'target'),
            )
        before = self.snapshot()
        with self.assertRaises(OverflowError):
            self.send()
        self.assertEqual(self.snapshot(), before)

    def test_ignored_required_write_rolls_back(self):
        cases = (
            ('accounts', 'UPDATE', "NEW.tenant='alpha' AND NEW.name='source'"),
            ('accounts', 'UPDATE', "NEW.tenant='alpha' AND NEW.name='target'"),
            ('transfers', 'INSERT', "NEW.key LIKE 'ignored-%'"),
            ('audit', 'INSERT', "NEW.key LIKE 'ignored-%'"),
        )
        for index, (table, event, condition) in enumerate(cases):
            with self.subTest(table=table, condition=condition):
                with closing(sqlite3.connect(self.path)) as con, con:
                    con.execute(
                        f'CREATE TRIGGER skip_write BEFORE {event} ON {table} '
                        f'WHEN {condition} BEGIN SELECT RAISE(IGNORE); END'
                    )
                try:
                    before = self.snapshot()
                    with self.assertRaises(sqlite3.IntegrityError):
                        self.send(key=f'ignored-{index}')
                    self.assertEqual(self.snapshot(), before)
                    # A harmless trigger condition still permits a normal transfer.
                    self.send(tenant='beta', key=f'allowed-{index}')
                    with closing(sqlite3.connect(self.path)) as con:
                        self.assertIsNotNone(con.execute(
                            "SELECT sql FROM sqlite_master WHERE name='skip_write'"
                        ).fetchone())
                finally:
                    with closing(sqlite3.connect(self.path)) as con, con:
                        con.execute('DROP TRIGGER skip_write')

    def test_concurrent_same_key_executes_once(self):
        results = self.run_concurrently([{'amount': 60}] * 8)
        expected = dict(tenant='alpha', key='key', source='source', target='target', amount=60)
        self.assertEqual(results, [expected] * 8)
        self.assertEqual(vault.balance(self.path, 'alpha', 'source'), 40)
        self.assertEqual(vault.balance(self.path, 'alpha', 'target'), 60)
        state = self.snapshot()
        self.assertEqual(state['transfers'], [('alpha', 'key', 'source', 'target', 60)])
        self.assertEqual(state['audit'], state['transfers'])
        self.assertEqual(self.send(amount=60), expected)
        self.assertEqual(self.snapshot(), state)

    def test_concurrent_same_key_different_payload_conflicts(self):
        results = self.run_concurrently([{'amount': 10}, {'amount': 20}])
        receipts = [result for result in results if isinstance(result, dict)]
        conflicts = [result for result in results if isinstance(result, ValueError)]
        self.assertEqual(len(receipts), 1)
        self.assertEqual(len(conflicts), 1)
        amount = receipts[0]['amount']
        self.assertEqual(vault.balance(self.path, 'alpha', 'source'), 100 - amount)
        self.assertEqual(vault.balance(self.path, 'alpha', 'target'), amount)
        self.assertEqual(len(self.snapshot()['audit']), 1)

    def test_concurrent_distinct_keys_cannot_overspend(self):
        results = self.run_concurrently([{'key': f'key-{i}', 'amount': 30} for i in range(8)])
        successes = [result for result in results if isinstance(result, dict)]
        failures = [result for result in results if isinstance(result, ValueError)]
        self.assertEqual(len(successes), 3)
        self.assertEqual(len(failures), 5)
        self.assertEqual(vault.balance(self.path, 'alpha', 'source'), 10)
        self.assertEqual(vault.balance(self.path, 'alpha', 'target'), 90)
        state = self.snapshot()
        self.assertEqual(len(state['transfers']), 3)
        self.assertEqual(state['audit'], state['transfers'])
        for receipt in successes:
            self.assertEqual(self.send(key=receipt['key'], amount=30), receipt)
        self.assertEqual(self.snapshot(), state)

    def test_concurrent_sources_do_not_lose_shared_target_credits(self):
        with closing(sqlite3.connect(self.path)) as con, con:
            con.executemany('INSERT INTO accounts VALUES (?,?,?)', [
                ('alpha', f'source-{i}', 10) for i in range(8)
            ])
        results = self.run_concurrently([
            {'source': f'source-{i}', 'key': f'key-{i}'} for i in range(8)
        ])
        self.assertTrue(all(isinstance(result, dict) for result in results))
        self.assertEqual(vault.balance(self.path, 'alpha', 'target'), 80)
        for i in range(8):
            self.assertEqual(vault.balance(self.path, 'alpha', f'source-{i}'), 0)
        state = self.snapshot()
        self.assertEqual(len(state['transfers']), 8)
        self.assertEqual(state['audit'], state['transfers'])

    def test_cli_integrated_journey_replay_conflict_isolation_and_recovery(self):
        query = dict(op='balance', tenant='alpha', account='source')
        result = self.cli(query)
        self.assertEqual((result.returncode, json.loads(result.stdout), result.stderr), (0, 100, ''))
        request = dict(op='transfer', tenant='alpha', source='source', target='target', amount=15, key='shared')
        first = self.cli(request)
        expected = {key: value for key, value in request.items() if key != 'op'}
        self.assertEqual((first.returncode, json.loads(first.stdout), first.stderr), (0, expected, ''))
        committed = self.snapshot()
        replay = self.cli(request)
        self.assertEqual((replay.returncode, replay.stdout, replay.stderr), (0, first.stdout, ''))
        self.assert_cli_error(self.cli(dict(request, amount=16)))
        self.assert_cli_error(self.cli(dict(request, key='missing', target='private-account')))
        self.assert_cli_error(self.cli(dict(request, key='expensive', amount=200)))
        self.assertEqual(self.snapshot(), committed)
        second = self.cli(dict(request, tenant='beta'))
        self.assertEqual((second.returncode, second.stderr), (0, ''))
        self.assertEqual(json.loads(second.stdout), dict(expected, tenant='beta'))
        with closing(sqlite3.connect(self.path)) as con, con:
            con.execute('''CREATE TRIGGER unavailable_audit BEFORE INSERT ON audit
                           WHEN NEW.key='unavailable' BEGIN
                           SELECT RAISE(ABORT, 'beta-private-storage-detail'); END''')
        before = self.snapshot()
        self.assert_cli_error(self.cli(dict(request, key='unavailable')))
        self.assertEqual(self.snapshot(), before)
        recovered = self.cli(dict(request, key='recovered'))
        self.assertEqual((recovered.returncode, recovered.stderr), (0, ''))
        final = self.cli(query)
        self.assertEqual((final.returncode, json.loads(final.stdout), final.stderr), (0, 70, ''))
        self.assertEqual(vault.balance(self.path, 'beta', 'source'), 285)
        self.assertEqual(len(self.snapshot()['audit']), 3)

    def test_cli_invalid_shapes_and_types_are_generic_and_do_not_write(self):
        before = self.snapshot()
        valid = dict(op='transfer', tenant='alpha', source='source', target='target', amount=10, key='key')
        requests = [
            None, [], 'text', 4, {}, {'op': []}, {'op': 'init_db'},
            {'op': '__dict__'}, {'op': 'balance', 'tenant': 'alpha'},
            {'op': 'balance', 'tenant': 'alpha', 'account': 'private-account'},
            {'op': 'balance', 'tenant': 'alpha', 'account': 'missing'},
            {'op': 'balance', 'tenant': 'alpha', 'account': 'source', 'extra': 1},
            dict(valid, amount=True), dict(valid, amount=1.5),
            dict(valid, amount='10'), dict(valid, amount=-1),
            dict(valid, tenant=''), dict(valid, source=None), dict(valid, key=[]),
            dict(valid, target='source'), dict(valid, extra='private'),
            {key: value for key, value in valid.items() if key != 'key'},
        ]
        for request in requests:
            with self.subTest(request=request):
                self.assert_cli_error(self.cli(request))
        for args in ((), (str(self.path),), (str(self.path), '{'), (str(self.path), '{}', 'extra')):
            with self.subTest(args=args):
                self.assert_cli_error(self.raw_cli(*args))
        self.assertEqual(self.snapshot(), before)


if __name__ == '__main__':
    unittest.main()
