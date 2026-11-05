import unittest
from ledger import Ledger
class PublicTests(unittest.TestCase):
    def test_transfer(self):
        ledger=Ledger({'a':100,'b':0})
        ledger.transfer('a','b',20,'one')
        self.assertEqual(ledger.balances, {'a':80,'b':20})
