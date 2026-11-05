"""Public-interface regression checks for the local accounting contract."""

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
CORE = ('accounts', 'transfers', 'audit')


class VaultTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(dir=ROOT)
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / 'vault.db'
        vault.init_db(self.path)
        self.sql("INSERT INTO accounts VALUES "
                 "('one','a',100),('one','b',0),"
                 "('two','a',900),('two','b',0),('two','private',71)")

    def sql(self, script, path=None):
        with closing(sqlite3.connect(path or self.path)) as con, con:
            con.executescript(script)

    def rows(self, table, path=None):
        with closing(sqlite3.connect(path or self.path)) as con:
            return con.execute('SELECT rowid,* FROM "' + table + '"').fetchall()

    def schema(self, path=None):
        with closing(sqlite3.connect(path or self.path)) as con:
            return (con.execute('SELECT * FROM sqlite_schema ORDER BY name').fetchall(),
                    con.execute('PRAGMA schema_version').fetchone(),
                    con.execute('PRAGMA user_version').fetchone())

    def state(self):
        return self.schema(), {table: self.rows(table) for table in CORE}

    def transfer(self, **changes):
        args = dict(tenant='one', source='a', target='b', amount=10, key='k')
        args.update(changes)
        return vault.transfer(self.path, **args)

    def assertRejected(self, **changes):
        before = self.state()
        with self.assertRaises(ValueError):
            self.transfer(**changes)
        self.assertEqual(self.state(), before)

    def cli(self, request, *extra):
        raw = request if isinstance(request, str) else json.dumps(request)
        return subprocess.run([sys.executable, '-B', str(ROOT / 'app.py'),
                               str(self.path), raw, *extra],
                              text=True, capture_output=True, timeout=15)

    def test_balance_isolation_and_generic_missing_accounts(self):
        before = self.state()
        self.assertEqual(vault.balance(self.path, 'one', 'a'), 100)
        self.assertEqual(vault.balance(self.path, 'two', 'a'), 900)
        errors = []
        for account in ('private', 'absent'):
            with self.assertRaises(ValueError) as failure:
                vault.balance(self.path, 'one', account)
            errors.append(str(failure.exception))
        self.assertEqual(errors[0], errors[1])
        self.assertEqual(self.state(), before)

    def test_validation_and_no_writes(self):
        for name in ('tenant', 'source', 'target', 'key'):
            for value in ('', None, 1, True, [], {}, b'a'):
                with self.subTest(field=name, value=value):
                    self.assertRejected(**{name: value})
        for value in (0, -1, True, False, 1.0, '1', None, [], {}, 10**100):
            with self.subTest(amount=value):
                self.assertRejected(amount=value)
        for changes in ({'target': 'a'}, {'source': 'private'},
                        {'target': 'private'}, {'source': 'missing'},
                        {'target': 'missing'}, {'tenant': 'missing'},
                        {'amount': 101}):
            with self.subTest(changes=changes):
                self.assertRejected(**changes)
        for tenant, account in (('', 'a'), ('one', ''), ([], 'a'), ('one', {})):
            with self.assertRaises(ValueError):
                vault.balance(self.path, tenant, account)

    def test_replay_conflict_and_independent_tenant_keys_after_reopen(self):
        schema = self.schema()
        receipt = self.transfer(amount=100)
        before = self.state()
        receipt['amount'] = -1  # The caller does not own stored receipt state.
        replay = self.transfer(amount=100)
        self.assertEqual(replay['amount'], 100)
        self.assertEqual(self.state(), before)
        for changes in ({'amount': 1}, {'source': 'b', 'target': 'a'}):
            self.assertRejected(**changes)
        other = self.transfer(tenant='two')
        self.assertEqual(other['tenant'], 'two')
        self.assertEqual(vault.balance(self.path, 'two', 'a'), 890)
        self.assertEqual(vault.balance(self.path, 'one', 'a'), 0)
        self.assertEqual(len(self.rows('transfers')), 2)
        self.assertEqual(len(self.rows('audit')), 2)
        vault.init_db(self.path)
        self.assertEqual(self.schema(), schema)

    def test_scalar_subclasses_are_normalized_before_validation(self):
        class PretendNonempty(str):
            def __len__(self):
                return 1

        class PretendPositive(int):
            def __le__(self, other):
                return False

        for field in ('tenant', 'source', 'target', 'key'):
            self.assertRejected(**{field: PretendNonempty('')})
        self.assertRejected(amount=PretendPositive(-10))
        with self.assertRaises(ValueError):
            vault.balance(self.path, PretendNonempty(''), 'a')

    def test_tenant_identity_is_exact_even_with_declared_collations(self):
        path = Path(self.tmp.name) / 'collated.db'
        self.sql('CREATE TABLE accounts(tenant TEXT COLLATE NOCASE, name TEXT, '
                 'balance INTEGER, PRIMARY KEY(tenant COLLATE BINARY,name));', path)
        vault.init_db(path)
        self.sql("INSERT INTO accounts VALUES ('one','a',100),('one','b',0),"
                 "('ONE','a',900),('ONE','b',70);", path)
        protected = [row for row in self.rows('accounts', path) if row[1] == 'ONE']
        schema = self.schema(path)
        vault.transfer(path, 'one', 'a', 'b', 10, 'k')
        self.assertEqual(vault.balance(path, 'one', 'a'), 90)
        self.assertEqual(vault.balance(path, 'ONE', 'a'), 900)
        self.assertEqual(protected, [row for row in self.rows('accounts', path)
                                     if row[1] == 'ONE'])
        self.assertEqual(self.schema(path), schema)

    def test_audit_storage_failure_rolls_back_everything(self):
        self.sql("""
            CREATE TABLE events(value);
            CREATE TRIGGER event AFTER UPDATE ON accounts BEGIN
              INSERT INTO events VALUES (NEW.balance);
            END;
            CREATE TRIGGER fail BEFORE INSERT ON audit BEGIN
              SELECT RAISE(ABORT,'private audit implementation detail');
            END;
        """)
        before = self.state()
        with self.assertRaises(sqlite3.IntegrityError):
            self.transfer()
        self.assertEqual(self.state(), before)
        self.assertEqual(self.rows('events'), [])
        self.sql('DROP TRIGGER fail;')
        self.transfer()  # The failed key was never consumed.
        self.assertEqual(len(self.rows('audit')), 1)
        self.assertEqual(len(self.rows('events')), 2)

    def test_final_effects_reject_additions_losses_types_and_multiplicity(self):
        bodies = (
            "UPDATE accounts SET balance=balance+1 WHERE tenant='one' AND name='b';",
            "DELETE FROM accounts WHERE tenant='one' AND name='b';",
            "INSERT INTO accounts VALUES ('foreign','x',0);",
            "INSERT INTO audit VALUES (NEW.tenant,NEW.key,NEW.source,NEW.target,NEW.amount);",
            "DELETE FROM transfers WHERE tenant=NEW.tenant AND key=NEW.key;",
            "UPDATE transfers SET source=CAST(source AS BLOB) WHERE tenant=NEW.tenant;",
            "INSERT INTO transfers VALUES ('foreign','x','a','b',1);",
            "INSERT INTO audit VALUES ('foreign','x','a','b',1);",
            "DELETE FROM audit WHERE key='history';",
        )
        self.sql("INSERT INTO audit VALUES ('one','history','a','b',1);")
        for body in bodies:
            with self.subTest(body=body):
                self.sql('CREATE TRIGGER extra AFTER INSERT ON audit BEGIN ' + body + ' END;')
                self.assertRejected()
                self.sql('DROP TRIGGER extra;')

    def test_legitimate_noops_ignored_conflicts_and_row_moves(self):
        self.sql("""
            INSERT INTO audit VALUES ('one','history','a','b',1);
            CREATE TABLE messages(id INTEGER PRIMARY KEY AUTOINCREMENT, value TEXT UNIQUE);
            INSERT INTO messages(value) VALUES ('existing');
            CREATE VIEW message_view AS SELECT value FROM messages;
            CREATE TRIGGER insert_message INSTEAD OF INSERT ON message_view BEGIN
              INSERT INTO messages(value) VALUES (NEW.value);
            END;
            CREATE TABLE totals(name TEXT PRIMARY KEY, value INTEGER) WITHOUT ROWID;
            INSERT INTO totals VALUES ('n',0);
            CREATE TABLE generated(x INTEGER, y INTEGER GENERATED ALWAYS AS (x*2));
            CREATE TRIGGER permitted AFTER INSERT ON audit WHEN NEW.key='k' BEGIN
              UPDATE accounts SET balance=balance WHERE tenant=NEW.tenant;
              INSERT OR IGNORE INTO accounts VALUES (NEW.tenant,NEW.source,999);
              UPDATE audit SET rowid=rowid+100 WHERE key='history';
              INSERT OR IGNORE INTO message_view(value) VALUES ('existing');
              INSERT INTO message_view(value) VALUES ('new');
              UPDATE totals SET value=value+1;
              INSERT INTO generated(x) VALUES (7);
            END;
        """)
        schema = self.schema()
        self.transfer()
        self.assertEqual(self.rows('messages'), [(1, 1, 'existing'), (3, 3, 'new')])
        self.assertEqual(self.rows('generated'), [(1, 7, 14)])
        with closing(sqlite3.connect(self.path)) as con:
            self.assertEqual(con.execute('SELECT * FROM totals').fetchall(), [('n', 1)])
        self.assertEqual(len(self.rows('audit')), 2)
        self.assertEqual(self.schema(), schema)

    def test_native_trigger_noninterference_including_counters_and_views(self):
        script = """
            CREATE TABLE observations(id INTEGER PRIMARY KEY AUTOINCREMENT,
              n, receipts, audits, c, t, r);
            CREATE VIEW visible AS SELECT tenant,name,balance FROM main.accounts;
            CREATE TRIGGER inspect BEFORE UPDATE ON accounts WHEN NEW.name='a' BEGIN
              INSERT INTO observations(n,receipts,audits,c,t,r)
                SELECT (SELECT count(*) FROM visible),
                       (SELECT count(*) FROM main.transfers),
                       (SELECT count(*) FROM audit),
                       changes(),total_changes(),last_insert_rowid();
              UPDATE accounts SET balance=0 WHERE tenant IS NOT NEW.tenant;
              DELETE FROM transfers WHERE tenant IS NOT NEW.tenant;
              DELETE FROM audit WHERE tenant IS NOT NEW.tenant;
              SELECT CASE WHEN EXISTS (
                SELECT 1 FROM (WITH hidden AS (SELECT * FROM visible)
                  SELECT * FROM hidden WHERE tenant IS NOT NEW.tenant)
              ) THEN RAISE(ABORT,'foreign data was visible') END;
            END;
            CREATE TRIGGER local AFTER INSERT ON audit BEGIN
              INSERT INTO observations(n,receipts,audits,c,t,r)
                SELECT count(*),(SELECT count(*) FROM transfers),
                       (SELECT count(*) FROM audit),changes(),total_changes(),
                       last_insert_rowid() FROM visible;
            END;
        """
        outcomes = []
        for index, foreign in enumerate(([], [('two','a',900)],
                                         [('two','a','malformed'),
                                          (None,'private',b'private'),
                                          (b'two','b',-999)])):
            path = Path(self.tmp.name) / f'variant{index}.db'
            vault.init_db(path)
            with closing(sqlite3.connect(path)) as con, con:
                con.executemany('INSERT INTO accounts VALUES (?,?,?)',
                                [('one','a',100), ('one','b',0)] + foreign)
                if foreign:
                    con.execute("INSERT INTO transfers VALUES ('two','k','secret','target',999)")
                    con.execute("INSERT INTO audit VALUES ('two','k','secret','target',999)")
            self.sql(script, path)
            protected = {table: [row for row in self.rows(table, path) if row[1] != 'one']
                         for table in CORE}
            schema = self.schema(path)
            receipt = vault.transfer(path, 'one', 'a', 'b', 10, 'k')
            self.assertEqual(vault.transfer(path, 'one', 'a', 'b', 10, 'k'), receipt)
            # Reopen after a real commit: physical core rowids may have been
            # allocated above hidden history, and must not seed later counters.
            vault.transfer(path, 'one', 'a', 'b', 10, 'next')
            outcomes.append((receipt, self.rows('observations', path)))
            self.assertEqual(schema, self.schema(path))
            self.assertEqual(protected, {
                table: [row for row in self.rows(table, path) if row[1] != 'one']
                for table in CORE})
        self.assertEqual(outcomes[0], outcomes[1])
        self.assertEqual(outcomes[0], outcomes[2])
        # Compare against the native engine on the genuinely tenant-only state.
        oracle = Path(self.tmp.name) / 'oracle.db'
        vault.init_db(oracle)
        self.sql("INSERT INTO accounts VALUES ('one','a',100),('one','b',0);" + script, oracle)
        for key in ('k', 'next'):
            with closing(sqlite3.connect(oracle)) as con, con:
                con.execute("UPDATE accounts SET balance=balance-10 WHERE tenant='one' AND name='a'")
                con.execute("UPDATE accounts SET balance=balance+10 WHERE tenant='one' AND name='b'")
                con.execute("INSERT INTO transfers VALUES ('one',?,'a','b',10)", (key,))
                con.execute("INSERT INTO audit VALUES ('one',?,'a','b',10)", (key,))
        self.assertEqual(outcomes[0][1], self.rows('observations', oracle))

    def test_local_view_failure_remains_native(self):
        self.sql("""
            CREATE VIEW active AS SELECT * FROM accounts WHERE balance>0;
            CREATE TRIGGER local_failure BEFORE INSERT ON audit BEGIN
              SELECT CASE WHEN (SELECT count(*) FROM active)=2
                THEN RAISE(FAIL,'local condition') END;
            END;
        """)
        before = self.state()
        with self.assertRaises(sqlite3.IntegrityError):
            self.transfer()
        self.assertEqual(self.state(), before)

    def concurrent(self, requests):
        barrier = threading.Barrier(len(requests))

        def run(request):
            barrier.wait(timeout=15)
            try:
                return self.transfer(**request)
            except ValueError:
                return None

        with ThreadPoolExecutor(max_workers=len(requests)) as pool:
            return list(pool.map(run, requests))

    def test_simultaneous_duplicate_requests_execute_once(self):
        receipts = self.concurrent([{} for _ in range(8)])
        self.assertTrue(all(receipt == receipts[0] for receipt in receipts))
        self.assertIsNotNone(receipts[0])
        self.assertEqual(vault.balance(self.path, 'one', 'a'), 90)
        self.assertEqual(vault.balance(self.path, 'one', 'b'), 10)
        self.assertEqual(len(self.rows('transfers')), 1)
        self.assertEqual(len(self.rows('audit')), 1)

    def test_simultaneous_distinct_requests_never_overspend(self):
        receipts = self.concurrent([{'key': str(i), 'amount': 17} for i in range(10)])
        self.assertEqual(sum(receipt is not None for receipt in receipts), 5)
        self.assertEqual(vault.balance(self.path, 'one', 'a'), 15)
        self.assertEqual(vault.balance(self.path, 'one', 'b'), 85)
        self.assertEqual(len(self.rows('transfers')), 5)
        self.assertEqual(len(self.rows('audit')), 5)

    def test_simultaneous_sources_do_not_lose_credits(self):
        self.sql("INSERT INTO accounts VALUES ('one','c',100);")
        receipts = self.concurrent([{'source': 'a' if i % 2 else 'c', 'key': str(i)}
                                    for i in range(8)])
        self.assertTrue(all(receipts))
        self.assertEqual(vault.balance(self.path, 'one', 'a'), 60)
        self.assertEqual(vault.balance(self.path, 'one', 'c'), 60)
        self.assertEqual(vault.balance(self.path, 'one', 'b'), 80)
        self.assertEqual(len(self.rows('audit')), 8)

    def test_wal_and_schema_preservation(self):
        with closing(sqlite3.connect(self.path)) as con:
            con.execute('PRAGMA journal_mode=WAL')
        self.sql("CREATE INDEX by_amount ON audit(amount);"
                 "CREATE VIEW receipts AS SELECT * FROM transfers;"
                 "PRAGMA user_version=37;")
        schema = self.schema()
        self.transfer()
        self.assertEqual(vault.balance(self.path, 'one', 'b'), 10)
        self.assertEqual(schema, self.schema())

    def test_cli_integrated_journey_and_generic_failures(self):
        request = dict(op='transfer', tenant='one', source='a', target='b', amount=10, key='k')
        first = self.cli(request)
        self.assertEqual(first.returncode, 0, first.stderr)
        self.assertEqual(first.stderr, '')
        self.assertEqual(json.loads(first.stdout), {k: v for k, v in request.items() if k != 'op'})
        before = self.state()
        self.assertEqual(self.cli(request).stdout, first.stdout)
        self.assertEqual(self.state(), before)
        result = self.cli(dict(op='balance', tenant='one', account='b'))
        self.assertEqual((result.returncode, result.stderr, json.loads(result.stdout)), (0, '', 10))
        cases = ['{', 'null', '[]', '{}', {'op': []}, {'op': 'init_db'},
                 dict(request, amount=True), dict(request, amount=11),
                 dict(request, extra=1), dict(op='balance', tenant='one', account='private'),
                 dict(op='balance', tenant='one', account='missing')]
        for invalid in cases:
            with self.subTest(request=invalid):
                result = self.cli(invalid)
                self.assertEqual(result.returncode, 2)
                self.assertEqual(result.stdout, '')
                self.assertEqual(json.loads(result.stderr), {'error': 'invalid request'})
                self.assertEqual(self.state(), before)
        result = self.cli(request, 'extra')
        self.assertEqual((result.returncode, result.stdout), (2, ''))
        self.sql("CREATE TRIGGER cli_fail BEFORE INSERT ON audit BEGIN "
                 "SELECT RAISE(ABORT,'secret SQL tenant=two'); END;")
        before = self.state()
        result = self.cli(dict(request, key='new'))
        self.assertEqual((result.returncode, result.stdout), (2, ''))
        self.assertEqual(json.loads(result.stderr), {'error': 'invalid request'})
        self.assertEqual(self.state(), before)


if __name__ == '__main__':
    unittest.main()
