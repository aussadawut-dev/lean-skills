"""Native SQLite controls for the second bounded repair."""
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
CORE = ('accounts', 'transfers', 'audit')
REQUEST = dict(tenant='one', source='a', target='b', amount=10, key='k')


class RepairTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(dir=ROOT)
        self.addCleanup(self.tmp.cleanup)
        self.index = 0

    def database(self, script=''):
        self.index += 1
        path = Path(self.tmp.name) / f'{self.index}.db'
        vault.init_db(path)
        with closing(sqlite3.connect(path)) as con:
            con.executescript("INSERT INTO accounts(rowid,tenant,name,balance) VALUES "
                              "(10,'one','a',100),(20,'one','b',0);" + script)
        return path

    def query(self, path, sql):
        with closing(sqlite3.connect(path)) as con:
            return con.execute(sql).fetchall()

    def schema(self, path):
        return self.query(path, 'SELECT * FROM sqlite_schema ORDER BY name')

    def state(self, path):
        return {table: self.query(path, f'SELECT rowid,* FROM {table} ORDER BY rowid')
                for table in CORE}

    def native(self, path, key='k'):
        with closing(sqlite3.connect(path)) as con, con:
            con.execute("UPDATE accounts SET balance=balance-10 WHERE tenant='one' AND name='a'")
            con.execute("UPDATE accounts SET balance=balance+10 WHERE tenant='one' AND name='b'")
            con.execute("INSERT INTO transfers VALUES ('one',?,'a','b',10)", (key,))
            con.execute("INSERT INTO audit VALUES ('one',?,'a','b',10)", (key,))

    def invoke(self, path, interface='api', key='k'):
        request = dict(REQUEST, key=key)
        if interface == 'api':
            return vault.transfer(path, **request)
        result = subprocess.run([sys.executable, '-B', str(ROOT / 'app.py'),
                                 str(path), json.dumps(dict(request, op='transfer'))],
                                text=True, capture_output=True, timeout=15)
        self.assertEqual((result.returncode, result.stderr), (0, ''), result.stderr)
        return json.loads(result.stdout)

    def test_sparse_account_rowids_keep_native_references(self):
        script = """
            CREATE TABLE account_refs(account_row INTEGER PRIMARY KEY,last_balance);
            INSERT INTO account_refs VALUES(10,100),(20,0);
            CREATE TRIGGER refs AFTER UPDATE ON accounts BEGIN
              UPDATE account_refs SET last_balance=NEW.balance WHERE account_row=NEW.rowid;
            END;
        """
        oracle = self.database(script)
        self.native(oracle)
        expected = self.query(oracle, 'SELECT * FROM account_refs ORDER BY account_row')
        self.assertEqual(expected, [(10, 90), (20, 10)])
        for interface in ('api', 'cli'):
            for foreign in (None, 777, 778):
                with self.subTest(interface=interface, foreign=foreign):
                    extra = '' if foreign is None else (
                        "INSERT INTO accounts(rowid,tenant,name,balance) VALUES "
                        f"(15,'two','private',{foreign});")
                    path = self.database(script + extra)
                    schema = self.schema(path)
                    protected = self.query(path, "SELECT rowid,* FROM accounts WHERE tenant='two'")
                    self.assertEqual(self.invoke(path, interface), REQUEST)
                    self.assertEqual(self.query(path, 'SELECT * FROM account_refs ORDER BY account_row'), expected)
                    self.assertEqual(self.query(path, "SELECT rowid,* FROM accounts WHERE tenant='two'"), protected)
                    self.assertEqual(self.schema(path), schema)

    def test_case_renamed_core_tables_preserve_foreign_rows(self):
        for table in CORE:
            for interface in ('api', 'cli'):
                for foreign in (None, 777, 778):
                    with self.subTest(table=table, interface=interface, foreign=foreign):
                        extra = ''
                        if foreign is not None:
                            extra = (f"INSERT INTO accounts VALUES ('two','private',{foreign});"
                                     f"INSERT INTO transfers VALUES ('two','private','x','y',{foreign});"
                                     f"INSERT INTO audit VALUES ('two','private','x','y',{foreign});")
                        script = f"""
                            ALTER TABLE {table} RENAME TO staging;
                            ALTER TABLE staging RENAME TO {table.upper()};
                            CREATE TABLE observations(n);
                            CREATE TRIGGER hidden AFTER UPDATE ON accounts BEGIN
                              UPDATE accounts SET balance=0 WHERE tenant='two';
                              DELETE FROM transfers WHERE tenant='two';
                              DELETE FROM audit WHERE tenant='two';
                              INSERT INTO observations VALUES ((SELECT count(*) FROM accounts));
                            END;
                        """
                        path = self.database(extra + script)
                        schema = self.schema(path)
                        protected = {t: self.query(path, f"SELECT rowid,* FROM {t} WHERE tenant='two'") for t in CORE}
                        self.assertEqual(self.invoke(path, interface), REQUEST)
                        self.assertEqual(protected, {t: self.query(path, f"SELECT rowid,* FROM {t} WHERE tenant='two'") for t in CORE})
                        self.assertEqual(self.query(path, 'SELECT * FROM observations'), [(2,), (2,)])
                        self.assertEqual(self.schema(path), schema)
                        self.assertEqual(vault.balance(path, 'one', 'a'), 90)
                        before = self.state(path)
                        self.assertEqual(self.invoke(path, interface), REQUEST)
                        self.assertEqual(self.state(path), before)

    def test_fts_backing_state_matches_native_and_survives_reopen(self):
        base = """
            CREATE TABLE documents(id INTEGER PRIMARY KEY,body TEXT);
            INSERT INTO documents VALUES (1,'ledger entry');
            CREATE VIRTUAL TABLE search USING fts5(body,content='documents',content_rowid='id');
        """
        cases = {
            'external_content': ("INSERT INTO search(rowid,body) VALUES(1,'ledger entry');",
                                 "SELECT rowid FROM search WHERE search MATCH 'ledger'"),
            'configuration': ("INSERT INTO search(search,rank) VALUES('automerge',2);",
                              "SELECT v FROM search_config WHERE k='automerge'"),
            'readonly_vocabulary': ("INSERT INTO search(rowid,body) VALUES(1,'ledger entry');",
                                    'SELECT * FROM vocabulary'),
        }
        for name, (body, query) in cases.items():
            with self.subTest(case=name):
                script = base
                if name == 'readonly_vocabulary':
                    script += "CREATE VIRTUAL TABLE vocabulary USING fts5vocab(search,'row');"
                script += 'CREATE TRIGGER index_audit AFTER INSERT ON audit BEGIN ' + body + ' END;'
                oracle = self.database(script)
                path = self.database(script)
                schema = self.schema(path)
                self.native(oracle)
                self.invoke(path)
                self.assertEqual(self.query(path, query), self.query(oracle, query))
                self.assertTrue(self.query(oracle, query))
                self.assertEqual(self.schema(path), schema)
                before = self.state(path), self.query(path, query)
                self.invoke(path)  # Replay must not execute a virtual-table command again.
                self.assertEqual((self.state(path), self.query(path, query)), before)
                self.assertEqual(self.query(path, 'PRAGMA integrity_check'), [('ok',)])

    def test_fts_writes_roll_back_with_audit_failure(self):
        path = self.database("""
            CREATE VIRTUAL TABLE search USING fts5(body);
            CREATE TRIGGER index_audit BEFORE INSERT ON audit BEGIN
              INSERT INTO search(rowid,body) VALUES(1,'ledger entry');
            END;
            CREATE TRIGGER fail AFTER INSERT ON audit BEGIN
              SELECT RAISE(ABORT,'audit failure');
            END;
        """)
        before = self.state(path), self.schema(path)
        with self.assertRaises(sqlite3.IntegrityError):
            self.invoke(path)
        self.assertEqual((self.state(path), self.schema(path)), before)
        self.assertEqual(self.query(path, "SELECT rowid FROM search WHERE search MATCH 'ledger'"), [])

    def test_fts_commit_effects_are_verified_before_import(self):
        cases = (
            ("UPDATE accounts SET balance=balance+1 WHERE tenant='one' AND name='b';", ValueError),
            ("SELECT RAISE(ABORT,'backing store failure');", sqlite3.DatabaseError),
        )
        for body, error in cases:
            with self.subTest(body=body):
                path = self.database("""
                    CREATE VIRTUAL TABLE search USING fts5(body);
                    CREATE TRIGGER index_audit AFTER INSERT ON audit BEGIN
                      INSERT INTO search(rowid,body) VALUES(1,'ledger entry');
                    END;
                    CREATE TRIGGER at_sync AFTER INSERT ON search_data BEGIN
                """ + body + ' END;')
                before = self.state(path), self.schema(path)
                with self.assertRaises(error):
                    self.invoke(path)
                self.assertEqual((self.state(path), self.schema(path)), before)
                self.assertEqual(self.query(path, "SELECT rowid FROM search WHERE search MATCH 'ledger'"), [])

    def test_sparse_receipt_rowids_keep_native_references(self):
        # The account-only repair must not be mistaken for a complete solution
        # to native row references in every protected table.
        for table in ('transfers', 'audit'):
            with self.subTest(table=table):
                script = f"""
                    INSERT INTO {table}(rowid,tenant,key,source,target,amount)
                      VALUES(10,'one','history','a','b',1);
                    CREATE TABLE observations(history_row);
                    CREATE TRIGGER inspect BEFORE UPDATE ON accounts WHEN NEW.name='a' BEGIN
                      INSERT INTO observations SELECT rowid FROM {table} WHERE key='history';
                    END;
                """
                path = self.database(script)
                oracle = self.database(script)
                self.native(oracle)
                self.invoke(path)
                self.assertEqual(self.query(path, 'SELECT * FROM observations'),
                                 self.query(oracle, 'SELECT * FROM observations'))

    def sparse_history(self, table, fail=False):
        script = f"""
            INSERT INTO {table}(rowid,tenant,key,source,target,amount)
              VALUES(10,'one','history','a','b',1);
            CREATE TABLE receipt_refs(history_row INTEGER PRIMARY KEY,seen_balance);
            INSERT INTO receipt_refs VALUES(10,100);
            CREATE VIEW history_rows AS
              SELECT rowid AS history_row FROM {table} WHERE key='history';
            CREATE TRIGGER refresh_refs AFTER UPDATE ON accounts WHEN NEW.name='a' BEGIN
              UPDATE receipt_refs SET seen_balance=NEW.balance
                WHERE history_row IN (SELECT history_row FROM history_rows);
            END;
        """
        if fail:
            script += """
                CREATE TRIGGER reject_ref AFTER UPDATE ON receipt_refs BEGIN
                  SELECT RAISE(ABORT,'private reference failure');
                END;
            """
        return script

    def test_sparse_history_reference_writes_commit_and_replay(self):
        for table in ('transfers', 'audit'):
            script = self.sparse_history(table)
            oracle = self.database(script)
            self.native(oracle)
            query = (f'SELECT receipt_refs.history_row,{table}.tenant,{table}.key,seen_balance '
                     f'FROM receipt_refs JOIN {table} ON {table}.rowid=history_row')
            expected = self.query(oracle, query)
            self.assertEqual(expected, [(10, 'one', 'history', 90)])
            for interface in ('api', 'cli'):
                for foreign in (None, 777, 778):
                    with self.subTest(table=table, interface=interface, foreign=foreign):
                        extra = '' if foreign is None else f"""
                            INSERT INTO accounts(rowid,tenant,name,balance)
                              VALUES(15,'two','private',{foreign});
                            INSERT INTO transfers(rowid,tenant,key,source,target,amount)
                              VALUES(40,'two','history','x','y',{foreign});
                            INSERT INTO audit(rowid,tenant,key,source,target,amount)
                              VALUES(40,'two','history','x','y',{foreign});
                        """
                        path = self.database(script + extra)
                        schema = self.schema(path)
                        protected = {t: self.query(path, f"SELECT rowid,* FROM {t} WHERE tenant='two'")
                                     for t in CORE}
                        self.assertEqual(self.invoke(path, interface), REQUEST)
                        self.assertEqual(self.query(path, query), expected)
                        self.assertEqual((vault.balance(path, 'one', 'a'),
                                          vault.balance(path, 'one', 'b')), (90, 10))
                        for t in CORE:
                            self.assertEqual(self.query(path, f"SELECT rowid,* FROM {t} WHERE tenant='two'"),
                                             protected[t])
                            self.assertEqual(self.query(path, f"SELECT * FROM {t} WHERE tenant='one' ORDER BY 2"),
                                             self.query(oracle, f"SELECT * FROM {t} WHERE tenant='one' ORDER BY 2"))
                        self.assertEqual(self.schema(path), schema)
                        committed = self.state(path), self.query(path, query)
                        self.assertEqual(self.invoke(path, interface), REQUEST)
                        self.assertEqual((self.state(path), self.query(path, query)), committed)
                        self.assertEqual(self.query(path, 'PRAGMA integrity_check'), [('ok',)])

    def test_sparse_history_reference_failure_is_native_and_atomic(self):
        for table in ('transfers', 'audit'):
            script = self.sparse_history(table, fail=True)
            oracle = self.database(script)
            with self.assertRaises(sqlite3.IntegrityError):
                self.native(oracle)
            for interface in ('api', 'cli'):
                with self.subTest(table=table, interface=interface):
                    path = self.database(script)
                    before = self.state(path), self.query(path, 'SELECT * FROM receipt_refs'), self.schema(path)
                    if interface == 'api':
                        with self.assertRaises(sqlite3.IntegrityError):
                            self.invoke(path)
                    else:
                        result = subprocess.run(
                            [sys.executable, '-B', str(ROOT / 'app.py'), str(path),
                             json.dumps(dict(REQUEST, op='transfer'))],
                            text=True, capture_output=True, timeout=15)
                        self.assertEqual((result.returncode, result.stdout), (2, ''))
                        self.assertEqual(json.loads(result.stderr), {'error': 'invalid request'})
                    self.assertEqual((self.state(path), self.query(path, 'SELECT * FROM receipt_refs'),
                                      self.schema(path)), before)
                    self.assertEqual(self.state(path), self.state(oracle))

    def test_audit_references_resolve_after_foreign_rowid_collision(self):
        script = """
            CREATE TABLE audit_refs(audit_row INTEGER);
            CREATE TRIGGER remember AFTER INSERT ON audit BEGIN
              INSERT INTO audit_refs VALUES(NEW.rowid);
            END;
        """
        query = ("SELECT audit.key FROM audit_refs JOIN audit ON audit.rowid=audit_refs.audit_row "
                 "WHERE audit.tenant='one'")
        oracle = self.database(script)
        self.native(oracle)
        expected = self.query(oracle, query)
        self.assertEqual(expected, [('k',)])
        for interface in ('api', 'cli'):
            for foreign in (False, True):
                with self.subTest(interface=interface, foreign=foreign):
                    extra = '' if not foreign else (
                        "INSERT INTO audit(rowid,tenant,key,source,target,amount) "
                        "VALUES(1,'two','private','a','b',1);")
                    path = self.database(extra + script)
                    protected = self.query(path, "SELECT rowid,* FROM audit WHERE tenant='two'")
                    self.invoke(path, interface)
                    self.assertEqual(self.query(path, "SELECT rowid,* FROM audit WHERE tenant='two'"), protected)
                    self.assertEqual(self.query(path, query), expected)


if __name__ == '__main__':
    unittest.main()
