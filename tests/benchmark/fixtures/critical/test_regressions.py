"""Regression checks every synthetic Critical candidate passes."""
import sqlite3
import tempfile
import unittest
from pathlib import Path

import vault


class RegressionTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix='synthetic-regressions-')
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / 'ledger.sqlite'
        vault.init_db(self.path)
        with sqlite3.connect(self.path) as con:
            con.executemany('INSERT INTO accounts VALUES (?,?,?)',
                            [('one', 'a', 100), ('one', 'b', 0), ('two', 'a', 700)])

    def test_exact_replay_returns_the_original_receipt(self):
        first = vault.transfer(self.path, 'one', 'a', 'b', 10, 'k')
        self.assertEqual(vault.transfer(self.path, 'one', 'a', 'b', 10, 'k'), first)
        self.assertEqual(vault.balance(self.path, 'one', 'a'), 90)

    def test_insufficient_funds_change_nothing(self):
        with self.assertRaises(ValueError):
            vault.transfer(self.path, 'one', 'a', 'b', 101, 'big')
        self.assertEqual(vault.balance(self.path, 'one', 'a'), 100)

    def test_other_tenant_account_is_unavailable(self):
        with self.assertRaises(ValueError):
            vault.balance(self.path, 'one', 'secret')
        self.assertEqual(vault.balance(self.path, 'two', 'a'), 700)


if __name__ == '__main__':
    unittest.main()
