"""Public-interface regressions for the coordinator's bounded repair findings."""
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


class RepairTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(dir=ROOT)
        self.addCleanup(self.tmp.cleanup)
        self.serial = 0
        self.new_db()

    def new_db(self, encoding='UTF-8'):
        self.serial += 1
        self.path = Path(self.tmp.name) / str(self.serial)
        with closing(sqlite3.connect(self.path)) as con:
            con.execute("PRAGMA encoding='" + encoding + "'")
            con.execute('CREATE TABLE encoding_seed(x)')
        vault.init_db(self.path)
        with closing(sqlite3.connect(self.path)) as con, con:
            con.executemany('INSERT INTO accounts VALUES (?,?,?)',
                            [('red','a',100), ('red','b',20), ('blue','private',77)])
            con.execute("INSERT INTO transfers VALUES ('red','old','a','b',2)")
            con.execute("INSERT INTO audit VALUES ('red','old','a','b',2)")

    def sql(self, sql):
        with closing(sqlite3.connect(self.path)) as con, con:
            con.executescript(sql)

    def snapshot(self):
        with closing(sqlite3.connect(self.path)) as con:
            # Typed, byte-preserving images also work for malformed TEXT.
            result = {}
            for table, columns in (
                ('accounts', ('tenant','name','balance')),
                ('transfers', ('tenant','key','source','target','amount')),
                ('audit', ('tenant','key','source','target','amount')),
            ):
                expressions = ','.join(f'typeof({c}),hex(CAST({c} AS BLOB))' for c in columns)
                result[table] = sorted(con.execute(f'SELECT {expressions} FROM {table}').fetchall())
            result['schema'] = con.execute('SELECT type,name,tbl_name,sql FROM sqlite_schema ORDER BY name').fetchall()
            return result

    def transfer(self):
        return vault.transfer(self.path,'red','a','b',10,'new')

    def assert_rejected(self):
        before = self.snapshot()
        with self.assertRaises(sqlite3.Error):
            self.transfer()
        self.assertEqual(self.snapshot(), before)

    def assert_valid(self):
        schema = self.snapshot()['schema']
        receipt = self.transfer()
        self.assertEqual(vault.balance(self.path,'red','a'),90)
        self.assertEqual(vault.balance(self.path,'red','b'),30)
        self.assertEqual(self.snapshot()['schema'],schema)
        before = self.snapshot()
        self.assertEqual(self.transfer(),receipt)
        self.assertEqual(self.snapshot(),before)

    def cli(self, payload):
        return subprocess.run([sys.executable,'-B',str(ROOT/'app.py'),str(self.path),payload],
                              text=True,capture_output=True,timeout=15)

    def test_duplicate_decoded_keys(self):
        for extra in ('"amount":1,', '"amou\\u006et":1,', '"tenant":"blue",', '"op":"balance",'):
            with self.subTest(extra=extra):
                before = self.snapshot()
                payload = '{' + extra + '"op":"transfer","tenant":"red","source":"a","target":"b","amount":10,"key":"new"}'
                result = self.cli(payload)
                self.assertEqual((result.returncode,result.stdout),(2,''))
                self.assertEqual(json.loads(result.stderr),{'error':'invalid request'})
                self.assertEqual(self.snapshot(),before)

    def test_trigger_effects_and_history_are_atomic(self):
        cases = (
            "DELETE FROM audit WHERE key=NEW.key;",
            "UPDATE accounts SET balance=20 WHERE tenant='red' AND name='b';",
            "UPDATE accounts SET balance=78 WHERE tenant='blue';",
            "DELETE FROM transfers WHERE key='old';",
            "DELETE FROM audit WHERE key='old';",
            "INSERT INTO audit VALUES(NEW.tenant,NEW.key,NEW.source,NEW.target,NEW.amount);",
            "UPDATE audit SET amount=CAST(amount AS TEXT) WHERE key='old';",
            "UPDATE transfers SET source=CAST(source AS BLOB) WHERE key='old';",
        )
        for body in cases:
            with self.subTest(body=body):
                self.new_db()
                # TEXT amount has integer affinity, so force the storage class
                # distinction on a TEXT column for this case.
                body = body.replace('amount=CAST(amount AS TEXT)', 'source=CAST(source AS BLOB)')
                self.sql('CREATE TRIGGER effect AFTER INSERT ON audit BEGIN '+body+' END')
                self.assert_rejected()

    def test_stale_old_image_and_restored_control(self):
        for final_change in (False,True):
            for encoding in ('UTF-8','UTF-16'):
                with self.subTest(final_change=final_change,encoding=encoding):
                    self.new_db(encoding)
                    self.sql("""CREATE TRIGGER early_restore BEFORE UPDATE ON accounts
                      WHEN OLD.tenant='blue' AND OLD.name='private' AND OLD.balance=78 AND NEW.balance=77
                      BEGIN UPDATE accounts SET balance=77 WHERE tenant=OLD.tenant AND name=OLD.name; END;
                      CREATE TRIGGER touch_foreign AFTER INSERT ON audit BEGIN
                      UPDATE accounts SET balance=78 WHERE tenant='blue' AND name='private';
                      UPDATE accounts SET balance=77 WHERE tenant='blue' AND name='private';
                    """ + ("UPDATE accounts SET balance=78 WHERE tenant='blue' AND name='private';" if final_change else '') + ' END;')
                    if final_change:
                        self.assert_rejected()
                    else:
                        self.assert_valid()
                        self.assertEqual(vault.balance(self.path,'blue','private'),77)

    def test_final_endpoints_after_before_changes(self):
        for name, final in (('a',90),('b',30)):
            for restore in (False,True):
                with self.subTest(name=name,restore=restore):
                    self.new_db()
                    self.sql(f"""CREATE TRIGGER early BEFORE UPDATE ON accounts
                      WHEN OLD.tenant='red' AND OLD.name='{name}' AND NEW.balance={final}
                      BEGIN UPDATE accounts SET balance=99 WHERE tenant='red' AND name='{name}'; END;
                      CREATE TRIGGER later AFTER INSERT ON audit BEGIN
                      UPDATE accounts SET balance={final if restore else 88} WHERE tenant='red' AND name='{name}'; END;""")
                    if restore:
                        self.assert_valid()
                    else:
                        self.assert_rejected()

    def test_implicit_replacements_and_valid_controls(self):
        cases = (
            ("CREATE UNIQUE INDEX extra ON audit(amount)", "INSERT OR REPLACE INTO audit VALUES('red','other','a','b',2);",False),
            ("CREATE UNIQUE INDEX extra ON audit((amount+0)) WHERE key!='new'", "INSERT OR REPLACE INTO audit VALUES('red','other','a','b',2);",False),
            ("CREATE UNIQUE INDEX extra ON accounts(balance)", "UPDATE OR REPLACE accounts SET balance=77 WHERE tenant='red' AND name='b'; UPDATE accounts SET balance=30 WHERE tenant='red' AND name='b';",False),
            ("CREATE UNIQUE INDEX extra ON audit(amount)", "INSERT OR IGNORE INTO audit VALUES('red','other','a','b',2);",True),
            ("CREATE UNIQUE INDEX extra ON audit(amount)", "INSERT OR REPLACE INTO audit VALUES('red','old','a','b',2);",True),
            ('', "UPDATE accounts SET rowid=rowid+100 WHERE tenant='blue'; UPDATE audit SET rowid=rowid+100 WHERE key='old';",True),
        )
        for index, body, valid in cases:
            with self.subTest(body=body):
                self.new_db()
                self.sql(index+';' if index else '')
                self.sql('CREATE TRIGGER effect AFTER INSERT ON audit BEGIN '+body+' END')
                if valid:
                    self.assert_valid()
                else:
                    self.assert_rejected()

    def test_foreign_predicates_are_scoped_through_views_and_cli(self):
        for via_view in (False,True):
            for foreign in (77,78):
                with self.subTest(via_view=via_view,foreign=foreign):
                    self.new_db()
                    self.sql(f"UPDATE accounts SET balance={foreign} WHERE tenant='blue'; CREATE VIEW private_view AS SELECT balance FROM accounts WHERE tenant='blue' AND name='private';")
                    source = 'SELECT balance FROM private_view' if via_view else "SELECT balance FROM main.accounts WHERE tenant='blue' AND name='private'"
                    self.sql("CREATE TRIGGER scope_probe BEFORE INSERT ON audit WHEN ("+source+")=77 BEGIN SELECT RAISE(ABORT,'private predicate'); END")
                    result = self.cli('{"op":"transfer","tenant":"red","source":"a","target":"b","amount":10,"key":"new"}')
                    self.assertEqual((result.returncode,result.stderr),(0,''))
                    self.assertEqual(json.loads(result.stdout)['amount'],10)
        self.new_db()
        self.sql("CREATE TRIGGER local_guard BEFORE INSERT ON audit WHEN (SELECT balance FROM accounts WHERE tenant=NEW.tenant AND name='a')=90 BEGIN SELECT RAISE(ABORT,'local guard'); END")
        self.assert_rejected()

    def test_read_sources_and_shadowed_objects(self):
        cases = (
            "SELECT b.balance FROM (accounts AS a, accounts AS b) WHERE a.tenant='red' AND b.tenant='blue'",
            "SELECT a.balance FROM 'accounts' AS a NOT INDEXED WHERE a.tenant='blue'",
            "SELECT a.balance FROM (main.accounts AS a) WHERE a.tenant='blue'",
            "WITH local AS (SELECT balance FROM accounts WHERE tenant='blue') SELECT * FROM local",
        )
        for select in cases:
            with self.subTest(select=select):
                self.new_db()
                self.sql("CREATE TRIGGER scope BEFORE INSERT ON audit WHEN ("+select+")=77 BEGIN SELECT RAISE(ABORT,'foreign'); END")
                self.assert_valid()
        self.new_db()
        self.sql("""CREATE TABLE pragma_recursive_triggers(recursive_triggers);
          INSERT INTO pragma_recursive_triggers VALUES(9);
          CREATE TRIGGER shadow BEFORE INSERT ON audit WHEN
          (SELECT recursive_triggers FROM main.pragma_recursive_triggers)!=9
          BEGIN SELECT RAISE(ABORT,'shadowed table'); END;""")
        self.assert_valid()

    def test_malformed_foreign_text_is_kept_inside_storage(self):
        self.sql("UPDATE accounts SET balance=CAST(X'FF' AS TEXT) WHERE tenant='blue';")
        before = self.snapshot()['accounts']
        self.sql("""CREATE TRIGGER restore_foreign AFTER INSERT ON audit BEGIN
          UPDATE accounts SET balance=balance WHERE tenant='blue'; END;""")
        self.assert_valid()
        self.assertIn(next(row for row in before if row[1]=='626C7565'),self.snapshot()['accounts'])

    def test_view_trigger_dependencies_keep_their_definitions(self):
        self.sql("""CREATE VIEW local_accounts AS SELECT * FROM accounts;
          CREATE TRIGGER via_view INSTEAD OF UPDATE ON local_accounts BEGIN
            UPDATE accounts SET balance=NEW.balance WHERE tenant=OLD.tenant AND name=OLD.name;
          END;
          CREATE TRIGGER audit_view AFTER INSERT ON audit BEGIN
            UPDATE local_accounts SET balance=balance WHERE tenant=NEW.tenant;
          END;""")
        self.assert_valid()

    def test_implicit_replace_keeps_native_delete_trigger_behavior(self):
        for explicit in (False,True):
            with self.subTest(explicit=explicit):
                self.new_db()
                self.sql("""CREATE UNIQUE INDEX extra ON audit(amount);
                  CREATE TRIGGER delete_guard BEFORE DELETE ON audit BEGIN
                    SELECT RAISE(ABORT,'explicit delete'); END;
                  CREATE TRIGGER replace_old AFTER INSERT ON audit BEGIN
                """ + ("DELETE FROM audit WHERE key='old';" if explicit else '') + """
                    INSERT OR REPLACE INTO audit VALUES('red','old','a','b',2); END;""")
                if explicit:
                    self.assert_rejected()
                else:
                    self.assert_valid()

    def test_literal_punctuation_does_not_change_scope(self):
        self.sql("""CREATE TRIGGER punctuation BEFORE INSERT ON audit
          WHEN '(' != ')' AND (SELECT balance FROM accounts WHERE tenant='blue')=77
          BEGIN SELECT RAISE(ABORT,'foreign'); END;""")
        self.assert_valid()

    def test_native_recursive_pragma_sources_and_names(self):
        sources = (
            "(SELECT recursive_triggers FROM 'pragma_recursive_triggers'())",
            '(SELECT pragma_recursive_triggers.recursive_triggers FROM pragma_recursive_triggers NOT INDEXED)',
            '(SELECT main.pragma_recursive_triggers.recursive_triggers FROM main.pragma_recursive_triggers NOT INDEXED)',
            '(1 IN pragma_recursive_triggers)',
            '(1 IN main.pragma_recursive_triggers)',
            '(WITH pragma_recursive_triggers AS (SELECT 0 AS recursive_triggers) SELECT recursive_triggers FROM pragma_recursive_triggers)',
            '(WITH pragma_recursive_triggers AS (SELECT 1 AS recursive_triggers) SELECT recursive_triggers FROM main.pragma_recursive_triggers)',
            '(WITH c AS (SELECT recursive_triggers FROM pragma_recursive_triggers) SELECT * FROM c)',
        )
        for source in sources:
            for abort in (False,True):
                with self.subTest(source=source,abort=abort):
                    self.new_db()
                    self.sql(f'CREATE VIEW saved_mode AS SELECT {source} AS mode; CREATE TRIGGER guard BEFORE INSERT ON audit WHEN (SELECT mode FROM saved_mode)={0 if abort else 1} BEGIN SELECT RAISE(ABORT,\'native guard\'); END;')
                    if abort:
                        self.assert_rejected()
                    else:
                        self.assert_valid()
        for name in ('begin','end','"when"','réserve','dollar$name','a\ufeffb','a\u00a0b'):
            for separator in (' ',' \ufeff'):
                with self.subTest(name=name,separator=separator):
                    self.new_db()
                    self.sql(f"CREATE TRIGGER {name} AFTER INSERT ON audit BEGIN{separator}SELECT CASE WHEN 1 THEN 'pragma_recursive_triggers' END; SELECT * FROM (VALUES(1)) WHERE 0; END")
                    self.assert_valid()

    def test_native_separator_rejections(self):
        # This installed SQLite rejects VT as whitespace; NBSP and a BOM
        # embedded in a token are identifier characters, not separators.
        for separator in ('\v','\u00a0','\ufeff'):
            with self.subTest(separator=separator):
                with closing(sqlite3.connect(':memory:')) as con:
                    with self.assertRaises(sqlite3.OperationalError):
                        con.execute('SELECT'+separator+'1')

    def test_counters_and_nested_ignore_match_native(self):
        for abort in (False,True):
            with self.subTest(abort=abort):
                self.new_db()
                self.sql("""CREATE TABLE work(x); INSERT INTO work VALUES(1),(2);
                  CREATE TABLE counters(c,t,r);
                  CREATE TRIGGER inner_guard BEFORE UPDATE ON work BEGIN
                    SELECT CASE WHEN OLD.x=1 THEN RAISE(IGNORE) END;
                  """ + ("SELECT RAISE(ABORT,'second row');" if abort else 'SELECT 1;') + """ END;
                  CREATE TRIGGER outer_guard AFTER INSERT ON audit BEGIN
                    INSERT INTO counters VALUES(changes(),total_changes(),last_insert_rowid());
                    UPDATE work SET x=x;
                    INSERT INTO counters VALUES(changes(),total_changes(),last_insert_rowid());
                  END;""")
                native = Path(self.tmp.name) / ('native'+str(abort))
                with closing(sqlite3.connect(self.path)) as c, closing(sqlite3.connect(native)) as copy:
                    c.backup(copy)
                if abort:
                    self.assert_rejected()
                    continue
                with closing(sqlite3.connect(native)) as con, con:
                    con.execute('BEGIN IMMEDIATE')
                    con.execute("UPDATE accounts SET balance=90 WHERE tenant='red' AND name='a'")
                    con.execute("UPDATE accounts SET balance=30 WHERE tenant='red' AND name='b'")
                    con.execute("INSERT INTO transfers VALUES('red','new','a','b',10)")
                    con.execute("INSERT INTO audit VALUES('red','new','a','b',10)")
                    expected = con.execute('SELECT * FROM counters').fetchall()
                self.assert_valid()
                with closing(sqlite3.connect(self.path)) as con:
                    self.assertEqual(con.execute('SELECT * FROM counters').fetchall(),expected)

    def test_foreign_write_predicates_do_not_disclose_balances(self):
        statements = (
            "UPDATE accounts SET balance=balance WHERE tenant='blue' AND name='private' AND balance=77;",
            "DELETE FROM accounts WHERE tenant='blue' AND name='private' AND balance=77;",
            "UPDATE accounts SET balance=balance WHERE (balance=77 OR balance=78) AND tenant='blue';",
            "UPDATE accounts SET balance=CASE WHEN balance=77 THEN 77 ELSE 0 END WHERE tenant='blue';",
            "UPDATE accounts SET rowid=balance WHERE tenant='blue';",
            'UPDATE accounts SET balance=balance WHERE accounts.tenant=\'blue\' AND "accounts"."balance"=77;',
            "INSERT INTO accounts VALUES('blue','private',0) ON CONFLICT(tenant,name) DO UPDATE SET balance=accounts.balance WHERE accounts.balance=77;",
        )
        for statement in statements:
            for foreign in (77,78):
                with self.subTest(statement=statement,foreign=foreign):
                    self.new_db()
                    self.sql(f"UPDATE accounts SET balance={foreign} WHERE tenant='blue';")
                    self.sql('CREATE TRIGGER guard BEFORE INSERT ON audit BEGIN '+statement+
                             " SELECT CASE WHEN changes()=1 THEN RAISE(ABORT,'audit rule') END; END;")
                    schema = self.snapshot()['schema']
                    result = self.cli(json.dumps(dict(op='transfer',tenant='red',source='a',target='b',amount=10,key='new')))
                    self.assertEqual((result.returncode,result.stderr),(0,''))
                    self.assertEqual(json.loads(result.stdout)['key'],'new')
                    self.assertEqual(vault.balance(self.path,'blue','private'),foreign)
                    self.assertEqual(self.snapshot()['schema'],schema)
        self.new_db()
        self.sql("""CREATE TRIGGER guard BEFORE INSERT ON audit BEGIN
          UPDATE accounts SET balance=balance WHERE tenant=NEW.tenant AND name='a' AND balance=90;
          SELECT CASE WHEN changes()=1 THEN RAISE(ABORT,'local rule') END; END;""")
        self.assert_rejected()

    def test_foreign_update_trigger_expressions_are_scoped(self):
        for foreign in (77,78):
            for in_when in (False,True):
                with self.subTest(foreign=foreign,in_when=in_when):
                    self.new_db()
                    self.sql(f"UPDATE accounts SET balance={foreign} WHERE tenant='blue';")
                    condition = "OLD.tenant='blue' AND OLD.balance=77"
                    body = "SELECT RAISE(ABORT,'foreign value');" if in_when else f"SELECT CASE WHEN {condition} THEN RAISE(ABORT,'foreign value') END;"
                    self.sql('CREATE TRIGGER inspect_row BEFORE UPDATE ON accounts '+
                             ('WHEN '+condition if in_when else '')+' BEGIN '+body+' END; '+
                             "CREATE TRIGGER invoke_row AFTER INSERT ON audit BEGIN UPDATE accounts SET balance=balance WHERE tenant='blue'; END;")
                    self.assert_valid()
                    self.assertEqual(vault.balance(self.path,'blue','private'),foreign)

    def test_scoped_sources_preserve_hidden_rowids_and_star_shape(self):
        for column in ('rowid','_rowid_','oid'):
            for source, qualifier in (('accounts',''),('accounts AS a','a.'),
                                      ('(main.accounts AS a)','main.a.'),
                                      ('((main.accounts)) AS a','main.a.')):
                for abort in (False,True):
                    with self.subTest(column=column,source=source,abort=abort):
                        self.new_db()
                        self.sql(f"""CREATE VIEW local_shape AS SELECT * FROM accounts;
                          CREATE TABLE captured_shape(tenant,name,balance);
                          CREATE TRIGGER capture_shape AFTER INSERT ON audit BEGIN
                            INSERT INTO captured_shape SELECT * FROM local_shape;
                          END;
                          CREATE TRIGGER guard BEFORE INSERT ON audit WHEN
                          (SELECT {qualifier}{column} FROM {source} WHERE tenant=NEW.tenant AND name=NEW.source)={1 if abort else 999}
                          BEGIN SELECT RAISE(ABORT,'row guard'); END;""")
                        if abort:
                            before = self.snapshot()
                            with self.assertRaisesRegex(sqlite3.IntegrityError,'row guard'):
                                self.transfer()
                            self.assertEqual(self.snapshot(),before)
                        else:
                            self.assert_valid()
                            with closing(sqlite3.connect(self.path)) as con:
                                self.assertEqual(sorted(con.execute('SELECT * FROM captured_shape').fetchall()),
                                                 [('red','a',90),('red','b',30)])
                                self.assertEqual([c[0] for c in con.execute('SELECT * FROM local_shape').description],
                                                 ['tenant','name','balance'])

    def test_schema_replace_keeps_native_delete_guards(self):
        for dependency in (False,True):
            for statement in ('INSERT','INSERT OR REPLACE','DELETE'):
                with self.subTest(dependency=dependency,statement=statement):
                    self.new_db()
                    if dependency:
                        self.sql('CREATE TABLE work(x PRIMARY KEY ON CONFLICT REPLACE); INSERT INTO work VALUES(1);')
                        table, values = 'work', '(1)'
                    else:
                        self.sql("""ALTER TABLE audit RENAME TO old_audit;
                          CREATE TABLE audit(tenant TEXT,key TEXT,source TEXT,target TEXT,amount INTEGER,
                                             UNIQUE(tenant,key) ON CONFLICT REPLACE);
                          INSERT INTO audit SELECT * FROM old_audit; DROP TABLE old_audit;""")
                        table, values = 'audit', "('red','old','a','b',2)"
                    action = f'DELETE FROM {table};' if statement=='DELETE' else f'{statement} INTO {table} VALUES{values};'
                    self.sql(f"""CREATE TRIGGER stop_delete BEFORE DELETE ON {table} BEGIN SELECT RAISE(ABORT,'native guard'); END;
                      CREATE TRIGGER keep_old AFTER INSERT ON audit WHEN NEW.key='new' BEGIN {action} END;""")
                    if statement=='DELETE':
                        self.assert_rejected()
                    else:
                        self.assert_valid()
                    if dependency:
                        with closing(sqlite3.connect(self.path)) as con:
                            self.assertEqual(con.execute('SELECT * FROM work').fetchall(),[(1,)])

    def test_schema_qualified_parenthesized_pragma_alias(self):
        query = 'SELECT main.p.recursive_triggers FROM (main.pragma_recursive_triggers() AS p)'
        for view in (False,True):
            for abort in (False,True):
                for cli in (False,True):
                    with self.subTest(view=view,abort=abort,cli=cli):
                        self.new_db()
                        if view:
                            self.sql('CREATE VIEW saved_mode AS '+query)
                        scalar = 'SELECT * FROM saved_mode' if view else query
                        self.sql(f"CREATE TRIGGER guard BEFORE INSERT ON audit WHEN ({scalar}){'=' if abort else '<>'}0 BEGIN SELECT RAISE(ABORT,'native guard'); END;")
                        before = self.snapshot()
                        if cli:
                            result = self.cli(json.dumps(dict(op='transfer',tenant='red',source='a',target='b',amount=10,key='new')))
                            self.assertEqual(result.returncode,2 if abort else 0,result.stderr)
                            if abort:
                                self.assertEqual((result.stdout,json.loads(result.stderr)),('',{'error':'invalid request'}))
                                self.assertEqual(self.snapshot(),before)
                            else:
                                self.assertEqual(json.loads(result.stdout)['amount'],10)
                                self.assertEqual(vault.balance(self.path,'red','a'),90)
                        elif abort:
                            with self.assertRaisesRegex(sqlite3.IntegrityError,'native guard'):
                                self.transfer()
                            self.assertEqual(self.snapshot(),before)
                        else:
                            self.assert_valid()
                        self.assertEqual(self.snapshot()['schema'],before['schema'])


if __name__ == '__main__':
    unittest.main()
