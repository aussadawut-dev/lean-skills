from collections import Counter
from copy import deepcopy
import unittest

from ledger import Ledger


def operation(source='a', target='b', amount=10, key='one'):
    return dict(source=source, target=target, amount=amount, key=key)


def invalid_operations():
    cases = []
    for field in ('source', 'target'):
        for value in (None, True, 1, [], {}, 'missing'):
            cases.append((field, value, operation(**{field: value})))
    for value in (0, -1, True, False, 1.0, '1', None, [], {}):
        cases.append(('amount', value, operation(amount=value)))
    for value in ('', None, True, 1, [], {}):
        cases.append(('key', value, operation(key=value)))
    cases.append(('same account', 'a', operation(target='a')))
    cases.append(('insufficient funds', 1000, operation(amount=1000)))
    return cases


class LedgerTests(unittest.TestCase):
    def setUp(self):
        self.ledger = Ledger({'a': 100, 'b': 20, 'c': 0})

    def assert_state(self, balances, history):
        self.assertEqual(self.ledger.balances, balances)
        self.assertEqual(self.ledger.history, history)

    def assert_rejected_without_change(self, action, *args, **kwargs):
        balances = self.ledger.balances
        history = self.ledger.history
        receipts = history.copy()
        before = deepcopy((balances, history))
        with self.assertRaises(ValueError):
            action(*args, **kwargs)
        self.assert_state(*before)
        self.assertIs(self.ledger.balances, balances)
        self.assertIs(self.ledger.history, history)
        for key, receipt in receipts.items():
            self.assertIs(self.ledger.history[key], receipt)

    def test_constructor_copies_input_in_both_directions(self):
        original = {'a': 100, 'b': 20, 'c': 0}
        self.ledger = Ledger(original)
        self.assertIsNot(self.ledger.balances, original)
        self.ledger.transfer('a', 'b', 10, 'one')
        self.assertEqual(original, {'a': 100, 'b': 20, 'c': 0})
        original['a'] = 999
        original['new'] = 10
        del original['b']
        self.assert_state({'a': 90, 'b': 30, 'c': 0}, {'one': operation()})

    def test_constructor_rejects_invalid_containers(self):
        for value in (None, [], [('a', 100)], 'a', True, 1):
            with self.subTest(value=value), self.assertRaises(ValueError):
                Ledger(value)

    def test_constructor_rejects_invalid_elements_without_changing_input(self):
        cases = [{'a': value} for value in (-1, True, False, 1.0, '1', None, [], {})]
        cases.extend({key: 1} for key in (None, True, 1, ('a',)))
        for invalid in cases:
            with self.subTest(balances=invalid):
                before = deepcopy(invalid)
                with self.assertRaises(ValueError):
                    Ledger(invalid)
                self.assertEqual(invalid, before)

    def test_empty_ledger_zero_balances_and_large_integers_are_valid(self):
        self.assertEqual(Ledger({}).balances, {})
        self.assertEqual(Ledger({'zero': 0}).history, {})
        huge = 10 ** 100
        self.ledger = Ledger({'': huge, 'destination': 0})
        receipt = self.ledger.transfer('', 'destination', huge, ' ')
        self.assert_state({'': 0, 'destination': huge}, {' ': receipt})

    def test_transfer_receipt_and_public_dictionary_identity(self):
        balances, history = self.ledger.balances, self.ledger.history
        receipt = self.ledger.transfer('a', 'b', 10, 'one')
        self.assertEqual(receipt, operation())
        self.assert_state({'a': 90, 'b': 30, 'c': 0}, {'one': operation()})
        self.assertIs(self.ledger.balances, balances)
        self.assertIs(self.ledger.history, history)

    def test_invalid_transfers_leave_all_state_unchanged(self):
        self.ledger.transfer('b', 'c', 1, 'seed')
        for field, value, op in invalid_operations():
            with self.subTest(field=field, value=value):
                self.assert_rejected_without_change(self.ledger.transfer, **op)

    def test_failed_transfer_does_not_reserve_its_key(self):
        self.assert_rejected_without_change(self.ledger.transfer, 'c', 'a', 1, 'retry')
        self.ledger.transfer('b', 'c', 1, 'fund')
        receipt = self.ledger.transfer('c', 'a', 1, 'retry')
        self.assertEqual(receipt, operation('c', 'a', 1, 'retry'))
        self.assertEqual(self.ledger.balances, {'a': 101, 'b': 19, 'c': 0})

    def test_replay_succeeds_even_when_original_funds_have_been_spent(self):
        first = self.ledger.transfer('a', 'b', 100, 'all')
        before = deepcopy((self.ledger.balances, self.ledger.history))
        for _ in range(2):
            replay = self.ledger.transfer('a', 'b', 100, 'all')
            self.assertEqual(replay, first)
            self.assertIsNot(replay, first)
            self.assert_state(*before)

    def test_changed_replays_and_invalid_equal_values_are_rejected(self):
        self.ledger.transfer('a', 'b', 1, 'one')
        for changes in ({'source': 'c'}, {'target': 'c'}, {'amount': 2},
                        {'source': 'b', 'target': 'a'}, {'amount': True},
                        {'amount': 1.0}):
            with self.subTest(changes=changes):
                op = operation(amount=1)
                op.update(changes)
                self.assert_rejected_without_change(self.ledger.transfer, **op)

    def test_returned_transfer_receipts_cannot_mutate_history(self):
        first = self.ledger.transfer('a', 'b', 10, 'one')
        first['amount'] = 999
        first['extra'] = True
        replay = self.ledger.transfer('a', 'b', 10, 'one')
        self.assertEqual(replay, operation())
        replay.clear()
        self.assert_state({'a': 90, 'b': 30, 'c': 0}, {'one': operation()})
        self.assertEqual(self.ledger.transfer('a', 'b', 10, 'one'), operation())

    def test_batch_rejects_non_lists_without_state_change(self):
        self.ledger.transfer('b', 'c', 1, 'seed')
        for value in (None, {}, (), (operation(),), iter([operation()]), 'batch', True, 1):
            with self.subTest(value=value):
                self.assert_rejected_without_change(self.ledger.batch, value)

    def test_malformed_batch_operations_roll_back_prior_operations(self):
        self.ledger.transfer('b', 'c', 1, 'seed')
        cases = [None, [], (), 'operation', True, 1, {},
                 {**operation(), 'extra': 1}, {**operation(), 1: 'invalid'},
                 {**operation(), None: 'invalid'}]
        for field in operation():
            incomplete = operation()
            del incomplete[field]
            cases.append(incomplete)
        for malformed in cases:
            with self.subTest(operation=malformed):
                self.assert_rejected_without_change(
                    self.ledger.batch, [operation(key='staged'), malformed])

    def test_invalid_batch_transfers_roll_back_prior_operations(self):
        self.ledger.transfer('b', 'c', 1, 'seed')
        for field, value, invalid in invalid_operations():
            with self.subTest(field=field, value=value):
                self.assert_rejected_without_change(
                    self.ledger.batch, [operation(key='staged'), invalid])

    def test_batch_conflicts_with_existing_or_staged_keys_are_atomic(self):
        self.ledger.transfer('b', 'c', 1, 'seed')
        for invalid in (operation(key='seed'), operation(amount=11, key='staged')):
            with self.subTest(operation=invalid):
                self.assert_rejected_without_change(self.ledger.batch, [
                    operation('b', 'c', 1, 'seed'),
                    operation(key='staged'),
                    invalid,
                ])
        self.assertEqual(self.ledger.transfer('a', 'b', 10, 'staged'),
                         operation(key='staged'))

    def test_batch_uses_earlier_credits_and_returns_receipts_in_order(self):
        balances, history = self.ledger.balances, self.ledger.history
        operations = [operation('a', 'c', 60, 'fund'),
                      operation('c', 'b', 60, 'spend'),
                      operation('b', 'a', 80, 'return')]
        before = deepcopy(operations)
        receipts = self.ledger.batch(operations)
        self.assertEqual(receipts, before)
        self.assertEqual(operations, before)
        self.assert_state({'a': 120, 'b': 0, 'c': 0},
                          {op['key']: op for op in before})
        self.assertIs(self.ledger.balances, balances)
        self.assertIs(self.ledger.history, history)
        operations[0]['amount'] = 999
        self.assertEqual(self.ledger.history['fund'], before[0])

    def test_batch_replays_and_receipts_remain_independent(self):
        seed = operation(key='seed')
        self.ledger.transfer(**seed)
        new = operation('b', 'c', 30, 'new')
        operations = [seed, new, new, operation('a', 'c', 20, 'last')]
        receipts = self.ledger.batch(operations)
        self.assertEqual(receipts, operations)
        expected = ({'a': 70, 'b': 0, 'c': 50},
                    {op['key']: deepcopy(op) for op in operations})
        self.assert_state(*expected)
        for i, receipt in enumerate(receipts):
            self.assertIsNot(receipt, operations[i])
            self.assertIsNot(receipt, self.ledger.history[receipt['key']])
        self.assertIsNot(receipts[1], receipts[2])
        receipts[1].clear()
        self.assertEqual(receipts[2], new)
        receipts[0]['amount'] = 999
        self.assert_state(*expected)
        replays = self.ledger.batch(operations)
        self.assertEqual(replays, operations)
        replays[-1].clear()
        self.assert_state(*expected)
        self.assertEqual(self.ledger.transfer(**new), new)

    def test_empty_batch_preserves_state_and_dictionary_identity(self):
        self.ledger.transfer('a', 'b', 10, 'one')
        balances, history = self.ledger.balances, self.ledger.history
        before = deepcopy((balances, history))
        self.assertEqual(self.ledger.batch([]), [])
        self.assert_state(*before)
        self.assertIs(self.ledger.balances, balances)
        self.assertIs(self.ledger.history, history)

    def test_counter_input_empty_fresh_and_replayed_batches(self):
        payment = operation(amount=3, key='payment')
        cases = (
            ('empty', False, [], {'a': 10, 'b': 0}),
            ('fresh', False, [payment], {'a': 7, 'b': 3}),
            ('replay', True, [payment], {'a': 7, 'b': 3}),
        )
        for name, seed, operations, expected_balances in cases:
            with self.subTest(case=name):
                opening = Counter(a=10, b=0)
                self.ledger = Ledger(opening)
                balances, history = self.ledger.balances, self.ledger.history
                if seed:
                    self.assertEqual(self.ledger.transfer(**payment), payment)
                receipts = self.ledger.batch(operations)
                self.assertEqual(receipts, operations)
                expected_history = {'payment': payment} if seed or operations else {}
                self.assert_state(expected_balances, expected_history)
                self.assertIs(self.ledger.balances, balances)
                self.assertIs(self.ledger.history, history)
                self.assertEqual(dict(opening), {'a': 10, 'b': 0})

                opening['a'] = 999
                opening['extra'] = 1
                for receipt in receipts:
                    receipt.clear()
                self.assert_state(expected_balances, expected_history)

    def test_integrated_multi_transfer_failure_retry_and_replay_journey(self):
        opening = {'payroll': 500, 'checking': 0, 'savings': 0, 'merchant': 0}
        self.ledger = Ledger(opening)
        paycheck = operation('payroll', 'checking', 200, 'paycheck')
        self.assertEqual(self.ledger.transfer(**paycheck), paycheck)
        purchase = operation('checking', 'merchant', 50, 'purchase')
        first_batch = [operation('checking', 'savings', 80, 'save'), purchase,
                       operation('merchant', 'checking', 10, 'refund'), purchase]
        self.assertEqual(self.ledger.batch(first_batch), first_batch)
        reserve = operation('payroll', 'savings', 300, 'reserve')
        self.ledger.transfer(**reserve)
        self.assertEqual(self.ledger.transfer(**paycheck), paycheck)
        history = {op['key']: op for op in [paycheck, *first_batch, reserve]}
        before = ({'payroll': 0, 'checking': 80, 'savings': 380, 'merchant': 40}, history)
        self.assert_state(*before)

        retry_batch = [operation('checking', 'savings', 30, 'move'),
                       operation('checking', 'merchant', 60, 'retry')]
        self.assert_rejected_without_change(self.ledger.batch, retry_batch)
        self.assert_state(*before)
        retry_batch[1]['amount'] = 50
        self.assertEqual(self.ledger.batch(retry_batch), retry_batch)
        history = {**history, **{op['key']: op for op in retry_batch}}
        final = ({'payroll': 0, 'checking': 0, 'savings': 410, 'merchant': 90}, history)
        self.assert_state(*final)
        self.assertEqual(self.ledger.batch(retry_batch), retry_batch)
        self.assert_rejected_without_change(self.ledger.transfer,
                                           'checking', 'merchant', 51, 'purchase')
        self.assert_state(*final)
        self.assertEqual(sum(self.ledger.balances.values()), sum(opening.values()))
        self.assertEqual(opening, {'payroll': 500, 'checking': 0, 'savings': 0, 'merchant': 0})


if __name__ == '__main__':
    unittest.main()
