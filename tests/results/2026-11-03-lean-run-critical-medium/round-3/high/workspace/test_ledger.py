from copy import deepcopy
import unittest

from ledger import Ledger


def operation(source='a', target='b', amount=10, key='new'):
    return dict(source=source, target=target, amount=amount, key=key)


class LedgerTests(unittest.TestCase):
    def assert_rejected_unchanged(self, ledger, action):
        balances, history = ledger.balances, ledger.history
        before = deepcopy((balances, history))
        with self.assertRaises(ValueError):
            action()
        self.assertEqual((ledger.balances, ledger.history), before)
        self.assertIs(ledger.balances, balances)
        self.assertIs(ledger.history, history)

    def seeded_ledger(self):
        ledger = Ledger({'a': 100, 'b': 0, 'c': 0, 'untouched': 7})
        ledger.transfer('a', 'c', 5, 'seed')
        return ledger

    def test_constructor_copies_input_and_accepts_valid_boundaries(self):
        initial = {'': 10**30, 'b': 0}
        ledger = Ledger(initial)
        initial['b'] = 50
        initial['outside'] = 1
        self.assertEqual(ledger.balances, {'': 10**30, 'b': 0})
        receipt = ledger.transfer('', 'b', 10**30, ' ')
        self.assertEqual(receipt, operation('', 'b', 10**30, ' '))
        self.assertEqual(ledger.balances, {'': 0, 'b': 10**30})
        self.assertEqual(initial, {'': 10**30, 'b': 50, 'outside': 1})
        self.assertEqual(Ledger({}).batch([]), [])

    def test_constructor_rejects_invalid_balances_without_changing_input(self):
        for value in (-1, True, False, 1.0, '1', None, [], {}):
            with self.subTest(value=value):
                initial = {'valid': 10, 'invalid': value}
                before = deepcopy(initial)
                with self.assertRaises(ValueError):
                    Ledger(initial)
                self.assertEqual(initial, before)
        for initial in (None, [], [('a', 1)], 'a', {1: 10}, {None: 10}):
            with self.subTest(initial=initial):
                with self.assertRaises(ValueError):
                    Ledger(initial)

    def test_transfer_records_exact_receipt_and_preserves_other_state(self):
        ledger = self.seeded_ledger()
        balances, history = ledger.balances, ledger.history
        seed = deepcopy(history['seed'])
        receipt = ledger.transfer('a', 'b', 20, 'payment')
        expected = operation('a', 'b', 20, 'payment')
        self.assertEqual(receipt, expected)
        self.assertEqual(ledger.balances, {'a': 75, 'b': 20, 'c': 5, 'untouched': 7})
        self.assertEqual(ledger.history, {'seed': seed, 'payment': expected})
        self.assertIs(ledger.balances, balances)
        self.assertIs(ledger.history, history)

    def test_invalid_transfers_leave_balances_and_history_unchanged(self):
        cases = [
            ('insufficient funds', {'amount': 96}),
            ('same account', {'target': 'a'}),
            ('missing source', {'source': 'missing'}),
            ('missing target', {'target': 'missing'}),
        ]
        for amount in (0, -1, True, False, 1.0, '1', None, [], {}):
            cases.append(('invalid amount', {'amount': amount}))
        for key in ('', None, 1, True, [], {}):
            cases.append(('invalid key', {'key': key}))
        for field in ('source', 'target'):
            for value in (None, 1, True, [], {}):
                cases.append(('invalid account', {field: value}))
        for label, changes in cases:
            with self.subTest(label=label, changes=changes):
                ledger = self.seeded_ledger()
                request = operation(**changes)
                self.assert_rejected_unchanged(
                    ledger, lambda: ledger.transfer(**request))

    def test_replay_succeeds_without_funds_and_returns_independent_receipts(self):
        ledger = Ledger({'a': 1, 'b': 0, 'c': 0})
        first = ledger.transfer('a', 'b', 1, 'one')
        ledger.transfer('b', 'c', 1, 'two')
        before = deepcopy((ledger.balances, ledger.history))
        replay = ledger.transfer('a', 'b', 1, 'one')
        self.assertEqual(replay, first)
        self.assertIsNot(replay, first)
        first['amount'] = 999
        first['extra'] = 'caller data'
        replay.clear()
        self.assertEqual((ledger.balances, ledger.history), before)
        self.assertEqual(ledger.transfer('a', 'b', 1, 'one'), operation(amount=1, key='one'))
        self.assertEqual((ledger.balances, ledger.history), before)

    def test_replay_rejects_each_changed_payload_and_invalid_equal_values(self):
        ledger = Ledger({'a': 100, 'b': 10, 'c': 10})
        original = operation(amount=1, key='one')
        ledger.transfer(**original)
        changes = (
            {'source': 'c'}, {'target': 'c'}, {'amount': 2},
            {'source': 'b', 'target': 'a'},
            {'amount': True}, {'amount': 1.0},
        )
        for change in changes:
            with self.subTest(change=change):
                request = dict(original, **change)
                self.assert_rejected_unchanged(
                    ledger, lambda: ledger.transfer(**request))
        before = deepcopy((ledger.balances, ledger.history))
        self.assertEqual(ledger.transfer(**original), original)
        self.assertEqual((ledger.balances, ledger.history), before)

    def test_failed_transfer_does_not_reserve_key(self):
        ledger = Ledger({'a': 10, 'b': 0})
        request = operation('b', 'a', 5, 'retry')
        self.assert_rejected_unchanged(ledger, lambda: ledger.transfer(**request))
        ledger.transfer('a', 'b', 5, 'fund')
        self.assertEqual(ledger.transfer(**request), request)
        self.assertEqual(ledger.balances, {'a': 10, 'b': 0})
        self.assertEqual(set(ledger.history), {'fund', 'retry'})

    def test_batch_is_ordered_and_receipts_and_inputs_are_isolated(self):
        ledger = self.seeded_ledger()
        balances, history = ledger.balances, ledger.history
        requests = [
            operation('a', 'b', 30, 'one'),
            operation('b', 'c', 10, 'two'),
            operation('a', 'c', 5, 'seed'),
            operation('a', 'b', 30, 'one'),
            operation('c', 'a', 5, 'three'),
        ]
        original_requests = deepcopy(requests)
        receipts = ledger.batch(requests)
        self.assertEqual(receipts, original_requests)
        self.assertEqual(requests, original_requests)
        self.assertEqual(ledger.balances, {'a': 70, 'b': 20, 'c': 10, 'untouched': 7})
        self.assertEqual(ledger.history, {op['key']: op for op in original_requests})
        self.assertIs(ledger.balances, balances)
        self.assertIs(ledger.history, history)
        before = deepcopy((ledger.balances, ledger.history))
        receipts[0]['amount'] = 999
        self.assertEqual(receipts[3], original_requests[3])
        for receipt in receipts:
            receipt.clear()
        for request in requests:
            request.clear()
        self.assertEqual((ledger.balances, ledger.history), before)
        self.assertEqual(ledger.batch(original_requests), original_requests)
        self.assertEqual((ledger.balances, ledger.history), before)

    def test_batch_failure_rolls_back_every_effect_and_preserves_old_replays(self):
        failures = [
            ('insufficient funds', operation('b', 'c', 11, 'bad')),
            ('missing source', operation('missing', 'a', 1, 'bad')),
            ('missing target', operation('c', 'missing', 1, 'bad')),
            ('same account', operation('a', 'a', 1, 'bad')),
            ('boolean amount', operation(amount=True, key='bad')),
            ('invalid key', operation(key=[])),
            ('old key conflict', operation('a', 'c', 6, 'seed')),
            ('new key conflict', operation('a', 'b', 21, 'first')),
            ('missing field', {'source': 'a', 'target': 'b', 'amount': 1}),
            ('extra field', dict(operation(), unexpected=1)),
            ('wrong field', {'source': 'a', 'target': 'b', 'amount': 1, 'id': 'bad'}),
            ('not a dictionary', None),
            ('pairs instead of dictionary', list(operation().items())),
        ]
        prefix = [operation('a', 'b', 20, 'first'), operation('b', 'c', 10, 'second')]
        seed = operation('a', 'c', 5, 'seed')
        for label, failure in failures:
            with self.subTest(label=label):
                ledger = self.seeded_ledger()
                requests = prefix + [failure, operation('c', 'a', 1, 'after')]
                original_requests = deepcopy(requests)
                before = deepcopy((ledger.balances, ledger.history))
                self.assert_rejected_unchanged(ledger, lambda: ledger.batch(requests))
                self.assertEqual(requests, original_requests)
                self.assertEqual(ledger.transfer(**seed), seed)
                self.assertEqual((ledger.balances, ledger.history), before)
                self.assertEqual(ledger.batch(prefix), prefix)
                self.assertEqual(ledger.balances, {'a': 75, 'b': 10, 'c': 15, 'untouched': 7})
                self.assertEqual(ledger.history, {op['key']: op for op in [seed] + prefix})

    def test_batch_requires_list_and_empty_batch_preserves_state(self):
        ledger = self.seeded_ledger()
        for requests in (None, {}, 'operations', (operation(),), iter([operation()])):
            with self.subTest(requests=requests):
                self.assert_rejected_unchanged(ledger, lambda: ledger.batch(requests))
        balances, history = ledger.balances, ledger.history
        before = deepcopy((balances, history))
        self.assertEqual(ledger.batch([]), [])
        self.assertEqual((ledger.balances, ledger.history), before)
        self.assertIs(ledger.balances, balances)
        self.assertIs(ledger.history, history)

    def test_integrated_transfers_batch_failure_retry_and_replay(self):
        initial = {'wallet': 120, 'merchant': 0, 'savings': 0, 'untouched': 7}
        ledger = Ledger(initial)
        balances, history = ledger.balances, ledger.history
        saved = operation('wallet', 'savings', 20, 'saved')
        self.assertEqual(ledger.transfer(**saved), saved)
        purchases = [
            operation('wallet', 'merchant', 40, 'purchase'),
            operation('merchant', 'savings', 15, 'reserve'),
            operation('wallet', 'merchant', 40, 'purchase'),
            operation('savings', 'wallet', 5, 'rebate'),
        ]
        self.assertEqual(ledger.batch(purchases), purchases)
        self.assertEqual(ledger.balances, {'wallet': 65, 'merchant': 25, 'savings': 30, 'untouched': 7})
        retry = operation('wallet', 'merchant', 10, 'retry')
        failing = [retry, operation('merchant', 'savings', 40, 'settle')]
        self.assert_rejected_unchanged(ledger, lambda: ledger.batch(failing))
        before = deepcopy((ledger.balances, ledger.history))
        self.assertEqual(ledger.batch([saved] + purchases), [saved] + purchases)
        self.assertEqual((ledger.balances, ledger.history), before)
        settlement = [retry, operation('merchant', 'savings', 35, 'settle')]
        self.assertEqual(ledger.batch(settlement), settlement)
        self.assertEqual(ledger.balances, {'wallet': 55, 'merchant': 0, 'savings': 65, 'untouched': 7})
        before = deepcopy((ledger.balances, ledger.history))
        self.assertEqual(ledger.batch(settlement), settlement)
        self.assertEqual((ledger.balances, ledger.history), before)
        self.assertEqual(ledger.history, {op['key']: op for op in [saved] + purchases + settlement})
        self.assertEqual(sum(ledger.balances.values()), sum(initial.values()))
        self.assertTrue(all(balance >= 0 for balance in ledger.balances.values()))
        self.assertEqual(initial, {'wallet': 120, 'merchant': 0, 'savings': 0, 'untouched': 7})
        self.assertIs(ledger.balances, balances)
        self.assertIs(ledger.history, history)


if __name__ == '__main__':
    unittest.main()
