"""Contract checks through the public vault API and the actual CLI process."""

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


ROOT = Path(__file__).resolve().parent
TABLES = ('accounts', 'transfers', 'audit')


class TransferTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(dir=ROOT)
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / 'vault.sqlite'
        vault.init_db(self.path)
        self.sql("""
            INSERT INTO accounts VALUES
                ('one','a',100),('one','b',0),('one','c',20),
                ('two','a',900),('two','b',50),('two','secret',77);
            INSERT INTO transfers VALUES ('two','old','a','b',3);
            INSERT INTO audit VALUES ('two','old','a','b',3);
        """)

    def sql(self, script):
        with closing(sqlite3.connect(self.path)) as con:
            con.executescript(script)

    def rows(self, query, params=()):
        with closing(sqlite3.connect(self.path)) as con:
            return con.execute(query, params).fetchall()

    def state(self, tables=TABLES):
        # A single reusable state assertion includes duplicates and SQLite types.
        with closing(sqlite3.connect(self.path)) as con:
            result = {}
            for table in tables:
                columns = [row[1] for row in con.execute(f'PRAGMA table_info("{table}")')]
                fields = ','.join(
                    f'typeof("{col}"),hex(CAST("{col}" AS BLOB))' for col in columns
                )
                result[table] = Counter(con.execute(f'SELECT {fields} FROM "{table}"'))
            return result

    def send(self, **changes):
        args = dict(tenant='one', source='a', target='b', amount=10, key='k')
        args.update(changes)
        return vault.transfer(self.path, **args)

    def assert_rejected(self, exception=ValueError, tables=TABLES, **changes):
        before = self.state(tables)
        with self.assertRaises(exception):
            self.send(**changes)
        self.assertEqual(self.state(tables), before)

    def cli(self, payload, *extra):
        request = payload if isinstance(payload, str) else json.dumps(payload)
        return subprocess.run(
            [sys.executable, '-B', str(ROOT / 'app.py'), str(self.path), request, *extra],
            text=True, capture_output=True, timeout=20,
        )

    def test_init_preserves_existing_schema_and_rows(self):
        before = self.state()
        schema = self.rows('SELECT type,name,sql FROM sqlite_schema ORDER BY name')
        vault.init_db(self.path)
        self.assertEqual(self.state(), before)
        self.assertEqual(self.rows('SELECT type,name,sql FROM sqlite_schema ORDER BY name'), schema)

    def test_balance_scoping_and_generic_missing_errors(self):
        self.assertEqual(vault.balance(self.path, 'one', 'a'), 100)
        self.assertEqual(vault.balance(self.path, 'two', 'a'), 900)
        errors = []
        for account in ('missing', 'secret'):
            with self.assertRaises(ValueError) as caught:
                vault.balance(self.path, 'one', account)
            errors.append(str(caught.exception))
        self.assertEqual(errors[0], errors[1])

    def test_malformed_requests_do_not_write(self):
        invalid = []
        for field in ('tenant', 'source', 'target', 'key'):
            invalid.extend({field: value} for value in ('', None, 1, True, [], b'a'))
        invalid.extend({'amount': value} for value in (0, -1, True, False, 1.0, '1', None, [], 2**80))
        invalid.extend(({'target': 'a'}, {'target': 'missing'}, {'source': 'missing'},
                        {'target': 'secret'}, {'source': 'secret'}, {'amount': 101}))
        for changes in invalid:
            with self.subTest(changes=changes):
                self.assert_rejected(**changes)
        for tenant, account in (('', 'a'), ('one', ''), (None, 'a'), ('one', [])):
            with self.subTest(tenant=tenant, account=account), self.assertRaises(ValueError):
                vault.balance(self.path, tenant, account)

    def test_exact_replay_conflicts_and_independent_tenant_keys(self):
        receipt = self.send(amount=100)
        self.assertEqual(receipt, dict(tenant='one', key='k', source='a', target='b', amount=100))
        before = self.state()
        self.assertEqual(self.send(amount=100), receipt)
        self.assertEqual(self.state(), before)
        for payload in ({'amount': 1}, {'source': 'b', 'target': 'a'}, {'target': 'c'}):
            with self.subTest(payload=payload):
                self.assert_rejected(**payload)
        other = self.send(tenant='two', amount=100)
        self.assertEqual(other['tenant'], 'two')
        self.assertEqual(vault.balance(self.path, 'two', 'a'), 800)
        self.assertEqual(self.rows('SELECT tenant,key FROM audit ORDER BY tenant,key'),
                         [('one', 'k'), ('two', 'k'), ('two', 'old')])

    def test_foreign_cached_receipt_is_invisible(self):
        receipt = self.send(key='old')
        self.assertEqual(receipt['tenant'], 'one')
        self.assertEqual(receipt['amount'], 10)
        self.assertEqual(vault.balance(self.path, 'two', 'a'), 900)

    def test_replay_requires_existing_scoped_endpoints(self):
        receipt = self.send()
        receipt['amount'] = 999
        self.assertEqual(self.send()['amount'], 10)
        self.sql("DELETE FROM accounts WHERE tenant='one' AND name='b';")
        self.assert_rejected()

    def test_audit_failures_propagate_and_rollback_every_effect(self):
        for action in ('ABORT', 'FAIL', 'ROLLBACK', 'IGNORE'):
            with self.subTest(action=action):
                self.sql('DROP TRIGGER IF EXISTS reject_audit; DROP TABLE IF EXISTS side; '
                         'CREATE TABLE side(value); '
                         'CREATE TRIGGER account_side AFTER UPDATE ON accounts BEGIN '
                         'INSERT INTO side VALUES(new.balance); END;')
                raise_sql = "RAISE(IGNORE)" if action == 'IGNORE' else f"RAISE({action}, 'private SQL detail')"
                self.sql(f'CREATE TRIGGER reject_audit BEFORE INSERT ON audit BEGIN SELECT {raise_sql}; END;')
                exception = ValueError if action == 'IGNORE' else sqlite3.IntegrityError
                self.assert_rejected(exception, tables=(*TABLES, 'side'))
                self.assertEqual(self.rows("SELECT count(*) FROM sqlite_schema WHERE name='reject_audit'"), [(1,)])
                self.sql('DROP TRIGGER account_side;')

    def test_final_ledger_validation_includes_duplicates_and_foreign_insertions(self):
        actions = (
            "UPDATE accounts SET balance=balance+1 WHERE tenant='one' AND name='c';",
            "DELETE FROM accounts WHERE tenant='one' AND name='c';",
            "INSERT INTO accounts VALUES('one','extra',0);",
            "INSERT INTO accounts VALUES('two','phantom',0);",
            "INSERT INTO transfers VALUES('two','phantom','a','b',1);",
            "INSERT INTO audit VALUES('two','phantom','a','b',1);",
            "INSERT INTO audit VALUES(new.tenant,new.key,new.source,new.target,new.amount);",
            "UPDATE transfers SET amount=amount+1 WHERE tenant=new.tenant AND key=new.key;",
        )
        for action in actions:
            with self.subTest(action=action):
                self.sql('DROP TRIGGER IF EXISTS extra_effect; '
                         f'CREATE TRIGGER extra_effect AFTER INSERT ON audit BEGIN {action} END;')
                self.assert_rejected()

    def test_local_views_and_side_effects_keep_native_behavior(self):
        self.sql("""
            CREATE TABLE observations(id INTEGER PRIMARY KEY AUTOINCREMENT, n INTEGER, amount INTEGER);
            CREATE VIEW local_accounts AS SELECT * FROM main.accounts;
            CREATE VIEW record_observation AS SELECT n,amount FROM observations;
            CREATE TRIGGER record_view INSTEAD OF INSERT ON record_observation BEGIN
                INSERT INTO observations(n,amount) VALUES(new.n,new.amount);
            END;
            CREATE TRIGGER observe AFTER INSERT ON audit BEGIN
                INSERT INTO record_observation SELECT count(*),sum(balance) FROM local_accounts;
                UPDATE accounts SET balance=0 WHERE tenant='two';
                DELETE FROM transfers WHERE tenant='two';
                DELETE FROM audit WHERE tenant='two';
            END;
        """)
        foreign_before = {table: self.rows(f'SELECT rowid,* FROM {table} WHERE tenant="two"') for table in TABLES}
        self.send()
        self.assertEqual(self.rows('SELECT * FROM observations'), [(1, 3, 120)])
        for table in TABLES:
            self.assertEqual(self.rows(f'SELECT rowid,* FROM {table} WHERE tenant="two"'), foreign_before[table])
        self.send(key='second')
        self.assertEqual(self.rows('SELECT * FROM observations'), [(1, 3, 120), (2, 3, 120)])

    def test_valid_noops_ignored_conflicts_and_row_moves(self):
        self.sql("""
            CREATE TRIGGER valid_effects AFTER INSERT ON audit BEGIN
                UPDATE accounts SET balance=balance WHERE tenant='one';
                UPDATE OR IGNORE accounts SET name='b' WHERE tenant='one' AND name='c';
                INSERT OR IGNORE INTO transfers VALUES(new.tenant,new.key,'x','y',999);
                UPDATE accounts SET rowid=rowid+100 WHERE tenant='one' AND name='c';
                INSERT INTO audit VALUES('one','temporary','a','b',1);
                DELETE FROM audit WHERE key='temporary';
            END;
        """)
        self.send()
        self.assertEqual(vault.balance(self.path, 'one', 'a'), 90)
        self.assertEqual(self.rows("SELECT count(*) FROM audit WHERE tenant='one'"), [(1,)])

    def test_trigger_noninterference_with_absent_different_and_malformed_foreign_rows(self):
        self.sql("""
            CREATE TABLE observations(a,t,u,n,changed,total,last_id);
            CREATE VIEW all_names AS SELECT tenant,name FROM main.accounts;
            CREATE TRIGGER probe AFTER INSERT ON audit BEGIN
                UPDATE accounts SET balance=0 WHERE tenant <> new.tenant;
                INSERT INTO observations SELECT
                    (SELECT count(*) FROM all_names),
                    (SELECT count(*) FROM main.transfers),
                    (SELECT count(*) FROM main.audit),
                    (SELECT coalesce(sum(balance),0) FROM accounts WHERE tenant='two'),
                    changes(),total_changes(),last_insert_rowid();
                SELECT CASE WHEN EXISTS(SELECT 1 FROM accounts WHERE tenant='two')
                    THEN RAISE(ABORT,'hidden data') END;
            END;
        """)
        outcomes = []
        for variant in ('present', 'absent', 'malformed'):
            with self.subTest(variant=variant):
                path = Path(self.tmp.name) / f'{variant}.sqlite'
                with closing(sqlite3.connect(self.path)) as src, closing(sqlite3.connect(path)) as dest:
                    src.backup(dest)
                    if variant == 'absent':
                        for table in TABLES:
                            dest.execute(f'DELETE FROM {table} WHERE tenant="two"')
                    elif variant == 'malformed':
                        dest.execute("UPDATE accounts SET balance=x'ff', name=CAST(x'fe' AS TEXT) WHERE tenant='two' AND name='secret'")
                        dest.execute("UPDATE audit SET amount=CAST(x'fd' AS TEXT) WHERE tenant='two'")
                    dest.commit()
                original = self.path
                self.path = path
                try:
                    protected = self.state()
                    receipt = self.send()
                    outcomes.append((receipt, self.rows('SELECT * FROM observations')))
                    # Protected values, including malformed TEXT, remain byte-identical.
                    after = self.state()
                    for table in TABLES:
                        before_foreign = Counter({row: n for row, n in protected[table].items() if row[1] != '6F6E65'})
                        after_foreign = Counter({row: n for row, n in after[table].items() if row[1] != '6F6E65'})
                        self.assertEqual(before_foreign, after_foreign)
                finally:
                    self.path = original
        self.assertEqual(outcomes[0], outcomes[1])
        self.assertEqual(outcomes[1], outcomes[2])
        self.assertEqual(outcomes[0][1], [(3, 1, 1, 0, 0, 3, 1)])

    def test_local_trigger_failure_is_not_suppressed(self):
        self.sql("""
            CREATE TRIGGER local_policy BEFORE INSERT ON audit BEGIN
                SELECT CASE WHEN (SELECT count(*) FROM accounts WHERE tenant=new.tenant)=3
                    THEN RAISE(ABORT,'local policy') END;
            END;
        """)
        self.assert_rejected(sqlite3.IntegrityError)

    def test_rowid_counters_remain_isolated_across_successive_transfers(self):
        outcomes = []
        for hidden in (False, True):
            path = Path(self.tmp.name) / f'counter-{hidden}.sqlite'
            vault.init_db(path)
            with closing(sqlite3.connect(path)) as con:
                con.executescript("INSERT INTO accounts VALUES('one','a',100),('one','b',0);")
                if hidden:
                    con.executescript("INSERT INTO transfers VALUES('hidden','old','a','b',1); "
                                      "INSERT INTO audit VALUES('hidden','old','a','b',1);")
                con.executescript('CREATE TABLE seen(n,t,a); '
                                 'CREATE TRIGGER probe AFTER INSERT ON audit BEGIN '
                                 'INSERT INTO seen SELECT last_insert_rowid(), '
                                 '(SELECT max(rowid) FROM transfers), '
                                 '(SELECT max(rowid) FROM accounts); END;')
            for key in ('first', 'second', 'third'):
                vault.transfer(path, 'one', 'a', 'b', 10, key)
            with closing(sqlite3.connect(path)) as con:
                outcomes.append(con.execute('SELECT * FROM seen').fetchall())
        self.assertEqual(outcomes[0], outcomes[1])
        self.assertEqual(outcomes[0], [(1, 1, 2), (2, 2, 2), (3, 3, 2)])

    def test_auxiliary_types_generated_columns_and_without_rowid(self):
        self.sql("""
            CREATE TABLE extra(k TEXT PRIMARY KEY, v BLOB, n INTEGER, doubled AS (n*2) STORED) WITHOUT ROWID;
            INSERT INTO extra(k,v,n) VALUES('old',x'ff00',3);
            CREATE TRIGGER side_effect AFTER INSERT ON audit BEGIN
                UPDATE extra SET n=n+1 WHERE k='old';
                INSERT INTO extra(k,v,n) VALUES(new.key,x'0102',new.amount);
            END;
        """)
        self.send()
        self.assertEqual(self.rows('SELECT * FROM extra ORDER BY k'), [('k', b'\x01\x02', 10, 20), ('old', b'\xff\x00', 4, 8)])

    def test_auxiliary_checks_are_evaluated_in_native_trigger_context(self):
        self.sql("""
            CREATE TABLE side(n CHECK(n>0 AND total_changes()=1));
            CREATE TRIGGER side_write AFTER UPDATE ON accounts WHEN new.name='b' BEGIN
                INSERT INTO side VALUES(1);
            END;
        """)
        # Independent native SQLite control: the first UPDATE has completed,
        # while the second UPDATE's AFTER trigger has not yet been counted.
        with closing(sqlite3.connect(self.path)) as native:
            native.execute("UPDATE accounts SET balance=balance-10 WHERE tenant='one' AND name='a'")
            native.execute("UPDATE accounts SET balance=balance+10 WHERE tenant='one' AND name='b'")
            self.assertEqual(native.execute('SELECT * FROM side').fetchall(), [(1,)])
            native.rollback()
        self.send()
        self.assertEqual(self.rows('SELECT * FROM side'), [(1,)])
        self.sql('DROP TRIGGER side_write; CREATE TRIGGER side_write AFTER UPDATE ON accounts '
                 "WHEN new.name='b' BEGIN INSERT INTO side VALUES(0); END;")
        self.assert_rejected(sqlite3.IntegrityError, tables=(*TABLES, 'side'), key='invalid-side')

    def test_storage_failure_during_merge_rolls_back_prior_writes(self):
        # Cross-tenant uniqueness is outside the isolation guarantee, but gives
        # a real storage failure after the durable debit/credit, without mocks.
        self.sql('CREATE UNIQUE INDEX storage_fault ON audit(key); '
                 'CREATE TABLE side(n); '
                 'CREATE TRIGGER side_write AFTER UPDATE ON accounts BEGIN '
                 'INSERT INTO side VALUES(new.balance); END;')
        self.assert_rejected(sqlite3.IntegrityError, tables=(*TABLES, 'side'), key='old')

    def concurrent(self, requests):
        barrier = threading.Barrier(len(requests))
        def run(request):
            barrier.wait(timeout=10)
            try:
                return self.send(**request)
            except ValueError:
                return None
        with ThreadPoolExecutor(max_workers=len(requests)) as pool:
            return list(pool.map(run, requests))

    def test_concurrent_duplicates_execute_once(self):
        receipts = self.concurrent([{} for _ in range(8)])
        self.assertTrue(all(receipt == receipts[0] for receipt in receipts))
        self.assertIsNotNone(receipts[0])
        self.assertEqual(vault.balance(self.path, 'one', 'a'), 90)
        self.assertEqual(vault.balance(self.path, 'one', 'b'), 10)
        self.assertEqual(self.rows("SELECT count(*) FROM audit WHERE tenant='one'"), [(1,)])

    def test_concurrent_distinct_keys_never_overspend(self):
        results = self.concurrent([{'key': str(i), 'amount': 30} for i in range(8)])
        self.assertEqual(sum(result is not None for result in results), 3)
        self.assertEqual(vault.balance(self.path, 'one', 'a'), 10)
        self.assertEqual(vault.balance(self.path, 'one', 'b'), 90)
        self.assertEqual(self.rows("SELECT count(*) FROM transfers WHERE tenant='one'"), [(3,)])
        self.assertEqual(self.rows("SELECT count(*) FROM audit WHERE tenant='one'"), [(3,)])

    def test_concurrent_distinct_sources_do_not_lose_credits(self):
        results = self.concurrent([{'key': str(i), 'source': 'a' if i % 2 else 'c', 'amount': 5} for i in range(8)])
        self.assertTrue(all(results))
        self.assertEqual(vault.balance(self.path, 'one', 'a'), 80)
        self.assertEqual(vault.balance(self.path, 'one', 'c'), 0)
        self.assertEqual(vault.balance(self.path, 'one', 'b'), 40)

    def test_wal_transfer_and_replay_after_reopen(self):
        self.sql('PRAGMA journal_mode=WAL;')
        receipt = self.send()
        before = self.state()
        vault.init_db(self.path)
        self.assertEqual(self.send(), receipt)
        self.assertEqual(self.state(), before)

    def test_cli_integrated_journey_and_failures(self):
        request = dict(op='transfer', tenant='one', source='a', target='b', amount=10, key='cli')
        first = self.cli(request)
        self.assertEqual((first.returncode, first.stderr), (0, ''))
        self.assertEqual(json.loads(first.stdout), {k: v for k, v in request.items() if k != 'op'})
        before = self.state()
        replay = self.cli(request)
        self.assertEqual((replay.returncode, replay.stdout, replay.stderr), (0, first.stdout, ''))
        self.assertEqual(self.state(), before)
        read = self.cli(dict(op='balance', tenant='one', account='a'))
        self.assertEqual((read.returncode, json.loads(read.stdout), read.stderr), (0, 90, ''))
        failures = [
            '{', '[]', 'null', {}, {'op': 'init_db'}, {'op': '__dict__'},
            {'op': 'balance', 'tenant': 'one', 'account': 'secret'},
            {'op': 'balance', 'tenant': 'one', 'account': 'absent'},
            {'op': 'balance', 'tenant': 'one', 'account': 'a', 'extra': 1},
            dict(request, amount=True), dict(request, amount=11),
            dict(request, key='overspend', amount=1000),
        ]
        for payload in failures:
            with self.subTest(payload=payload):
                result = self.cli(payload)
                self.assertEqual((result.returncode, result.stdout), (2, ''))
                self.assertEqual(json.loads(result.stderr), {'error': 'invalid request'})
                self.assertEqual(self.state(), before)
        for args in ([], [str(self.path)], [str(self.path), '{}', 'extra']):
            result = subprocess.run([sys.executable, '-B', str(ROOT / 'app.py'), *args], capture_output=True, text=True, timeout=20)
            self.assertEqual((result.returncode, result.stdout), (2, ''))
            self.assertEqual(json.loads(result.stderr), {'error': 'invalid request'})
        self.sql("CREATE TRIGGER fail_cli BEFORE INSERT ON audit BEGIN SELECT RAISE(ABORT,'SECRET SQL'); END;")
        failed = self.cli(dict(request, key='storage'))
        self.assertEqual((failed.returncode, failed.stdout), (2, ''))
        self.assertEqual(json.loads(failed.stderr), {'error': 'invalid request'})
        self.assertEqual(self.state(), before)


if __name__ == '__main__':
    unittest.main()
