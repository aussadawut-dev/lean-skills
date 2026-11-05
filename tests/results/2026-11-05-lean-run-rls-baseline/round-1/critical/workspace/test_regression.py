import concurrent.futures
from collections import Counter
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


class TransferTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(dir=Path(__file__).parent)
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / 'ledger.sqlite'
        vault.init_db(self.path)
        self.sql("INSERT INTO accounts VALUES ('one','a',100),('one','b',0),"
                 "('two','a',900),('two','b',20)")

    def sql(self, statement, parameters=()):
        with closing(sqlite3.connect(self.path)) as con, con:
            return con.execute(statement, parameters).fetchall()

    def state(self):
        # Include storage types and exact bytes, even for malformed hidden text.
        with closing(sqlite3.connect(self.path)) as con:
            con.text_factory = bytes
            schema = con.execute('SELECT type,name,tbl_name,sql FROM sqlite_schema '
                                 'ORDER BY type,name').fetchall()
            result = {'schema': schema}
            for (raw_name,) in con.execute("SELECT name FROM sqlite_schema WHERE type='table'"):
                name = raw_name.decode()
                quoted = '"' + name.replace('"', '""') + '"'
                fields = [row[1].decode() for row in con.execute('PRAGMA table_info(' + quoted + ')')]
                expressions = []
                for field in fields:
                    identifier = '"' + field.replace('"', '""') + '"'
                    expressions.extend(('typeof(' + identifier + ')', 'CAST(' + identifier + ' AS BLOB)'))
                result[name] = Counter(con.execute('SELECT ' + ','.join(expressions) + ' FROM ' + quoted))
            return result

    def move(self, **changes):
        request = dict(tenant='one', source='a', target='b', amount=10, key='k')
        request.update(changes)
        return vault.transfer(self.path, **request)

    def rejected_unchanged(self, call, exception=ValueError):
        before = self.state()
        with self.assertRaises(exception):
            call()
        self.assertEqual(self.state(), before)

    def trigger(self, body, when='BEFORE INSERT ON audit'):
        self.sql('CREATE TRIGGER probe ' + when + ' BEGIN ' + body + ' END')

    def cli(self, request, *args):
        payload = request if isinstance(request, str) else json.dumps(request)
        return subprocess.run([sys.executable, '-B', str(Path(__file__).with_name('app.py')),
                               str(self.path), payload, *args],
                              capture_output=True, text=True, check=False)

    def test_scoped_reads_replay_conflicts_and_reopen(self):
        self.assertEqual(vault.balance(self.path, 'one', 'a'), 100)
        receipt = self.move()
        expected = dict(tenant='one', key='k', source='a', target='b', amount=10)
        self.assertEqual(receipt, expected)
        before = self.state()
        receipt['tenant'] = 'tampered'
        vault.init_db(self.path)
        self.assertEqual(self.move(), expected)
        self.assertEqual(self.state(), before)
        for change in ({'amount': 11}, {'source': 'b', 'target': 'a'}, {'target': 'missing'}):
            with self.subTest(change=change):
                self.rejected_unchanged(lambda: self.move(**change))
        self.assertEqual(self.move(tenant='two')['tenant'], 'two')
        self.assertEqual(vault.balance(self.path, 'two', 'a'), 890)
        self.assertEqual(self.sql('SELECT count(*) FROM audit'), [(2,)])

    def test_malformed_inputs_and_account_boundaries(self):
        for field in ('tenant', 'source', 'target', 'key'):
            for value in ('', None, False, 12, [], {}):
                with self.subTest(field=field, value=value):
                    self.rejected_unchanged(lambda: self.move(**{field: value}))
        for amount in (True, False, 0, -1, 1.0, '10', None, [], float('nan'), 2**100):
            with self.subTest(amount=amount):
                self.rejected_unchanged(lambda: self.move(amount=amount))
        for changes in ({'source': 'b'}, {'source': 'absent'}, {'target': 'absent'},
                        {'amount': 101}, {'tenant': 'absent'}):
            self.rejected_unchanged(lambda: self.move(**changes))
        self.sql("INSERT INTO accounts VALUES ('two','private',123)")
        errors = []
        for name in ('private', 'missing'):
            with self.assertRaises(ValueError) as error:
                vault.balance(self.path, 'one', name)
            errors.append(str(error.exception))
            self.rejected_unchanged(lambda: self.move(target=name))
            self.rejected_unchanged(lambda: self.move(source=name))
        self.assertEqual(errors[0], errors[1])
        for tenant, name in (('', 'a'), ('one', ''), (None, 'a'), ('one', [])):
            with self.assertRaises(ValueError):
                vault.balance(self.path, tenant, name)

    def test_integer_limits_and_literal_identifiers(self):
        self.sql('UPDATE accounts SET balance=? WHERE tenant=? AND name=?', (2**63-1, 'one', 'b'))
        self.rejected_unchanged(self.move, sqlite3.IntegrityError)
        tenant = "one'\x00 tenant"
        self.sql('INSERT INTO accounts VALUES (?,?,?),(?,?,?)', (tenant, "s'", 5, tenant, 't', 0))
        self.assertEqual(vault.transfer(self.path, tenant, "s'", 't', 5, "k'\x00")['amount'], 5)
        self.assertEqual(vault.balance(self.path, tenant, 't'), 5)

    def test_failures_at_each_write_roll_back(self):
        points = ('AFTER UPDATE ON accounts WHEN NEW.name=\'a\'',
                  'AFTER UPDATE ON accounts WHEN NEW.name=\'b\'',
                  'AFTER INSERT ON transfers', 'BEFORE INSERT ON audit', 'AFTER INSERT ON audit')
        for point in points:
            with self.subTest(point=point):
                self.trigger("SELECT RAISE(ABORT,'private SQL failure');", point)
                self.rejected_unchanged(self.move, sqlite3.IntegrityError)
                self.sql('DROP TRIGGER probe')
        self.move()
        self.assertEqual(vault.balance(self.path, 'one', 'a'), 90)

    def test_publication_storage_failure_rolls_back(self):
        # This permitted cross-tenant uniqueness conflict appears only when
        # publishing to storage, after the isolated trigger execution succeeds.
        self.sql("INSERT INTO audit VALUES ('two','old','a','b',10)")
        self.sql('CREATE UNIQUE INDEX amount_unique ON audit(amount)')
        self.rejected_unchanged(self.move, sqlite3.IntegrityError)
        self.assertEqual(self.move(amount=11)['amount'], 11)

    def test_native_trigger_noops_replacements_and_views(self):
        self.sql('CREATE VIEW visible_balances AS SELECT tenant,name,balance FROM accounts')
        self.trigger("""
            INSERT OR IGNORE INTO accounts VALUES ('one','a',999);
            INSERT OR REPLACE INTO accounts SELECT * FROM visible_balances WHERE tenant='one' AND name='a';
            UPDATE accounts SET balance=balance WHERE tenant='one';
            SELECT CASE WHEN (SELECT balance FROM visible_balances WHERE name='a') != 90
                THEN RAISE(ABORT,'wrong visible balance') END;
        """)
        self.move()
        self.assertEqual(self.sql("SELECT name,balance FROM accounts WHERE tenant='one' ORDER BY name"),
                         [('a', 90), ('b', 10)])
        self.assertEqual(self.sql("SELECT count(*) FROM sqlite_schema WHERE type='trigger'"), [(1,)])
        self.sql('DROP TRIGGER probe')
        self.trigger("SELECT CASE WHEN (SELECT balance FROM visible_balances WHERE name='a') = 80 "
                     "THEN RAISE(ABORT,'native local failure') END;")
        self.rejected_unchanged(lambda: self.move(key='next'), sqlite3.IntegrityError)

    def test_check_constraints_use_tenant_local_counters(self):
        self.sql('DROP TABLE audit')
        self.sql('CREATE TABLE audit(tenant TEXT,key TEXT,source TEXT,target TEXT,'
                 'amount INTEGER CHECK(amount=10 AND last_insert_rowid()=1))')
        with closing(sqlite3.connect(self.path)) as original:
            for hidden in (False, True):
                with self.subTest(hidden=hidden):
                    other = Path(self.tmp.name) / f'checks-{hidden}.sqlite'
                    with closing(sqlite3.connect(other)) as clone:
                        original.backup(clone)
                        if hidden:
                            clone.execute("INSERT INTO transfers VALUES ('two','old','x','y',1)")
                            clone.commit()
                    previous = self.path
                    self.path = other
                    try:
                        self.assertEqual(self.move()['amount'], 10)
                        self.rejected_unchanged(lambda: self.move(key='fail', amount=11),
                                                sqlite3.IntegrityError)
                        self.assertEqual(self.sql("SELECT * FROM transfers WHERE tenant='two'"),
                                         [('two', 'old', 'x', 'y', 1)] if hidden else [])
                    finally:
                        self.path = previous

    def test_hidden_rows_cannot_influence_queries_or_counters(self):
        self.sql("INSERT INTO transfers VALUES ('one','history','a','b',1)")
        self.sql("INSERT INTO audit VALUES ('one','history','a','b',1),('one','history','a','b',1)")
        self.sql('CREATE VIEW visible_summary AS SELECT count(*) AS n, sum(balance) AS total FROM main.accounts')
        self.trigger("""
            SELECT CASE WHEN (SELECT n FROM visible_summary) != 2
                OR (SELECT total FROM visible_summary) != 100
                OR (SELECT count(*) FROM main.transfers) != 2
                OR (SELECT count(*) FROM main.audit) != 2
                OR total_changes() != 3
                OR EXISTS (SELECT 1 FROM accounts WHERE tenant IN (SELECT 'two'))
                OR EXISTS (SELECT tenant FROM accounts EXCEPT SELECT 'one')
                THEN RAISE(ABORT,'hidden data observed') END;
            UPDATE accounts SET balance=0 WHERE lower(tenant)='two';
            SELECT CASE WHEN changes()!=0 THEN RAISE(ABORT,'hidden update') END;
            DELETE FROM transfers WHERE tenant IN (WITH hidden(t) AS (VALUES('two')) SELECT t FROM hidden);
            SELECT CASE WHEN changes()!=0 THEN RAISE(ABORT,'hidden delete') END;
            DELETE FROM audit WHERE tenant!='one';
            SELECT CASE WHEN changes()!=0 THEN RAISE(ABORT,'hidden audit') END;
        """)
        # Same logical request across absent, ordinary, and malformed protected
        # data. Rebuild using a SQLite backup so visible data/schema are identical.
        with closing(sqlite3.connect(self.path)) as original:
            for variant in ('absent', 'ordinary', 'malformed'):
                with self.subTest(variant=variant):
                    other = Path(self.tmp.name) / (variant + '.sqlite')
                    with closing(sqlite3.connect(other)) as clone:
                        original.backup(clone)
                        clone.setconfig(sqlite3.SQLITE_DBCONFIG_ENABLE_TRIGGER, False)
                        clone.execute("DELETE FROM accounts WHERE tenant='two'")
                        if variant != 'absent':
                            clone.execute("INSERT INTO accounts VALUES ('two','secret',9999)")
                            clone.execute("INSERT INTO transfers VALUES ('two','secret','secret','hidden',999)")
                            clone.execute("INSERT INTO audit VALUES ('two','secret','secret','hidden',999)")
                        if variant == 'malformed':
                            clone.execute("UPDATE accounts SET name=CAST(x'ff' AS TEXT),balance=x'0001' WHERE tenant='two'")
                        clone.commit()
                        clone.setconfig(sqlite3.SQLITE_DBCONFIG_ENABLE_TRIGGER, True)
                    previous = self.path
                    self.path = other
                    try:
                        before = self.state()
                        self.assertEqual(self.move()['amount'], 10)
                        after = self.state()
                        # Required local changes are the only row differences.
                        for table in ('accounts', 'transfers', 'audit'):
                            self.assertEqual(Counter({r: n for r, n in before[table].items() if r[1] != b'one'}),
                                             Counter({r: n for r, n in after[table].items() if r[1] != b'one'}))
                    finally:
                        self.path = previous

    def test_cross_tenant_new_rows_and_extra_effects_reject(self):
        self.sql('CREATE TABLE counters (value INTEGER)')
        self.sql('INSERT INTO counters VALUES (0)')
        effects = (
            "INSERT INTO accounts VALUES ('two','new',1);",
            "INSERT INTO transfers VALUES ('two','new','a','b',1);",
            "INSERT INTO audit VALUES ('two','new','a','b',1);",
            "UPDATE accounts SET tenant='two' WHERE name='a';",
            "UPDATE counters SET value=value+1;",
            "INSERT INTO accounts VALUES ('one','extra',0);",
            "INSERT INTO audit SELECT * FROM audit WHERE key='k';",
            "DELETE FROM transfers WHERE key='k';",
            "UPDATE accounts SET balance=balance+1 WHERE name='a';",
            "SELECT RAISE(IGNORE);",
        )
        for effect in effects:
            with self.subTest(effect=effect):
                when = 'BEFORE INSERT ON audit' if effect == 'SELECT RAISE(IGNORE);' else 'AFTER INSERT ON audit'
                self.trigger(effect, when)
                self.rejected_unchanged(self.move, sqlite3.IntegrityError)
                self.sql('DROP TRIGGER probe')
        self.move()

    def parallel(self, requests):
        barrier = threading.Barrier(len(requests))
        def run(request):
            barrier.wait(timeout=10)
            try:
                return self.move(**request)
            except ValueError:
                return None
        with concurrent.futures.ThreadPoolExecutor(max_workers=len(requests)) as pool:
            return list(pool.map(run, requests))

    def test_concurrent_same_key_executes_once(self):
        replies = self.parallel([{} for _ in range(12)])
        self.assertTrue(all(reply == replies[0] for reply in replies))
        self.assertIsNotNone(replies[0])
        self.assertEqual(vault.balance(self.path, 'one', 'a'), 90)
        self.assertEqual(vault.balance(self.path, 'one', 'b'), 10)
        self.assertEqual(self.sql('SELECT count(*) FROM transfers'), [(1,)])
        self.assertEqual(self.sql('SELECT count(*) FROM audit'), [(1,)])
        before = self.state()
        self.assertEqual(self.move(), replies[0])
        self.assertEqual(self.state(), before)

    def test_concurrent_distinct_keys_never_overspend_or_lose_credits(self):
        replies = self.parallel([dict(key=f'k{i}', amount=7) for i in range(20)])
        self.assertEqual(sum(reply is not None for reply in replies), 14)
        self.assertEqual(vault.balance(self.path, 'one', 'a'), 2)
        self.assertEqual(vault.balance(self.path, 'one', 'b'), 98)
        self.assertEqual(self.sql('SELECT count(*) FROM audit'), [(14,)])
        self.assertEqual(self.sql('SELECT count(*) FROM transfers'), [(14,)])
        self.assertEqual(vault.balance(self.path, 'two', 'a'), 900)

    def test_cli_integrated_journey_and_generic_failures(self):
        request = dict(op='transfer', tenant='one', source='a', target='b', amount=10, key='cli')
        for operation, expected in ((dict(op='balance', tenant='one', account='a'), 100),
                                    (request, {k: v for k, v in request.items() if k != 'op'}),
                                    (request, {k: v for k, v in request.items() if k != 'op'}),
                                    (dict(op='balance', tenant='one', account='b'), 10)):
            result = self.cli(operation)
            self.assertEqual((result.returncode, result.stderr), (0, ''))
            self.assertEqual(json.loads(result.stdout), expected)
            self.assertEqual(len(result.stdout.splitlines()), 1)
        invalid = ('{', '[]', 'null', '{"op":"balance","op":"transfer"}',
                   dict(request, amount=True), dict(request, amount=11),
                   dict(request, key='new', amount=1000),
                   dict(op='balance', tenant='one', account='missing'),
                   dict(op='init_db'), dict(op='__dict__'), dict(op=[]),
                   dict(request, extra=True), dict(op='balance', tenant='one'))
        self.trigger("SELECT RAISE(ABORT,'SECRET SQL accounts two');")
        invalid += (dict(request, key='audit-failure'),)
        for operation in invalid:
            with self.subTest(operation=operation):
                before = self.state()
                result = self.cli(operation)
                self.assertEqual((result.returncode, result.stdout), (2, ''))
                self.assertEqual(json.loads(result.stderr), {'error': 'invalid request'})
                self.assertEqual(len(result.stderr.splitlines()), 1)
                self.assertEqual(self.state(), before)
        self.assertEqual(self.cli(request, 'extra').returncode, 2)
        self.sql('DROP TRIGGER probe')
        self.assertEqual(self.cli(dict(request, key='recovered')).returncode, 0)
        self.assertEqual(vault.balance(self.path, 'one', 'a'), 80)


if __name__ == '__main__':
    unittest.main()
