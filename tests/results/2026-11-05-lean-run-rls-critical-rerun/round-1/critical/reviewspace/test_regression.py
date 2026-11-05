"""Regression checks through the public API and real SQLite/CLI boundaries."""
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


class VaultCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(dir=ROOT)
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / 'vault.sqlite'
        vault.init_db(self.path)
        self.sql("""INSERT INTO accounts VALUES
                    ('one','a',100),('one','b',0),
                    ('two','a',500),('two','b',20);""")

    def sql(self, script):
        with closing(sqlite3.connect(self.path)) as con, con:
            con.executescript(script)

    def query(self, sql, args=()):
        with closing(sqlite3.connect(self.path)) as con:
            return con.execute(sql, args).fetchall()

    def state(self):
        # Compare storage types and multiplicities, not physical rowids.
        with closing(sqlite3.connect(self.path)) as con:
            tables = con.execute("SELECT name FROM sqlite_schema WHERE type='table' ORDER BY name").fetchall()
            result = {}
            for (table,) in tables:
                quoted = '"' + table.replace('"', '""') + '"'
                columns = [row[1] for row in con.execute(f'PRAGMA table_info({quoted})')]
                fields = ','.join('typeof("{0}"),"{0}"'.format(col.replace('"', '""')) for col in columns)
                con.text_factory = bytes
                result[table] = Counter(con.execute(f'SELECT {fields} FROM {quoted}'))
                con.text_factory = str
            return result

    def transfer(self, **overrides):
        args = dict(tenant='one', source='a', target='b', amount=10, key='k')
        args.update(overrides)
        return vault.transfer(self.path, **args)

    def assert_unchanged(self, action, error=ValueError):
        before = self.state()
        with self.assertRaises(error):
            action()
        self.assertEqual(before, self.state())

    def cli(self, request, *extra):
        encoded = request if isinstance(request, str) else json.dumps(request)
        return subprocess.run([sys.executable, '-B', str(ROOT / 'app.py'),
                               str(self.path), encoded, *extra], cwd=ROOT,
                              capture_output=True, text=True, check=False)


