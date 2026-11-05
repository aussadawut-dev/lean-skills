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


ROOT = Path(__file__).resolve().parent
TABLES = ('accounts', 'transfers', 'audit')


class VaultRegressionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(dir=ROOT)
        self.addCleanup(self.tmp.cleanup)
        self.path = self.new_db('vault')

    def new_db(self, name):
        path = Path(self.tmp.name) / f'{name}.sqlite'
        vault.init_db(path)
        with closing(sqlite3.connect(path)) as con, con:
            con.executemany(
                'INSERT INTO accounts VALUES (?, ?, ?)',
                [('one', 'a', 100), ('one', 'b', 0),
                 ('two', 'a', 700), ('two', 'b', 40),
                 ('two', 'private', 900)],
            )
        return path

    def snapshot(self, path=None):
        with closing(sqlite3.connect(path or self.path)) as con:
            return {table: con.execute(
                f'SELECT * FROM {table} ORDER BY '
                + ('1, 2, 3' if table == 'accounts' else '1, 2, 3, 4, 5')
            ).fetchall() for table in TABLES}

    def sql(self, script, path=None):
        with closing(sqlite3.connect(path or self.path)) as con:
            con.executescript(script)

    def cli(self, request):
        return self.command(str(self.path), json.dumps(request))

    def command(self, *arguments):
        return subprocess.run(
            [sys.executable, '-B', str(ROOT / 'app.py'), *arguments],
            capture_output=True, text=True, cwd=ROOT, timeout=15,
        )

    def history(self, path):
        return [vault.transfer(path, tenant, 'a', 'b', 9, f'past_{tenant}')
                for tenant in ('one', 'two')]

    def check_history_replay(self, path, receipts):
        before = self.snapshot(path)
        vault.init_db(path)
        for receipt in receipts:
            self.assertEqual(vault.transfer(path, **receipt), receipt)
        self.assertEqual(self.snapshot(path), before)

    def concurrent(self, path, requests):
        barrier = threading.Barrier(len(requests))

        def run(request):
            barrier.wait(timeout=5)
            try:
                return vault.transfer(path, **request)
            except ValueError as error:
                return error

        with ThreadPoolExecutor(max_workers=len(requests)) as pool:
            futures = [pool.submit(run, request) for request in requests]
            return [future.result(timeout=20) for future in futures]

    def test_balance_is_scoped_and_missing_is_generic(self):
        self.assertEqual(vault.balance(self.path, 'two', 'a'), 700)
        errors = []
        for account in ('private', 'missing'):
            with self.assertRaises(ValueError) as raised:
                vault.balance(self.path, 'one', account)
            errors.append(str(raised.exception))
        self.assertEqual(errors[0], errors[1])
        self.assertNotIn('private', errors[0])
        self.assertNotIn('two', errors[0])

    def test_transfer_is_scoped_and_replay_is_payload_bound(self):
        before = self.snapshot()
        receipt = vault.transfer(self.path, 'one', 'a', 'b', 10, 'shared')
        self.assertEqual(receipt, dict(
            tenant='one', key='shared', source='a', target='b', amount=10))
        after = self.snapshot()
        self.assertEqual(after['accounts'], [
            ('one', 'a', 90), ('one', 'b', 10), *before['accounts'][2:]])
        self.assertEqual(
            vault.transfer(self.path, 'one', 'a', 'b', 10, 'shared'), receipt)
        self.assertEqual(self.snapshot(), after)
        with self.assertRaises(ValueError):
            vault.transfer(self.path, 'one', 'a', 'b', 11, 'shared')
        self.assertEqual(self.snapshot(), after)
        other = vault.transfer(self.path, 'two', 'a', 'b', 20, 'shared')
        self.assertEqual(other['tenant'], 'two')
        self.assertEqual(vault.balance(self.path, 'two', 'a'), 680)
        self.assertEqual(len(self.snapshot()['audit']), 2)

    def test_audit_failure_rolls_back_every_effect(self):
        self.sql("""
            CREATE TRIGGER fail_audit BEFORE INSERT ON audit BEGIN
              SELECT RAISE(ABORT, 'private storage details');
            END;
        """)
        before = self.snapshot()
        with self.assertRaises(sqlite3.DatabaseError):
            vault.transfer(self.path, 'one', 'a', 'b', 10, 'failure')
        self.assertEqual(self.snapshot(), before)

    def test_cli_errors_are_generic_json(self):
        before = self.snapshot()
        result = self.cli(dict(op='balance', tenant='one', account='private'))
        self.assertEqual(result.returncode, 2)
        self.assertEqual(result.stdout, '')
        error = json.loads(result.stderr)
        self.assertEqual(set(error), {'error'})
        self.assertNotIn('private', result.stderr)
        self.assertNotIn('two', result.stderr)
        self.assertEqual(self.snapshot(), before)

    def test_invalid_inputs_are_rejected_without_writes(self):
        valid = dict(tenant='one', source='a', target='b', amount=10, key='new')
        invalid = [dict(valid, **{field: value})
                   for field in ('tenant', 'source', 'target', 'key')
                   for value in ('', None, 1, True, b'a', [], {})]
        invalid += [dict(valid, amount=value)
                    for value in (0, -1, True, False, 1.0, '1', None, [], {})]
        invalid += [dict(valid, target='a'), dict(valid, amount=101),
                    dict(valid, amount=2**100)]
        before = self.snapshot()
        for request in invalid:
            with self.subTest(request=request):
                with self.assertRaises(ValueError):
                    vault.transfer(self.path, **request)
                self.assertEqual(self.snapshot(), before)
        for field in ('tenant', 'account'):
            for value in ('', None, 1, True, [], {}):
                with self.subTest(field=field, value=value):
                    request = dict(tenant='one', account='a')
                    request[field] = value
                    with self.assertRaises(ValueError):
                        vault.balance(self.path, **request)
                    self.assertEqual(self.snapshot(), before)

    def test_missing_or_inaccessible_transfer_ends_are_generic(self):
        before = self.snapshot()
        messages = []
        for field in ('source', 'target'):
            for account in ('private', 'missing', "a' OR 1=1 --"):
                with self.subTest(field=field, account=account):
                    request = dict(tenant='one', source='a', target='b',
                                   amount=10, key='missing')
                    request[field] = account
                    with self.assertRaises(ValueError) as raised:
                        vault.transfer(self.path, **request)
                    messages.append(str(raised.exception))
                    self.assertEqual(self.snapshot(), before)
        with self.assertRaises(ValueError) as raised:
            vault.balance(self.path, 'unknown', 'a')
        messages.append(str(raised.exception))
        self.assertEqual(len(set(messages)), 1)
        self.assertFalse(any(word in messages[0] for word in ('two', 'private', '900')))

    def test_replay_checks_every_payload_field_and_needs_no_funds(self):
        request = dict(tenant='one', source='a', target='b', amount=100, key='all')
        receipt = vault.transfer(self.path, **request)
        self.assertEqual(vault.balance(self.path, 'one', 'a'), 0)
        after = self.snapshot()
        self.assertEqual(vault.transfer(self.path, **request), receipt)
        for change in ({'amount': 99}, {'source': 'missing'},
                       {'target': 'missing'}, {'source': 'b', 'target': 'a'}):
            with self.subTest(change=change):
                with self.assertRaises(ValueError):
                    vault.transfer(self.path, **dict(request, **change))
                self.assertEqual(self.snapshot(), after)
        with self.assertRaises(ValueError):
            vault.transfer(self.path, **dict(request, key='different'))
        self.assertEqual(self.snapshot(), after)

    def test_init_preserves_schema_rows_and_triggers(self):
        self.history(self.path)
        self.sql('CREATE TRIGGER retained AFTER INSERT ON audit BEGIN SELECT 1; END;')
        before = self.snapshot()
        with closing(sqlite3.connect(self.path)) as con:
            schema = con.execute('SELECT type, name, sql FROM sqlite_master ORDER BY name').fetchall()
        vault.init_db(self.path)
        vault.init_db(self.path)
        self.assertEqual(self.snapshot(), before)
        with closing(sqlite3.connect(self.path)) as con:
            self.assertEqual(con.execute(
                'SELECT type, name, sql FROM sqlite_master ORDER BY name'
            ).fetchall(), schema)

    def test_integer_boundaries_and_literal_identifiers(self):
        maximum = 2**63 - 1
        with closing(sqlite3.connect(self.path)) as con, con:
            con.execute('UPDATE accounts SET balance=? WHERE tenant=? AND name=?',
                        (maximum, 'one', 'a'))
            con.executemany('INSERT INTO accounts VALUES (?, ?, ?)', [
                ("tenant' --", ' ', 1), ("tenant' --", '雪', 0)])
        receipt = vault.transfer(self.path, 'one', 'a', 'b', maximum, 'maximum')
        self.assertIs(type(vault.balance(self.path, 'one', 'b')), int)
        self.assertEqual(vault.balance(self.path, 'one', 'b'), maximum)
        self.assertEqual(vault.transfer(self.path, **receipt), receipt)
        strange = vault.transfer(self.path, "tenant' --", ' ', '雪', 1, "key' --")
        self.assertEqual(vault.transfer(self.path, **strange), strange)

    def test_credit_overflow_rolls_back(self):
        with closing(sqlite3.connect(self.path)) as con, con:
            con.execute("UPDATE accounts SET balance=? WHERE tenant='one' AND name='b'",
                        (2**63 - 1,))
        before = self.snapshot()
        with self.assertRaises(sqlite3.DatabaseError):
            vault.transfer(self.path, 'one', 'a', 'b', 1, 'overflow')
        self.assertEqual(self.snapshot(), before)

    def test_malformed_other_tenant_data_does_not_affect_requests(self):
        self.sql("""
            UPDATE accounts SET balance='private nonnumeric balance' WHERE tenant='two';
            INSERT INTO transfers VALUES ('two', 'shared', 'private', 'secret', 'bad amount');
            INSERT INTO audit VALUES ('two', 'shared', NULL, 'secret', X'ABCD');
        """)
        before = self.snapshot()
        self.assertEqual(vault.balance(self.path, 'one', 'a'), 100)
        receipt = vault.transfer(self.path, 'one', 'a', 'b', 10, 'shared')
        self.assertEqual(receipt['tenant'], 'one')
        after = self.snapshot()
        for table in TABLES:
            self.assertEqual([row for row in after[table] if row[0] == 'two'],
                             [row for row in before[table] if row[0] == 'two'])

    def test_storage_failures_at_each_stage_roll_back(self):
        triggers = [
            "BEFORE UPDATE ON accounts WHEN OLD.tenant='one' AND OLD.name='b'",
            'BEFORE INSERT ON transfers',
            'AFTER INSERT ON transfers',
            'BEFORE INSERT ON audit',
            'AFTER INSERT ON audit',
        ]
        for index, clause in enumerate(triggers):
            for action in ('ABORT', 'FAIL', 'ROLLBACK'):
                with self.subTest(clause=clause, action=action):
                    path = self.new_db(f'failure-{index}-{action}')
                    receipts = self.history(path)
                    self.sql(f"""CREATE TRIGGER fault {clause} BEGIN
                        SELECT RAISE({action}, 'private storage details'); END;""", path)
                    before = self.snapshot(path)
                    with self.assertRaises(sqlite3.DatabaseError):
                        vault.transfer(path, 'one', 'a', 'b', 10, 'failed')
                    self.assertEqual(self.snapshot(path), before)
                    self.check_history_replay(path, receipts)
                    with closing(sqlite3.connect(path)) as con:
                        self.assertIsNotNone(con.execute(
                            "SELECT 1 FROM sqlite_master WHERE type='trigger' AND name='fault'"
                        ).fetchone())

    def test_silent_missing_or_wrong_effects_roll_back(self):
        scripts = [
            """CREATE TRIGGER fault BEFORE UPDATE ON accounts
               WHEN OLD.tenant='one' AND OLD.name='a' BEGIN SELECT RAISE(IGNORE); END;""",
            """CREATE TRIGGER fault BEFORE UPDATE ON accounts
               WHEN OLD.tenant='one' AND OLD.name='b' BEGIN SELECT RAISE(IGNORE); END;""",
            'CREATE TRIGGER fault BEFORE INSERT ON transfers BEGIN SELECT RAISE(IGNORE); END;',
            'CREATE TRIGGER fault BEFORE INSERT ON audit BEGIN SELECT RAISE(IGNORE); END;',
            """CREATE TRIGGER fault AFTER INSERT ON audit BEGIN
               UPDATE accounts SET balance=balance+1 WHERE tenant='one' AND name='b'; END;""",
            """CREATE TRIGGER fault AFTER INSERT ON audit BEGIN
               UPDATE transfers SET amount=amount+1 WHERE tenant=NEW.tenant AND key=NEW.key; END;""",
            """CREATE TRIGGER fault AFTER INSERT ON audit BEGIN
               UPDATE audit SET amount=amount+1 WHERE rowid=NEW.rowid; END;""",
            """CREATE TRIGGER fault AFTER INSERT ON audit BEGIN
               INSERT INTO audit VALUES(NEW.tenant,NEW.key,NEW.source,NEW.target,NEW.amount); END;""",
        ]
        for index, script in enumerate(scripts):
            with self.subTest(script=script):
                path = self.new_db(f'silent-{index}')
                self.sql(script, path)
                before = self.snapshot(path)
                with self.assertRaises(sqlite3.DatabaseError):
                    vault.transfer(path, 'one', 'a', 'b', 10, 'new')
                self.assertEqual(self.snapshot(path), before)

    def test_unrelated_accounts_and_history_cannot_change(self):
        statements = [
            "DELETE FROM accounts WHERE tenant='two' AND name='private'",
            "UPDATE accounts SET balance=balance+1 WHERE tenant='two' AND name='b'",
            "INSERT INTO accounts VALUES('two','unexpected',1)",
            "DELETE FROM transfers WHERE tenant='one' AND key='past_one'",
            "DELETE FROM transfers WHERE tenant='two' AND key='past_two'",
            "UPDATE transfers SET amount=amount+1 WHERE tenant='two'",
            "INSERT INTO transfers VALUES('one','unexpected','a','b',1)",
            "DELETE FROM audit WHERE tenant='one' AND key='past_one'",
            "UPDATE audit SET amount=amount+1 WHERE tenant='two'",
            "INSERT INTO audit SELECT * FROM audit WHERE tenant='two'",
        ]
        for index, statement in enumerate(statements):
            with self.subTest(statement=statement):
                path = self.new_db(f'unrelated-{index}')
                receipts = self.history(path)
                self.sql(f'CREATE TRIGGER fault AFTER INSERT ON audit BEGIN {statement}; END;', path)
                before = self.snapshot(path)
                with self.assertRaises(sqlite3.DatabaseError):
                    vault.transfer(path, 'one', 'a', 'b', 10, 'new')
                self.assertEqual(self.snapshot(path), before)
                self.check_history_replay(path, receipts)

    def test_replace_cannot_silently_destroy_collision_victims(self):
        statements = [
            """UPDATE OR REPLACE accounts SET rowid=(
                 SELECT rowid FROM accounts WHERE tenant='two' AND name='private')
               WHERE tenant='one' AND name='b'""",
            """INSERT OR REPLACE INTO accounts(rowid,tenant,name,balance)
               SELECT (SELECT rowid FROM accounts WHERE tenant='two' AND name='private'),
                 tenant,name,balance FROM accounts WHERE tenant='one' AND name='b'""",
            """UPDATE OR REPLACE transfers SET rowid=(
                 SELECT rowid FROM transfers WHERE tenant='two' AND key='past_two')
               WHERE tenant=NEW.tenant AND key=NEW.key""",
            """INSERT OR REPLACE INTO transfers(rowid,tenant,key,source,target,amount)
               SELECT (SELECT rowid FROM transfers WHERE tenant='two' AND key='past_two'),
                 tenant,key,source,target,amount FROM transfers
               WHERE tenant=NEW.tenant AND key=NEW.key""",
            """UPDATE OR REPLACE audit SET rowid=(
                 SELECT rowid FROM audit WHERE tenant='two' AND key='past_two')
               WHERE rowid=NEW.rowid""",
            """INSERT OR REPLACE INTO audit(rowid,tenant,key,source,target,amount)
               VALUES((SELECT rowid FROM audit WHERE tenant='two' AND key='past_two'),
                 NEW.tenant,NEW.key,NEW.source,NEW.target,NEW.amount);
               DELETE FROM audit WHERE rowid=NEW.rowid""",
        ]
        for index, statement in enumerate(statements):
            with self.subTest(statement=statement):
                path = self.new_db(f'replace-{index}')
                receipts = self.history(path)
                self.sql(f'CREATE TRIGGER fault AFTER INSERT ON audit BEGIN {statement}; END;', path)
                before = self.snapshot(path)
                with self.assertRaises(sqlite3.DatabaseError):
                    vault.transfer(path, 'one', 'a', 'b', 10, 'new')
                self.assertEqual(self.snapshot(path), before)
                self.check_history_replay(path, receipts)

    def test_ignored_writes_noops_and_rowid_moves_remain_valid(self):
        statements = [
            'UPDATE accounts SET balance=balance',
            "INSERT OR IGNORE INTO accounts VALUES('two','a',-999)",
            """UPDATE OR IGNORE accounts SET tenant='two',name='private'
               WHERE tenant='one' AND name='a'""",
            """UPDATE OR IGNORE transfers SET rowid=(
                 SELECT rowid FROM transfers WHERE tenant='two' AND key='past_two')
               WHERE tenant=NEW.tenant AND key=NEW.key""",
            """INSERT OR IGNORE INTO audit(rowid,tenant,key,source,target,amount)
               VALUES((SELECT rowid FROM audit WHERE tenant='two' AND key='past_two'),
                 'ignored','ignored','ignored','ignored',-999)""",
            """UPDATE accounts SET rowid=rowid+1000;
               UPDATE transfers SET rowid=rowid+1000;
               UPDATE audit SET rowid=rowid+1000""",
            """INSERT OR REPLACE INTO transfers(tenant,key,source,target,amount)
               SELECT tenant,key,source,target,amount FROM transfers WHERE tenant='two'""",
            """INSERT OR REPLACE INTO audit(rowid,tenant,key,source,target,amount)
               SELECT rowid,tenant,key,source,target,amount FROM audit WHERE tenant='two'""",
            """UPDATE accounts SET balance=balance+1 WHERE tenant='two';
               UPDATE accounts SET balance=balance-1 WHERE tenant='two'""",
        ]
        for index, statement in enumerate(statements):
            with self.subTest(statement=statement):
                path = self.new_db(f'benign-{index}')
                receipts = self.history(path)
                before = self.snapshot(path)
                self.sql(f'CREATE TRIGGER benign AFTER INSERT ON audit BEGIN {statement}; END;', path)
                receipt = vault.transfer(path, 'one', 'a', 'b', 10, 'new')
                expected = dict(before)
                expected['accounts'] = [
                    ('one', 'a', 81), ('one', 'b', 19), *before['accounts'][2:]]
                row = ('one', 'new', 'a', 'b', 10)
                expected['transfers'] = sorted([*before['transfers'], row])
                expected['audit'] = sorted([*before['audit'], row])
                self.assertEqual(self.snapshot(path), expected)
                self.check_history_replay(path, [*receipts, receipt])

    def test_benign_self_update_trigger_keeps_existing_recursion_behavior(self):
        self.sql("""CREATE TRIGGER benign AFTER UPDATE ON accounts BEGIN
            UPDATE accounts SET balance=balance WHERE tenant=NEW.tenant AND name=NEW.name;
        END;""")
        receipt = vault.transfer(self.path, 'one', 'a', 'b', 10, 'new')
        self.assertEqual(vault.balance(self.path, 'one', 'a'), 90)
        self.assertEqual(vault.balance(self.path, 'one', 'b'), 10)
        self.check_history_replay(self.path, [receipt])

    def test_unquoted_begin_trigger_succeeds_through_api_and_cli(self):
        for mode in ('DELETE', 'WAL'):
            for interface in ('API', 'CLI'):
                with self.subTest(journal=mode, interface=interface):
                    path = self.new_db(f'begin-{mode}-{interface}')
                    self.sql(f'PRAGMA journal_mode={mode};', path)
                    past = vault.transfer(path, 'two', 'a', 'b', 9, 'past')
                    self.sql('CREATE TRIGGER begin AFTER INSERT ON audit BEGIN SELECT 1; END;', path)
                    before = self.snapshot(path)
                    with closing(sqlite3.connect(path)) as con:
                        schema = con.execute(
                            'SELECT type, name, sql FROM sqlite_schema ORDER BY name'
                        ).fetchall()
                    request = dict(tenant='one', source='a', target='b', amount=10, key='new')
                    if interface == 'API':
                        receipt = vault.transfer(path, **request)
                    else:
                        result = self.command(str(path), json.dumps(dict(op='transfer', **request)))
                        self.assertEqual(result.returncode, 0, result.stderr)
                        self.assertEqual(result.stderr, '')
                        self.assertEqual(len(result.stdout.splitlines()), 1)
                        receipt = json.loads(result.stdout)
                    self.assertEqual(receipt, request)
                    expected = dict(before)
                    expected['accounts'] = [
                        ('one', 'a', 90), ('one', 'b', 10), *before['accounts'][2:]]
                    row = ('one', 'new', 'a', 'b', 10)
                    for table in ('transfers', 'audit'):
                        expected[table] = sorted([*before[table], row])
                    self.assertEqual(self.snapshot(path), expected)
                    self.check_history_replay(path, [past, receipt])
                    with closing(sqlite3.connect(path)) as con:
                        self.assertEqual(con.execute(
                            'SELECT type, name, sql FROM sqlite_schema ORDER BY name'
                        ).fetchall(), schema)
                        self.assertEqual(con.execute('PRAGMA journal_mode').fetchone()[0], mode.lower())

    def test_trigger_header_keywords_preserve_conditions_and_failures(self):
        headers = [
            'CREATE TRIGGER IF NOT EXISTS main.begin INSERT ON audit '
            'FOR EACH ROW WHEN NEW.amount=7',
            'CREATE TRIGGER before BEFORE UPDATE OF begin, balance ON accounts '
            'WHEN NEW.balance=83',
            'CREATE TRIGGER after AFTER INSERT ON audit '
            'WHEN (SELECT begin FROM (SELECT 1 AS begin)) AND NEW.amount=7',
            'CREATE TRIGGER "begin" AFTER INSERT ON audit WHEN NEW.amount=7',
        ]
        scripts = [header + """ /* BEGIN WHEN DELETE */ BEGIN
            SELECT RAISE(ABORT, 'private trigger failure'); END;""" for header in headers]
        for statement in (
            "VALUES(RAISE(ABORT, 'private trigger failure'))",
            "WITH failure AS (SELECT RAISE(ABORT, 'private trigger failure')) SELECT * FROM failure",
        ):
            scripts.append('CREATE TRIGGER begin AFTER INSERT ON audit WHEN NEW.amount=7 '
                           f'BEGIN {statement}; END;')
        scripts.append("""
            CREATE VIEW begin AS SELECT * FROM audit;
            CREATE TRIGGER instead INSTEAD OF INSERT ON begin WHEN NEW.amount=7 BEGIN
                SELECT RAISE(ABORT, 'private trigger failure'); END;
            CREATE TRIGGER forward AFTER INSERT ON audit BEGIN
                INSERT INTO begin VALUES(NEW.tenant,NEW.key,NEW.source,NEW.target,NEW.amount);
            END;
        """)
        for index, script in enumerate(scripts):
            with self.subTest(script=script):
                path = self.new_db(f'header-{index}')
                self.sql(script, path)
                with closing(sqlite3.connect(path)) as con:
                    schema = con.execute(
                        'SELECT type, name, sql FROM sqlite_schema ORDER BY name'
                    ).fetchall()
                receipt = vault.transfer(path, 'one', 'a', 'b', 10, 'new')
                self.assertEqual(vault.balance(path, 'one', 'a'), 90)
                self.assertEqual(vault.balance(path, 'one', 'b'), 10)
                after = self.snapshot(path)
                with self.assertRaises(sqlite3.DatabaseError):
                    vault.transfer(path, 'one', 'a', 'b', 7, 'failure')
                self.assertEqual(self.snapshot(path), after)
                result = self.command(str(path), json.dumps(dict(
                    op='transfer', tenant='one', source='a', target='b', amount=7, key='failure')))
                self.assertEqual(result.returncode, 2)
                self.assertEqual(result.stdout, '')
                self.assertEqual(set(json.loads(result.stderr)), {'error'})
                self.assertFalse(any(text in result.stderr for text in ('private', 'Traceback', 'SELECT')))
                self.assertEqual(self.snapshot(path), after)
                self.check_history_replay(path, [receipt])
                with closing(sqlite3.connect(path)) as con:
                    self.assertEqual(con.execute(
                        'SELECT type, name, sql FROM sqlite_schema ORDER BY name'
                    ).fetchall(), schema)

    def test_duplicate_requests_execute_once_on_separate_connections(self):
        for mode in ('DELETE', 'WAL'):
            with self.subTest(journal=mode):
                path = self.new_db(f'duplicate-{mode}')
                self.sql(f'PRAGMA journal_mode={mode};', path)
                request = dict(tenant='one', source='a', target='b', amount=100, key='same')
                results = self.concurrent(path, [request] * 8)
                self.assertEqual(results, [request] * 8)
                after = self.snapshot(path)
                self.assertEqual(after['accounts'][:2], [('one', 'a', 0), ('one', 'b', 100)])
                self.assertEqual(after['transfers'], [('one', 'same', 'a', 'b', 100)])
                self.assertEqual(after['audit'], after['transfers'])
                self.check_history_replay(path, [request])

    def test_competing_payloads_conflict_after_one_commit(self):
        requests = [dict(tenant='one', source='a', target='b', amount=amount, key='same')
                    for amount in (10, 20)]
        results = self.concurrent(self.path, requests)
        receipts = [result for result in results if isinstance(result, dict)]
        self.assertEqual(len(receipts), 1)
        self.assertEqual(sum(isinstance(result, ValueError) for result in results), 1)
        amount = receipts[0]['amount']
        after = self.snapshot()
        self.assertEqual(after['accounts'][:2], [('one', 'a', 100-amount), ('one', 'b', amount)])
        self.assertEqual(after['transfers'], [('one', 'same', 'a', 'b', amount)])
        self.assertEqual(after['audit'], after['transfers'])

    def test_distinct_keys_cannot_overspend(self):
        requests = [dict(tenant='one', source='a', target='b', amount=30, key=f'key-{i}')
                    for i in range(6)]
        results = self.concurrent(self.path, requests)
        self.assertEqual(sum(isinstance(result, dict) for result in results), 3)
        self.assertEqual(sum(isinstance(result, ValueError) for result in results), 3)
        after = self.snapshot()
        self.assertEqual(after['accounts'][:2], [('one', 'a', 10), ('one', 'b', 90)])
        self.assertEqual(len(after['transfers']), 3)
        self.assertEqual(after['audit'], after['transfers'])

    def test_concurrent_sources_do_not_lose_credits(self):
        self.sql("INSERT INTO accounts VALUES('one','c',100);")
        requests = [dict(tenant='one', source='a' if i % 2 else 'c', target='b',
                         amount=10, key=f'key-{i}') for i in range(8)]
        results = self.concurrent(self.path, requests)
        self.assertEqual(results, requests)
        after = self.snapshot()
        self.assertEqual(after['accounts'][:3],
                         [('one', 'a', 60), ('one', 'b', 80), ('one', 'c', 60)])
        self.assertEqual(len(after['transfers']), 8)
        self.assertEqual(after['audit'], after['transfers'])

    def test_cli_rejects_malformed_calls_and_unexposed_operations(self):
        requests = [None, [], {}, {'op': []}, {'op': 'init_db'}, {'op': '__dict__'},
                    {'op': 'balance', 'tenant': 'one'},
                    {'op': 'balance', 'tenant': 'one', 'account': 'a', 'extra': 1},
                    {'op': 'balance', 'tenant': None, 'account': 'a'},
                    {'op': 'transfer', 'tenant': 'one', 'source': 'a', 'target': 'b',
                     'amount': True, 'key': 'bad'}]
        calls = [(), (str(self.path),), (str(self.path), '{}', 'extra')]
        calls += [(str(self.path), raw) for raw in (
            '{broken', '[]', 'NaN',
            '{"op":"balance","tenant":"one","account":"a","account":"b"}',
            '{"op":"transfer","tenant":"one","source":"a","target":"b",'
            '"amount":Infinity,"key":"bad"}',
        )]
        calls += [(str(self.path), json.dumps(request)) for request in requests]
        before = self.snapshot()
        errors = []
        for call in calls:
            with self.subTest(arguments=call):
                result = self.command(*call)
                self.assertEqual(result.returncode, 2)
                self.assertEqual(result.stdout, '')
                self.assertEqual(set(json.loads(result.stderr)), {'error'})
                errors.append(result.stderr)
                self.assertEqual(self.snapshot(), before)
        self.assertEqual(len(set(errors)), 1)

    def test_integrated_cli_transfer_replay_failure_and_recovery(self):
        def success(request):
            result = self.cli(request)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stderr, '')
            self.assertEqual(len(result.stdout.splitlines()), 1)
            return json.loads(result.stdout)

        self.assertEqual(success(dict(op='balance', tenant='one', account='a')), 100)
        request = dict(op='transfer', tenant='one', source='a', target='b', amount=10, key='shared')
        receipt = success(request)
        self.assertEqual(receipt, {key: value for key, value in request.items() if key != 'op'})
        after = self.snapshot()
        self.assertEqual(success(request), receipt)
        self.assertEqual(self.snapshot(), after)
        for change in ({'amount': 11}, {'key': 'poor', 'amount': 1000},
                       {'key': 'hidden', 'target': 'private'}):
            result = self.cli(dict(request, **change))
            self.assertEqual(result.returncode, 2)
            self.assertEqual(result.stdout, '')
            self.assertEqual(set(json.loads(result.stderr)), {'error'})
            self.assertEqual(self.snapshot(), after)
        other = success(dict(request, tenant='two', amount=20))
        self.assertEqual(other['tenant'], 'two')
        self.sql("""CREATE TRIGGER fault AFTER INSERT ON audit WHEN NEW.amount=7 BEGIN
            SELECT RAISE(FAIL, 'SELECT private details FROM tenant_two'); END;""")
        before_failure = self.snapshot()
        retry = dict(request, key='retry', amount=7)
        result = self.cli(retry)
        self.assertEqual(result.returncode, 2)
        self.assertEqual(result.stdout, '')
        self.assertEqual(set(json.loads(result.stderr)), {'error'})
        self.assertFalse(any(text in result.stderr for text in ('SELECT', 'private', 'Traceback', 'tenant_two')))
        self.assertEqual(self.snapshot(), before_failure)
        recovered = success(dict(retry, amount=6))
        self.assertEqual(recovered['amount'], 6)
        self.assertEqual(success(dict(op='balance', tenant='one', account='a')), 84)
        self.assertEqual(success(dict(op='balance', tenant='one', account='b')), 16)
        self.assertEqual(success(dict(op='balance', tenant='two', account='a')), 680)
        after = self.snapshot()
        self.assertEqual(len(after['transfers']), 3)
        self.assertEqual(after['audit'], after['transfers'])
        self.check_history_replay(self.path, [receipt, other, recovered])


if __name__ == '__main__':
    unittest.main()
