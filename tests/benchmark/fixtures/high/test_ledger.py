import unittest

from ledger import Ledger


class LedgerTests(unittest.TestCase):
    def test_failed_batch_restores_prior_state(self):
        ledger = Ledger({'a': 50, 'b': 0})
        ledger.transfer('a', 'b', 5, 'first')
        with self.assertRaises(ValueError):
            ledger.batch([dict(source='a', target='b', amount=10, key='two'),
                          dict(source='a', target='b', amount=100, key='three')])
        self.assertEqual(ledger.balances, {'a': 45, 'b': 5})
        self.assertEqual(set(ledger.history), {'first'})

    def test_replay_returns_equal_receipt_without_second_debit(self):
        ledger = Ledger({'a': 50, 'b': 0})
        first = ledger.transfer('a', 'b', 5, 'k')
        self.assertEqual(ledger.transfer('a', 'b', 5, 'k'), first)
        self.assertEqual(ledger.balances, {'a': 45, 'b': 5})


if __name__ == '__main__':
    unittest.main()
