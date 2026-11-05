"""Native SQLite controls for the bounded rowid, encoding and name repair."""

from contextlib import closing
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest

import vault


ROOT = Path(__file__).resolve().parent
LEDGER = ('accounts', 'transfers', 'audit')


class RepairTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(dir=ROOT)
        self.addCleanup(self.tmp.cleanup)

    def database(self, name, *, encoding='UTF-8', hidden=None):
        path = Path(self.tmp.name) / name
        with closing(sqlite3.connect(path)) as con:
            con.execute(f"PRAGMA encoding='{encoding}'")
            # SQLite fixes the encoding when the first table is created.
            con.execute('CREATE TABLE encoding_marker(n)')
        vault.init_db(path)
        with closing(sqlite3.connect(path)) as con:
            con.executescript("""
                INSERT INTO accounts(rowid,tenant,name,balance)
                VALUES(10,'one','a',100),(20,'one','b',0);
            """)
            if hidden is not None:
                con.execute("INSERT INTO accounts VALUES('two','secret',?)", (hidden,))
                con.execute("INSERT INTO transfers VALUES('two','old','secret','other',1)")
                con.execute("INSERT INTO audit VALUES('two','old','secret','other',1)")
                con.commit()
        return path

    def sql(self, path, script):
        with closing(sqlite3.connect(path)) as con:
            con.executescript(script)

    def rows(self, path, sql):
        with closing(sqlite3.connect(path)) as con:
            return con.execute(sql).fetchall()

    def snapshot(self, path, tables=LEDGER):
        return {table: self.rows(path, f'SELECT rowid,* FROM "{table}" ORDER BY rowid')
                for table in tables}

    def send(self, path, key='k'):
        return vault.transfer(path, 'one', 'a', 'b', 10, key)

    def native(self, path, key='k'):
        # Independent SQL control; no private application helper is used.
        with closing(sqlite3.connect(path)) as con, con:
            con.execute("UPDATE accounts SET balance=balance-10 WHERE tenant='one' AND name='a'")
            con.execute("UPDATE accounts SET balance=balance+10 WHERE tenant='one' AND name='b'")
            con.execute('INSERT INTO transfers VALUES(?,?,?,?,?)', ('one', key, 'a', 'b', 10))
            con.execute('INSERT INTO audit VALUES(?,?,?,?,?)', ('one', key, 'a', 'b', 10))

    def cli(self, path, operation='transfer', **changes):
        request = (dict(op='balance', tenant='one', account='a') if operation == 'balance'
                   else dict(op='transfer', tenant='one', source='a', target='b', amount=10, key='cli'))
        request.update(changes)
        return subprocess.run([sys.executable, '-B', str(ROOT / 'app.py'), str(path), json.dumps(request)],
                              text=True, capture_output=True, timeout=20)

    def assert_cli_success(self, result):
        self.assertEqual((result.returncode, result.stderr), (0, ''), result.stderr)
        return json.loads(result.stdout)

    def test_rowid_policy_view_matches_native_failure_and_success(self):
        for hidden in (None, 777, 778):
            with self.subTest(hidden=hidden):
                native = self.database(f'native-policy-{hidden}', hidden=hidden)
                candidate = self.database(f'candidate-policy-{hidden}', hidden=hidden)
                for path in (native, candidate):
                    self.sql(path, """
                        CREATE TABLE frozen_accounts(account_row INTEGER PRIMARY KEY);
                        INSERT INTO frozen_accounts VALUES(10);
                        CREATE VIEW frozen AS SELECT a.tenant,a.name FROM accounts a
                            JOIN frozen_accounts f ON a.rowid=f.account_row;
                        CREATE TRIGGER policy BEFORE INSERT ON audit BEGIN
                            SELECT CASE WHEN EXISTS(SELECT 1 FROM frozen
                                WHERE tenant=new.tenant AND name=new.source)
                                THEN RAISE(ABORT,'frozen account') END;
                        END;
                    """)
                before = self.snapshot(candidate, (*LEDGER, 'frozen_accounts'))
                for operation, path in ((self.native, native), (self.send, candidate)):
                    with self.assertRaises(sqlite3.IntegrityError):
                        operation(path)
                    self.assertEqual(self.snapshot(path, (*LEDGER, 'frozen_accounts')), before)
                rejected = self.cli(candidate)
                self.assertEqual((rejected.returncode, rejected.stdout), (2, ''))
                self.assertEqual(json.loads(rejected.stderr), {'error': 'invalid request'})
                self.assertEqual(self.snapshot(candidate, (*LEDGER, 'frozen_accounts')), before)
                for path in (native, candidate):
                    self.sql(path, 'DELETE FROM frozen_accounts;')
                self.native(native)
                self.send(candidate)
                self.assertEqual(self.snapshot(candidate), self.snapshot(native))
                self.assertEqual(self.rows(candidate, 'SELECT rowid FROM accounts WHERE tenant=\'one\' ORDER BY rowid'),
                                 [(10,), (20,)])

    def test_fully_shadowed_auxiliary_rowids_keep_native_counter_sequence(self):
        observations = []
        for mode in ('native', 'candidate'):
            path = self.database(mode)
            self.sql(path, """
                CREATE TABLE side(rowid,_rowid_,oid);
                INSERT INTO side VALUES('delete',0,0),('keep',0,0);
                DELETE FROM side WHERE rowid='delete';
                CREATE VIEW side_view AS SELECT rowid,_rowid_,oid FROM side;
                CREATE TABLE seen(n);
                CREATE TRIGGER effect AFTER INSERT ON audit BEGIN
                    INSERT INTO side VALUES(new.key,0,0);
                    INSERT INTO seen VALUES(last_insert_rowid());
                END;
            """)
            operation = self.native if mode == 'native' else self.send
            for key in ('first', 'second', 'third'):
                operation(path, key)
            observations.append((self.rows(path, 'SELECT * FROM seen'),
                                 self.rows(path, 'SELECT * FROM side_view')))
            if mode == 'candidate':
                before = self.snapshot(path, (*LEDGER, 'side', 'seen'))
                self.send(path, 'third')
                self.assertEqual(self.snapshot(path, (*LEDGER, 'side', 'seen')), before)
                self.sql(path, "CREATE TRIGGER fail BEFORE INSERT ON audit BEGIN SELECT RAISE(ABORT,'fail'); END;")
                with self.assertRaises(sqlite3.IntegrityError):
                    self.send(path, 'failed')
                self.assertEqual(self.snapshot(path, (*LEDGER, 'side', 'seen')), before)
        self.assertEqual(observations[0], observations[1])
        self.assertEqual(observations[1][0], [(3,), (4,), (5,)])

    def test_encodings_match_native_and_support_cli_and_replay(self):
        for encoding in ('UTF-8', 'UTF-16le', 'UTF-16be'):
            with self.subTest(encoding=encoding):
                native = self.database('native-' + encoding, encoding=encoding, hidden=777)
                candidate = self.database('candidate-' + encoding, encoding=encoding, hidden=777)
                # Exercise non-ASCII TEXT and preserve an unrelated BLOB too.
                for path in (native, candidate):
                    self.sql(path, "INSERT INTO audit VALUES('one','é水','a','b',x'ff00');")
                self.assertEqual(vault.balance(candidate, 'one', 'a'), 100)
                self.native(native, 'é水')
                receipt = self.send(candidate, 'é水')
                self.assertEqual(self.snapshot(candidate), self.snapshot(native))
                before = self.snapshot(candidate)
                self.assertEqual(self.send(candidate, 'é水'), receipt)
                self.assertEqual(self.snapshot(candidate), before)
                self.assertEqual(self.assert_cli_success(self.cli(candidate, 'balance')), 90)
                self.assertEqual(self.assert_cli_success(self.cli(candidate))['key'], 'cli')
                self.native(native, 'cli')
                self.assertEqual(self.snapshot(candidate), self.snapshot(native))
                self.assertEqual(self.rows(candidate, 'PRAGMA encoding'), [(encoding,)])
                before = self.snapshot(candidate)
                rejected = self.cli(candidate, amount=11)
                self.assertEqual((rejected.returncode, rejected.stdout), (2, ''))
                self.assertEqual(json.loads(rejected.stderr), {'error': 'invalid request'})
                self.assertEqual(self.snapshot(candidate), before)

    def test_table_name_case_api_cli_and_foreign_noninterference(self):
        outcomes = []
        for hidden in (None, 777, 778):
            with self.subTest(hidden=hidden):
                native = self.database(f'native-case-{hidden}', hidden=hidden)
                candidate = self.database(f'candidate-case-{hidden}', hidden=hidden)
                for path in (native, candidate):
                    for old, new in (('accounts', 'ACCOUNTS'), ('transfers', 'TrAnSfErS'), ('audit', 'AUDIT')):
                        self.sql(path, f'ALTER TABLE {old} RENAME TO staging; ALTER TABLE staging RENAME TO {new};')
                    self.sql(path, 'CREATE VIEW local_accounts AS SELECT * FROM ACCOUNTS; '
                             'CREATE TABLE seen(n); CREATE TRIGGER observe AFTER INSERT ON AUDIT BEGIN '
                             'INSERT INTO seen SELECT count(*) FROM local_accounts; END;')
                foreign = {table: self.rows(candidate, f'SELECT rowid,* FROM {table} WHERE tenant=\'two\'')
                           for table in LEDGER}
                self.native(native)
                receipt = self.send(candidate)
                self.assertEqual(self.snapshot(candidate), self.snapshot(native))
                self.assertEqual(self.assert_cli_success(self.cli(candidate, 'balance')), 90)
                cli_receipt = self.assert_cli_success(self.cli(candidate))
                self.native(native, 'cli')
                self.assertEqual(self.snapshot(candidate), self.snapshot(native))
                self.assertEqual({table: self.rows(candidate, f'SELECT rowid,* FROM {table} WHERE tenant=\'two\'')
                                  for table in LEDGER}, foreign)
                outcomes.append((receipt, cli_receipt, self.rows(candidate, 'SELECT * FROM seen')))
        self.assertEqual(outcomes[0], outcomes[1])
        self.assertEqual(outcomes[1], outcomes[2])
        self.assertEqual(outcomes[0][2], [(2,), (2,)])

    def test_sparse_ledger_references_and_local_row_moves_survive_merge(self):
        path = self.database('row-moves', hidden=777)
        self.sql(path, """
            INSERT INTO transfers(rowid,tenant,key,source,target,amount) VALUES(10,'one','prior','a','b',1);
            INSERT INTO audit(rowid,tenant,key,source,target,amount) VALUES(20,'one','prior','a','b',1);
            CREATE TABLE references_to_rows(t,a);
            INSERT INTO references_to_rows VALUES(10,20);
            CREATE TABLE seen(t,a,b);
            CREATE TRIGGER observe AFTER INSERT ON audit BEGIN
                INSERT INTO seen SELECT
                    (SELECT count(*) FROM transfers JOIN references_to_rows r ON transfers.rowid=r.t),
                    (SELECT count(*) FROM audit JOIN references_to_rows r ON audit.rowid=r.a),
                    (SELECT rowid FROM accounts WHERE name='b');
                UPDATE accounts SET rowid=100 WHERE tenant=new.tenant AND name='b';
            END;
        """)
        for key in ('first', 'second'):
            self.send(path, key)
        self.assertEqual(self.rows(path, 'SELECT * FROM seen'), [(1, 1, 20), (1, 1, 100)])
        self.assertEqual(self.rows(path, "SELECT rowid FROM accounts WHERE tenant='one' AND name='b'"), [(100,)])

    def test_rowid_references_survive_interleaved_tenants_and_rollback(self):
        path = self.database('interleaved', hidden=777)
        self.sql(path, """
            INSERT INTO accounts VALUES('two','other',0);
            CREATE TABLE links(tenant,identity);
            CREATE TABLE seen(tenant,key,t,a,matches,tables);
            CREATE TRIGGER observe AFTER INSERT ON audit BEGIN
                INSERT INTO seen SELECT new.tenant,new.key,
                    (SELECT max(rowid) FROM transfers),new.rowid,
                    (SELECT count(*) FROM audit JOIN links ON audit.rowid=links.identity
                        WHERE links.tenant=new.tenant),
                    (SELECT count(*) FROM sqlite_schema WHERE type='table');
                INSERT INTO links VALUES(new.tenant,new.rowid);
            END;
        """)
        for tenant, key in (('one', 'first'), ('two', 'first'), ('one', 'second'), ('two', 'second')):
            foreign = {table: self.rows(path, f"SELECT rowid,* FROM {table} WHERE tenant!='{tenant}'")
                       for table in LEDGER}
            source, target = ('a', 'b') if tenant == 'one' else ('secret', 'other')
            vault.transfer(path, tenant, source, target, 10, key)
            self.assertEqual({table: self.rows(path, f"SELECT rowid,* FROM {table} WHERE tenant!='{tenant}'")
                              for table in LEDGER}, foreign)
        self.assert_cli_success(self.cli(path, key='third'))
        self.assertEqual(self.rows(path, 'SELECT * FROM seen'), [
            ('one', 'first', 1, 1, 0, 6), ('two', 'first', 2, 2, 0, 6),
            ('one', 'second', 2, 2, 1, 6), ('two', 'second', 3, 3, 1, 6),
            ('one', 'third', 3, 3, 2, 6),
        ])
        # An existing map must survive a storage failure after account writes.
        self.sql(path, "CREATE UNIQUE INDEX storage_fault ON audit(key) WHERE key='old';")
        before = self.snapshot(path, (*LEDGER, 'links', 'seen'))
        with self.assertRaises(sqlite3.IntegrityError):
            self.send(path, 'old')
        self.assertEqual(self.snapshot(path, (*LEDGER, 'links', 'seen')), before)
        self.send(path, 'fourth')
        self.assertEqual(self.rows(path, "SELECT t,a,matches FROM seen WHERE tenant='one' AND key='fourth'"),
                         [(4, 4, 3)])


if __name__ == '__main__':
    unittest.main()