class VaultTests(VaultCase):
    def test_tenant_reads_writes_and_reopen(self):
        self.assertEqual(100, vault.balance(self.path, 'one', 'a'))
        self.assertEqual(500, vault.balance(self.path, 'two', 'a'))
        receipt = self.transfer()
        self.assertEqual(dict(tenant='one', source='a', target='b', amount=10, key='k'), receipt)
        self.assertEqual([('one', 'a', 90), ('one', 'b', 10), ('two', 'a', 500), ('two', 'b', 20)],
                         self.query('SELECT * FROM accounts ORDER BY tenant,name'))
        before = self.state()
        vault.init_db(self.path)
        self.assertEqual(before, self.state())
        self.assertEqual(receipt, self.transfer())
        self.assertEqual(before, self.state())
        receipt['source'] = 'changed'
        self.assertEqual('a', self.transfer()['source'])

    def test_missing_and_inaccessible_are_identical(self):
        self.sql("INSERT INTO accounts VALUES ('two','private',700)")
        errors = []
        for account in ('missing', 'private'):
            with self.assertRaises(ValueError) as raised:
                vault.balance(self.path, 'one', account)
            errors.append(str(raised.exception))
            for field in ('source', 'target'):
                self.assert_unchanged(lambda: self.transfer(**{field: account}))
        self.assertEqual(errors[0], errors[1])

    def test_invalid_fields_are_rejected_without_writes(self):
        cases = [{field: value} for field in ('tenant', 'source', 'target', 'key')
                 for value in ('', None, 12, True, [], {}, b'one', '\ud800')]
        cases += [{'amount': value} for value in (0, -1, True, False, 1.0, '1', None, [], {}, 10**100)]
        cases += [{'target': 'a'}, {'amount': 101}]
        for case in cases:
            with self.subTest(case=case):
                self.assert_unchanged(lambda: self.transfer(**case))
        for tenant, account in (('', 'a'), ('one', ''), (None, 'a'), ('one', 1)):
            with self.subTest(tenant=tenant, account=account), self.assertRaises(ValueError):
                vault.balance(self.path, tenant, account)

    def test_tenant_key_scope_and_conflicts(self):
        first = self.transfer(amount=100)
        before = self.state()
        self.assertEqual(first, self.transfer(amount=100))
        self.assertEqual(before, self.state())
        for overrides in ({'amount': 10}, {'source': 'b', 'target': 'a'}, {'target': 'missing'}):
            self.assert_unchanged(lambda: self.transfer(**overrides))
        other = self.transfer(tenant='two', amount=20)
        self.assertEqual('two', other['tenant'])
        self.assertEqual(480, vault.balance(self.path, 'two', 'a'))
        self.assertEqual(2, self.query('SELECT count(*) FROM audit')[0][0])

    def test_cached_receipt_types_are_not_confused(self):
        self.sql("INSERT INTO transfers VALUES ('one','k',X'61','b',10)")
        self.assert_unchanged(self.transfer)

    def test_unicode_and_nonempty_keys(self):
        self.sql("INSERT INTO accounts VALUES ('組','源',9),('組','先',1)")
        receipt = self.transfer(tenant='組', source='源', target='先', amount=4, key=' \u0000鍵')
        self.assertEqual(5, vault.balance(self.path, '組', '先'))
        self.assertEqual(receipt, self.transfer(tenant='組', source='源', target='先', amount=4, key=' \u0000鍵'))

    def test_audit_failure_rolls_back_all_tables_and_side_effects(self):
        self.sql("""CREATE TABLE effects(value);
          CREATE TRIGGER side_effect AFTER UPDATE ON accounts BEGIN
            INSERT INTO effects VALUES(NEW.balance);
          END;
          CREATE TRIGGER fail_audit BEFORE INSERT ON audit BEGIN
            SELECT RAISE(ABORT,'private SQL detail');
          END;""")
        self.assert_unchanged(self.transfer, sqlite3.IntegrityError)
        self.assertEqual(2, self.query("SELECT count(*) FROM sqlite_schema WHERE type='trigger'")[0][0])
        self.sql('DROP TRIGGER fail_audit')
        self.transfer()
        self.assertEqual([(90,), (10,)], self.query('SELECT * FROM effects'))

    def test_storage_failure_after_receipt_is_atomic(self):
        self.sql("""CREATE TABLE impossible(value INTEGER CHECK(value > 0));
          CREATE TRIGGER fail AFTER INSERT ON transfers BEGIN
            INSERT INTO impossible VALUES(-1);
          END;""")
        self.assert_unchanged(self.transfer, sqlite3.IntegrityError)

    def test_final_effect_guard_rejects_extra_or_missing_effects(self):
        cases = [
            "UPDATE accounts SET balance=balance+1 WHERE name='b';",
            "INSERT INTO accounts VALUES ('one','extra',1);",
            "DELETE FROM accounts WHERE name='b';",
            "INSERT INTO audit VALUES (NEW.tenant,'extra',NEW.source,NEW.target,NEW.amount);",
            "DELETE FROM audit WHERE key='history';",
            "DELETE FROM transfers WHERE key=NEW.key;",
            "INSERT INTO transfers VALUES ('two','extra','a','b',1);",
            "INSERT INTO accounts VALUES ('two','extra',1);",
            "INSERT INTO audit VALUES ('two','extra','a','b',1);",
            "UPDATE audit SET amount=CAST(amount AS BLOB) WHERE key=NEW.key;",
        ]
        self.sql("INSERT INTO audit VALUES ('one','history','a','b',3),('one','history','a','b',3)")
        for body in cases:
            with self.subTest(body=body):
                self.sql(f'CREATE TRIGGER corrupt AFTER INSERT ON audit BEGIN {body} END;')
                self.assert_unchanged(self.transfer)
                self.sql('DROP TRIGGER corrupt')
        for table in ('accounts', 'transfers', 'audit'):
            operation = 'UPDATE' if table == 'accounts' else 'INSERT'
            with self.subTest(ignored=table):
                self.sql(f'CREATE TRIGGER skip BEFORE {operation} ON {table} BEGIN SELECT RAISE(IGNORE); END;')
                self.assert_unchanged(self.transfer)
                self.sql('DROP TRIGGER skip')

    def test_native_transient_writes_ignored_conflicts_and_row_moves(self):
        self.sql("""CREATE TABLE effects(value);
          INSERT INTO transfers VALUES ('one','old','a','b',1);
          INSERT INTO audit VALUES ('one','old','a','b',1),('one','old','a','b',1);
          CREATE TRIGGER native AFTER INSERT ON audit BEGIN
            UPDATE accounts SET balance=balance+5;
            UPDATE accounts SET balance=balance-5;
            INSERT OR IGNORE INTO accounts VALUES ('one','a',999);
            INSERT OR IGNORE INTO transfers VALUES ('one','old','a','b',99);
            UPDATE audit SET rowid=rowid+100 WHERE key='old';
            INSERT INTO effects VALUES((SELECT sum(balance) FROM accounts));
          END;""")
        self.transfer()
        self.assertEqual([(100,)], self.query('SELECT * FROM effects'))
        self.assertEqual(3, self.query("SELECT count(*) FROM audit WHERE tenant='one'")[0][0])

    def test_native_views_and_instead_of_trigger(self):
        self.sql("""CREATE TABLE effects(value);
          CREATE VIEW visible_accounts AS SELECT tenant,name,balance FROM accounts;
          CREATE VIEW event_sink AS SELECT value FROM effects;
          CREATE TRIGGER route INSTEAD OF INSERT ON event_sink BEGIN
            INSERT INTO effects VALUES (NEW.value);
          END;
          CREATE TRIGGER observe AFTER INSERT ON audit BEGIN
            INSERT INTO event_sink SELECT sum(balance) FROM visible_accounts;
          END;""")
        self.transfer()
        self.assertEqual([(100,)], self.query('SELECT * FROM effects'))

    def _parallel(self, requests):
        barrier = threading.Barrier(len(requests))
        def call(overrides):
            barrier.wait(timeout=10)
            try:
                return self.transfer(**overrides)
            except ValueError:
                return 'rejected'
        with ThreadPoolExecutor(max_workers=len(requests)) as workers:
            return list(workers.map(call, requests))

    def test_concurrent_duplicate_executes_once(self):
        results = self._parallel([{} for _ in range(10)])
        self.assertTrue(all(result == results[0] for result in results))
        self.assertIsInstance(results[0], dict)
        self.assertEqual(90, vault.balance(self.path, 'one', 'a'))
        self.assertEqual([(1,)], self.query('SELECT count(*) FROM transfers'))
        self.assertEqual([(1,)], self.query('SELECT count(*) FROM audit'))
        before = self.state()
        self.assertEqual(results[0], self.transfer())
        self.assertEqual(before, self.state())

    def test_concurrent_distinct_keys_never_overspend_or_lose_credit(self):
        results = self._parallel([{'key': str(i), 'amount': 30} for i in range(8)])
        self.assertEqual(3, sum(isinstance(result, dict) for result in results))
        self.assertEqual(10, vault.balance(self.path, 'one', 'a'))
        self.assertEqual(90, vault.balance(self.path, 'one', 'b'))
        self.assertEqual([(3,)], self.query('SELECT count(*) FROM audit'))

    def test_concurrent_conflicting_payload_has_one_winner(self):
        results = self._parallel([{'amount': amount} for amount in (10, 20)])
        self.assertEqual(1, results.count('rejected'))
        winner = next(value for value in results if isinstance(value, dict))
        self.assertEqual(winner['amount'], vault.balance(self.path, 'one', 'b'))
        self.assertEqual([(1,)], self.query('SELECT count(*) FROM audit'))

    def test_cli_integrated_journey(self):
        request = dict(op='transfer', tenant='one', source='a', target='b', amount=25, key='cli')
        first = self.cli(request)
        self.assertEqual((0, ''), (first.returncode, first.stderr))
        self.assertEqual(1, len(first.stdout.splitlines()))
        receipt = json.loads(first.stdout)
        self.assertEqual(25, receipt['amount'])
        before = self.state()
        replay = self.cli(request)
        self.assertEqual(receipt, json.loads(replay.stdout))
        self.assertEqual(before, self.state())
        read = self.cli(dict(op='balance', tenant='one', account='b'))
        self.assertEqual((0, '25\n', ''), (read.returncode, read.stdout, read.stderr))
        for invalid in (dict(request, amount=26), dict(request, key='new', target='private')):
            result = self.cli(invalid)
            self.assertEqual((2, ''), (result.returncode, result.stdout))
            self.assertEqual({'error': 'invalid request'}, json.loads(result.stderr))
            self.assertEqual(before, self.state())
        other = self.cli(dict(request, tenant='two'))
        self.assertEqual('two', json.loads(other.stdout)['tenant'])

    def test_cli_invalid_inputs_and_storage_failure_are_generic(self):
        inputs = ['{', '[]', 'null', '1', '{}', '{"op":"balance","op":"transfer"}',
                  '{"op":"transfer","amount":NaN}',
                  dict(op='init_db'), dict(op='__dict__'),
                  dict(op='balance', tenant='one'),
                  dict(op='balance', tenant='one', account='a', extra=1),
                  dict(op='balance', tenant='one', account='missing'),
                  dict(op='transfer', tenant='one', source='a', target='b', amount=True, key='k')]
        before = self.state()
        for request in inputs:
            with self.subTest(request=request):
                result = self.cli(request)
                self.assertEqual((2, ''), (result.returncode, result.stdout))
                self.assertEqual({'error': 'invalid request'}, json.loads(result.stderr))
                self.assertEqual(before, self.state())
        self.sql("CREATE TRIGGER fail BEFORE INSERT ON audit BEGIN SELECT RAISE(ABORT,'two secret SQL'); END")
        result = self.cli(dict(op='transfer', tenant='one', source='a', target='b', amount=1, key='k'))
        self.assertEqual((2, ''), (result.returncode, result.stdout))
        self.assertEqual({'error': 'invalid request'}, json.loads(result.stderr))
        self.assertEqual(before, self.state())
        result = self.cli('{}', 'extra')
        self.assertEqual((2, ''), (result.returncode, result.stdout))


