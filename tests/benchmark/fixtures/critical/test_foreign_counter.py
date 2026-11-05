"""A pre-policy expectation: a trigger counts every tenant's audit rows.

Under row-level security the other tenant's row is invisible during the
transfer, so this suite fails on every row-hiding candidate. The synthetic
policy record lists that failure as superseded.
"""
import sqlite3
import tempfile
import unittest
from pathlib import Path

import vault


class ForeignCounterTests(unittest.TestCase):
    def test_counter_sees_all_tenants(self):
        with tempfile.TemporaryDirectory(prefix='synthetic-counter-') as directory:
            path = Path(directory) / 'ledger.sqlite'
            vault.init_db(path)
            with sqlite3.connect(path) as con:
                con.executemany('INSERT INTO accounts VALUES (?,?,?)',
                                [('one', 'a', 100), ('one', 'b', 0), ('two', 'x', 5)])
                con.execute('INSERT INTO audit VALUES (?,?,?,?,?)', ('two', 'old', 'x', 'x', 1))
                con.execute('CREATE TABLE tally(rows INTEGER)')
                con.execute('CREATE TRIGGER tally_audit AFTER INSERT ON audit '
                            'BEGIN INSERT INTO tally SELECT count(*) FROM audit; END')
            vault.transfer(path, 'one', 'a', 'b', 10, 'k')
            with sqlite3.connect(path) as con:
                self.assertEqual(con.execute('SELECT rows FROM tally').fetchone()[0], 2)


if __name__ == '__main__':
    unittest.main()
