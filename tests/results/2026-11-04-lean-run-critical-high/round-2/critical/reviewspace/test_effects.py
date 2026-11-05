import json
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

import vault


ROOT = Path(__file__).resolve().parent
REQUEST = dict(tenant="red", source="a", target="b", amount=10, key="new")


class EffectsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(dir=ROOT)
        self.addCleanup(self.tmp.cleanup)

    def database(self, name, ddl="", encoding="UTF-8"):
        path = Path(self.tmp.name) / (name + ".sqlite")
        with closing(sqlite3.connect(path)) as con:
            con.execute(f"PRAGMA encoding='{encoding}'")
            # Set the encoding before init_db opens its separate connection.
            con.execute("CREATE TABLE encoding_marker (value)")
        vault.init_db(path)
        with closing(sqlite3.connect(path)) as con, con:
            con.executemany("INSERT INTO accounts VALUES (?,?,?)", [
                ("red", "a", 100), ("red", "b", 0), ("blue", "private", 777),
            ])
            con.executescript(ddl)
        return path

    def snapshot(self, path):
        with closing(sqlite3.connect(path)) as con:
            # bytes permits exact comparisons of legacy, invalid TEXT too.
            con.text_factory = bytes
            return (
                con.execute("SELECT type,name,tbl_name,sql FROM sqlite_schema ORDER BY name").fetchall(),
                [con.execute(f"SELECT * FROM {table} ORDER BY rowid").fetchall()
                 for table in ("accounts", "transfers", "audit")],
            )

    def cli(self, path, request):
        return subprocess.run(
            [sys.executable, "-B", str(ROOT / "app.py"), str(path), json.dumps(dict(op="transfer", **request))],
            capture_output=True, text=True, cwd=ROOT, timeout=10,
        )

    def assert_rejected(self, path, request=REQUEST):
        before = self.snapshot(path)
        with self.assertRaises(sqlite3.DatabaseError):
            vault.transfer(path, **request)
        self.assertEqual(self.snapshot(path), before)
        result = self.cli(path, request)
        self.assertEqual((result.returncode, result.stdout), (2, ""))
        self.assertEqual(json.loads(result.stderr), {"error": "invalid request"})
        self.assertEqual(len(result.stderr.splitlines()), 1)
        self.assertEqual(self.snapshot(path), before)

    def test_skipped_required_writes_roll_back_and_keep_trigger(self):
        for table, event, condition in (
            ("accounts", "UPDATE", "NEW.name='a'"),
            ("accounts", "UPDATE", "NEW.name='b'"),
            ("transfers", "INSERT", "1"),
            ("audit", "INSERT", "1"),
        ):
            with self.subTest(table=table, condition=condition):
                path = self.database(table + condition, f"""
                    CREATE TRIGGER skip BEFORE {event} ON {table}
                    WHEN ({condition}) AND NEW.tenant='red'
                    BEGIN SELECT RAISE(IGNORE); END;
                """)
                self.assert_rejected(path)
        path = self.database("conditional", """
            CREATE TRIGGER skip BEFORE INSERT ON audit WHEN NEW.key='new'
            BEGIN SELECT RAISE(IGNORE); END;
        """)
        self.assert_rejected(path)
        control = dict(REQUEST, key="control")
        result = self.cli(path, control)
        self.assertEqual((result.returncode, result.stderr), (0, ""))
        self.assertEqual(json.loads(result.stdout), control)
        before = self.snapshot(path)
        self.assertEqual(vault.transfer(path, **control), control)
        self.assertEqual(self.snapshot(path), before)

    def test_replace_is_rejected_but_ignored_conflict_and_noop_are_valid(self):
        for operation, allowed in (
            ("INSERT OR REPLACE INTO accounts VALUES ('blue','private',0)", False),
            ("INSERT OR IGNORE INTO accounts VALUES ('blue','private',0)", True),
            ("UPDATE accounts SET balance=balance WHERE tenant='blue'", True),
        ):
            with self.subTest(operation=operation):
                path = self.database(str(allowed) + operation.split()[0], f"""
                    CREATE TRIGGER side_effect AFTER INSERT ON audit BEGIN {operation}; END;
                """)
                if not allowed:
                    self.assert_rejected(path)
                else:
                    schema = self.snapshot(path)[0]
                    result = self.cli(path, REQUEST)
                    self.assertEqual((result.returncode, result.stderr), (0, ""))
                    self.assertEqual(json.loads(result.stdout), REQUEST)
                    self.assertEqual(vault.balance(path, "blue", "private"), 777)
                    self.assertEqual(self.snapshot(path)[0], schema)

    def test_unique_index_replace_victims_are_observed_in_each_table(self):
        for table, column, where, original, victim in (
            ("accounts", "balance", "tenant='red' AND name='a'", 90, 777),
            ("transfers", "amount", "tenant='red' AND key='new'", 10, 777),
            ("audit", "amount", "tenant='red' AND key='new'", 10, 777),
        ):
            for conflict in ("REPLACE", "IGNORE"):
                with self.subTest(table=table, conflict=conflict):
                    path = self.database(table + conflict, f"""
                        INSERT INTO transfers VALUES ('blue','old','x','y',777);
                        INSERT INTO audit VALUES ('blue','old','x','y',777);
                        CREATE UNIQUE INDEX extra ON {table} ({column});
                        CREATE TRIGGER side_effect AFTER INSERT ON audit BEGIN
                            UPDATE OR {conflict} {table} SET {column}={victim} WHERE {where};
                            UPDATE {table} SET {column}={original} WHERE {where};
                        END;
                    """)
                    if conflict == "REPLACE":
                        self.assert_rejected(path)
                    else:
                        before = self.snapshot(path)
                        self.assertEqual(vault.transfer(path, **REQUEST), REQUEST)
                        after = self.snapshot(path)
                        self.assertEqual(after[0], before[0])
                        for old, new in zip(before[1], after[1]):
                            self.assertEqual([r for r in new if r[0] == b"blue"],
                                             [r for r in old if r[0] == b"blue"])

    def test_extra_audit_wrong_receipt_and_erased_history_roll_back(self):
        for name, body in (
            ("duplicate", "INSERT INTO audit VALUES(NEW.tenant,NEW.key,NEW.source,NEW.target,NEW.amount);"),
            ("receipt", "UPDATE transfers SET amount=11 WHERE tenant=NEW.tenant AND key=NEW.key;"),
            ("history", "DELETE FROM audit WHERE tenant='blue';"),
        ):
            with self.subTest(name=name):
                path = self.database(name, f"""
                    INSERT INTO audit VALUES ('blue','old','x','y',1), ('blue','old','x','y',1);
                    CREATE TRIGGER side_effect AFTER INSERT ON audit BEGIN {body} END;
                """)
                self.assert_rejected(path)

    def test_rowid_moves_and_delete_reinsert_preserve_logical_rows(self):
        path = self.database("row_moves", """
            CREATE TRIGGER move AFTER INSERT ON audit BEGIN
                UPDATE accounts SET rowid=rowid+100 WHERE tenant='blue';
                INSERT OR REPLACE INTO accounts VALUES('blue','private',777);
                INSERT OR REPLACE INTO transfers SELECT * FROM transfers WHERE tenant=NEW.tenant AND key=NEW.key;
                DELETE FROM accounts WHERE tenant='blue' AND name='private';
                INSERT INTO accounts VALUES('blue','private',777);
            END;
        """)
        self.assertEqual(vault.transfer(path, **REQUEST), REQUEST)
        self.assertEqual(vault.balance(path, "blue", "private"), 777)

    def compare_native(self, name, ddl):
        outcomes = []
        for mode in ("native", "app"):
            path = self.database(name + mode, ddl)
            schema = self.snapshot(path)[0]
            if mode == "native":
                with closing(sqlite3.connect(path)) as con, con:
                    con.execute("BEGIN IMMEDIATE")
                    con.execute("UPDATE accounts SET balance=90 WHERE tenant='red' AND name='a'")
                    con.execute("UPDATE accounts SET balance=10 WHERE tenant='red' AND name='b'")
                    con.execute("INSERT INTO transfers VALUES('red','new','a','b',10)")
                    con.execute("INSERT INTO audit VALUES('red','new','a','b',10)")
            else:
                self.assertEqual(vault.transfer(path, **REQUEST), REQUEST)
            self.assertEqual(self.snapshot(path)[0], schema)
            with closing(sqlite3.connect(path)) as con:
                outcomes.append(con.execute("SELECT * FROM log ORDER BY rowid").fetchall())
        self.assertEqual(outcomes[1], outcomes[0])
        return outcomes[0]

    def test_native_trigger_order_recursion_and_visible_counters(self):
        rows = self.compare_native("counters", """
            CREATE TABLE log (step, changes_seen, total_seen, last_id);
            CREATE TRIGGER counts AFTER UPDATE ON accounts BEGIN
                INSERT INTO log VALUES ('before',changes(),total_changes(),last_insert_rowid());
                SELECT 42;
                INSERT INTO log VALUES ('after',changes(),total_changes(),last_insert_rowid());
                UPDATE accounts SET balance=balance WHERE tenant=NEW.tenant AND name=NEW.name;
            END;
            CREATE TRIGGER audit_counts AFTER INSERT ON audit BEGIN
                INSERT INTO log VALUES ('first',changes(),total_changes(),last_insert_rowid());
            END;
            CREATE TRIGGER audit_counts_last AFTER INSERT ON audit BEGIN
                INSERT INTO log VALUES ('last',changes(),total_changes(),last_insert_rowid());
            END;
        """)
        self.assertEqual([row[0] for row in rows], ["before", "after", "before", "after", "last", "first"])

    def test_native_explicit_deletes_and_ignore_across_rows(self):
        rows = self.compare_native("ignore", """
            CREATE TABLE log (step);
            CREATE TABLE scratch (n PRIMARY KEY);
            INSERT INTO scratch VALUES(1),(2),(3);
            CREATE TRIGGER on_delete AFTER DELETE ON scratch BEGIN
                INSERT INTO log VALUES('delete-' || OLD.n);
            END;
            CREATE TRIGGER each_row BEFORE UPDATE ON scratch BEGIN
                INSERT INTO log VALUES(OLD.n);
                SELECT CASE WHEN OLD.n=1 THEN RAISE(IGNORE) ELSE 0 END;
                SELECT RAISE(IGNORE);
            END;
            CREATE TRIGGER parent AFTER INSERT ON audit BEGIN
                UPDATE scratch SET n=n;
                INSERT INTO log VALUES('continued');
                INSERT OR REPLACE INTO scratch VALUES(1);
                DELETE FROM scratch WHERE n=2;
                UPDATE scratch SET n=n;
            END;
        """)
        self.assertEqual(rows, [(1,), (2,), (3,), ("continued",), ("delete-2",), (3,), (1,)])

    def test_native_sql_names_compound_bodies_and_separators(self):
        self.compare_native("grammar", """
            CREATE TABLE log (step);
            CREATE TRIGGER begin AFTER INSERT ON audit BEGIN
                SELECT CASE WHEN NEW.amount>0 THEN 1 ELSE 0 END;
                INSERT INTO log VALUES('begin; -- END');
            END;
            CREATE TRIGGER end AFTER INSERT ON audit BEGIN
                VALUES(1), (2); WITH v(x) AS (VALUES(1)) SELECT x FROM v;
                INSERT INTO log VALUES('end');
            END;
            CREATE TRIGGER é 名 AFTER INSERT ON audit BEGIN
                INSERT INTO log SELECT 'compound' WHERE 1 UNION ALL SELECT 'second' WHERE 1;
            END;
            CREATE TRIGGER a﻿b AFTER INSERT ON audit BEGIN
                ﻿SELECT 1; ﻿DELETE FROM accounts WHERE 0;
                INSERT INTO log VALUES('BOM identifier');
            END;
            CREATE TRIGGER `quoted``name` AFTER INSERT ON audit WHEN NEW.amount=10 BEGIN
                INSERT INTO log VALUES('quoted');
            END;
        """)
        # A lone VT cannot start SQLite whitespace, although a space followed
        # by VT is accepted (covered at DELETE boundaries below).
        path = self.database("vertical_tab")
        with closing(sqlite3.connect(path)) as con:
            with self.assertRaises(sqlite3.OperationalError):
                con.execute("CREATE TRIGGER vt AFTER INSERT ON audit BEGIN SELECT 1;\vDELETE FROM accounts WHERE 0; END")
        self.assertEqual(vault.transfer(path, **REQUEST), REQUEST)

    def assert_native_outcome(self, name, ddl, rejected):
        """Compare fresh native, API and CLI transactions and reopened storage."""
        outcomes = []
        for mode in ("native", "api", "cli"):
            with self.subTest(mode=mode):
                path = self.database(name + mode, ddl)
                before = self.snapshot(path)
                if mode == "cli":
                    result = self.cli(path, REQUEST)
                    if rejected:
                        self.assertEqual((result.returncode, result.stdout), (2, ""))
                        self.assertEqual(json.loads(result.stderr), {"error": "invalid request"})
                        self.assertEqual(len(result.stderr.splitlines()), 1)
                    else:
                        self.assertEqual((result.returncode, result.stderr), (0, ""))
                        self.assertEqual(json.loads(result.stdout), REQUEST)
                        self.assertEqual(len(result.stdout.splitlines()), 1)
                else:
                    def transfer():
                        if mode == "api":
                            return vault.transfer(path, **REQUEST)
                        with closing(sqlite3.connect(path)) as con, con:
                            con.execute("BEGIN IMMEDIATE")
                            con.execute("UPDATE accounts SET balance=90 WHERE tenant='red' AND name='a'")
                            con.execute("UPDATE accounts SET balance=10 WHERE tenant='red' AND name='b'")
                            con.execute("INSERT INTO transfers VALUES('red','new','a','b',10)")
                            con.execute("INSERT INTO audit VALUES('red','new','a','b',10)")
                        return REQUEST

                    if rejected:
                        with self.assertRaisesRegex(sqlite3.IntegrityError, "audit storage failure"):
                            transfer()
                    else:
                        self.assertEqual(transfer(), REQUEST)
                after = self.snapshot(path)
                self.assertEqual(after[0], before[0])
                if rejected:
                    self.assertEqual(after, before)
                else:
                    self.assertEqual(vault.balance(path, "red", "a"), 90)
                    self.assertEqual(vault.balance(path, "red", "b"), 10)
                    self.assertEqual(after[1][1][-1], (b"red", b"new", b"a", b"b", 10))
                    self.assertEqual(after[1][2][-1], after[1][1][-1])
                outcomes.append(after)
        if len(outcomes) == 3:
            self.assertEqual(outcomes, [outcomes[0]] * 3)

    def test_recursive_pragma_audit_guards_match_native_api_and_cli(self):
        for setting in (0, 1):
            with self.subTest(setting=setting):
                self.assert_native_outcome(f"pragma_guard_{setting}", f"""
                    CREATE TRIGGER audit_guard BEFORE INSERT ON audit
                    WHEN (SELECT recursive_triggers FROM pragma_recursive_triggers)={setting}
                    BEGIN SELECT RAISE(ABORT,'audit storage failure'); END;
                """, rejected=setting == 0)

    def test_pragma_sources_and_lookalike_identifiers_keep_native_meaning(self):
        cases = (
            ("", 'SELECT "recursive_triggers" FROM main."pragma_recursive_triggers"()', 0),
            ("", "SELECT * FROM pragma_recursive_triggers()", 0),
            ("CREATE VIEW settings AS SELECT * FROM pragma_recursive_triggers;",
             "SELECT recursive_triggers FROM settings", 0),
            ("CREATE TABLE pragma_recursive_triggers(recursive_triggers);"
             "INSERT INTO pragma_recursive_triggers VALUES(1);",
             "SELECT recursive_triggers FROM pragma_recursive_triggers", 1),
            ("", "WITH pragma_recursive_triggers(recursive_triggers) AS (VALUES(1)) "
             "SELECT recursive_triggers FROM pragma_recursive_triggers", 1),
            ("", "SELECT pragma_recursive_triggers FROM "
             "(SELECT 1 AS pragma_recursive_triggers)", 1),
            ("", "SELECT length('pragma_recursive_triggers') > 0", 1),
        )
        for index, (ddl, query, value) in enumerate(cases):
            for setting in (0, 1):
                with self.subTest(query=query, setting=setting):
                    self.assert_native_outcome(f"pragma_source_{index}_{setting}", ddl + f"""
                        CREATE TRIGGER audit_guard BEFORE INSERT ON audit
                        WHEN ({query})={setting}
                        BEGIN SELECT RAISE(ABORT,'audit storage failure'); END;
                    """, rejected=setting == value)

    def test_pragma_reads_retain_replace_effect_detection(self):
        for value in (0, 777):
            with self.subTest(value=value):
                ddl = f"""
                    CREATE TRIGGER replace_guard AFTER INSERT ON audit
                    WHEN (SELECT recursive_triggers FROM pragma_recursive_triggers)=0
                    BEGIN
                        SELECT recursive_triggers FROM pragma_recursive_triggers();
                        INSERT OR REPLACE INTO accounts VALUES('blue','private',{value});
                    END;
                """
                if value == 0:
                    self.assert_rejected(self.database("pragma_replace_bad", ddl))
                else:
                    self.assert_native_outcome("pragma_replace_same", ddl, rejected=False)

    def test_trigger_identifier_and_separator_boundaries_preserve_delete_semantics(self):
        for index, header in enumerate((
            "gate \vDELETE", "gate \t\vDELETE", "gate \ufeffDELETE",
            "a\ufeffb DELETE", "é\u00a0名 DELETE", '"DELETE" \vDELETE',
            "gate AFTER \vDELETE",
        )):
            for explicit in (False, True):
                with self.subTest(header=header, explicit=explicit):
                    body = (" \vDELETE FROM transfers WHERE tenant=NEW.tenant AND key=NEW.key;"
                            if explicit else "INSERT OR REPLACE INTO transfers SELECT * FROM transfers "
                            "WHERE tenant=NEW.tenant AND key=NEW.key;")
                    self.assert_native_outcome(f"delete_separator_{index}_{explicit}", f"""
                        INSERT INTO transfers VALUES('blue','history','x','y',4);
                        INSERT INTO audit VALUES('blue','history','x','y',4);
                        CREATE TRIGGER {header} ON transfers
                        BEGIN SELECT RAISE(ABORT,'audit storage failure'); END;
                        CREATE TRIGGER writer AFTER INSERT ON audit BEGIN {body} END;
                    """, rejected=explicit)

    def test_storage_classes_legacy_text_and_database_encoding(self):
        for encoding in ("UTF-8", "UTF-16le", "UTF-16be"):
            for change in (False, True):
                with self.subTest(encoding=encoding, change=change):
                    path = self.database(encoding + str(change), f"""
                        INSERT INTO audit VALUES('blue','legacy',CAST(X'FF00' AS TEXT),X'3100',NULL);
                        CREATE TRIGGER legacy AFTER INSERT ON audit BEGIN
                            UPDATE audit SET source=source, target={'CAST(target AS TEXT)' if change else 'target'}
                            WHERE tenant='blue';
                        END;
                    """, encoding=encoding)
                    if change:
                        self.assert_rejected(path)
                    else:
                        before = self.snapshot(path)
                        self.assertEqual(vault.transfer(path, **REQUEST), REQUEST)
                        after = self.snapshot(path)
                        self.assertEqual(after[0], before[0])
                        self.assertEqual(after[1][2][0], before[1][2][0])

    def test_durable_replay_and_conflict_precede_missing_endpoint_reads(self):
        path = self.database("replay")
        receipt = vault.transfer(path, **REQUEST)
        with closing(sqlite3.connect(path)) as con, con:
            con.execute("DELETE FROM accounts WHERE tenant='red'")
        before = self.snapshot(path)
        self.assertEqual(vault.transfer(path, **REQUEST), receipt)
        result = self.cli(path, REQUEST)
        self.assertEqual((result.returncode, result.stderr), (0, ""))
        self.assertEqual(json.loads(result.stdout), receipt)
        with self.assertRaisesRegex(ValueError, "key conflict"):
            vault.transfer(path, **dict(REQUEST, amount=11))
        with self.assertRaisesRegex(ValueError, "account unavailable"):
            vault.transfer(path, **dict(REQUEST, key="uncached"))
        self.assertEqual(self.snapshot(path), before)


if __name__ == "__main__":
    unittest.main()
