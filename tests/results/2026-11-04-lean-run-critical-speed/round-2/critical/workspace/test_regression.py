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

    def test_trigger_effects_are_validated_before_commit(self):
        cases = (
            ('erase_receipt', "DELETE FROM transfers WHERE tenant=NEW.tenant AND key=NEW.key;"),
            ('cancel_credit', "UPDATE accounts SET balance=balance-NEW.amount "
             "WHERE tenant=NEW.tenant AND name=NEW.target;"),
            ('overwrite_foreign', "UPDATE accounts SET balance=0 WHERE tenant='other' AND name='a';"),
            ('duplicate_audit', "INSERT INTO audit VALUES(NEW.tenant,NEW.key,NEW.source,NEW.target,NEW.amount);"),
            ('change_history', "UPDATE transfers SET amount=1 WHERE key='historic';"),
        )
        for name, body in cases:
            with self.subTest(trigger=name):
                path = Path(self.tmp.name) / (name + '.sqlite')
                self.make_database(path)
                vault.transfer(path, **self.request(key='historic'))
                with closing(sqlite3.connect(path)) as con:
                    con.execute('CREATE TRIGGER ' + name + " AFTER INSERT ON audit WHEN NEW.key='probe' "
                                'BEGIN ' + body + ' END')
                    schema = con.execute('SELECT type,name,sql FROM sqlite_master ORDER BY rowid').fetchall()
                before = self.snapshot(path)
                for _ in range(2):
                    with self.assertRaises(sqlite3.IntegrityError):
                        vault.transfer(path, **self.request(key='probe'))
                    self.assertEqual(self.snapshot(path), before)
                control = self.request(key='control')
                self.assertEqual(vault.transfer(path, **control), control)
                with closing(sqlite3.connect(path)) as con:
                    self.assertEqual(con.execute('SELECT type,name,sql FROM sqlite_master ORDER BY rowid').fetchall(), schema)

    def test_replace_victims_cannot_disappear_behind_cancelled_changes(self):
        cases = (
            ('receipt_primary_key', '',
             "INSERT OR REPLACE INTO transfers VALUES('other','historic','a','b',99); "
             "DELETE FROM transfers WHERE tenant='other' AND key='historic';"),
            ('receipt_unique_index', 'CREATE UNIQUE INDEX extra ON transfers(source,amount)',
             "INSERT OR REPLACE INTO transfers VALUES('one','shadow','a','b',5); "
             "DELETE FROM transfers WHERE tenant='one' AND key='shadow';"),
            ('receipt_rowid', '',
             "INSERT OR REPLACE INTO transfers(rowid,tenant,key,source,target,amount) "
             "SELECT rowid,'one','shadow','a','b',99 FROM transfers WHERE tenant='other'; "
             "DELETE FROM transfers WHERE tenant='one' AND key='shadow';"),
            ('account_primary_key', '',
             "UPDATE OR REPLACE accounts SET name='a' WHERE tenant='other' AND name='b'; "
             "UPDATE accounts SET name='b' WHERE tenant='other' AND name='a';"),
            ('account_unique_expression', "CREATE UNIQUE INDEX extra ON accounts((balance+0)) WHERE tenant='other'",
             "INSERT OR REPLACE INTO accounts VALUES('other','shadow',895); "
             "DELETE FROM accounts WHERE tenant='other' AND name='shadow';"),
            ('account_rowid', '',
             "UPDATE OR REPLACE accounts SET rowid=(SELECT rowid FROM accounts WHERE tenant='other' AND name='a') "
             "WHERE tenant='other' AND name='b';"),
            ('audit_rowid', '',
             "INSERT OR REPLACE INTO audit(rowid,tenant,key,source,target,amount) "
             "SELECT rowid,'one','shadow','a','b',99 FROM audit WHERE tenant='other'; "
             "DELETE FROM audit WHERE tenant='one' AND key='shadow';"),
        )
        for name, index, body in cases:
            with self.subTest(conflict=name):
                path = Path(self.tmp.name) / (name + '.sqlite')
                self.make_database(path)
                vault.transfer(path, **self.request(tenant='other', key='historic', amount=5))
                with closing(sqlite3.connect(path)) as con:
                    if index:
                        con.execute(index)
                    con.execute("CREATE TRIGGER replace_history AFTER INSERT ON audit WHEN NEW.key='probe' "
                                'BEGIN ' + body + ' END')
                before = self.snapshot(path)
                with self.assertRaises(sqlite3.IntegrityError):
                    vault.transfer(path, **self.request(key='probe'))
                self.assertEqual(self.snapshot(path), before)
                control = self.request(key='control')
                self.assertEqual(vault.transfer(path, **control), control)

    def test_ignored_conflicts_noops_and_row_moves_preserve_logical_rows(self):
        vault.transfer(self.path, **self.request(tenant='other', key='historic', amount=5))
        with closing(sqlite3.connect(self.path)) as con, con:
            con.execute('INSERT INTO audit SELECT * FROM audit')  # Historical multiplicity is preserved.
            con.execute("CREATE UNIQUE INDEX extra ON accounts((balance+0)) WHERE tenant='other'")
            con.execute('''CREATE TRIGGER 記録 AFTER INSERT ON audit WHEN NEW.key='control' BEGIN
                INSERT OR IGNORE INTO accounts VALUES('other','shadow',895);
                UPDATE accounts SET balance=balance WHERE tenant='other';
                UPDATE accounts SET rowid=rowid+100 WHERE tenant='other';
                UPDATE audit SET rowid=rowid+100 WHERE tenant='other';
                INSERT OR REPLACE INTO transfers SELECT * FROM transfers WHERE tenant='other';
                SELECT CASE WHEN NEW.amount>0 THEN 'BEGIN; END; RAISE(IGNORE)' ELSE 'unused' END;
            END''')
            # REPLACE must not start firing this pre-existing DELETE trigger.
            con.execute('''CREATE TRIGGER begin BEFORE DELETE ON transfers BEGIN
                SELECT RAISE(FAIL, 'unexpected implicit delete callback'); END''')
            triggers = con.execute("SELECT name,sql FROM sqlite_master WHERE type='trigger' ORDER BY rowid").fetchall()
        before = self.snapshot()
        request = self.request(key='control')
        self.assertEqual(vault.transfer(self.path, **request), request)
        after = self.snapshot()
        for table in before:
            self.assertEqual([row for row in after[table] if row[0] == 'other'],
                             [row for row in before[table] if row[0] == 'other'])
        self.assertEqual(vault.transfer(self.path, **request), request)
        self.assertEqual(self.snapshot(), after)
        with closing(sqlite3.connect(self.path)) as con:
            self.assertEqual(con.execute("SELECT name,sql FROM sqlite_master WHERE type='trigger' ORDER BY rowid").fetchall(), triggers)

    def test_trigger_identifier_and_separator_boundaries_preserve_delete_semantics(self):
        cases = (
            ('nbsp_name', '\u00a0 DELETE'),
            ('ascii_name', 'gate DELETE'),
            ('dollar_name', 'gate$DELETE DELETE'),
            ('vertical_tab_separator', 'gate \vDELETE'),
            ('bom_before_name', '\ufeffgate DELETE'),
            ('bom_before_event', 'gate \ufeffDELETE'),
            ('bom_inside_name', 'gate\ufeff DELETE'),
        )
        for label, header in cases:
            for interface in ('api', 'cli'):
                with self.subTest(case=label, interface=interface):
                    path = Path(self.tmp.name) / (label + '-' + interface + '.sqlite')
                    self.make_database(path)
                    with closing(sqlite3.connect(path)) as con:
                        con.execute('CREATE TRIGGER ' + header +
                                    " ON transfers BEGIN SELECT RAISE(FAIL,'delete gate'); END")
                        con.execute('CREATE TRIGGER mirror AFTER INSERT ON audit BEGIN '
                                    'INSERT OR REPLACE INTO transfers SELECT * FROM transfers; END')
                        con.execute("CREATE TRIGGER explicit_delete AFTER INSERT ON audit "
                                    "WHEN NEW.key='blocked' BEGIN DELETE FROM transfers "
                                    'WHERE tenant=NEW.tenant AND key=NEW.key; END')
                        schema = con.execute(
                            'SELECT type,name,sql FROM sqlite_master ORDER BY rowid').fetchall()
                    expected = self.snapshot(path)
                    expected['accounts'] = [
                        ('one', 'a', 90) if row[:2] == ('one', 'a') else
                        ('one', 'b', 10) if row[:2] == ('one', 'b') else row
                        for row in expected['accounts']
                    ]
                    expected['transfers'] = [('one', 'k', 'a', 'b', 10)]
                    expected['audit'] = [('one', 'k', 'a', 'b', 10)]
                    request = self.request(key='k')
                    # A fresh write and its replay both preserve the logical rows.
                    for _ in range(2):
                        if interface == 'api':
                            self.assertEqual(vault.transfer(path, **request), request)
                        else:
                            self.assert_cli_success(self.cli(
                                str(path), json.dumps(dict(op='transfer', **request))), request)
                        self.assertEqual(self.snapshot(path), expected)
                    self.assertEqual(vault.balance(path, 'one', 'a'), 90)
                    self.assertEqual(vault.balance(path, 'one', 'b'), 10)

                    # Explicit DELETE still invokes the gate and rolls back all writes.
                    blocked = self.request(key='blocked')
                    if interface == 'api':
                        with self.assertRaisesRegex(sqlite3.IntegrityError, 'delete gate'):
                            vault.transfer(path, **blocked)
                    else:
                        self.assert_cli_error(self.cli(
                            str(path), json.dumps(dict(op='transfer', **blocked))))
                    self.assertEqual(self.snapshot(path), expected)
                    with closing(sqlite3.connect(path)) as con:
                        self.assertEqual(con.execute(
                            'SELECT type,name,sql FROM sqlite_master ORDER BY rowid').fetchall(), schema)

    def test_nonrecursive_trigger_order_and_ignore_unwinding(self):
        with closing(sqlite3.connect(self.path)) as con:
            con.executescript('''
                CREATE TABLE notes(message);
                CREATE TABLE work(value);
                INSERT INTO work VALUES(0);
                CREATE TRIGGER 再帰 AFTER UPDATE ON work BEGIN
                    INSERT INTO notes VALUES('nested');
                    UPDATE work SET value=value;
                    SELECT CASE WHEN NEW.value=0 THEN RAISE(IGNORE) ELSE 0 END;
                    INSERT INTO notes VALUES('unreachable');
                END;
                CREATE TRIGGER first AFTER INSERT ON audit WHEN NEW.key='control' BEGIN
                    INSERT INTO notes VALUES('first');
                END;
                CREATE TRIGGER `second` AFTER INSERT ON audit
                WHEN CASE WHEN NEW.key='control' THEN 1 ELSE 0 END BEGIN
                    INSERT INTO notes VALUES('second');
                    UPDATE work SET value=0;
                    UPDATE work SET value=0;
                    INSERT INTO notes VALUES('resumed');
                END;
            ''')
        request = self.request(key='control')
        self.assertEqual(vault.transfer(self.path, **request), request)
        with closing(sqlite3.connect(self.path)) as con:
            self.assertEqual(con.execute('SELECT message FROM notes').fetchall(),
                             [('second',), ('nested',), ('nested',), ('resumed',), ('first',)])

    def test_trigger_counters_and_last_insert_rowid_keep_native_values(self):
        with closing(sqlite3.connect(self.path)) as con:
            con.executescript('''
                CREATE TABLE counters(stage, changed, total, inserted);
                CREATE TRIGGER credit_counter BEFORE UPDATE ON accounts WHEN NEW.name='b' BEGIN
                    INSERT INTO counters VALUES('credit',changes(),total_changes(),last_insert_rowid());
                END;
                CREATE TRIGGER receipt_counter AFTER INSERT ON transfers BEGIN
                    INSERT INTO counters VALUES('receipt',changes(),total_changes(),last_insert_rowid());
                END;
                CREATE TRIGGER audit_counter AFTER INSERT ON audit BEGIN
                    INSERT INTO counters VALUES('audit',changes(),total_changes(),last_insert_rowid());
                END;
            ''')
        # Use SQLite's original trigger execution as the compatibility control.
        with closing(sqlite3.connect(self.path)) as con:
            con.execute('BEGIN')
            con.execute("UPDATE accounts SET balance=90 WHERE tenant='one' AND name='a'")
            con.execute("UPDATE accounts SET balance=10 WHERE tenant='one' AND name='b'")
            con.execute("INSERT INTO transfers VALUES('one','counter','a','b',10)")
            con.execute("INSERT INTO audit VALUES('one','counter','a','b',10)")
            native = con.execute('SELECT * FROM counters').fetchall()
            con.rollback()
        request = self.request(key='counter')
        self.assertEqual(vault.transfer(self.path, **request), request)
        with closing(sqlite3.connect(self.path)) as con:
            self.assertEqual(con.execute('SELECT * FROM counters').fetchall(), native)

    def test_after_ignore_cannot_hide_effects_and_explicit_delete_still_fails(self):
        for body in (
            "UPDATE accounts SET balance=0 WHERE tenant='other' AND name='a'; SELECT RAISE(IGNORE);",
            "DELETE FROM transfers WHERE tenant=NEW.tenant AND key=NEW.key;",
        ):
            with self.subTest(body=body):
                path = Path(self.tmp.name) / ('ignore.sqlite' if 'IGNORE' in body else 'delete.sqlite')
                self.make_database(path)
                with closing(sqlite3.connect(path)) as con:
                    con.execute("CREATE TRIGGER effect AFTER INSERT ON audit BEGIN " + body + ' END')
                    con.execute("CREATE TRIGGER delete_gate BEFORE DELETE ON transfers "
                                "BEGIN SELECT RAISE(FAIL, 'delete failure'); END")
                before = self.snapshot(path)
                with self.assertRaises(sqlite3.Error):
                    vault.transfer(path, **self.request())
                self.assertEqual(self.snapshot(path), before)

    def test_durable_receipt_replays_without_former_endpoints(self):
        request = self.request(key='durable')
        self.assertEqual(vault.transfer(self.path, **request), request)
        with closing(sqlite3.connect(self.path)) as con, con:
            con.execute("DELETE FROM accounts WHERE tenant='one' AND name IN ('a','b')")
        before = self.snapshot()
        vault.init_db(self.path)
        self.assertEqual(vault.transfer(self.path, **request), request)
        self.assert_cli_success(self.cli_request(dict(op='transfer', **request)), request)
        with self.assertRaisesRegex(ValueError, 'key conflict'):
            vault.transfer(self.path, **dict(request, amount=11))
        with self.assertRaisesRegex(ValueError, 'account unavailable'):
            vault.transfer(self.path, **dict(request, key='new'))
        self.assertEqual(self.snapshot(), before)
        other = dict(request, tenant='other')
        self.assertEqual(vault.transfer(self.path, **other), other)

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

    def test_cli_rejects_duplicate_object_keys_without_effects(self):
        before = self.snapshot()
        requests = (
            '{"op":"balance","tenant":"one","account":"missing","account":"a"}',
            '{"op":"balance","tenant":"other","tenant":"one","account":"a"}',
            '{"op":"balance","tenant":"one","account":"a","acc\\u006funt":"a"}',
            '{"op":"transfer","tenant":"one","source":"a","target":"b","amount":1,"amount":10,"key":"dup"}',
            '{"op":"transfer","tenant":"one","source":"a","target":"b","amount":10,"key":"dup","key":"dup"}',
        )
        for request in requests:
            with self.subTest(request=request):
                self.assert_cli_error(self.cli(str(self.path), request))
                self.assertEqual(self.snapshot(), before)
        self.assert_cli_success(self.cli_request(dict(op='balance', tenant='one', account='a')), 100)
        request = self.request(key='valid')
        self.assert_cli_success(self.cli_request(dict(op='transfer', **request)), request)

    def test_cli_rejects_unexpected_effects_then_recovers(self):
        with closing(sqlite3.connect(self.path)) as con:
            con.execute("CREATE TRIGGER erase_receipt AFTER INSERT ON audit WHEN NEW.key='probe' "
                        "BEGIN DELETE FROM transfers WHERE tenant=NEW.tenant AND key=NEW.key; END")
        before = self.snapshot()
        for _ in range(2):
            self.assert_cli_error(self.cli_request(dict(op='transfer', **self.request(key='probe'))))
            self.assertEqual(self.snapshot(), before)
        control = self.request(key='control')
        self.assert_cli_success(self.cli_request(dict(op='transfer', **control)), control)
        after = self.snapshot()
        self.assert_cli_success(self.cli_request(dict(op='transfer', **control)), control)
        self.assertEqual(self.snapshot(), after)


if __name__ == '__main__':
    unittest.main()
