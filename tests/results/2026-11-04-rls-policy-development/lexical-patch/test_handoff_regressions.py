"""Regressions for final review F2 (REPLACE UPSERT, main-qualified trigger) and R3."""
from contextlib import closing
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest

import vault

HERE = Path(__file__).resolve().parent
UPSERT = """CREATE TRIGGER guard BEFORE INSERT ON audit BEGIN
  {verb} INTO accounts VALUES('beta','private',0)
  ON CONFLICT(tenant,name) DO UPDATE SET balance=accounts.balance WHERE accounts.balance=777;
  SELECT CASE WHEN changes()=1 THEN RAISE(ABORT,'audit rule') END;
END;"""
OBSERVE = """CREATE TRIGGER observe BEFORE UPDATE ON {target}
WHEN OLD.tenant='beta' AND OLD.balance=777 BEGIN SELECT RAISE(ABORT,'foreign balance'); END;
CREATE TRIGGER invoke AFTER INSERT ON audit BEGIN
  UPDATE accounts SET balance=balance WHERE tenant='beta' AND name='private';
END;"""
NATURAL = "(SELECT balance FROM accounts NATURAL JOIN (SELECT 'alpha' AS tenant,'cash' AS name))"


class HandoffRegressions(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def db(self, sql, foreign=777, name='db'):
        self.count = getattr(self, 'count', 0) + 1
        path = Path(self.tmp.name) / f'{name}-{foreign}-{self.count}.sqlite'
        vault.init_db(path)
        with closing(sqlite3.connect(path)) as con, con:
            con.executemany('INSERT INTO accounts VALUES (?,?,?)',
                            [('alpha', 'cash', 100), ('alpha', 'savings', 0), ('beta', 'private', foreign)])
            con.executescript(sql)
        return path

    def state(self, path):
        with closing(sqlite3.connect(path)) as con:
            return [con.execute(f'SELECT * FROM {t} ORDER BY rowid').fetchall()
                    for t in ('accounts', 'transfers', 'audit')] + [
                con.execute('SELECT type,name,sql FROM sqlite_schema ORDER BY type,name').fetchall()]

    def outcome(self, path):
        before = self.state(path)
        try:
            receipt = vault.transfer(path, 'alpha', 'cash', 'savings', 10, 'k')
        except sqlite3.Error as error:
            self.assertEqual(self.state(path), before)
            return 'rejected', str(error)
        after = self.state(path)
        self.assertEqual(after[0], [('alpha', 'cash', 90), ('alpha', 'savings', 10), before[0][2]])
        self.assertEqual(after[3], before[3])
        return 'success', receipt

    def cli(self, path):
        request = json.dumps(dict(op='transfer', tenant='alpha', source='cash', target='savings',
                                  amount=10, key='k'))
        run = subprocess.run([sys.executable, '-B', str(HERE / 'app.py'), str(path), request],
                             capture_output=True, text=True, timeout=30)
        return run.returncode, run.stdout, run.stderr

    def test_foreign_balance_is_not_observable_through_equivalent_forms(self):
        for sql in (UPSERT.format(verb='REPLACE'), UPSERT.format(verb='INSERT OR REPLACE'),
                    OBSERVE.format(target='main.accounts'), OBSERVE.format(target='accounts')):
            with self.subTest(sql=sql.split('\n')[0]):
                api = [self.outcome(self.db(sql, foreign, 'api')) for foreign in (777, 778)]
                cli = [self.cli(self.db(sql, foreign, 'cli')) for foreign in (777, 778)]
                self.assertEqual(api[0], api[1])
                self.assertEqual(cli[0], cli[1])
                self.assertEqual(api[0][0], 'success')

    def test_natural_join_tenant_guard_keeps_native_behavior(self):
        for view in (False, True):
            source = '(SELECT balance FROM local_cash)' if view else NATURAL
            prefix = f'CREATE VIEW local_cash AS SELECT balance FROM accounts NATURAL JOIN ' \
                     f"(SELECT 'alpha' AS tenant,'cash' AS name);" if view else ''
            for threshold, expected in ((999, 'success'), (90, 'rejected')):
                with self.subTest(view=view, threshold=threshold):
                    sql = prefix + (f'CREATE TRIGGER natural_guard BEFORE INSERT ON audit '
                                    f'WHEN {source}={threshold} '
                                    f"BEGIN SELECT RAISE(ABORT,'local guard'); END;")
                    status, detail = self.outcome(self.db(sql))
                    self.assertEqual(status, expected)
                    if expected == 'rejected':
                        self.assertEqual(detail, 'local guard')


if __name__ == '__main__':
    unittest.main()
