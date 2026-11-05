from collections import Counter
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


class VaultRegressionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='.vault-test-', dir=WORKSPACE)
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / 'vault.sqlite'
        vault.init_db(self.path)
        with closing(sqlite3.connect(self.path)) as con, con:
            con.executemany('INSERT INTO accounts VALUES (?,?,?)', [
                ('one', 'a', 100), ('one', 'b', 0), ('one', 'c', 50),
                ('two', 'a', 700), ('two', 'b', 11),
                ('two', 'private', 900), ('two', 'broken', 'foreign secret'),
            ])
            for table in ('transfers', 'audit'):
                con.executemany('INSERT INTO ' + table + ' VALUES (?,?,?,?,?)', [
                    ('one', 'historic', 'a', 'b', 7),
                    ('two', 'historic', 'a', 'b', 9),
                ])
            # Existing audit multiplicities must survive initialization/writes.
            con.execute("INSERT INTO audit VALUES ('one','historic','a','b',7)")

    def execute(self, sql, parameters=()):
        with closing(sqlite3.connect(self.path)) as con, con:
            return con.execute(sql, parameters).fetchall()

    def snapshot(self):
        with closing(sqlite3.connect(self.path)) as con:
            return {table: Counter(con.execute('SELECT * FROM ' + table))
                    for table in ('accounts', 'transfers', 'audit')}

    def request(self, **changes):
        request = dict(tenant='one', source='a', target='b', amount=10, key='new')
        request.update(changes)
        return request

    def assert_transfer_delta(self, before, *receipts):
        expected = {table: rows.copy() for table, rows in before.items()}
        balances = {(tenant, name): amount
                    for tenant, name, amount in before['accounts']}
        for receipt in receipts:
            tenant = receipt['tenant']
            for name, delta in ((receipt['source'], -receipt['amount']),
                                (receipt['target'], receipt['amount'])):
                old = balances[tenant, name]
                expected['accounts'][tenant, name, old] -= 1
                balances[tenant, name] = old + delta
                expected['accounts'][tenant, name, old + delta] += 1
            row = tuple(receipt[field] for field in
                        ('tenant', 'key', 'source', 'target', 'amount'))
            expected['transfers'][row] += 1
            expected['audit'][row] += 1
        self.assertEqual(self.snapshot(), expected)

    def test_init_preserves_schema_history_and_triggers(self):
        self.execute('CREATE TRIGGER 审核 BEFORE INSERT ON audit '
                     "WHEN NEW.key='blocked' BEGIN SELECT 1; "
                     "SELECT RAISE(ABORT, 'audit unavailable'); END")
        schema = self.execute('SELECT name, sql FROM sqlite_schema ORDER BY name')
        before = self.snapshot()
        vault.init_db(self.path)
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(self.execute('SELECT name, sql FROM sqlite_schema ORDER BY name'),
                         schema)

    def test_balance_is_scoped_and_missing_accounts_are_indistinguishable(self):
        before = self.snapshot()
        self.assertEqual(vault.balance(self.path, 'one', 'a'), 100)
        self.assertEqual(vault.balance(self.path, 'two', 'a'), 700)
        errors = []
        for name in ('private', 'broken', 'missing'):
            with self.assertRaises(ValueError) as caught:
                vault.balance(self.path, 'one', name)
            errors.append(str(caught.exception))
        self.assertEqual(len(set(errors)), 1)
        self.assertEqual(self.snapshot(), before)

    def test_transfer_changes_only_its_tenant_and_preserves_history(self):
        before = self.snapshot()
        receipt = vault.transfer(self.path, **self.request())
        self.assertEqual(receipt, self.request())
        self.assert_transfer_delta(before, receipt)

    def test_both_transfer_accounts_must_exist_in_tenant(self):
        before = self.snapshot()
        errors = []
        for field in ('source', 'target'):
            for name in ('missing', 'private', 'broken'):
                with self.subTest(field=field, name=name):
                    with self.assertRaises(ValueError) as caught:
                        vault.transfer(self.path, **self.request(**{field: name}))
                    errors.append(str(caught.exception))
                    self.assertEqual(self.snapshot(), before)
        self.assertEqual(len(set(errors)), 1)

    def test_invalid_names_and_amounts_make_no_changes(self):
        before = self.snapshot()
        invalid_names = ('', None, 1, True, [], {})
        for field in ('tenant', 'account'):
            for value in invalid_names:
                request = dict(tenant='one', account='a')
                request[field] = value
                with self.subTest(api='balance', field=field, value=value):
                    with self.assertRaises(ValueError):
                        vault.balance(self.path, **request)
        for field in ('tenant', 'source', 'target', 'key'):
            for value in invalid_names:
                with self.subTest(api='transfer', field=field, value=value):
                    with self.assertRaises(ValueError):
                        vault.transfer(self.path, **self.request(**{field: value}))
        for amount in (True, False, 0, -1, 1.5, '1', None, [], {}, 10**100):
            with self.subTest(amount=amount):
                with self.assertRaises(ValueError):
                    vault.transfer(self.path, **self.request(amount=amount))
        for request in (self.request(target='a'), self.request(amount=101)):
            with self.assertRaises(ValueError):
                vault.transfer(self.path, **request)
        self.assertEqual(self.snapshot(), before)

    def test_unicode_and_sql_shaped_strings_are_literal_names(self):
        tenant = "租户' OR 1=1 --"
        self.execute('INSERT INTO accounts VALUES (?,?,?)', (tenant, 'α', 10))
        self.execute('INSERT INTO accounts VALUES (?,?,?)', (tenant, ' ', 0))
        before = self.snapshot()
        receipt = vault.transfer(self.path, tenant, 'α', ' ', 1,
                                 "k'; DROP TABLE accounts; --")
        self.assertEqual(vault.balance(self.path, tenant, 'α'), 9)
        self.assert_transfer_delta(before, receipt)

    def test_replay_after_reopening_and_exhausting_source_is_read_only(self):
        request = self.request(amount=100)
        original = vault.transfer(self.path, **request)
        before = self.snapshot()
        vault.init_db(self.path)
        self.assertEqual(vault.transfer(self.path, **request), original)
        self.assertEqual(vault.balance(self.path, 'one', 'a'), 0)
        self.assertEqual(self.snapshot(), before)

    def test_replays_compare_all_payload_fields_and_validate_input(self):
        vault.transfer(self.path, **self.request())
        before = self.snapshot()
        for changes in ({'source': 'c'}, {'target': 'c'}, {'amount': 11},
                        {'source': 'b', 'target': 'a'}, {'amount': True}):
            with self.subTest(changes=changes):
                with self.assertRaises(ValueError):
                    vault.transfer(self.path, **self.request(**changes))
                self.assertEqual(self.snapshot(), before)

    def test_keys_and_cached_receipts_are_tenant_scoped(self):
        before = self.snapshot()
        one = vault.transfer(self.path, **self.request(key='shared'))
        two_request = self.request(tenant='two', key='shared', amount=20)
        two = vault.transfer(self.path, **two_request)
        self.assertEqual(two, two_request)
        self.assert_transfer_delta(before, one, two)
        snapshot = self.snapshot()
        for tenant in ('unknown', 'three'):
            with self.assertRaises(ValueError):
                vault.transfer(self.path, **self.request(tenant=tenant, key='shared'))
        self.assertEqual(vault.transfer(self.path, **two_request), two)
        self.assertEqual(self.snapshot(), snapshot)

    def test_integer_boundaries_are_exact_and_overflow_is_rejected(self):
        maximum = 2**63 - 1
        self.execute("UPDATE accounts SET balance=? WHERE tenant='one' AND name='a'",
                     (maximum,))
        before = self.snapshot()
        receipt = vault.transfer(self.path, **self.request(amount=maximum))
        self.assertEqual(vault.balance(self.path, 'one', 'b'), maximum)
        self.assert_transfer_delta(before, receipt)
        before = self.snapshot()
        with self.assertRaises(ValueError):
            vault.transfer(self.path, **self.request(source='c', amount=1, key='overflow'))
        self.assertEqual(self.snapshot(), before)

    def test_storage_failures_at_each_stage_roll_back_and_preserve_triggers(self):
        stages = [
            ('BEFORE UPDATE ON accounts', "NEW.name='b'", 'ABORT'),
            ('BEFORE INSERT ON transfers', '1', 'ABORT'),
            ('BEFORE INSERT ON audit', '1', 'ABORT'),
            ('AFTER INSERT ON audit', '1', 'FAIL'),
            ('AFTER INSERT ON audit', '1', 'ROLLBACK'),
        ]
        for stage, condition, action in stages:
            with self.subTest(stage=stage, action=action):
                self.execute('CREATE TRIGGER injected_failure ' + stage + ' WHEN ' +
                             condition + ' BEGIN SELECT RAISE(' + action +
                             ", 'injected storage failure'); END")
                before = self.snapshot()
                trigger = self.execute("SELECT sql FROM sqlite_schema WHERE name='injected_failure'")
                with self.assertRaisesRegex(sqlite3.Error, 'injected storage failure'):
                    vault.transfer(self.path, **self.request())
                self.assertEqual(self.snapshot(), before)
                self.assertEqual(self.execute("SELECT sql FROM sqlite_schema WHERE name='injected_failure'"),
                                 trigger)
                self.execute('DROP TRIGGER injected_failure')
        before = self.snapshot()
        receipt = vault.transfer(self.path, **self.request())
        self.assert_transfer_delta(before, receipt)

    def test_ignored_writes_and_extra_audit_rows_cannot_partially_commit(self):
        triggers = [
            "BEFORE UPDATE ON accounts WHEN NEW.name='b' BEGIN SELECT RAISE(IGNORE); END",
            'BEFORE INSERT ON transfers BEGIN SELECT RAISE(IGNORE); END',
            'BEFORE INSERT ON audit BEGIN SELECT RAISE(IGNORE); END',
            'AFTER INSERT ON audit BEGIN INSERT INTO audit VALUES '
            '(NEW.tenant,NEW.key,NEW.source,NEW.target,NEW.amount); END',
            'AFTER INSERT ON audit BEGIN UPDATE accounts SET balance=balance+1 '
            'WHERE tenant=NEW.tenant AND name=NEW.target; END',
        ]
        for trigger in triggers:
            with self.subTest(trigger=trigger):
                self.execute('CREATE TRIGGER injected_effect ' + trigger)
                before = self.snapshot()
                with self.assertRaises(sqlite3.Error):
                    vault.transfer(self.path, **self.request())
                self.assertEqual(self.snapshot(), before)
                self.execute('DROP TRIGGER injected_effect')

    def test_existing_unique_constraint_failure_is_atomic(self):
        self.execute('CREATE UNIQUE INDEX audit_amount ON audit(tenant,amount) '
                     "WHERE key <> 'historic'")
        vault.transfer(self.path, **self.request())
        before = self.snapshot()
        with self.assertRaises(sqlite3.IntegrityError):
            vault.transfer(self.path, **self.request(key='conflict'))
        self.assertEqual(self.snapshot(), before)
        receipt = vault.transfer(self.path, **self.request(key='control', amount=11))
        self.assert_transfer_delta(before, receipt)

    def test_conditional_unicode_and_keyword_triggers_keep_their_behavior(self):
        self.execute('CREATE TRIGGER 审核 BEFORE INSERT ON audit '
                     "WHEN NEW.key='blocked' BEGIN SELECT 1; "
                     "SELECT RAISE(ABORT, 'blocked audit'); END")
        self.execute('CREATE TRIGGER after AFTER INSERT ON transfers '
                     'WHEN NEW.amount > 0 BEGIN SELECT 1; SELECT 2; END')
        schema = self.execute("SELECT name,sql FROM sqlite_schema WHERE type='trigger' ORDER BY name")
        before = self.snapshot()
        receipt = vault.transfer(self.path, **self.request())
        self.assert_transfer_delta(before, receipt)
        before = self.snapshot()
        with self.assertRaisesRegex(sqlite3.IntegrityError, 'blocked audit'):
            vault.transfer(self.path, **self.request(key='blocked'))
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(self.execute("SELECT name,sql FROM sqlite_schema WHERE type='trigger' ORDER BY name"),
                         schema)

    def simultaneous(self, requests):
        barrier = threading.Barrier(len(requests))

        def run(request):
            barrier.wait(timeout=10)
            try:
                return vault.transfer(self.path, **request)
            except ValueError as exc:
                return exc

        with ThreadPoolExecutor(max_workers=len(requests)) as pool:
            futures = [pool.submit(run, request) for request in requests]
            return [future.result(timeout=45) for future in futures]

    def test_simultaneous_duplicate_connections_execute_once(self):
        before = self.snapshot()
        request = self.request(amount=33)
        results = self.simultaneous([request] * 8)
        self.assertEqual(results, [request] * 8)
        self.assert_transfer_delta(before, request)
        self.assertEqual(vault.transfer(self.path, **request), request)
        self.assert_transfer_delta(before, request)

    def test_simultaneous_conflicting_payloads_choose_one_receipt(self):
        before = self.snapshot()
        requests = [self.request(amount=5), self.request(amount=7)] * 4
        results = self.simultaneous(requests)
        winners = [result for result in results if isinstance(result, dict)]
        losers = [result for result in results if isinstance(result, ValueError)]
        self.assertEqual(len(winners), 4)
        self.assertEqual(len(losers), 4)
        self.assertTrue(all(result == winners[0] for result in winners))
        self.assert_transfer_delta(before, winners[0])

    def test_simultaneous_distinct_keys_cannot_overspend(self):
        before = self.snapshot()
        requests = [self.request(amount=30, key='spend-' + str(i)) for i in range(8)]
        results = self.simultaneous(requests)
        winners = [result for result in results if isinstance(result, dict)]
        self.assertEqual(len(winners), 3)
        self.assertEqual(sum(isinstance(result, ValueError) for result in results), 5)
        self.assert_transfer_delta(before, *winners)
        self.assertEqual(vault.balance(self.path, 'one', 'a'), 10)

    def test_simultaneous_sources_do_not_lose_credits(self):
        requests = []
        for i in range(8):
            name = 'source-' + str(i)
            self.execute('INSERT INTO accounts VALUES (?,?,?)', ('one', name, 20))
            requests.append(self.request(source=name, amount=3, key=name))
        before = self.snapshot()
        self.assertEqual(self.simultaneous(requests), requests)
        self.assert_transfer_delta(before, *requests)
        self.assertEqual(vault.balance(self.path, 'one', 'b'), 24)

    def test_simultaneous_tenants_can_share_a_key(self):
        before = self.snapshot()
        one = self.request(amount=15)
        two = self.request(tenant='two', amount=20)
        requests = [one, two] * 4
        self.assertEqual(self.simultaneous(requests), requests)
        self.assert_transfer_delta(before, one, two)

    def cli(self, request=None, *, raw=None, argv=None):
        arguments = argv if argv is not None else [
            str(self.path), raw if raw is not None else json.dumps(request)]
        return subprocess.run([sys.executable, '-B', str(WORKSPACE / 'app.py'), *arguments],
                              cwd=WORKSPACE, capture_output=True, text=True, timeout=10)

    def assert_cli_error(self, result):
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertEqual(result.stdout, '')
        self.assertEqual(result.stderr, '{"error": "invalid request"}\n')

    def test_cli_rejects_malformed_requests_and_unexposed_operations(self):
        before = self.snapshot()
        invalid = [None, [], True, 4, 'balance', {}, {'op': []}, {'op': {}},
                   {'op': 'init_db'}, {'op': '__dict__'}, {'op': 'transfer'},
                   {'op': 'balance', 'tenant': 'one'},
                   {'op': 'balance', 'tenant': 'one', 'account': 'a', 'extra': 1},
                   {'op': 'balance', 'tenant': 'one', 'account': ['a']},
                   {'op': 'transfer', **self.request(amount=True)},
                   {'op': 'transfer', **self.request(tenant=None)}]
        for request in invalid:
            with self.subTest(request=request):
                self.assert_cli_error(self.cli(request))
        for raw in ('{', '', '{"op":'):
            with self.subTest(raw=raw):
                self.assert_cli_error(self.cli(raw=raw))
        for argv in ([], [str(self.path)], [str(self.path), '{}', 'extra']):
            with self.subTest(argv=argv):
                self.assert_cli_error(self.cli(argv=argv))
        self.assertEqual(self.snapshot(), before)

    def test_cli_integrated_transfer_replay_failure_and_recovery(self):
        self.execute('CREATE TRIGGER audit_failure BEFORE INSERT ON audit '
                     "WHEN NEW.key='blocked' BEGIN SELECT RAISE(ABORT, "
                     "'foreign secret: SELECT * FROM accounts'); END")
        before = self.snapshot()
        result = self.cli({'op': 'balance', 'tenant': 'one', 'account': 'a'})
        self.assertEqual((result.returncode, result.stdout, result.stderr), (0, '100\n', ''))
        request = self.request(amount=20)
        for _ in range(2):
            result = self.cli({'op': 'transfer', **request})
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads(result.stdout), request)
            self.assertEqual(len(result.stdout.splitlines()), 1)
            self.assertEqual(result.stderr, '')
        self.assert_transfer_delta(before, request)
        after_success = self.snapshot()
        failures = [
            {'op': 'transfer', **self.request(amount=21)},
            {'op': 'transfer', **self.request(key='insufficient', amount=1000)},
            {'op': 'transfer', **self.request(key='blocked')},
            {'op': 'balance', 'tenant': 'one', 'account': 'private'},
            {'op': 'balance', 'tenant': 'one', 'account': 'missing'},
        ]
        for request in failures:
            self.assert_cli_error(self.cli(request))
            self.assertEqual(self.snapshot(), after_success)
        two = self.request(tenant='two', amount=5)
        recovery = self.request(key='recovery', amount=1)
        for request in (two, recovery):
            result = self.cli({'op': 'transfer', **request})
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads(result.stdout), request)
            self.assertEqual(result.stderr, '')
        self.assert_transfer_delta(after_success, two, recovery)
        vault.init_db(self.path)
        self.assertEqual(vault.balance(self.path, 'one', 'a'), 79)
        self.assertEqual(vault.balance(self.path, 'two', 'a'), 695)
        self.assertEqual(vault.transfer(self.path, **recovery), recovery)

    def test_cli_storage_errors_do_not_disclose_sql_or_tracebacks(self):
        missing_parent = Path(self.tmp.name) / 'absent' / 'db.sqlite'
        request = json.dumps({'op': 'balance', 'tenant': 'one', 'account': 'a'})
        self.assert_cli_error(self.cli(argv=[str(missing_parent), request]))
        empty_db = Path(self.tmp.name) / 'empty.sqlite'
        self.assert_cli_error(self.cli(argv=[str(empty_db), request]))


if __name__ == '__main__':
    unittest.main()