class IsolationTests(VaultCase):
    def test_trigger_counters_match_native_sqlite(self):
        script = """CREATE TABLE observed(stage,rows_seen,changed,total,lastid);
          CREATE VIEW account_view AS SELECT * FROM accounts;
          CREATE TRIGGER before_debit BEFORE UPDATE ON accounts BEGIN
            INSERT INTO observed SELECT 'account',count(*),changes(),total_changes(),last_insert_rowid()
              FROM account_view;
          END;
          CREATE TRIGGER after_receipt AFTER INSERT ON transfers BEGIN
            INSERT INTO observed SELECT 'receipt',count(*),changes(),total_changes(),last_insert_rowid()
              FROM transfers;
          END;
          CREATE TRIGGER after_audit AFTER INSERT ON audit BEGIN
            INSERT INTO observed SELECT 'audit',count(*),changes(),total_changes(),last_insert_rowid()
              FROM audit;
          END;"""
        self.sql(script)
        native = Path(self.tmp.name) / 'native.sqlite'
        vault.init_db(native)
        with closing(sqlite3.connect(native)) as con, con:
            con.executescript("INSERT INTO accounts VALUES ('one','a',100),('one','b',0);" + script)
        # A fresh connection and ordinary SQLite statements are the reference
        # for counters, views and nested trigger effects over this tenant.
        with closing(sqlite3.connect(native)) as con, con:
            con.execute('BEGIN IMMEDIATE')
            con.execute("UPDATE accounts SET balance=balance-10 WHERE tenant='one' AND name='a'")
            con.execute("UPDATE accounts SET balance=balance+10 WHERE tenant='one' AND name='b'")
            con.execute("INSERT INTO transfers VALUES ('one','k','a','b',10)")
            con.execute("INSERT INTO audit VALUES ('one','k','a','b',10)")
            expected = con.execute('SELECT * FROM observed').fetchall()
        self.transfer()
        self.assertEqual(expected, self.query('SELECT * FROM observed'))

    def test_noninterference_of_hidden_values_counts_and_types(self):
        results = []
        for variant in ('absent', 'ordinary', 'malformed'):
            with self.subTest(variant=variant):
                self.sql('DELETE FROM accounts; DELETE FROM transfers; DELETE FROM audit;')
                self.sql("""INSERT INTO accounts VALUES ('one','a',100),('one','b',0);
                  INSERT INTO transfers VALUES ('one','history','a','b',2);
                  INSERT INTO audit VALUES ('one','history','a','b',2),('one','history','a','b',2);""")
                if variant == 'ordinary':
                    self.sql("""INSERT INTO accounts(rowid,tenant,name,balance) VALUES (900,'two','a',999);
                      INSERT INTO transfers(rowid,tenant,key,source,target,amount) VALUES (800,'two','k','a','b',777);
                      INSERT INTO audit(rowid,tenant,key,source,target,amount) VALUES (700,'two','secret','a','b',777);""")
                elif variant == 'malformed':
                    self.sql("""INSERT INTO accounts VALUES ('two',X'FF',X'0011'),(NULL,CAST(X'FF' AS TEXT),NULL);
                      INSERT INTO transfers VALUES ('two','k',CAST(X'FF' AS TEXT),X'FF',NULL);
                      INSERT INTO audit VALUES ('two',NULL,X'FF',CAST(X'FF' AS TEXT),X'00'),
                        ('two',NULL,X'FF',CAST(X'FF' AS TEXT),X'00');""")
                self.sql("""CREATE TABLE observation(stage,ac,tr,au,changed,total,lastid);
                  CREATE VIEW tenant_rows AS SELECT * FROM accounts;
                  CREATE TRIGGER account_observer BEFORE UPDATE ON accounts BEGIN
                    INSERT INTO observation SELECT 'account',
                      (SELECT count(*) FROM tenant_rows),(SELECT count(*) FROM transfers),
                      (SELECT count(*) FROM audit),changes(),total_changes(),last_insert_rowid();
                    UPDATE accounts SET balance=0 WHERE tenant='two';
                    DELETE FROM transfers WHERE tenant='two';
                    DELETE FROM audit WHERE tenant IS NULL OR tenant='two';
                  END;
                  CREATE TRIGGER receipt_observer AFTER INSERT ON transfers BEGIN
                    INSERT INTO observation SELECT 'receipt',
                      (SELECT count(*) FROM accounts),(SELECT count(*) FROM transfers),
                      (SELECT count(*) FROM audit),changes(),total_changes(),last_insert_rowid();
                  END;""")
                protected = self.state()
                receipt = self.transfer()
                after = self.state()
                for table in ('accounts', 'transfers', 'audit'):
                    def others(rows):
                        return Counter({row: count for row, count in rows.items()
                                        if row[:2] != (b'text', b'one')})
                    self.assertEqual(others(protected[table]), others(after[table]))
                results.append((receipt, self.query('SELECT * FROM observation')))
                self.sql('DROP TRIGGER account_observer; DROP TRIGGER receipt_observer; DROP VIEW tenant_rows; DROP TABLE observation;')
        self.assertEqual(results[0], results[1])
        self.assertEqual(results[0], results[2])

    def test_hidden_values_cannot_control_trigger_outcome(self):
        self.sql("""CREATE TRIGGER policy BEFORE INSERT ON audit BEGIN
          SELECT CASE WHEN EXISTS(SELECT 1 FROM accounts WHERE balance>=500)
            THEN RAISE(ABORT,'secret') END;
        END;""")
        self.transfer()
        self.sql("UPDATE accounts SET balance=500 WHERE tenant='one' AND name='b'")
        self.assert_unchanged(lambda: self.transfer(key='fail'), sqlite3.IntegrityError)


if __name__ == '__main__':
    unittest.main()
