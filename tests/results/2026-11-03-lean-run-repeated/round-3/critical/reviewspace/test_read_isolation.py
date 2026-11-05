"""Public-interface regressions for isolation during transfer integrity checks."""

import json
import re
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

import vault


ROOT = Path(__file__).resolve().parent


class ReadIsolationTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(dir=ROOT)
        self.addCleanup(tmp.cleanup)
        self.path = Path(tmp.name) / "vault.sqlite"
        vault.init_db(self.path)
        with closing(sqlite3.connect(self.path)) as con, con:
            con.executemany("INSERT INTO accounts VALUES (?, ?, ?)", [
                ("alpha", "a", 100), ("alpha", "b", 0),
                ("beta", "a", 999), ("beta", "b", 1),
            ])
        self.request = dict(tenant="alpha", source="a", target="b", amount=10, key="k")

    def poison_other_tenant(self, table):
        with closing(sqlite3.connect(self.path)) as con, con:
            if table == "accounts":
                con.execute("INSERT INTO accounts VALUES "
                            "('beta', CAST(X'626574612d707269766174652d736563726574ff' AS TEXT), 999)")
            else:
                # Reuse alpha's key to exercise both new and cached receipt isolation.
                con.execute(f"INSERT INTO {table} VALUES "
                            "('beta', 'k', CAST(X'626574612d707269766174652d736563726574ff' AS TEXT), 'b', 7)")

    def contents(self, tenant=None):
        with closing(sqlite3.connect(self.path)) as con:
            # Test-only byte reads can compare malformed foreign data without decoding it.
            con.text_factory = bytes
            condition, values = ("", ()) if tenant is None else (" WHERE tenant=?", (tenant,))
            return {table: con.execute(f"SELECT * FROM {table}{condition} ORDER BY rowid", values).fetchall()
                    for table in ("accounts", "transfers", "audit")}

    def schema(self):
        with closing(sqlite3.connect(self.path)) as con:
            return con.execute("SELECT type, name, tbl_name, sql FROM sqlite_master "
                               "ORDER BY type, name").fetchall()

    def cli(self, request):
        return subprocess.run([sys.executable, "-B", str(ROOT / "app.py"),
                               str(self.path), json.dumps(request)], cwd=ROOT,
                              capture_output=True, text=True, timeout=10)

    def assert_success(self, result, expected):
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stderr, "")
        self.assertEqual(len(result.stdout.splitlines()), 1)
        self.assertEqual(json.loads(result.stdout), expected)

    def test_account_and_receipt_selects_have_authenticated_tenant_predicates(self):
        statements = []
        connect = sqlite3.connect

        def traced_connect(*args, **kwargs):
            con = connect(*args, **kwargs)
            con.set_trace_callback(statements.append)
            return con

        with patch.object(vault.sqlite3, "connect", traced_connect):
            self.assertEqual(vault.balance(self.path, "alpha", "a"), 100)
            self.assertEqual(vault.transfer(self.path, **self.request), self.request)
            self.assertEqual(vault.transfer(self.path, **self.request), self.request)
            with self.assertRaises(ValueError):
                vault.transfer(self.path, **dict(self.request, amount=11))
            with self.assertRaises(ValueError):
                vault.balance(self.path, "alpha", "missing")

        reads = [statement for statement in statements
                 if re.match(r"\s*SELECT\b", statement, re.I)
                 and re.search(r"\bFROM\s+(?:main\.)?(accounts|transfers)\b", statement, re.I)]
        self.assertTrue(reads)
        for statement in reads:
            with self.subTest(statement=statement):
                self.assertRegex(statement, r"(?i)\bWHERE\s+tenant\s*=\s*'alpha'")

    def test_foreign_malformed_text_does_not_affect_transfer_or_replay(self):
        for table in ("accounts", "transfers", "audit"):
            with self.subTest(table=table):
                self.poison_other_tenant(table)
                foreign, schema = self.contents("beta"), self.schema()
                request = dict(self.request, key=f"key-{table}")
                self.assertEqual(vault.transfer(self.path, **request), request)
                after = self.contents()
                self.assertEqual(vault.transfer(self.path, **request), request)
                self.assertEqual(self.contents(), after)
                self.assertEqual(self.contents("beta"), foreign)
                self.assertEqual(self.schema(), schema)
        self.assertEqual(vault.balance(self.path, "alpha", "a"), 70)
        self.assertEqual(vault.balance(self.path, "alpha", "b"), 30)

    def test_cli_transfer_replay_conflict_and_balance_with_foreign_malformed_text(self):
        for table in ("accounts", "transfers", "audit"):
            self.poison_other_tenant(table)
        foreign, schema = self.contents("beta"), self.schema()
        request = dict(op="transfer", **self.request)
        self.assert_success(self.cli(request), self.request)
        after = self.contents()
        self.assert_success(self.cli(request), self.request)
        failed = self.cli(dict(request, amount=11))
        self.assertEqual((failed.returncode, failed.stdout, failed.stderr),
                         (2, "", '{"error": "request failed"}\n'))
        for account, expected in (("a", 90), ("b", 10)):
            self.assert_success(self.cli(dict(op="balance", tenant="alpha", account=account)), expected)
        self.assertEqual(self.contents(), after)
        self.assertEqual(self.contents("beta"), foreign)
        self.assertEqual(self.schema(), schema)
        for table in ("transfers", "audit"):
            self.assertEqual(after[table].count((b"alpha", b"k", b"a", b"b", 10)), 1)

    def test_foreign_noop_and_rowid_trigger_effects_do_not_decode_rows(self):
        for table in ("accounts", "transfers", "audit"):
            self.poison_other_tenant(table)
        with closing(sqlite3.connect(self.path)) as con, con:
            con.execute("CREATE TRIGGER harmless AFTER INSERT ON audit BEGIN "
                        "INSERT OR IGNORE INTO accounts VALUES ('beta', 'a', 0); "
                        "UPDATE accounts SET balance=balance, rowid=rowid+1000 WHERE tenant='beta'; "
                        "UPDATE transfers SET amount=amount, rowid=rowid+1000 WHERE tenant='beta'; "
                        "UPDATE audit SET amount=amount, rowid=rowid+1000 WHERE tenant='beta'; END")
        foreign, schema = self.contents("beta"), self.schema()
        self.assertEqual(vault.transfer(self.path, **self.request), self.request)
        after = self.contents()
        self.assertEqual(vault.transfer(self.path, **self.request), self.request)
        self.assertEqual(self.contents(), after)
        self.assertEqual(self.contents("beta"), foreign)
        self.assertEqual(self.schema(), schema)

    def test_foreign_trigger_mutations_roll_back_without_decoding_private_text(self):
        for table in ("accounts", "transfers", "audit"):
            self.poison_other_tenant(table)
        mutations = [
            "UPDATE accounts SET balance=0 WHERE tenant='beta';",
            "DELETE FROM transfers WHERE tenant='beta';",
            "UPDATE audit SET amount=amount+1 WHERE tenant='beta';",
            # REPLACE can suppress DELETE triggers; deleting its replacement
            # must not conceal the loss of the original account or receipt.
            "INSERT OR REPLACE INTO accounts VALUES ('beta', 'a', 0); "
            "DELETE FROM accounts WHERE tenant='beta' AND name='a';",
            "INSERT OR REPLACE INTO transfers VALUES ('beta', 'k', 'a', 'b', 1); "
            "DELETE FROM transfers WHERE tenant='beta' AND key='k';",
        ]
        for body in mutations:
            with self.subTest(body=body):
                with closing(sqlite3.connect(self.path)) as con, con:
                    con.execute(f"CREATE TRIGGER mutation AFTER INSERT ON audit BEGIN {body} END")
                before, schema = self.contents(), self.schema()
                try:
                    with self.assertRaises(sqlite3.IntegrityError) as error:
                        vault.transfer(self.path, **self.request)
                    self.assertNotIn("beta", str(error.exception))
                    self.assertEqual(self.contents(), before)
                    self.assertEqual(self.schema(), schema)
                finally:
                    with closing(sqlite3.connect(self.path)) as con, con:
                        con.execute("DROP TRIGGER mutation")
        self.assertEqual(vault.transfer(self.path, **self.request), self.request)

    def test_rowid_replacement_cannot_silently_delete_existing_rows(self):
        with closing(sqlite3.connect(self.path)) as con, con:
            for table in ("transfers", "audit"):
                con.executemany(f"INSERT INTO {table} VALUES (?, ?, ?, ?, ?)", [
                    ("beta", "old-1", "a", "b", 1),
                    ("beta", "old-2", "a", "b", 2),
                ])
        for table in ("accounts", "transfers", "audit"):
            with self.subTest(table=table):
                with closing(sqlite3.connect(self.path)) as con, con:
                    victim, moved = con.execute(
                        f"SELECT rowid FROM {table} WHERE tenant='beta' ORDER BY rowid"
                    ).fetchall()
                    con.execute("CREATE TRIGGER collision AFTER INSERT ON audit BEGIN "
                                f"UPDATE OR REPLACE {table} SET rowid={victim[0]} "
                                f"WHERE rowid={moved[0]}; END")
                before, schema = self.contents(), self.schema()
                try:
                    with self.assertRaises(sqlite3.IntegrityError):
                        vault.transfer(self.path, **self.request)
                    self.assertEqual(self.contents(), before)
                    self.assertEqual(self.schema(), schema)
                finally:
                    with closing(sqlite3.connect(self.path)) as con, con:
                        con.execute("DROP TRIGGER collision")
        with closing(sqlite3.connect(self.path)) as con, con:
            con.execute("CREATE TRIGGER relocation AFTER INSERT ON audit BEGIN "
                        "UPDATE OR REPLACE accounts SET rowid=rowid+1000; "
                        "UPDATE OR REPLACE transfers SET rowid=rowid+1000; "
                        "UPDATE OR REPLACE audit SET rowid=rowid+1000; END")
        foreign, schema = self.contents("beta"), self.schema()
        self.assertEqual(vault.transfer(self.path, **self.request), self.request)
        self.assertEqual(self.contents("beta"), foreign)
        self.assertEqual(self.schema(), schema)


if __name__ == "__main__":
    unittest.main()
