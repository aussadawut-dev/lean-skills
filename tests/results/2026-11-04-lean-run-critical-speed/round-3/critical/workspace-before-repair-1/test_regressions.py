"""Public-interface regression checks for isolation, durability, and the CLI."""

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
TABLES = ('accounts', 'transfers', 'audit')


class VaultFixture(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(dir=ROOT)
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / 'vault.sqlite'
        vault.init_db(self.path)
        self.execute_many('INSERT INTO accounts VALUES (?,?,?)', [
            ('other', 'a', 900), ('other', 'b', 400), ('other', 'secret', 500),
            ('one', 'a', 100), ('one', 'b', 0), ('one', 'c', 20),
        ])

    def execute(self, sql, values=()):
        with closing(sqlite3.connect(self.path)) as con, con:
            con.execute(sql, values)

    def execute_many(self, sql, values):
        with closing(sqlite3.connect(self.path)) as con, con:
            con.executemany(sql, values)

    def rows(self, table):
        with closing(sqlite3.connect(self.path)) as con:
            return con.execute('SELECT * FROM ' + table).fetchall()

    def snapshot(self):
        # Compare logical rows, including duplicate audit history, not rowids.
        return tuple(tuple(sorted(self.rows(table), key=repr)) for table in TABLES)

    def assert_rejected(self, callback, error=ValueError):
        before = self.snapshot()
        with self.assertRaises(error) as caught:
            callback()
        self.assertEqual(before, self.snapshot())
        return str(caught.exception)

    def parallel(self, requests):
        barrier = threading.Barrier(len(requests))

        def invoke(request):
            barrier.wait(timeout=10)
            try:
                return vault.transfer(self.path, **request)
            except ValueError as error:
                return error

        with ThreadPoolExecutor(max_workers=len(requests)) as pool:
            return list(pool.map(invoke, requests))

    def request(self, **changes):
        request = dict(tenant='one', source='a', target='b', amount=10, key='k')
        request.update(changes)
        return request


class VaultRegressionTests(VaultFixture):
    def test_reads_and_transfers_are_scoped_to_tenant(self):
        foreign = [row for row in self.rows('accounts') if row[0] == 'other']
        self.assertEqual(vault.balance(self.path, 'one', 'a'), 100)
        self.assertEqual(vault.balance(self.path, 'other', 'a'), 900)
        receipt = vault.transfer(self.path, **self.request())
        self.assertEqual(receipt, self.request())
        self.assertEqual(vault.balance(self.path, 'one', 'a'), 90)
        self.assertEqual(vault.balance(self.path, 'one', 'b'), 10)
        self.assertEqual(vault.balance(self.path, 'one', 'c'), 20)
        self.assertEqual(foreign, [row for row in self.rows('accounts') if row[0] == 'other'])
        self.assertEqual(self.rows('transfers'), [('one', 'k', 'a', 'b', 10)])
        self.assertEqual(self.rows('audit'), [('one', 'k', 'a', 'b', 10)])

    def test_missing_and_inaccessible_accounts_have_identical_errors(self):
        messages = []
        for account in ('absent', 'secret'):
            messages.append(self.assert_rejected(lambda: vault.balance(self.path, 'one', account)))
            for endpoint in ('source', 'target'):
                request = self.request(**{endpoint: account})
                messages.append(self.assert_rejected(lambda: vault.transfer(self.path, **request)))
        messages.append(self.assert_rejected(lambda: vault.balance(self.path, 'unknown', 'a')))
        self.assertEqual(len(set(messages)), 1)
        self.assertNotIn('other', messages[0])
        self.assertNotIn('secret', messages[0])

    def test_malformed_identifiers_do_not_write(self):
        for invalid in ('', None, 1, True, [], {}, b'a'):
            for field in ('tenant', 'source', 'target', 'key'):
                with self.subTest(field=field, invalid=invalid):
                    request = self.request(**{field: invalid})
                    self.assert_rejected(lambda: vault.transfer(self.path, **request))
            for field in ('tenant', 'account'):
                with self.subTest(balance_field=field, invalid=invalid):
                    request = dict(tenant='one', account='a')
                    request[field] = invalid
                    self.assert_rejected(lambda: vault.balance(self.path, **request))

    def test_malformed_amounts_and_self_transfers_do_not_write(self):
        for amount in (0, -1, True, False, 1.0, '10', None, [], {}, float('nan'), float('inf')):
            with self.subTest(amount=amount):
                self.assert_rejected(lambda: vault.transfer(self.path, **self.request(amount=amount)))
        self.assert_rejected(lambda: vault.transfer(self.path, **self.request(target='a')))

    def test_insufficient_funds_and_full_balance_boundary(self):
        for amount in (101, 2**100):
            self.assert_rejected(lambda: vault.transfer(self.path, **self.request(amount=amount)))
        receipt = vault.transfer(self.path, **self.request(amount=100))
        self.assertEqual(vault.balance(self.path, 'one', 'a'), 0)
        self.assertEqual(vault.balance(self.path, 'one', 'b'), 100)
        before = self.snapshot()
        self.assertEqual(vault.transfer(self.path, **self.request(amount=100)), receipt)
        self.assertEqual(before, self.snapshot())
        self.assert_rejected(lambda: vault.transfer(self.path, **self.request(amount=1, key='new')))

    def test_exact_replay_and_conflicts_survive_reopening(self):
        receipt = vault.transfer(self.path, **self.request())
        before = self.snapshot()
        vault.init_db(self.path)
        self.assertEqual(vault.transfer(self.path, **self.request()), receipt)
        self.assertEqual(before, self.snapshot())
        for change in (dict(amount=11), dict(source='c'), dict(target='c'), dict(source='b', target='a')):
            with self.subTest(change=change):
                self.assert_rejected(lambda: vault.transfer(self.path, **self.request(**change)))

    def test_keys_are_independent_between_tenants(self):
        one = vault.transfer(self.path, **self.request())
        other = vault.transfer(self.path, **self.request(tenant='other', amount=7))
        self.assertEqual(one, self.request())
        self.assertEqual(other, self.request(tenant='other', amount=7))
        before = self.snapshot()
        self.assertEqual(vault.transfer(self.path, **self.request()), one)
        self.assertEqual(vault.transfer(self.path, **self.request(tenant='other', amount=7)), other)
        self.assertEqual(before, self.snapshot())
        self.assertEqual(len(self.rows('audit')), 2)

    def test_corrupt_foreign_rows_and_cached_receipts_are_never_used(self):
        self.execute("UPDATE accounts SET balance='private malformed value' WHERE tenant='other'")
        self.execute('INSERT INTO transfers VALUES (?,?,?,?,?)',
                     ('other', 'k', 'private source', 'private target', b'private amount'))
        before_foreign = [row for row in self.rows('accounts') if row[0] == 'other']
        self.assertEqual(vault.balance(self.path, 'one', 'a'), 100)
        self.assertEqual(vault.transfer(self.path, **self.request()), self.request())
        self.assertEqual(before_foreign, [row for row in self.rows('accounts') if row[0] == 'other'])
        self.assertIn(('other', 'k', 'private source', 'private target', b'private amount'), self.rows('transfers'))

    def test_nonempty_unicode_whitespace_and_sql_characters_are_literal(self):
        tenant, source, target, key = '租户\' OR 1=1 --', ' ', '收款; DROP TABLE accounts;', '\x00key'
        self.execute_many('INSERT INTO accounts VALUES (?,?,?)', [(tenant, source, 3), (tenant, target, 0)])
        receipt = vault.transfer(self.path, tenant, source, target, 1, key)
        self.assertEqual(receipt['tenant'], tenant)
        self.assertEqual(vault.balance(self.path, tenant, source), 2)
        self.assertEqual(vault.balance(self.path, 'one', 'a'), 100)
        self.assertEqual(vault.transfer(self.path, tenant, source, target, 1, key), receipt)

    def test_initialization_and_transfer_preserve_history_and_schema(self):
        history = [('other', 'old', 'a', 'b', 8), ('one', 'old', 'c', 'b', 5)]
        self.execute_many('INSERT INTO transfers VALUES (?,?,?,?,?)', history)
        self.execute_many('INSERT INTO audit VALUES (?,?,?,?,?)', history + history)
        self.execute('CREATE TRIGGER "审计" BEFORE INSERT ON audit WHEN NEW.amount < 0 '
                     "BEGIN SELECT 1; SELECT RAISE(ABORT, 'negative'); END")
        before = self.snapshot()
        with closing(sqlite3.connect(self.path)) as con:
            schema_before = con.execute('SELECT type,name,sql FROM sqlite_master ORDER BY type,name').fetchall()
        vault.init_db(self.path)
        vault.init_db(self.path)
        self.assertEqual(before, self.snapshot())
        vault.transfer(self.path, **self.request())
        self.assertCountEqual(self.rows('transfers'), history + [('one', 'k', 'a', 'b', 10)])
        self.assertCountEqual(self.rows('audit'), history + history + [('one', 'k', 'a', 'b', 10)])
        with closing(sqlite3.connect(self.path)) as con:
            self.assertEqual(schema_before, con.execute('SELECT type,name,sql FROM sqlite_master ORDER BY type,name').fetchall())

    def test_audit_failures_rollback_all_effects_and_preserve_trigger(self):
        vault.transfer(self.path, **self.request(key='history'))
        for timing in ('BEFORE', 'AFTER'):
            for action in ('ABORT', 'FAIL', 'ROLLBACK'):
                with self.subTest(timing=timing, action=action):
                    sql = (f'CREATE TRIGGER "é_failure" {timing} INSERT ON audit '
                           f"WHEN NEW.key='failure' BEGIN SELECT 1; SELECT RAISE({action}, 'private failure'); END")
                    self.execute(sql)
                    self.assert_rejected(lambda: vault.transfer(self.path, **self.request(key='failure')), sqlite3.Error)
                    with closing(sqlite3.connect(self.path)) as con:
                        self.assertEqual(con.execute("SELECT sql FROM sqlite_master WHERE name='é_failure'").fetchone()[0], sql)
                    self.execute('DROP TRIGGER "é_failure"')
        vault.transfer(self.path, **self.request(key='recovery'))
        self.assertEqual(vault.balance(self.path, 'one', 'a'), 80)
        self.assertEqual(len(self.rows('audit')), 2)

    def test_credit_failure_rolls_back_the_debit(self):
        self.execute("CREATE TRIGGER fail_credit BEFORE UPDATE ON accounts "
                     "WHEN NEW.tenant='one' AND NEW.name='b' "
                     "BEGIN SELECT RAISE(FAIL, 'credit failure'); END")
        self.assert_rejected(lambda: vault.transfer(self.path, **self.request()), sqlite3.IntegrityError)

    def test_receipt_and_audit_storage_conflicts_rollback(self):
        for table in ('transfers', 'audit'):
            with self.subTest(table=table):
                self.execute(f'INSERT INTO {table} VALUES (?,?,?,?,?)', ('other', 'history', 'a', 'b', 10))
                self.execute(f'CREATE UNIQUE INDEX {table}_amount ON {table}(amount)')
                self.assert_rejected(lambda: vault.transfer(self.path, **self.request()), sqlite3.IntegrityError)
                self.execute(f'DROP INDEX {table}_amount')

    def test_silently_ignored_required_writes_are_rolled_back(self):
        cases = [
            ('accounts', 'UPDATE', "NEW.name='a'"),
            ('accounts', 'UPDATE', "NEW.name='b'"),
            ('transfers', 'INSERT', '1'),
            ('audit', 'INSERT', '1'),
        ]
        for table, event, condition in cases:
            with self.subTest(table=table, condition=condition):
                self.execute(f'CREATE TRIGGER ignore_write BEFORE {event} ON {table} '
                             f'WHEN {condition} BEGIN SELECT RAISE(IGNORE); END')
                self.assert_rejected(lambda: vault.transfer(self.path, **self.request()), sqlite3.IntegrityError)
                self.execute('DROP TRIGGER ignore_write')

    def test_unrepresentable_credit_does_not_lose_money(self):
        self.execute("UPDATE accounts SET balance=? WHERE tenant='one' AND name='b'", (2**63 - 1,))
        self.assert_rejected(lambda: vault.transfer(self.path, **self.request(amount=1)), OverflowError)

    def test_replace_victim_and_ignored_conflict_are_distinguished(self):
        self.execute('CREATE UNIQUE INDEX unique_balance ON accounts(balance + 0)')
        self.execute("CREATE TRIGGER side_effect AFTER INSERT ON audit BEGIN "
                     "INSERT OR IGNORE INTO accounts VALUES ('one','extra',500); END")
        self.assertEqual(vault.transfer(self.path, **self.request()), self.request())
        self.assertEqual(vault.balance(self.path, 'other', 'secret'), 500)
        self.execute('DROP TRIGGER side_effect')
        self.execute("CREATE TRIGGER side_effect AFTER INSERT ON audit BEGIN "
                     "INSERT OR REPLACE INTO accounts VALUES ('one','extra',500); END")
        self.assert_rejected(lambda: vault.transfer(self.path, **self.request(key='replace')), sqlite3.IntegrityError)

    def test_replacements_by_primary_key_and_rowid_cannot_erase_foreign_accounts(self):
        with closing(sqlite3.connect(self.path)) as con:
            victim = con.execute("SELECT rowid FROM accounts WHERE tenant='other' AND name='secret'").fetchone()[0]
        statements = [
            "INSERT OR REPLACE INTO accounts VALUES ('other','secret',999)",
            f"INSERT OR REPLACE INTO accounts(rowid,tenant,name,balance) VALUES ({victim},'one','extra',999)",
        ]
        for statement in statements:
            with self.subTest(statement=statement):
                self.execute(f'CREATE TRIGGER side_effect AFTER INSERT ON audit BEGIN {statement}; END')
                self.assert_rejected(lambda: vault.transfer(self.path, **self.request()), sqlite3.IntegrityError)
                self.execute('DROP TRIGGER side_effect')

    def test_extra_or_modified_receipts_and_audit_rows_are_rolled_back(self):
        history = ('other', 'history', 'a', 'b', 3)
        self.execute('INSERT INTO transfers VALUES (?,?,?,?,?)', history)
        self.execute('INSERT INTO audit VALUES (?,?,?,?,?)', history)
        self.execute('CREATE UNIQUE INDEX unique_audit_key ON audit(key)')
        statements = [
            "INSERT OR REPLACE INTO transfers VALUES ('other','history','a','b',99)",
            "INSERT OR REPLACE INTO audit VALUES ('one','history','a','b',99)",
            "INSERT INTO audit VALUES ('one','extra','a','b',1)",
            "UPDATE transfers SET amount=1 WHERE tenant=NEW.tenant AND key=NEW.key",
            "DELETE FROM audit WHERE tenant=NEW.tenant AND key=NEW.key",
            "UPDATE accounts SET balance=999 WHERE tenant='other' AND name='secret'",
        ]
        for statement in statements:
            with self.subTest(statement=statement):
                self.execute(f'CREATE TRIGGER side_effect AFTER INSERT ON audit BEGIN {statement}; END')
                self.assert_rejected(lambda: vault.transfer(self.path, **self.request()), sqlite3.IntegrityError)
                self.execute('DROP TRIGGER side_effect')

    def test_benign_noops_and_internal_moves_preserve_logical_rows(self):
        self.execute("CREATE TRIGGER benign AFTER INSERT ON audit BEGIN "
                     "UPDATE accounts SET balance=balance WHERE tenant='other'; "
                     "UPDATE accounts SET name='temporary' WHERE tenant='other' AND name='secret'; "
                     "UPDATE accounts SET name='secret' WHERE tenant='other' AND name='temporary'; END")
        self.assertEqual(vault.transfer(self.path, **self.request()), self.request())
        self.assertEqual(vault.balance(self.path, 'other', 'secret'), 500)

    def test_replace_noop_preserves_original_delete_trigger_behavior(self):
        self.execute('CREATE TABLE notes (value TEXT)')
        self.execute("CREATE TRIGGER deletion AFTER DELETE ON accounts BEGIN INSERT INTO notes VALUES ('deleted'); END")
        self.execute("CREATE TRIGGER replacement AFTER INSERT ON audit BEGIN "
                     "INSERT OR REPLACE INTO accounts VALUES ('other','secret',500); END")
        self.assertEqual(vault.transfer(self.path, **self.request()), self.request())
        self.assertEqual(self.rows('notes'), [])
        self.assertEqual(vault.balance(self.path, 'other', 'secret'), 500)

    def test_explicit_delete_trigger_behavior_is_preserved(self):
        self.execute('CREATE TABLE notes (value TEXT)')
        self.execute("CREATE TRIGGER deletion AFTER DELETE ON accounts BEGIN INSERT INTO notes VALUES ('deleted'); END")
        self.execute("CREATE TRIGGER move AFTER INSERT ON audit BEGIN "
                     "DELETE FROM accounts WHERE tenant='other' AND name='secret'; "
                     "INSERT INTO accounts VALUES ('other','secret',500); END")
        self.assertEqual(vault.transfer(self.path, **self.request()), self.request())
        self.assertEqual(self.rows('notes'), [('deleted',)])
        self.assertEqual(vault.balance(self.path, 'other', 'secret'), 500)

    def test_original_nonrecursive_triggers_still_run_once(self):
        self.execute('CREATE TABLE notes (value TEXT)')
        self.execute("CREATE TRIGGER nonrecursive AFTER UPDATE ON accounts BEGIN "
                     "UPDATE accounts SET balance=balance WHERE tenant=NEW.tenant AND name=NEW.name; "
                     "INSERT INTO notes VALUES (NEW.name); END")
        self.assertEqual(vault.transfer(self.path, **self.request()), self.request())
        self.assertEqual(self.rows('notes'), [('a',), ('b',)])

    def test_ignored_trigger_steps_unwind_before_the_next_step(self):
        self.execute('CREATE TABLE notes (value TEXT)')
        self.execute("CREATE TRIGGER ignored BEFORE UPDATE ON accounts WHEN NEW.name='c' BEGIN "
                     "INSERT INTO notes VALUES ('ignored'); "
                     "SELECT CASE WHEN OLD.balance=NEW.balance THEN RAISE /* exit */ (IGNORE) END; END")
        self.execute("CREATE TRIGGER repeated AFTER INSERT ON audit BEGIN "
                     "UPDATE accounts SET balance=balance WHERE tenant='one' AND name='c'; "
                     "UPDATE accounts SET balance=balance WHERE tenant='one' AND name='c'; END")
        self.assertEqual(vault.transfer(self.path, **self.request()), self.request())
        self.assertEqual(self.rows('notes'), [('ignored',), ('ignored',)])

    def test_trigger_sql_names_conditions_bodies_and_order_are_preserved(self):
        self.execute('CREATE TABLE steps (begin INTEGER)')
        self.execute('CREATE TABLE notes (value TEXT)')
        self.execute("CREATE TRIGGER 复核 AFTER INSERT ON steps WHEN NEW.begin > 0 BEGIN "
                     "INSERT INTO notes VALUES ('BEGIN; RAISE(IGNORE)'); "
                     "INSERT INTO notes VALUES ('compound'); END")
        self.execute("CREATE TRIGGER begin AFTER INSERT ON audit WHEN NEW.tenant='one' BEGIN "
                     "INSERT INTO steps VALUES (1); INSERT INTO notes VALUES ('first'); END")
        self.execute("CREATE TRIGGER [second BEGIN] AFTER INSERT ON audit BEGIN "
                     "INSERT INTO notes VALUES ('second'); END")
        with closing(sqlite3.connect(self.path)) as con:
            definitions = con.execute("SELECT name,sql FROM sqlite_master WHERE type='trigger' ORDER BY name").fetchall()
            con.execute('BEGIN')
            con.execute("INSERT INTO audit VALUES ('one','control','a','b',1)")
            expected = con.execute('SELECT * FROM notes').fetchall()
            con.rollback()
        self.assertEqual(vault.transfer(self.path, **self.request()), self.request())
        self.assertEqual(self.rows('notes'), expected)
        with closing(sqlite3.connect(self.path)) as con:
            self.assertEqual(definitions, con.execute("SELECT name,sql FROM sqlite_master WHERE type='trigger' ORDER BY name").fetchall())

    def test_simultaneous_duplicates_execute_once(self):
        request = self.request(amount=30)
        receipts = self.parallel([request] * 12)
        self.assertEqual(receipts, [request] * 12)
        self.assertEqual(vault.balance(self.path, 'one', 'a'), 70)
        self.assertEqual(vault.balance(self.path, 'one', 'b'), 30)
        self.assertEqual(self.rows('transfers'), [('one', 'k', 'a', 'b', 30)])
        self.assertEqual(self.rows('audit'), [('one', 'k', 'a', 'b', 30)])
        before = self.snapshot()
        self.assertEqual(vault.transfer(self.path, **request), request)
        self.assertEqual(before, self.snapshot())

    def test_concurrent_distinct_keys_cannot_overspend(self):
        requests = [self.request(key=f'key-{i}') for i in range(12)]
        results = self.parallel(requests)
        self.assertEqual(sum(isinstance(result, dict) for result in results), 10)
        self.assertEqual(sum(isinstance(result, ValueError) for result in results), 2)
        self.assertEqual(vault.balance(self.path, 'one', 'a'), 0)
        self.assertEqual(vault.balance(self.path, 'one', 'b'), 100)
        self.assertEqual(len(self.rows('transfers')), 10)
        self.assertCountEqual(self.rows('transfers'), self.rows('audit'))

    def test_concurrent_sources_do_not_lose_credits(self):
        requests = [self.request(source=source, key=f'key-{i}')
                    for i, source in enumerate(('a', 'c', 'a', 'c', 'a', 'a'))]
        self.assertEqual(self.parallel(requests), requests)
        self.assertEqual(vault.balance(self.path, 'one', 'a'), 60)
        self.assertEqual(vault.balance(self.path, 'one', 'c'), 0)
        self.assertEqual(vault.balance(self.path, 'one', 'b'), 60)
        self.assertEqual(len(self.rows('audit')), 6)

    def test_concurrent_conflicting_payloads_have_one_winner(self):
        requests = [self.request(amount=amount) for amount in (10, 20) * 4]
        results = self.parallel(requests)
        winners = [result for result in results if isinstance(result, dict)]
        self.assertEqual(len(winners), 4)
        self.assertTrue(all(result == winners[0] for result in winners))
        self.assertEqual(sum(isinstance(result, ValueError) for result in results), 4)
        amount = winners[0]['amount']
        self.assertEqual(vault.balance(self.path, 'one', 'a'), 100 - amount)
        self.assertEqual(vault.balance(self.path, 'one', 'b'), amount)
        self.assertEqual(len(self.rows('transfers')), 1)
        self.assertEqual(len(self.rows('audit')), 1)

    def test_concurrent_tenants_can_share_a_key(self):
        requests = [self.request(tenant=tenant) for tenant in ('one', 'other') * 4]
        self.assertEqual(self.parallel(requests), requests)
        self.assertEqual(vault.balance(self.path, 'one', 'a'), 90)
        self.assertEqual(vault.balance(self.path, 'other', 'a'), 890)
        self.assertEqual(len(self.rows('transfers')), 2)
        self.assertEqual(len(self.rows('audit')), 2)


class CliRegressionTests(VaultFixture):
    def cli_args(self, args):
        return subprocess.run([sys.executable, '-B', str(ROOT / 'app.py'), *args],
                              cwd=ROOT, capture_output=True, text=True, timeout=15)

    def cli(self, request):
        return self.cli_args([str(self.path), json.dumps(request)])

    def assert_success(self, result, expected):
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stderr, '')
        self.assertEqual(len(result.stdout.splitlines()), 1)
        self.assertEqual(json.loads(result.stdout), expected)

    def assert_cli_error(self, result):
        self.assertEqual(result.returncode, 2)
        self.assertEqual(result.stdout, '')
        self.assertEqual(len(result.stderr.splitlines()), 1)
        self.assertEqual(json.loads(result.stderr), {'error': 'invalid request'})

    def test_cli_malformed_inputs_and_dispatch_are_generic(self):
        requests = [None, [], 1, True, 'text', {}, {'op': 'init_db'}, {'op': '__getattribute__'},
                    {'op': []}, {'op': 'balance', 'tenant': 'one'},
                    {'op': 'balance', 'tenant': 'one', 'account': 'a', 'extra': 1}]
        requests += [dict(op='transfer', **self.request(amount=value)) for value in (True, 0, 1.5, '1', None)]
        requests += [dict(op='transfer', **self.request(target='secret')),
                     dict(op='transfer', **self.request(amount=101)),
                     dict(op='balance', tenant='one', account='absent'),
                     dict(op='balance', tenant='one', account='secret')]
        before = self.snapshot()
        for request in requests:
            with self.subTest(request=request):
                self.assert_cli_error(self.cli(request))
                self.assertEqual(before, self.snapshot())
        for raw in ('{', '{"op":"balance","tenant":"other","tenant":"one","account":"a"}'):
            self.assert_cli_error(self.cli_args([str(self.path), raw]))
        for args in ([], [str(self.path)], [str(self.path), '{}', 'extra']):
            self.assert_cli_error(self.cli_args(args))
        self.assertEqual(before, self.snapshot())

    def test_cli_storage_failure_does_not_disclose_details(self):
        self.execute("CREATE TRIGGER private_failure BEFORE INSERT ON audit "
                     "BEGIN SELECT RAISE(ABORT, 'SELECT secret FROM other_tenant'); END")
        before = self.snapshot()
        self.assert_cli_error(self.cli(dict(op='transfer', **self.request())))
        self.assertEqual(before, self.snapshot())
        self.assert_cli_error(self.cli_args([str(Path(self.tmp.name) / 'missing' / 'db'),
                                             json.dumps(dict(op='balance', tenant='one', account='a'))]))

    def test_cli_persistent_transfer_replay_failure_and_recovery_journey(self):
        self.assert_success(self.cli(dict(op='balance', tenant='one', account='a')), 100)
        request = self.request(amount=25)
        self.assert_success(self.cli(dict(op='transfer', **request)), request)
        before = self.snapshot()
        self.assert_success(self.cli(dict(op='transfer', **request)), request)
        self.assertEqual(before, self.snapshot())
        self.assert_cli_error(self.cli(dict(op='transfer', **self.request(amount=26))))
        self.assertEqual(before, self.snapshot())
        other = self.request(tenant='other', amount=7)
        self.assert_success(self.cli(dict(op='transfer', **other)), other)
        self.execute("CREATE TRIGGER journey_failure AFTER INSERT ON audit WHEN NEW.key='fail' "
                     "BEGIN SELECT RAISE(FAIL, 'private details'); END")
        before = self.snapshot()
        self.assert_cli_error(self.cli(dict(op='transfer', **self.request(key='fail'))))
        self.assertEqual(before, self.snapshot())
        recovery = self.request(amount=5, key='recovery')
        self.assert_success(self.cli(dict(op='transfer', **recovery)), recovery)
        vault.init_db(self.path)
        self.assert_success(self.cli(dict(op='balance', tenant='one', account='a')), 70)
        self.assert_success(self.cli(dict(op='balance', tenant='one', account='b')), 30)
        self.assert_success(self.cli(dict(op='balance', tenant='other', account='a')), 893)
        self.assertEqual(len(self.rows('transfers')), 3)
        self.assertCountEqual(self.rows('transfers'), self.rows('audit'))


if __name__ == '__main__':
    unittest.main()
