import unittest
from copy import deepcopy

from ledger import Ledger


class LedgerRegressionTests(unittest.TestCase):
    def assert_rejected_without_changes(self, ledger, action):
        before = deepcopy((ledger.balances, ledger.history))
        balances, history = ledger.balances, ledger.history
        with self.assertRaises(ValueError):
            action()
        self.assertEqual((ledger.balances, ledger.history), before)
        self.assertIs(ledger.balances, balances)
        self.assertIs(ledger.history, history)

    def test_constructor_copies_balances(self):
        balances = {'a': 100, 'b': 0}
        ledger = Ledger(balances)
        balances['a'] = 1
        self.assertEqual(ledger.balances, {'a': 100, 'b': 0})
        ledger.transfer('a', 'b', 20, 'one')
        self.assertEqual(balances, {'a': 1, 'b': 0})

    def test_constructor_rejects_invalid_balances(self):
        invalid_inputs = [
            None, [], [('a', 1)], 'balances', 1,
            {'a': -1}, {'a': True}, {'a': False}, {'a': 0.0},
            {'a': 1.5}, {'a': '1'}, {'a': None}, {'a': []},
            {1: 10}, {None: 10},
        ]
        for balances in invalid_inputs:
            with self.subTest(balances=balances):
                before = deepcopy(balances)
                with self.assertRaises(ValueError):
                    Ledger(balances)
                self.assertEqual(balances, before)

    def test_empty_ledger_and_zero_balances_are_valid(self):
        empty = Ledger({})
        self.assertEqual(empty.balances, {})
        self.assertEqual(empty.history, {})
        self.assertEqual(empty.batch([]), [])
        ledger = Ledger({'a': 0, 'b': 0})
        self.assertEqual(ledger.balances, {'a': 0, 'b': 0})
        self.assert_rejected_without_changes(
            ledger, lambda: ledger.transfer('a', 'b', 1, 'unfunded'))

    def test_exact_balance_transfer_with_large_integer_and_string_names(self):
        amount = 10 ** 100
        ledger = Ledger({'': amount, '目的地': 0})
        operation = {'source': '', 'target': '目的地', 'amount': amount, 'key': ' '}
        self.assertEqual(ledger.transfer(**operation), operation)
        self.assertEqual(ledger.balances, {'': 0, '目的地': amount})
        self.assertEqual(ledger.history, {' ': operation})

    def test_insufficient_funds_leave_state_unchanged(self):
        ledger = Ledger({'a': 10, 'b': 0})
        before = deepcopy((ledger.balances, ledger.history))
        with self.assertRaises(ValueError):
            ledger.transfer('a', 'b', 11, 'too-much')
        self.assertEqual((ledger.balances, ledger.history), before)

    def test_unavailable_target_leaves_state_unchanged(self):
        ledger = Ledger({'a': 10, 'b': 0})
        before = deepcopy((ledger.balances, ledger.history))
        with self.assertRaises(ValueError):
            ledger.transfer('a', 'missing', 1, 'missing-target')
        self.assertEqual((ledger.balances, ledger.history), before)

    def test_conflicting_replay_leaves_state_unchanged(self):
        ledger = Ledger({'a': 10, 'b': 0, 'c': 10})
        operation = {'source': 'a', 'target': 'b', 'amount': 2, 'key': 'one'}
        ledger.transfer(**operation)
        for change in ({'source': 'c'}, {'target': 'c'}, {'amount': 3}):
            with self.subTest(change=change):
                changed = dict(operation, **change)
                self.assert_rejected_without_changes(
                    ledger, lambda: ledger.transfer(**changed))

    def test_transfer_validation_leaves_existing_state_unchanged(self):
        ledger = Ledger({'a': 20, 'b': 0})
        ledger.transfer('a', 'b', 2, 'existing')
        invalid_fields = [
            ('source', 'missing'), ('source', None), ('source', 1),
            ('source', []), ('target', 'a'), ('target', True),
            ('target', {}), ('amount', 0), ('amount', -1),
            ('amount', True), ('amount', False), ('amount', 1.0),
            ('amount', '1'), ('amount', None), ('amount', []),
            ('key', ''), ('key', None), ('key', 1), ('key', []),
        ]
        for field, value in invalid_fields:
            with self.subTest(field=field, value=value):
                operation = {'source': 'a', 'target': 'b', 'amount': 1, 'key': 'new'}
                operation[field] = value
                self.assert_rejected_without_changes(
                    ledger, lambda: ledger.transfer(**operation))

    def test_replay_succeeds_after_source_is_exhausted(self):
        ledger = Ledger({'a': 10, 'b': 0})
        operation = {'source': 'a', 'target': 'b', 'amount': 10, 'key': 'all'}
        first = ledger.transfer(**operation)
        before = deepcopy((ledger.balances, ledger.history))
        replay = ledger.transfer(**operation)
        self.assertEqual(first, operation)
        self.assertEqual(replay, first)
        self.assertIsNot(replay, first)
        self.assertEqual((ledger.balances, ledger.history), before)

    def test_replay_still_rejects_boolean_and_float_amounts(self):
        ledger = Ledger({'a': 10, 'b': 0})
        ledger.transfer('a', 'b', 1, 'one')
        for invalid in (True, 1.0):
            with self.subTest(amount=invalid):
                self.assert_rejected_without_changes(
                    ledger, lambda: ledger.transfer('a', 'b', invalid, 'one'))

    def test_same_payload_with_a_new_key_is_a_new_transfer(self):
        ledger = Ledger({'a': 10, 'b': 0})
        ledger.transfer('a', 'b', 2, 'one')
        ledger.transfer('a', 'b', 2, 'two')
        self.assertEqual(ledger.balances, {'a': 6, 'b': 4})
        self.assertEqual(set(ledger.history), {'one', 'two'})

    def test_returned_receipts_do_not_mutate_history(self):
        ledger = Ledger({'a': 10, 'b': 0})
        expected = {'source': 'a', 'target': 'b', 'amount': 2, 'key': 'one'}
        receipt = ledger.transfer(**expected)
        self.assertEqual(receipt, expected)
        receipt['amount'] = 9
        self.assertEqual(ledger.history, {'one': expected})
        replay = ledger.transfer(**expected)
        replay.clear()
        self.assertEqual(ledger.history, {'one': expected})

    def test_failed_batch_rolls_back_balances_and_history(self):
        ledger = Ledger({'a': 20, 'b': 0, 'c': 0})
        ledger.transfer('a', 'b', 2, 'existing')
        before = deepcopy((ledger.balances, ledger.history))
        balances, history = ledger.balances, ledger.history
        with self.assertRaises(ValueError):
            ledger.batch([
                {'source': 'a', 'target': 'b', 'amount': 3, 'key': 'first'},
                {'source': 'b', 'target': 'c', 'amount': 6, 'key': 'failed'},
            ])
        self.assertEqual((ledger.balances, ledger.history), before)
        self.assertIs(ledger.balances, balances)
        self.assertIs(ledger.history, history)

    def test_batch_rejects_non_list_inputs(self):
        ledger = Ledger({'a': 20, 'b': 0})
        operation = {'source': 'a', 'target': 'b', 'amount': 2, 'key': 'one'}
        for operations in (None, {}, 'batch', (operation,), iter([operation])):
            with self.subTest(operations=operations):
                self.assert_rejected_without_changes(
                    ledger, lambda: ledger.batch(operations))

    def test_malformed_batch_operations_roll_back_valid_prefix(self):
        ledger = Ledger({'a': 20, 'b': 0})
        ledger.transfer('a', 'b', 1, 'existing')
        prefix = {'source': 'a', 'target': 'b', 'amount': 2, 'key': 'prefix'}
        valid = {'source': 'b', 'target': 'a', 'amount': 1, 'key': 'last'}
        malformed = [None, [], (), 'operation', {}, dict(valid, extra=1)]
        malformed.extend({k: v for k, v in valid.items() if k != missing}
                         for missing in valid)
        malformed.append({**valid, 1: 'non-string field'})
        for operation in malformed:
            with self.subTest(operation=operation):
                self.assert_rejected_without_changes(
                    ledger, lambda: ledger.batch([prefix, operation]))

    def test_invalid_batch_values_roll_back_valid_prefix(self):
        ledger = Ledger({'a': 20, 'b': 0, 'c': 0})
        prefix = {'source': 'a', 'target': 'b', 'amount': 5, 'key': 'prefix'}
        last = {'source': 'b', 'target': 'c', 'amount': 1, 'key': 'last'}
        for change in ({'target': 'missing'}, {'target': 'b'}, {'amount': True},
                       {'amount': 0}, {'amount': 6}, {'key': ''}):
            with self.subTest(change=change):
                operation = dict(last, **change)
                self.assert_rejected_without_changes(
                    ledger, lambda: ledger.batch([prefix, operation]))

    def test_conflicting_keys_within_batch_roll_back_everything(self):
        ledger = Ledger({'a': 20, 'b': 0, 'c': 0})
        first = {'source': 'a', 'target': 'b', 'amount': 5, 'key': 'one'}
        for change in ({'source': 'b', 'target': 'c'}, {'target': 'c'}, {'amount': 4}):
            with self.subTest(change=change):
                conflicting = dict(first, **change)
                self.assert_rejected_without_changes(
                    ledger, lambda: ledger.batch([first, conflicting]))

    def test_batch_receipts_are_ordered_and_isolated(self):
        ledger = Ledger({'a': 10, 'b': 0, 'c': 0})
        balances, history = ledger.balances, ledger.history
        first = {'source': 'a', 'target': 'b', 'amount': 10, 'key': 'one'}
        second = {'source': 'b', 'target': 'c', 'amount': 10, 'key': 'two'}
        operations = [first, second, first]
        expected = deepcopy(operations)
        receipts = ledger.batch(operations)
        self.assertEqual(receipts, expected)
        self.assertEqual(operations, expected)
        self.assertEqual(ledger.balances, {'a': 0, 'b': 0, 'c': 10})
        self.assertIs(ledger.balances, balances)
        self.assertIs(ledger.history, history)
        self.assertIsNot(receipts[0], receipts[2])
        receipts[0].clear()
        self.assertEqual(receipts[2], expected[2])
        receipts[1]['amount'] = 0
        receipts[2]['target'] = 'a'
        first['amount'] = 1
        self.assertEqual(ledger.history, {'one': expected[0], 'two': expected[1]})
        before = deepcopy((ledger.balances, ledger.history))
        replayed = ledger.batch(expected)
        self.assertEqual(replayed, expected)
        replayed[0].clear()
        self.assertEqual((ledger.balances, ledger.history), before)

    def test_empty_batch_preserves_existing_state(self):
        ledger = Ledger({'a': 10, 'b': 0})
        ledger.transfer('a', 'b', 2, 'one')
        balances, history = ledger.balances, ledger.history
        before = deepcopy((balances, history))
        self.assertEqual(ledger.batch([]), [])
        self.assertEqual((ledger.balances, ledger.history), before)
        self.assertIs(ledger.balances, balances)
        self.assertIs(ledger.history, history)

    def test_integrated_transfer_batch_failure_and_recovery_journey(self):
        initial = {'a': 100, 'b': 20, 'c': 0, 'untouched': 7}
        ledger = Ledger(initial)
        deposit = {'source': 'a', 'target': 'b', 'amount': 30, 'key': 'deposit'}
        fund = {'source': 'b', 'target': 'c', 'amount': 40, 'key': 'fund'}
        refund = {'source': 'c', 'target': 'a', 'amount': 10, 'key': 'refund'}
        self.assertEqual(ledger.transfer(**deposit), deposit)
        operations = [deposit, fund, refund, fund]
        self.assertEqual(ledger.batch(operations), operations)
        self.assertEqual(ledger.balances, {'a': 80, 'b': 10, 'c': 30, 'untouched': 7})
        self.assertEqual(ledger.history, {'deposit': deposit, 'fund': fund, 'refund': refund})

        retryable = {'source': 'a', 'target': 'b', 'amount': 20, 'key': 'retryable'}
        overspend = {'source': 'c', 'target': 'a', 'amount': 31, 'key': 'recovered'}
        self.assert_rejected_without_changes(
            ledger, lambda: ledger.batch([retryable, overspend]))
        recovery = [retryable, dict(overspend, amount=30)]
        self.assertEqual(ledger.batch(recovery), recovery)
        self.assertEqual(ledger.balances, {'a': 90, 'b': 30, 'c': 0, 'untouched': 7})
        expected_history = {op['key']: op for op in [deposit, fund, refund, *recovery]}
        self.assertEqual(ledger.history, expected_history)
        before = deepcopy((ledger.balances, ledger.history))
        self.assertEqual(ledger.batch(recovery), recovery)
        self.assertEqual((ledger.balances, ledger.history), before)

        prefix = {'source': 'a', 'target': 'b', 'amount': 5, 'key': 'rolled-back'}
        self.assert_rejected_without_changes(
            ledger, lambda: ledger.batch([prefix, dict(fund, amount=1)]))
        self.assertEqual(ledger.transfer(**fund), fund)
        self.assertEqual((ledger.balances, ledger.history), before)
        self.assertEqual(sum(ledger.balances.values()), sum(initial.values()))
        self.assertEqual(initial, {'a': 100, 'b': 20, 'c': 0, 'untouched': 7})
