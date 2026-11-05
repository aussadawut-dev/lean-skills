import sqlite3
import tempfile
import unittest
from pathlib import Path
import vault
class PublicTests(unittest.TestCase):
    def test_valid_transfer(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'db.sqlite'
            vault.init_db(path)
            with sqlite3.connect(path) as con:
                con.executemany('INSERT INTO accounts VALUES (?,?,?)', [('one','a',100),('one','b',0)])
            vault.transfer(path,'one','a','b',10,'k')
            self.assertEqual(vault.balance(path,'one','a'),90)
