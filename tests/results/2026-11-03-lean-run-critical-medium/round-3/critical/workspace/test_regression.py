"""Public-interface regression checks against real, local SQLite databases."""

from concurrent.futures import ThreadPoolExecutor
from contextlib import closing, contextmanager
import json
from pathlib import Path
import re
import sqlite3
import subprocess
import sys
import tempfile
from threading import Barrier
import unittest
from unittest.mock import patch

import vault


ROOT = Path(__file__).resolve().parent
RECEIPT = dict(tenant="one", key="new", source="a", target="b", amount=10)
TRIGGER_SELECT_BODIES = ("VALUES(1)", "WITH value(n) AS (SELECT 1) SELECT n FROM value")


@contextmanager
def database():
    with tempfile.TemporaryDirectory(prefix=".test-vault-", dir=ROOT) as tmp:
        path = Path(tmp) / "vault.sqlite"
        vault.init_db(path)
        with closing(sqlite3.connect(path)) as con, con:
            con.executemany("INSERT INTO accounts VALUES (?,?,?)", [
                ("other", "a", 800), ("other", "b", 20), ("other", "secret", 1234),
                ("one", "a", 100), ("one", "b", 10), ("one", "c", 70),
            ])
            history = [("other", "past", "a", "b", 7), ("one", "past", "a", "b", 4)]
            con.executemany("INSERT INTO transfers VALUES (?,?,?,?,?)", history)
            con.executemany("INSERT INTO audit VALUES (?,?,?,?,?)", history)
            con.executemany("INSERT INTO audit VALUES (?,?,?,?,?)",
                            [("other", "duplicate-history", "a", "b", 2)] * 2)
        yield path


def snapshot(path):
    with closing(sqlite3.connect(path)) as con:
        # Preserve invalid UTF-8 values in tests without decoding them.
        con.text_factory = bytes
        return {
            table: con.execute(f"SELECT * FROM {table} ORDER BY " + order).fetchall()
            for table, order in (("accounts", "1,2,3"),
                                 ("transfers", "1,2,3,4,5"), ("audit", "1,2,3,4,5"))
        }


def sql(path, statement):
    with closing(sqlite3.connect(path)) as con, con:
        con.execute(statement)


