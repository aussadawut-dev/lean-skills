"""Public-interface regressions for the bounded projection repair."""

from contextlib import closing
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest

import vault


REQUEST = dict(tenant='one', source='a', target='b', amount=10, key='k')


class ProjectionRepairTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(dir=Path(__file__).parent)
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.next_db = 0

    def database(self, setup='', *, encoding='UTF-8', hidden=False, journal='DELETE'):
        self.next_db += 1
        path = self.root / (str(self.next_db) + '.sqlite')
        with closing(sqlite3.connect(path)) as con:
            con.execute("PRAGMA encoding='" + encoding + "'")
            con.execute('PRAGMA journal_mode=' + journal)
            con.execute('CREATE TABLE encoding_anchor(value)')
        vault.init_db(path)
        with closing(sqlite3.connect(path)) as con, con:
            con.execute("INSERT INTO accounts(rowid,tenant,name,balance) VALUES "
                        "(17,'one','a',100),(31,'one','b',0)")
            if hidden:
                con.execute("INSERT INTO accounts VALUES ('two','private-account',8675309)")
                con.execute("INSERT INTO transfers VALUES ('two','old','x','y',1)")
                con.execute("INSERT INTO audit VALUES ('two','old','temporary','spare',1)")
            con.executescript(setup)
        return path

    def sql(self, path, sql):
        with closing(sqlite3.connect(path)) as con, con:
            return con.execute(sql).fetchall()

    def snapshot(self, path):
        with closing(sqlite3.connect(path)) as con:
            con.text_factory = bytes
            result = {'schema': con.execute(
                'SELECT rowid,type,name,tbl_name,sql FROM sqlite_schema ORDER BY rowid').fetchall()}
            for (raw_name,) in con.execute("SELECT name FROM sqlite_schema WHERE type='table'"):
                name = raw_name.decode()
                quoted = '"' + name.replace('"', '""') + '"'
                fields = [row[1].decode() for row in con.execute('PRAGMA table_xinfo(' + quoted + ')')]
                expressions = []
                for field in fields:
                    column = '"' + field.replace('"', '""') + '"'
                    expressions.extend(('typeof(' + column + ')', 'CAST(' + column + ' AS BLOB)'))
                result[name] = con.execute('SELECT ' + ','.join(expressions) + ' FROM ' + quoted).fetchall()
            return result

    def native(self, path):
        # A new native connection, with the same four writes and initial counters.
        with closing(sqlite3.connect(path)) as con, con:
            con.execute('BEGIN IMMEDIATE')
            con.execute("UPDATE accounts SET balance=90 WHERE tenant='one' AND name='a'")
            con.execute("UPDATE accounts SET balance=10 WHERE tenant='one' AND name='b'")
            for table in ('transfers', 'audit'):
                con.execute('INSERT INTO ' + table +
                            "(tenant,key,source,target,amount) VALUES ('one','k','a','b',10)")

    def call(self, path, interface='api'):
        if interface == 'api':
            return vault.transfer(path, **REQUEST)
        result = subprocess.run([sys.executable, '-B', str(Path(__file__).with_name('app.py')),
                                 str(path), json.dumps(dict(REQUEST, op='transfer'))],
                                capture_output=True, text=True, check=False)
        if result.returncode:
            self.assertEqual((result.returncode, result.stdout), (2, ''))
            self.assertEqual(json.loads(result.stderr), {'error': 'invalid request'})
            raise sqlite3.IntegrityError('CLI rejected transfer')
        self.assertEqual(result.stderr, '')
        self.assertEqual(len(result.stdout.splitlines()), 1)
        return json.loads(result.stdout)

    def reject(self, path, interface='api', error=sqlite3.IntegrityError):
        before = self.snapshot(path)
        with self.assertRaises(error) as rejected:
            self.call(path, interface)
        self.assertEqual(self.snapshot(path), before)
        return rejected.exception

    def matches_native(self, setup, *, succeeds=True, encoding='UTF-8'):
        native = self.database(setup, encoding=encoding)
        candidate = self.database(setup, encoding=encoding)
        if succeeds:
            self.native(native)
            self.assertEqual(self.call(candidate), REQUEST)
            self.assertEqual(self.snapshot(candidate), self.snapshot(native))
        else:
            before = self.snapshot(native)
            with self.assertRaises(sqlite3.IntegrityError) as rejected:
                self.native(native)
            self.assertEqual(self.snapshot(native), before)
            self.assertEqual(str(self.reject(candidate)), str(rejected.exception))

    def test_trigger_installation_order_matches_native_in_both_directions(self):
        for skip_name, fail_name in (('z_skip', 'a_failure'), ('a_skip', 'z_failure')):
            skip = 'CREATE TRIGGER ' + skip_name + ' AFTER INSERT ON audit BEGIN SELECT RAISE(IGNORE); END;'
            fail = 'CREATE TRIGGER ' + fail_name + " AFTER INSERT ON audit BEGIN SELECT RAISE(ABORT,'audit veto'); END;"
            for setup, succeeds in ((skip + fail, False), (fail + skip, True)):
                with self.subTest(skip_name=skip_name, succeeds=succeeds):
                    self.matches_native(setup, succeeds=succeeds)

    def test_identifier_case_cannot_expose_any_protected_table(self):
        for spelling in ('tenant', 'Tenant', 'TENANT'):
            for hidden in (False, True):
                for interface in ('api', 'cli'):
                    with self.subTest(spelling=spelling, hidden=hidden, interface=interface):
                        setup = ''
                        if spelling != 'tenant':
                            setup += ''.join('ALTER TABLE ' + table + ' RENAME COLUMN tenant TO ' + spelling + ';'
                                             for table in ('accounts', 'transfers', 'audit'))
                        setup += """
                            CREATE TRIGGER probe BEFORE INSERT ON audit BEGIN
                                SELECT CASE WHEN EXISTS(SELECT 1 FROM accounts WHERE tenant='two')
                                  THEN RAISE(ABORT,(SELECT name || ':' || balance FROM accounts WHERE tenant='two')) END;
                                SELECT CASE WHEN EXISTS(SELECT 1 FROM transfers WHERE tenant='two')
                                  OR EXISTS(SELECT 1 FROM audit WHERE tenant='two')
                                  THEN RAISE(ABORT,'foreign history visible') END;
                            END;
                        """
                        path = self.database(setup, hidden=hidden)
                        before = self.snapshot(path)
                        self.assertEqual(self.call(path, interface), REQUEST)
                        after = self.snapshot(path)
                        self.assertEqual(after['schema'], before['schema'])
                        for table in ('accounts', 'transfers', 'audit'):
                            self.assertEqual([row for row in after[table] if row[1] == b'two'],
                                             [row for row in before[table] if row[1] == b'two'])
                        self.assertEqual(vault.balance(path, 'one', 'a'), 90)
                        self.assertEqual(self.call(path, interface), REQUEST)
                        self.assertEqual(self.snapshot(path), after)

    def test_storage_and_effect_rejections_have_database_exception_type(self):
        for body, when in (("SELECT RAISE(IGNORE);", 'BEFORE'),
                           ("INSERT INTO accounts VALUES ('one','extra',0);", 'AFTER'),
                           ("INSERT INTO audit VALUES ('two','new','a','b',1);", 'AFTER')):
            with self.subTest(body=body):
                path = self.database('CREATE TRIGGER probe ' + when + ' INSERT ON audit BEGIN ' + body + ' END;')
                self.reject(path)
        path = self.database("UPDATE accounts SET balance=9223372036854775807 WHERE name='b';")
        self.reject(path)
        insufficient = self.database("UPDATE accounts SET balance=1 WHERE name='a';")
        self.reject(insufficient, error=ValueError)

    def test_ignored_account_writes_have_database_exception_type(self):
        for name in ('a', 'b'):
            with self.subTest(name=name):
                path = self.database("CREATE TRIGGER ignored BEFORE UPDATE ON accounts WHEN OLD.name='" + name +
                                     "' BEGIN SELECT RAISE(IGNORE); END;")
                self.reject(path)

    def test_original_hidden_rowids_and_view_shape_match_native(self):
        for alias in ('rowid', '_rowid_', 'oid'):
            for succeeds in (True, False):
                with self.subTest(alias=alias, succeeds=succeeds):
                    expected = 17 if succeeds else 99
                    self.matches_native("""
                        INSERT INTO transfers(rowid,tenant,key,source,target,amount) VALUES (23,'one','old','a','b',1);
                        INSERT INTO audit(rowid,tenant,key,source,target,amount) VALUES (43,'one','old','a','b',1);
                        CREATE VIEW star_rows AS SELECT * FROM accounts;
                        CREATE TRIGGER probe BEFORE INSERT ON audit BEGIN
                            SELECT CASE WHEN (SELECT """ + alias + """ FROM accounts WHERE name='a') != """ + str(expected) + """
                                OR (SELECT """ + alias + """ FROM transfers WHERE key='old') != 23
                                OR (SELECT """ + alias + """ FROM audit WHERE key='old') != 43
                                OR (SELECT count(*) FROM pragma_table_info('star_rows')) != 3
                                OR last_insert_rowid()!=24
                                THEN RAISE(ABORT,'rowid or star shape changed') END;
                        END;
                    """, succeeds=succeeds)

    def test_encoding_and_storage_classes_match_native(self):
        for encoding, encoded in (('UTF-8', 'C3A9'), ('UTF-16le', 'E900'), ('UTF-16be', '00E9')):
            for succeeds in (True, False):
                with self.subTest(encoding=encoding, succeeds=succeeds):
                    expected = encoded if succeeds else 'BAD'
                    self.matches_native("""
                        INSERT INTO accounts VALUES ('one','é',x'00FF');
                        CREATE TRIGGER probe BEFORE INSERT ON audit BEGIN
                          SELECT CASE WHEN (SELECT hex(CAST(name AS BLOB)) FROM accounts WHERE name='é')!='""" + expected + """'
                            OR (SELECT typeof(balance) FROM accounts WHERE name='é')!='blob'
                            OR (SELECT hex(balance) FROM accounts WHERE name='é')!='00FF'
                            THEN RAISE(ABORT,'storage changed') END;
                        END;
                    """, encoding=encoding, succeeds=succeeds)

    def test_rowid_alias_shadowing_and_without_rowid_tables(self):
        for alias, definition, fields, values in (
                ('_rowid_', 'rowid TEXT', 'rowid', "'literal'"),
                ('oid', 'rowid TEXT,_rowid_ TEXT', 'rowid,_rowid_', "'literal','other'")):
            with self.subTest(alias=alias):
                self.matches_native("""
                    CREATE TABLE shadow(Tenant TEXT,""" + definition + """);
                    INSERT INTO shadow(""" + alias + ',Tenant,' + fields + ") VALUES (57,'one'," + values + """);
                    CREATE TABLE compact(Tenant TEXT,name TEXT,PRIMARY KEY(Tenant,name)) WITHOUT ROWID;
                    INSERT INTO compact VALUES ('one','visible');
                    CREATE TRIGGER probe BEFORE INSERT ON audit BEGIN
                        SELECT CASE WHEN (SELECT """ + alias + """ FROM shadow)!=57
                            OR (SELECT rowid FROM shadow)!='literal'
                            THEN RAISE(ABORT,'rowid alias changed') END;
                        UPDATE compact SET name=name;
                        SELECT CASE WHEN changes()!=1 THEN RAISE(ABORT,'compact row lost') END;
                    END;
                """)

    def test_unreadable_foreign_text_is_filtered_before_decoding(self):
        for encoding in ('UTF-8', 'UTF-16le', 'UTF-16be'):
            for interface in ('api', 'cli'):
                with self.subTest(encoding=encoding, interface=interface):
                    path = self.database("""
                        ALTER TABLE accounts RENAME COLUMN tenant TO Tenant;
                        ALTER TABLE transfers RENAME COLUMN tenant TO Tenant;
                        ALTER TABLE audit RENAME COLUMN tenant TO Tenant;
                        UPDATE accounts SET name=CAST(x'ff' AS TEXT),balance=x'0001' WHERE tenant='two';
                        UPDATE transfers SET source=CAST(x'ff' AS TEXT) WHERE tenant='two';
                        UPDATE audit SET target=CAST(x'ff' AS TEXT) WHERE tenant='two';
                        CREATE TRIGGER probe BEFORE INSERT ON audit BEGIN
                            SELECT CASE WHEN (SELECT count(*) FROM accounts)!=2
                                OR (SELECT count(*) FROM transfers)!=1
                                OR (SELECT count(*) FROM audit)!=0
                                OR total_changes()!=3 OR last_insert_rowid()!=1
                                THEN RAISE(ABORT,'foreign data observed') END;
                        END;
                    """, encoding=encoding, hidden=True)
                    before = self.snapshot(path)
                    self.assertEqual(self.call(path, interface), REQUEST)
                    after = self.snapshot(path)
                    for table in ('accounts', 'transfers', 'audit'):
                        # The tenant is stored in the database encoding.
                        tenant_bytes = 'two'.encode(encoding)
                        self.assertEqual([row for row in after[table] if row[1] == tenant_bytes],
                                         [row for row in before[table] if row[1] == tenant_bytes])

    def test_visible_payloads_preserve_raw_text_and_distinct_storage_types(self):
        for encoding in ('UTF-8', 'UTF-16le', 'UTF-16be'):
            for succeeds in (True, False):
                with self.subTest(encoding=encoding, succeeds=succeeds):
                    expected = 5 if succeeds else 99
                    self.matches_native("""
                        INSERT INTO accounts VALUES ('one',CAST(x'ff' AS TEXT),x'00ff');
                        CREATE TABLE payloads(value);
                        INSERT INTO payloads VALUES (1),(1.0),('1'),(x'31'),(NULL);
                        CREATE TRIGGER probe BEFORE INSERT ON audit BEGIN
                            SELECT CASE WHEN (SELECT count(DISTINCT typeof(value)) FROM payloads)!=""" + str(expected) + """
                              OR (SELECT count(*) FROM accounts)!=3
                              THEN RAISE(ABORT,'stored types changed') END;
                        END;
                    """, encoding=encoding, succeeds=succeeds)

    def test_effect_comparison_detects_raw_text_and_storage_type_changes(self):
        for effect in ("UPDATE payloads SET value=CAST(x'fe' AS TEXT);",
                       "UPDATE payloads SET value=x'ff';"):
            with self.subTest(effect=effect):
                path = self.database("""
                    CREATE TABLE payloads(value);
                    INSERT INTO payloads VALUES (CAST(x'ff' AS TEXT));
                    CREATE TRIGGER probe AFTER INSERT ON audit BEGIN
                """ + effect + ' END;')
                self.reject(path)

    def test_multirow_nested_ignore_and_recursive_noops_match_native_counters(self):
        for succeeds in (True, False):
            with self.subTest(succeeds=succeeds):
                expected_changes = 1 if succeeds else 2
                self.matches_native("""
                    CREATE TABLE visits(name TEXT);
                    CREATE TRIGGER ignored_visit BEFORE INSERT ON visits WHEN NEW.name='nested' BEGIN
                        SELECT RAISE(IGNORE);
                    END;
                    CREATE TRIGGER visit BEFORE UPDATE ON accounts WHEN NEW.balance=OLD.balance BEGIN
                        INSERT INTO visits VALUES ('nested');
                        INSERT INTO visits VALUES (NEW.name);
                        UPDATE accounts SET balance=balance WHERE name=NEW.name;
                        SELECT CASE WHEN NEW.name='a' THEN RAISE(IGNORE) END;
                    END;
                    CREATE TRIGGER probe BEFORE INSERT ON audit BEGIN
                        UPDATE accounts SET balance=balance;
                        SELECT CASE WHEN changes()!=""" + str(expected_changes) + """
                            OR (SELECT group_concat(name,',') FROM visits)!='a,b'
                            OR total_changes()!=8 OR last_insert_rowid()!=1
                            THEN RAISE(ABORT,'multirow counters changed') END;
                        DELETE FROM visits;
                        SELECT CASE WHEN changes()!=2 OR total_changes()!=10
                            THEN RAISE(ABORT,'parent did not resume') END;
                    END;
                """, succeeds=succeeds)

    def test_view_instead_of_triggers_and_compound_sql_keep_native_semantics(self):
        view = 'CREATE VIEW "select;雪" AS SELECT tenant,name,balance FROM accounts'
        view_sql_literal = view.replace("'", "''")
        for succeeds in (True, False):
            with self.subTest(succeeds=succeeds):
                expected_total = 5 if succeeds else 99
                self.matches_native(view + ";" + """
                    CREATE TRIGGER "end;雪" INSTEAD OF UPDATE ON "select;雪" BEGIN
                        UPDATE accounts SET balance=NEW.balance WHERE tenant=OLD.tenant AND name=OLD.name;
                    END;
                    CREATE TRIGGER "begin;--" BEFORE INSERT ON audit BEGIN
                        UPDATE "select;雪" SET balance=balance WHERE tenant=NEW.tenant;
                        SELECT CASE WHEN changes()!=0 OR total_changes()!=""" + str(expected_total) + """
                            OR (SELECT sql FROM sqlite_schema WHERE name='select;雪')!='""" + view_sql_literal + """'
                            THEN RAISE(ABORT,'view semantics changed') END;
                        INSERT OR IGNORE INTO accounts VALUES ('one','a',999);
                        SELECT CASE WHEN changes()!=0
                            OR (WITH "end"(n) AS (VALUES(2)) SELECT n FROM "end")!=2
                            OR instr('BEGIN; END; -- 雪',';')!=6
                            THEN RAISE(ABORT,'compound SQL changed') END;
                    END;
                """, succeeds=succeeds)

    def test_transient_foreign_rows_are_judged_by_final_effects(self):
        for journal in ('DELETE', 'WAL'):
            for interface in ('api', 'cli'):
                for remove in (True, False):
                    with self.subTest(journal=journal, interface=interface, remove=remove):
                        body = "INSERT OR IGNORE INTO audit VALUES ('two','old','temporary','spare',1);"
                        if remove:
                            body += "DELETE FROM audit WHERE tenant='two';"
                        setup = ('CREATE UNIQUE INDEX audit_identity ON audit(tenant,key);'
                                 'CREATE TRIGGER probe BEFORE INSERT ON audit BEGIN ' + body + ' END;')
                        path = self.database(setup,
                                             hidden=True, journal=journal)
                        before = self.snapshot(path)
                        if remove:
                            self.assertEqual(self.call(path, interface), REQUEST)
                            after = self.snapshot(path)
                            self.assertEqual([row for row in after['audit'] if row[1] == b'two'],
                                             [row for row in before['audit'] if row[1] == b'two'])
                        else:
                            self.reject(path, interface)


if __name__ == '__main__':
    unittest.main()