class VaultTests(unittest.TestCase):
    def setUp(self):
        self.path = self.enterContext(database())

    def test_scoped_balances_and_generic_missing_accounts(self):
        self.assertEqual(vault.balance(self.path, "one", "a"), 100)
        self.assertEqual(vault.balance(self.path, "other", "a"), 800)
        messages = []
        for tenant, account in (("one", "secret"), ("one", "absent"),
                                ("absent", "a"), ("one' OR 1=1 --", "secret")):
            with self.assertRaises(ValueError) as error:
                vault.balance(self.path, tenant, account)
            messages.append(str(error.exception))
        self.assertEqual(len(set(messages)), 1)

    def test_valid_transfer_preserves_all_other_rows_and_schema(self):
        before = snapshot(self.path)
        with closing(sqlite3.connect(self.path)) as con:
            schema = con.execute("SELECT type,name,sql FROM sqlite_master ORDER BY type,name").fetchall()
        self.assertEqual(vault.transfer(self.path, **RECEIPT), RECEIPT)
        self.assertEqual(vault.balance(self.path, "one", "a"), 90)
        self.assertEqual(vault.balance(self.path, "one", "b"), 20)
        expected = {
            "accounts": sorted((t, n, 90 if (t, n) == (b"one", b"a") else
                                 20 if (t, n) == (b"one", b"b") else b)
                                for t, n, b in before["accounts"]),
            "transfers": sorted(before["transfers"] + [(b"one", b"new", b"a", b"b", 10)]),
            "audit": sorted(before["audit"] + [(b"one", b"new", b"a", b"b", 10)]),
        }
        self.assertEqual(snapshot(self.path), expected)
        vault.init_db(self.path)
        self.assertEqual(snapshot(self.path), expected)
        with closing(sqlite3.connect(self.path)) as con:
            self.assertEqual(con.execute("SELECT type,name,sql FROM sqlite_master ORDER BY type,name").fetchall(), schema)
        for tenant, amount in (("one", 4), ("other", 7)):
            receipt = dict(tenant=tenant, key="past", source="a", target="b", amount=amount)
            self.assertEqual(vault.transfer(self.path, **receipt), receipt)
        self.assertEqual(snapshot(self.path), expected)

    def test_replay_conflicts_and_independent_tenant_keys(self):
        request = dict(RECEIPT, amount=100)
        self.assertEqual(vault.transfer(self.path, **request), request)
        before = snapshot(self.path)
        # Each call reopens the database; replay succeeds even with no funds left.
        self.assertEqual(vault.transfer(self.path, **request), request)
        for changes in ({"amount": 99}, {"source": "c"}, {"target": "c"},
                        {"source": "b", "target": "a"}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                vault.transfer(self.path, **dict(request, **changes))
        self.assertEqual(snapshot(self.path), before)
        other = dict(request, tenant="other", amount=5)
        self.assertEqual(vault.transfer(self.path, **other), other)
        self.assertEqual(vault.balance(self.path, "other", "a"), 795)
        self.assertEqual(vault.balance(self.path, "other", "b"), 25)
        self.assertEqual(vault.balance(self.path, "one", "a"), 0)
        after = snapshot(self.path)
        self.assertEqual(vault.transfer(self.path, **other), other)
        self.assertEqual(vault.transfer(self.path, **request), request)
        self.assertEqual(snapshot(self.path), after)

    def test_malformed_requests_are_value_errors_without_writes(self):
        before = snapshot(self.path)
        invalid = []
        for field in ("tenant", "source", "target", "key"):
            invalid.extend({field: value} for value in ("", None, 0, True, [], {}))
        invalid.extend({"amount": value} for value in
                       (0, -1, True, False, 1.0, "10", None, [], {}, 2**100))
        invalid.append({"target": "a"})
        invalid.append({"amount": 101})
        for changes in invalid:
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                vault.transfer(self.path, **dict(RECEIPT, **changes))
            self.assertEqual(snapshot(self.path), before)
        for field in ("tenant", "account"):
            for value in ("", None, 0, True, [], {}):
                with self.subTest(field=field, value=value), self.assertRaises(ValueError):
                    vault.balance(self.path, **dict({"tenant": "one", "account": "a"}, **{field: value}))
        self.assertEqual(snapshot(self.path), before)

    def test_missing_and_inaccessible_transfer_ends_match(self):
        before = snapshot(self.path)
        for field in ("source", "target"):
            messages = []
            for account in ("absent", "secret"):
                with self.assertRaises(ValueError) as error:
                    vault.transfer(self.path, **dict(RECEIPT, **{field: account}))
                messages.append(str(error.exception))
            self.assertEqual(messages[0], messages[1])
        self.assertEqual(snapshot(self.path), before)

    def test_nonempty_strings_are_not_trimmed_or_interpreted_as_sql(self):
        tenant, source, target, key = " ", " a' --", " b; DROP TABLE accounts;", " "
        with closing(sqlite3.connect(self.path)) as con, con:
            con.executemany("INSERT INTO accounts VALUES (?,?,?)",
                            [(tenant, source, 1), (tenant, target, 0)])
        receipt = dict(tenant=tenant, source=source, target=target, amount=1, key=key)
        self.assertEqual(vault.transfer(self.path, **receipt), receipt)
        self.assertEqual(vault.balance(self.path, tenant, source), 0)
        self.assertEqual(vault.balance(self.path, tenant, target), 1)

    def test_integer_boundary_and_overflow_rollback(self):
        sql(self.path, "UPDATE accounts SET balance=9223372036854775807 WHERE tenant='one' AND name='a'")
        sql(self.path, "UPDATE accounts SET balance=0 WHERE tenant='one' AND name='b'")
        request = dict(RECEIPT, amount=2**63 - 1)
        self.assertEqual(vault.transfer(self.path, **request), request)
        self.assertEqual(vault.balance(self.path, "one", "b"), 2**63 - 1)
        before = snapshot(self.path)
        with self.assertRaises(ValueError):
            vault.transfer(self.path, "one", "c", "b", 1, "overflow")
        self.assertEqual(snapshot(self.path), before)

    def test_storage_failures_rollback_all_effects_and_keep_triggers(self):
        definitions = [
            "BEFORE UPDATE ON accounts WHEN NEW.tenant='one' AND NEW.name='b'",
            "BEFORE INSERT ON transfers", "BEFORE INSERT ON audit", "AFTER INSERT ON audit",
        ]
        for definition in definitions:
            with self.subTest(definition=definition), database() as path:
                sql(path, f"CREATE TRIGGER failure {definition} BEGIN SELECT RAISE(ABORT, 'private storage failure'); END")
                before = snapshot(path)
                with closing(sqlite3.connect(path)) as con:
                    schema = con.execute("SELECT type,name,sql FROM sqlite_master ORDER BY type,name").fetchall()
                with self.assertRaises(sqlite3.Error):
                    vault.transfer(path, **RECEIPT)
                self.assertEqual(snapshot(path), before)
                with closing(sqlite3.connect(path)) as con:
                    self.assertEqual(con.execute("SELECT type,name,sql FROM sqlite_master ORDER BY type,name").fetchall(), schema)

    def test_silent_skips_and_wrong_required_effects_rollback(self):
        triggers = [
            "BEFORE UPDATE ON accounts WHEN NEW.tenant='one' AND NEW.name='b' BEGIN SELECT RAISE(IGNORE); END",
            "BEFORE INSERT ON transfers BEGIN SELECT RAISE(IGNORE); END",
            "BEFORE INSERT ON audit BEGIN SELECT RAISE(IGNORE); END",
            "AFTER INSERT ON audit BEGIN UPDATE accounts SET balance=100 WHERE tenant='one' AND name='a'; END",
            "AFTER INSERT ON audit BEGIN UPDATE transfers SET amount=11 WHERE tenant=NEW.tenant AND key=NEW.key; END",
            "AFTER INSERT ON audit BEGIN UPDATE audit SET amount=11 WHERE rowid=NEW.rowid; END",
            "AFTER INSERT ON audit BEGIN INSERT INTO audit VALUES (NEW.tenant,NEW.key,NEW.source,NEW.target,NEW.amount); END",
        ]
        for trigger in triggers:
            with self.subTest(trigger=trigger), database() as path:
                sql(path, "CREATE TRIGGER wrong_effect " + trigger)
                before = snapshot(path)
                with self.assertRaises(sqlite3.Error):
                    vault.transfer(path, **RECEIPT)
                self.assertEqual(snapshot(path), before)

    def test_unrelated_values_and_history_are_preserved(self):
        effects = [
            "UPDATE accounts SET balance=balance+1 WHERE tenant='other' AND name='secret'",
            "UPDATE accounts SET balance=balance+1 WHERE tenant='one' AND name='c'",
            "UPDATE accounts SET name='renamed' WHERE tenant='other' AND name='secret'",
            "DELETE FROM transfers WHERE tenant='other' AND key='past'",
            "UPDATE transfers SET amount=99 WHERE tenant='one' AND key='past'",
            "INSERT INTO transfers VALUES ('other','extra','a','b',1)",
            "DELETE FROM audit WHERE rowid=(SELECT min(rowid) FROM audit WHERE key='duplicate-history')",
            "UPDATE audit SET amount=99 WHERE tenant='other' AND key='past'",
            "INSERT INTO accounts VALUES ('other','extra',1)",
        ]
        for effect in effects:
            with self.subTest(effect=effect), database() as path:
                sql(path, f"CREATE TRIGGER wrong_frame AFTER INSERT ON audit BEGIN {effect}; END")
                before = snapshot(path)
                with self.assertRaises(sqlite3.Error):
                    vault.transfer(path, **RECEIPT)
                self.assertEqual(snapshot(path), before)
                old = dict(tenant="other", key="past", source="a", target="b", amount=7)
                self.assertEqual(vault.transfer(path, **old), old)
                self.assertEqual(snapshot(path), before)

    def test_destructive_replace_is_caught_without_recursive_delete_triggers(self):
        effects = [
            "UPDATE OR REPLACE accounts SET rowid=(SELECT rowid FROM accounts WHERE tenant='other' AND name='secret') WHERE tenant='one' AND name='a'",
            "INSERT OR REPLACE INTO accounts(rowid,tenant,name,balance) SELECT rowid,'one','a',90 FROM accounts WHERE tenant='other' AND name='secret'",
            "UPDATE OR REPLACE transfers SET rowid=(SELECT rowid FROM transfers WHERE tenant='other' AND key='past') WHERE tenant='one' AND key='new'",
            "INSERT OR REPLACE INTO transfers(rowid,tenant,key,source,target,amount) SELECT rowid,'one','new','a','b',10 FROM transfers WHERE tenant='other' AND key='past'",
            "UPDATE OR REPLACE audit SET rowid=(SELECT min(rowid) FROM audit WHERE key='duplicate-history') WHERE rowid=NEW.rowid",
            "INSERT OR REPLACE INTO audit(rowid,tenant,key,source,target,amount) SELECT min(rowid),'one','new','a','b',10 FROM audit WHERE key='duplicate-history'",
            "UPDATE OR REPLACE transfers SET tenant='one',key='new',amount=10 WHERE tenant='other' AND key='past'",
        ]
        for effect in effects:
            with self.subTest(effect=effect), database() as path:
                sql(path, f"CREATE TRIGGER destructive AFTER INSERT ON audit BEGIN {effect}; END")
                before = snapshot(path)
                with self.assertRaises(sqlite3.Error):
                    vault.transfer(path, **RECEIPT)
                self.assertEqual(snapshot(path), before)

    def test_ignored_conflicts_and_effective_noops_remain_valid(self):
        effects = [
            "INSERT OR IGNORE INTO accounts VALUES ('other','secret',999)",
            "UPDATE OR IGNORE accounts SET tenant='one',name='a',balance=999 WHERE tenant='other' AND name='secret'",
            "INSERT OR IGNORE INTO transfers VALUES ('other','past','a','b',999)",
            "UPDATE OR IGNORE transfers SET tenant='one',key='new',amount=999 WHERE tenant='other' AND key='past'",
            "INSERT OR IGNORE INTO audit(rowid,tenant,key,source,target,amount) SELECT rowid,'other','ignored','a','b',999 FROM audit WHERE key='past'",
            "UPDATE OR IGNORE audit SET rowid=NEW.rowid,amount=999 WHERE tenant='other' AND key='past'",
            "UPDATE accounts SET balance=balance WHERE tenant='other'",
            "UPDATE transfers SET amount=amount WHERE tenant='other'",
            "UPDATE audit SET amount=amount WHERE tenant='other'",
            "INSERT OR REPLACE INTO accounts SELECT * FROM accounts WHERE tenant='other' AND name='secret'",
        ]
        with database() as control:
            vault.transfer(control, **RECEIPT)
            expected = snapshot(control)
        for effect in effects:
            with self.subTest(effect=effect), database() as path:
                sql(path, f"CREATE TRIGGER benign AFTER INSERT ON audit BEGIN {effect}; END")
                self.assertEqual(vault.transfer(path, **RECEIPT), RECEIPT)
                self.assertEqual(snapshot(path), expected)

    def test_replace_through_additional_unique_indexes_preserves_rows(self):
        cases = [
            ("accounts", [
                "UPDATE accounts SET balance=90 WHERE tenant='other' AND name='secret'",
                "UPDATE accounts SET balance=21 WHERE tenant='other' AND name='b'",
                "CREATE UNIQUE INDEX unique_balance ON accounts(balance)",
            ], """BEFORE UPDATE ON accounts WHEN NEW.tenant='one' AND NEW.name='a'
                BEGIN UPDATE OR REPLACE accounts SET balance=NEW.balance
                    WHERE tenant=NEW.tenant AND name=NEW.name;
                SELECT RAISE(IGNORE); END"""),
            ("transfers", [
                "UPDATE transfers SET amount=10 WHERE tenant='other' AND key='past'",
                "CREATE UNIQUE INDEX unique_amount ON transfers(amount)",
            ], """BEFORE INSERT ON transfers WHEN NEW.tenant='one'
                BEGIN INSERT OR REPLACE INTO transfers VALUES
                    (NEW.tenant,NEW.key,NEW.source,NEW.target,NEW.amount);
                SELECT RAISE(IGNORE); END"""),
            ("audit", [
                "UPDATE audit SET amount=10 WHERE tenant='other' AND key='past'",
                "CREATE UNIQUE INDEX unique_amount ON audit(amount) WHERE key<>'duplicate-history'",
            ], """BEFORE INSERT ON audit WHEN NEW.tenant='one'
                BEGIN INSERT OR REPLACE INTO audit VALUES
                    (NEW.tenant,NEW.key,NEW.source,NEW.target,NEW.amount);
                SELECT RAISE(IGNORE); END"""),
        ]
        for table, setup, trigger in cases:
            with self.subTest(table=table), database() as path:
                for statement in setup:
                    sql(path, statement)
                sql(path, "CREATE TRIGGER secondary_replace " + trigger)
                before = snapshot(path)
                with self.assertRaises(sqlite3.Error):
                    vault.transfer(path, **RECEIPT)
                self.assertEqual(snapshot(path), before)

    def test_ignored_secondary_unique_conflict_remains_valid(self):
        sql(self.path, "UPDATE accounts SET balance=21 WHERE tenant='other' AND name='b'")
        sql(self.path, "CREATE UNIQUE INDEX unique_balance ON accounts(balance)")
        sql(self.path, """CREATE TRIGGER harmless_conflict AFTER INSERT ON audit BEGIN
            INSERT OR IGNORE INTO accounts VALUES ('other','phantom',1234);
            END""")
        with database() as control:
            sql(control, "UPDATE accounts SET balance=21 WHERE tenant='other' AND name='b'")
            vault.transfer(control, **RECEIPT)
            expected = snapshot(control)
        self.assertEqual(vault.transfer(self.path, **RECEIPT), RECEIPT)
        self.assertEqual(snapshot(self.path), expected)

    def test_rowid_relocation_and_benign_self_trigger_preserve_semantics(self):
        sql(self.path, """CREATE TRIGGER benign_update AFTER UPDATE ON accounts BEGIN
            UPDATE accounts SET balance=balance WHERE tenant=NEW.tenant AND name=NEW.name;
            END""")
        sql(self.path, """CREATE TRIGGER relocate AFTER INSERT ON audit BEGIN
            UPDATE accounts SET rowid=rowid+100 WHERE tenant='other';
            UPDATE transfers SET rowid=rowid+100;
            UPDATE audit SET rowid=rowid+100;
            END""")
        with database() as control:
            vault.transfer(control, **RECEIPT)
            expected = snapshot(control)
        self.assertEqual(vault.transfer(self.path, **RECEIPT), RECEIPT)
        self.assertEqual(snapshot(self.path), expected)
        old = dict(tenant="other", key="past", source="a", target="b", amount=7)
        self.assertEqual(vault.transfer(self.path, **old), old)
        self.assertEqual(vault.transfer(self.path, **RECEIPT), RECEIPT)
        self.assertEqual(snapshot(self.path), expected)

    def test_other_tenant_malformed_text_is_not_decoded_by_transfer(self):
        sql(self.path, "INSERT INTO accounts VALUES ('other',CAST(X'80' AS TEXT),CAST(X'81' AS TEXT))")
        sql(self.path, "INSERT INTO transfers VALUES ('other',CAST(X'80' AS TEXT),CAST(X'81' AS TEXT),'b',3)")
        sql(self.path, "INSERT INTO audit VALUES ('other',CAST(X'80' AS TEXT),CAST(X'81' AS TEXT),'b',3)")
        sql(self.path, """CREATE TRIGGER harmless AFTER INSERT ON audit BEGIN
            UPDATE accounts SET balance=balance WHERE tenant='other';
            UPDATE transfers SET source=source WHERE tenant='other';
            UPDATE audit SET source=source WHERE tenant='other';
            END""")
        before = snapshot(self.path)
        self.assertEqual(vault.transfer(self.path, **RECEIPT), RECEIPT)
        after = snapshot(self.path)
        for table in before:
            self.assertEqual([row for row in before[table] if row[0] == b"other"],
                             [row for row in after[table] if row[0] == b"other"])
        self.assertEqual(vault.balance(self.path, "one", "a"), 90)

    def test_account_queries_use_authenticated_scope_even_with_foreign_effects(self):
        sql(self.path, """CREATE TRIGGER foreign_noop AFTER INSERT ON audit BEGIN
            UPDATE accounts SET balance=balance WHERE tenant='other';
            END""")
        statements = []
        connect = sqlite3.connect

        def traced(*args, **kwargs):
            con = connect(*args, **kwargs)
            con.set_trace_callback(statements.append)
            return con

        with patch.object(sqlite3, "connect", traced):
            self.assertEqual(vault.transfer(self.path, **RECEIPT), RECEIPT)
            self.assertEqual(vault.transfer(self.path, **RECEIPT), RECEIPT)
            self.assertEqual(vault.balance(self.path, "one", "a"), 90)
        # Inspect actual SQL, including installed preservation triggers. OLD/NEW
        # change events are allowed; fetching stored foreign accounts is not.
        reads = [statement for statement in statements
                 if re.search(r"\bFROM\s+(?:main\.)?accounts\b", statement, re.I)]
        self.assertTrue(reads)
        unscoped = [statement for statement in reads
                    if not re.search(r"\bWHERE\s+(?:\w+\.)?tenant\s*=\s*'one'(?=\s|[);]|$)", statement)]
        self.assertEqual(unscoped, [])

    def test_when_trigger_values_and_with_preserve_behavior_and_schema(self):
        with database() as control:
            vault.transfer(control, **RECEIPT)
            expected = snapshot(control)
        for body in TRIGGER_SELECT_BODIES:
            for condition in ("1", "0"):
                with self.subTest(body=body, condition=condition), database() as path:
                    sql(path, "CREATE TABLE events(message)")
                    sql(path, f"""CREATE TRIGGER benign AFTER INSERT ON audit
                        WHEN {condition} BEGIN {body};
                        INSERT INTO events VALUES ('fired'); END""")
                    with closing(sqlite3.connect(path)) as con:
                        schema = con.execute("SELECT type,name,sql FROM sqlite_master ORDER BY type,name").fetchall()
                    self.assertEqual(vault.transfer(path, **RECEIPT), RECEIPT)
                    self.assertEqual(vault.balance(path, "one", "a"), 90)
                    self.assertEqual(vault.balance(path, "one", "b"), 20)
                    self.assertEqual(snapshot(path), expected)
                    with closing(sqlite3.connect(path)) as con:
                        events = con.execute("SELECT * FROM events").fetchall()
                        self.assertEqual(events, [("fired",)] if condition == "1" else [])
                        self.assertEqual(con.execute("SELECT type,name,sql FROM sqlite_master ORDER BY type,name").fetchall(), schema)
                    # Reopening preserves existing receipts and skips trigger replay.
                    old = dict(tenant="other", key="past", source="a", target="b", amount=7)
                    self.assertEqual(vault.transfer(path, **old), old)
                    self.assertEqual(vault.transfer(path, **RECEIPT), RECEIPT)
                    self.assertEqual(snapshot(path), expected)
                    with closing(sqlite3.connect(path)) as con:
                        self.assertEqual(con.execute("SELECT * FROM events").fetchall(), events)

    def test_when_trigger_values_and_with_failures_roll_back(self):
        for body in TRIGGER_SELECT_BODIES:
            with self.subTest(body=body), database() as path:
                sql(path, f"""CREATE TRIGGER failure AFTER INSERT ON audit
                    WHEN NEW.key='fail' BEGIN {body};
                    SELECT RAISE(ABORT, 'private audit failure'); END""")
                before = snapshot(path)
                with closing(sqlite3.connect(path)) as con:
                    schema = con.execute("SELECT type,name,sql FROM sqlite_master ORDER BY type,name").fetchall()
                with self.assertRaises(sqlite3.Error):
                    vault.transfer(path, **dict(RECEIPT, key="fail"))
                self.assertEqual(snapshot(path), before)
                with closing(sqlite3.connect(path)) as con:
                    self.assertEqual(con.execute("SELECT type,name,sql FROM sqlite_master ORDER BY type,name").fetchall(), schema)
                self.assertEqual(vault.transfer(path, **RECEIPT), RECEIPT)

    def test_stored_trigger_semantics_match_sqlite_with_recursion_disabled(self):
        definitions = [
            """CREATE TRIGGER begin BEFORE UPDATE ON accounts
                WHEN NEW.tenant='one' AND NEW.name='a' BEGIN
                INSERT INTO events VALUES ('before; RAISE(IGNORE) in text');
                UPDATE accounts SET balance=NEW.balance
                    WHERE tenant=NEW.tenant AND name=NEW.name;
                SELECT CASE WHEN NEW.balance>=0 THEN RAISE(IGNORE) END;
                END""",
            """CREATE TRIGGER état AFTER UPDATE ON accounts BEGIN
                INSERT INTO events VALUES ('état ' || NEW.name);
                UPDATE accounts SET balance=balance
                    WHERE tenant=NEW.tenant AND name=NEW.name;
                END""",
            """CREATE TRIGGER "select" AFTER INSERT ON audit BEGIN
                INSERT INTO events VALUES ('select');
                INSERT OR REPLACE INTO accounts VALUES ('other','secret',1234);
                UPDATE accounts SET rowid=rowid+100 WHERE tenant='other';
                END""",
            """CREATE TRIGGER "quoted""name" AFTER INSERT ON audit BEGIN
                INSERT INTO events VALUES ('quoted');
                DELETE FROM accounts WHERE tenant='other' AND name='secret';
                INSERT INTO accounts VALUES ('other','secret',1234);
                END""",
            """CREATE TRIGGER [delete event] AFTER DELETE ON accounts BEGIN
                INSERT INTO events VALUES ('explicit delete');
                END""",
        ]
        with database() as control:
            for path in (self.path, control):
                sql(path, "CREATE TABLE events(message)")
                for definition in definitions:
                    sql(path, definition)
            with closing(sqlite3.connect(control)) as con, con:
                con.execute("PRAGMA recursive_triggers=OFF")
                con.execute("UPDATE accounts SET balance=90 WHERE tenant='one' AND name='a'")
                con.execute("UPDATE accounts SET balance=20 WHERE tenant='one' AND name='b'")
                for table in ("transfers", "audit"):
                    con.execute(f"INSERT INTO {table} VALUES (?,?,?,?,?)", tuple(RECEIPT.values()))
            with closing(sqlite3.connect(self.path)) as con:
                schema = con.execute("SELECT type,name,sql FROM sqlite_master ORDER BY type,name").fetchall()
            self.assertEqual(vault.transfer(self.path, **RECEIPT), RECEIPT)
            self.assertEqual(snapshot(self.path), snapshot(control))
            with closing(sqlite3.connect(control)) as con:
                events = con.execute("SELECT * FROM events").fetchall()
            self.assertEqual(events.count(("explicit delete",)), 1)
            with closing(sqlite3.connect(self.path)) as con:
                self.assertEqual(con.execute("SELECT * FROM events").fetchall(), events)
                self.assertEqual(con.execute("SELECT type,name,sql FROM sqlite_master ORDER BY type,name").fetchall(), schema)
            # Reopening replays without invoking the stored triggers again.
            old = dict(tenant="other", key="past", source="a", target="b", amount=7)
            self.assertEqual(vault.transfer(self.path, **old), old)
            self.assertEqual(vault.transfer(self.path, **RECEIPT), RECEIPT)
            with closing(sqlite3.connect(self.path)) as con:
                self.assertEqual(con.execute("SELECT * FROM events").fetchall(), events)

    def concurrent(self, requests):
        barrier = Barrier(len(requests))

        def run(request):
            barrier.wait(timeout=10)
            try:
                return vault.transfer(self.path, **request)
            except ValueError as error:
                return error

        with ThreadPoolExecutor(max_workers=len(requests)) as pool:
            return list(pool.map(run, requests))

    def test_simultaneous_duplicates_execute_once_and_replay_after_reopen(self):
        results = self.concurrent([RECEIPT] * 12)
        self.assertEqual(results, [RECEIPT] * 12)
        self.assertEqual(vault.balance(self.path, "one", "a"), 90)
        self.assertEqual(vault.balance(self.path, "one", "b"), 20)
        with closing(sqlite3.connect(self.path)) as con:
            for table in ("transfers", "audit"):
                self.assertEqual(con.execute(f"SELECT count(*) FROM {table} WHERE tenant='one' AND key='new'").fetchone()[0], 1)
        before = snapshot(self.path)
        vault.init_db(self.path)
        self.assertEqual(vault.transfer(self.path, **RECEIPT), RECEIPT)
        self.assertEqual(snapshot(self.path), before)

    def test_simultaneous_distinct_keys_never_overspend(self):
        requests = [dict(RECEIPT, amount=15, key=f"spend-{i}") for i in range(12)]
        results = self.concurrent(requests)
        successes = [result for result in results if isinstance(result, dict)]
        self.assertEqual(len(successes), 6)
        self.assertEqual(sum(isinstance(result, ValueError) for result in results), 6)
        self.assertEqual(vault.balance(self.path, "one", "a"), 10)
        self.assertEqual(vault.balance(self.path, "one", "b"), 100)
        with closing(sqlite3.connect(self.path)) as con:
            for table in ("transfers", "audit"):
                self.assertEqual(con.execute(f"SELECT count(*) FROM {table} WHERE tenant='one' AND key LIKE 'spend-%'").fetchone()[0], 6)

    def test_simultaneous_distinct_sources_never_lose_credits(self):
        requests = [dict(RECEIPT, source="a" if i % 2 else "c", amount=5, key=f"credit-{i}")
                    for i in range(12)]
        self.assertEqual(self.concurrent(requests), requests)
        self.assertEqual(vault.balance(self.path, "one", "a"), 70)
        self.assertEqual(vault.balance(self.path, "one", "c"), 40)
        self.assertEqual(vault.balance(self.path, "one", "b"), 70)

    def test_simultaneous_conflicts_have_exactly_one_winner(self):
        requests = [dict(RECEIPT, amount=10 if i % 2 else 20) for i in range(10)]
        results = self.concurrent(requests)
        receipts = [result for result in results if isinstance(result, dict)]
        self.assertEqual(len(receipts), 5)
        self.assertTrue(all(receipt == receipts[0] for receipt in receipts))
        self.assertEqual(sum(isinstance(result, ValueError) for result in results), 5)
        self.assertEqual(vault.balance(self.path, "one", "a"), 100 - receipts[0]["amount"])
        self.assertEqual(vault.balance(self.path, "one", "b"), 10 + receipts[0]["amount"])
        with closing(sqlite3.connect(self.path)) as con:
            self.assertEqual(con.execute("SELECT count(*) FROM audit WHERE tenant='one' AND key='new'").fetchone()[0], 1)


class CLITests(unittest.TestCase):
    def setUp(self):
        self.path = self.enterContext(database())

    def cli(self, request):
        return self.invoke([str(self.path), json.dumps(request)])

    def invoke(self, args):
        return subprocess.run([sys.executable, "-B", str(ROOT / "app.py"), *args],
                              cwd=ROOT, text=True, capture_output=True, timeout=15)

    def success(self, request):
        result = self.cli(request)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stderr, "")
        self.assertEqual(len(result.stdout.splitlines()), 1)
        return json.loads(result.stdout)

    def failure(self, result):
        self.assertEqual(result.returncode, 2)
        self.assertEqual(result.stdout, "")
        self.assertEqual(len(result.stderr.splitlines()), 1)
        error = json.loads(result.stderr)
        self.assertIsInstance(error, dict)
        self.assertIn("error", error)
        for secret in ("Traceback", "SELECT", "INSERT", "private", "secret", "1234", "other"):
            self.assertNotIn(secret, result.stderr)
        return error

    def test_integrated_transfer_replay_isolation_failure_and_recovery(self):
        read = dict(op="balance", tenant="one", account="a")
        request = dict(RECEIPT, op="transfer")
        self.assertEqual(self.success(read), 100)
        self.assertEqual(self.success(request), RECEIPT)
        self.assertEqual(self.success(read), 90)
        self.assertEqual(self.success(dict(read, account="b")), 20)
        before = snapshot(self.path)
        self.assertEqual(self.success(request), RECEIPT)
        self.failure(self.cli(dict(request, amount=11)))
        hidden = self.failure(self.cli(dict(read, account="secret")))
        self.assertEqual(hidden, self.failure(self.cli(dict(read, account="absent"))))
        self.assertEqual(snapshot(self.path), before)
        other = dict(RECEIPT, tenant="other", amount=5)
        self.assertEqual(self.success(dict(other, op="transfer")), other)
        sql(self.path, """CREATE TRIGGER failed_audit BEFORE INSERT ON audit
            WHEN NEW.key='fail' BEGIN SELECT RAISE(ABORT, 'private SELECT other secret 1234'); END""")
        before = snapshot(self.path)
        self.assertEqual(hidden, self.failure(self.cli(dict(request, key="fail"))))
        self.assertEqual(snapshot(self.path), before)
        recovered = dict(RECEIPT, key="recovery")
        self.assertEqual(self.success(dict(recovered, op="transfer")), recovered)
        self.assertEqual(self.success(read), 80)
        with closing(sqlite3.connect(self.path)) as con:
            self.assertIsNotNone(con.execute("SELECT 1 FROM sqlite_master WHERE name='failed_audit'").fetchone())
            self.assertEqual(con.execute("SELECT count(*) FROM audit WHERE tenant='one' AND key='recovery'").fetchone()[0], 1)

    def test_when_trigger_values_and_with_succeed_and_replay(self):
        for index, body in enumerate(TRIGGER_SELECT_BODIES):
            with self.subTest(body=body):
                sql(self.path, f"""CREATE TRIGGER benign_{index} AFTER INSERT ON audit
                    WHEN 1 BEGIN {body}; END""")
                receipt = dict(RECEIPT, key=f"grammar-{index}")
                request = dict(receipt, op="transfer")
                self.assertEqual(self.success(request), receipt)
                self.assertEqual(self.success(dict(op="balance", tenant="one", account="a")),
                                 100 - 10 * (index + 1))
                self.assertEqual(self.success(dict(op="balance", tenant="one", account="b")),
                                 10 + 10 * (index + 1))
                after = snapshot(self.path)
                self.assertEqual(self.success(request), receipt)
                self.assertEqual(snapshot(self.path), after)

    def test_invalid_arguments_json_and_operations_are_generic(self):
        requests = [None, [], 42, "balance", {}, {"op": "init_db"}, {"op": "__dict__"},
                    {"op": "balance", "tenant": "one"},
                    {"op": "balance", "tenant": "one", "account": "a", "extra": 1},
                    {"op": "balance", "tenant": [], "account": "a"},
                    dict(RECEIPT, op="transfer", amount=True),
                    dict(RECEIPT, op="transfer", target="secret")]
        arguments = [[], [str(self.path)], [str(self.path), "{}", "extra"],
                     [str(self.path), "{"],
                     [str(self.path), '{"op":"balance","tenant":"other","tenant":"one","account":"a"}']]
        arguments.extend([str(self.path), json.dumps(request)] for request in requests)
        arguments.append([str(self.path.parent / "missing" / "db.sqlite"),
                          json.dumps(dict(op="balance", tenant="one", account="a"))])
        before = snapshot(self.path)
        errors = [self.failure(self.invoke(args)) for args in arguments]
        self.assertTrue(all(error == errors[0] for error in errors))
        self.assertEqual(snapshot(self.path), before)


if __name__ == "__main__":
    unittest.main()
