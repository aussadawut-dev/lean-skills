from collections import Counter
from copy import deepcopy
import unittest

from ledger import Ledger


def operation(source='a', target='b', amount=10, key='new'):
    return dict(source=source, target=target, amount=amount, key=key)


class LedgerTests(unittest.TestCase):
    def assert_rejected_without_change(self, ledger, action):
        balances, history = ledger.balances, ledger.history
        before = deepcopy((balances, history))
        with self.assertRaises(ValueError):
            action()
        self.assertEqual((ledger.balances, ledger.history), before)
        self.assertIs(ledger.balances, balances)
        self.assertIs(ledger.history, history)

    def seeded_ledger(self):
        ledger = Ledger({'a': 100, 'b': 0, 'c': 0})
        ledger.transfer('a', 'b', 10, 'existing')
        return ledger

    def test_constructor_owns_balances(self):
        supplied = {'a': 100, 'b': 0}
        ledger = Ledger(supplied)
        self.assertIsInstance(ledger.balances, dict)
        self.assertIsInstance(ledger.history, dict)
        self.assertIsNot(ledger.balances, supplied)
        supplied['a'] = 999
        supplied['outside'] = 5
        ledger.transfer('a', 'b', 20, 'one')
        self.assertEqual(ledger.balances, {'a': 80, 'b': 20})
        self.assertEqual(supplied, {'a': 999, 'b': 0, 'outside': 5})

    def test_counter_input_empty_batch_preserves_state_and_ownership(self):
        supplied = Counter({'a': 10, 'b': 0})
        ledger = Ledger(supplied)
        balances, history = ledger.balances, ledger.history
        self.assertIsNot(balances, supplied)
        self.assertEqual(ledger.batch([]), [])
        self.assertEqual(dict(ledger.balances), {'a': 10, 'b': 0})
        self.assertEqual(ledger.history, {})
        self.assertIs(ledger.balances, balances)
        self.assertIs(ledger.history, history)
        self.assertEqual(dict(supplied), {'a': 10, 'b': 0})
        supplied['a'] = 999
        supplied['outside'] = 5
        self.assertEqual(dict(ledger.balances), {'a': 10, 'b': 0})

    def test_counter_input_transfer_and_batch_replays_preserve_state(self):
        for first_call in ('transfer', 'batch'):
            with self.subTest(first_call=first_call):
                supplied = Counter({'a': 10, 'b': 0})
                ledger = Ledger(supplied)
                balances, history = ledger.balances, ledger.history
                expected = operation(amount=1, key='one')
                if first_call == 'transfer':
                    self.assertEqual(ledger.transfer(**expected), expected)
                else:
                    self.assertEqual(ledger.batch([expected]), [expected])
                self.assertEqual(dict(ledger.balances), {'a': 9, 'b': 1})
                self.assertEqual(ledger.history, {'one': expected})
                self.assertEqual(ledger.batch([expected]), [expected])
                self.assertEqual(ledger.transfer(**expected), expected)
                self.assertEqual(ledger.batch([expected, expected]), [expected, expected])
                self.assertEqual(dict(ledger.balances), {'a': 9, 'b': 1})
                self.assertEqual(ledger.history, {'one': expected})
                self.assertIs(ledger.balances, balances)
                self.assertIs(ledger.history, history)
                self.assertEqual(dict(supplied), {'a': 10, 'b': 0})

    def test_constructor_rejects_invalid_balances_without_changing_input(self):
        invalid = [-1, True, False, 1.0, '1', None, [], {}, float('inf')]
        for balance in invalid:
            with self.subTest(balance=balance):
                supplied = {'a': 10, 'b': balance}
                before = deepcopy(supplied)
                with self.assertRaises(ValueError):
                    Ledger(supplied)
                self.assertEqual(supplied, before)

    def test_constructor_requires_dictionary_with_string_accounts(self):
        for supplied in (None, [], [('a', 1)], 'a', {1: 10}, {False: 10}, {None: 0}):
            with self.subTest(supplied=supplied):
                with self.assertRaises(ValueError):
                    Ledger(supplied)

    def test_empty_ledger_and_empty_batch(self):
        ledger = Ledger({})
        balances, history = ledger.balances, ledger.history
        self.assertEqual(ledger.batch([]), [])
        self.assertEqual(ledger.balances, {})
        self.assertEqual(ledger.history, {})
        self.assertIs(ledger.balances, balances)
        self.assertIs(ledger.history, history)
        self.assert_rejected_without_change(
            ledger, lambda: ledger.transfer('a', 'b', 1, 'missing'))

    def test_transfer_full_balance_and_large_integers(self):
        for amount in (1, 10 ** 100):
            with self.subTest(amount=amount):
                ledger = Ledger({'a': amount, 'b': 0})
                expected = operation(amount=amount)
                self.assertEqual(ledger.transfer(**expected), expected)
                self.assertEqual(ledger.balances, {'a': 0, 'b': amount})
                self.assertEqual(ledger.history, {'new': expected})

    def test_empty_account_names_and_nonempty_whitespace_keys_are_valid(self):
        ledger = Ledger({'': 1, 'b': 0})
        expected = operation(source='', amount=1, key=' ')
        self.assertEqual(ledger.transfer(**expected), expected)
        self.assertEqual(ledger.balances, {'': 0, 'b': 1})

    def test_invalid_amounts_are_atomic(self):
        ledger = self.seeded_ledger()
        for amount in (0, -1, True, False, 1.0, '1', None, [], {}, float('nan')):
            with self.subTest(amount=amount):
                self.assert_rejected_without_change(
                    ledger, lambda: ledger.transfer('a', 'b', amount, 'invalid'))

    def test_invalid_keys_are_atomic(self):
        ledger = self.seeded_ledger()
        for key in ('', None, 1, True, [], {}, ('key',)):
            with self.subTest(key=key):
                self.assert_rejected_without_change(
                    ledger, lambda: ledger.transfer('a', 'b', 1, key))

    def test_unavailable_invalid_and_identical_accounts_are_atomic(self):
        ledger = self.seeded_ledger()
        for source, target in (
            ('missing', 'b'), ('a', 'missing'), ('a', 'a'),
            ([], 'b'), ('a', {}), (None, 'b'), ('a', 1), (True, 'b'),
        ):
            with self.subTest(source=source, target=target):
                self.assert_rejected_without_change(
                    ledger, lambda: ledger.transfer(source, target, 1, 'invalid'))

    def test_insufficient_funds_is_atomic_and_does_not_reserve_key(self):
        ledger = self.seeded_ledger()
        self.assert_rejected_without_change(
            ledger, lambda: ledger.transfer('b', 'c', 11, 'retry'))
        expected = operation(source='b', target='c', amount=10, key='retry')
        self.assertEqual(ledger.transfer(**expected), expected)
        self.assertEqual(ledger.balances, {'a': 90, 'b': 0, 'c': 10})

    def test_replay_is_equal_and_does_not_require_available_funds_again(self):
        ledger = Ledger({'a': 10, 'b': 0})
        expected = operation()
        first = ledger.transfer(**expected)
        before = deepcopy((ledger.balances, ledger.history))
        second = ledger.transfer(**expected)
        self.assertEqual(first, expected)
        self.assertEqual(second, expected)
        self.assertIsNot(first, second)
        self.assertEqual((ledger.balances, ledger.history), before)

    def test_replay_conflicts_in_every_payload_field_are_atomic(self):
        ledger = self.seeded_ledger()
        for changes in ({'source': 'c'}, {'target': 'c'}, {'amount': 11}):
            with self.subTest(changes=changes):
                replay = operation(key='existing')
                replay.update(changes)
                self.assert_rejected_without_change(
                    ledger, lambda: ledger.transfer(**replay))

    def test_replay_still_validates_boolean_and_float_amounts(self):
        ledger = Ledger({'a': 1, 'b': 0})
        ledger.transfer('a', 'b', 1, 'one')
        for amount in (True, 1.0):
            with self.subTest(amount=amount):
                self.assert_rejected_without_change(
                    ledger, lambda: ledger.transfer('a', 'b', amount, 'one'))

    def test_first_and_replayed_receipts_cannot_mutate_history(self):
        ledger = Ledger({'a': 10, 'b': 0})
        expected = operation()
        first = ledger.transfer(**expected)
        first['amount'] = 999
        first['extra'] = 'outside'
        second = ledger.transfer(**expected)
        self.assertEqual(second, expected)
        second.clear()
        self.assertEqual(ledger.history, {'new': expected})
        self.assertEqual(ledger.transfer(**expected), expected)

    def test_successful_batch_preserves_order_inputs_and_public_dictionaries(self):
        ledger = Ledger({'a': 20, 'b': 0, 'c': 0})
        balances, history = ledger.balances, ledger.history
        operations = [
            operation(amount=20, key='one'),
            operation(source='b', target='c', amount=15, key='two'),
            operation(source='c', target='a', amount=5, key='three'),
        ]
        before = deepcopy(operations)
        receipts = ledger.batch(operations)
        self.assertEqual(receipts, before)
        self.assertEqual(operations, before)
        self.assertEqual(ledger.balances, {'a': 5, 'b': 5, 'c': 10})
        self.assertEqual(ledger.history, {op['key']: op for op in before})
        self.assertIs(ledger.balances, balances)
        self.assertIs(ledger.history, history)
        operations[0]['amount'] = 999
        receipts[1].clear()
        self.assertEqual(ledger.history, {op['key']: op for op in before})

    def test_batch_replays_existing_and_new_keys_once_with_independent_receipts(self):
        ledger = Ledger({'a': 10, 'b': 0})
        first = operation(key='one')
        second = operation(source='b', target='a', key='two')
        ledger.transfer(**first)
        operations = [first, second, first, second]
        receipts = ledger.batch(operations)
        self.assertEqual(receipts, operations)
        self.assertEqual(ledger.balances, {'a': 10, 'b': 0})
        self.assertEqual(ledger.history, {'one': first, 'two': second})
        self.assertIsNot(receipts[0], receipts[2])
        self.assertIsNot(receipts[1], receipts[3])
        receipts[0].clear()
        receipts[1]['amount'] = 999
        self.assertEqual(receipts[2:], [first, second])
        self.assertEqual(ledger.history, {'one': first, 'two': second})

    def test_failed_batch_rolls_back_valid_prefix_and_keeps_existing_history(self):
        failures = [
            operation(amount=81, key='too-much'),
            operation(target='missing', key='bad-account'),
            operation(target='a', key='same-account'),
            operation(amount=True, key='bad-amount'),
            operation(key=''),
            operation(amount=11, key='existing'),
            operation(amount=11, key='prefix'),
            {},
            {'source': 'a', 'target': 'b', 'amount': 1},
            dict(operation(), extra='unexpected'),
            {'source': 'a', 'target': 'b', 'amount': 1, 1: 'invalid-key'},
            None,
            [],
        ]
        for failure in failures:
            with self.subTest(failure=failure):
                ledger = self.seeded_ledger()
                operations = [operation(key='existing'), operation(key='prefix'), failure]
                before = deepcopy(operations)
                self.assert_rejected_without_change(ledger, lambda: ledger.batch(operations))
                self.assertEqual(operations, before)
                # A discarded operation must not keep its idempotency key.
                retry = operation(amount=1, key='prefix')
                self.assertEqual(ledger.transfer(**retry), retry)
                self.assertEqual(ledger.balances, {'a': 89, 'b': 11, 'c': 0})

    def test_batch_rejects_non_list_containers_without_state_change(self):
        ledger = self.seeded_ledger()
        for operations in (None, {}, (), (operation(),), 'operations', iter([operation()])):
            with self.subTest(operations=operations):
                self.assert_rejected_without_change(ledger, lambda: ledger.batch(operations))

    def test_empty_batch_preserves_existing_state(self):
        ledger = self.seeded_ledger()
        before = deepcopy((ledger.balances, ledger.history))
        self.assertEqual(ledger.batch([]), [])
        self.assertEqual((ledger.balances, ledger.history), before)

    def test_integrated_transfer_batch_failure_retry_and_replay(self):
        supplied = {'alice': 100, 'bob': 30, 'carol': 0}
        ledger = Ledger(supplied)
        rent = operation('alice', 'bob', 25, 'rent')
        share = operation('bob', 'carol', 40, 'share')
        refund = operation('carol', 'alice', 15, 'refund')
        self.assertEqual(ledger.transfer(**rent), rent)
        self.assertEqual(ledger.batch([share, refund, rent]), [share, refund, rent])
        self.assertEqual(ledger.balances, {'alice': 90, 'bob': 15, 'carol': 25})

        retry = [operation('alice', 'bob', 10, 'retry-one'),
                 operation('bob', 'carol', 100, 'retry-two')]
        self.assert_rejected_without_change(ledger, lambda: ledger.batch(retry))
        retry[1]['amount'] = 20
        receipts = ledger.batch(retry)
        self.assertEqual(receipts, retry)
        self.assertEqual(ledger.balances, {'alice': 80, 'bob': 5, 'carol': 45})
        committed = deepcopy((ledger.balances, ledger.history))
        self.assertEqual(ledger.batch(retry), retry)
        self.assertEqual(ledger.transfer(**share), share)
        self.assertEqual((ledger.balances, ledger.history), committed)
        receipts[0].clear()
        self.assertEqual((ledger.balances, ledger.history), committed)
        self.assertEqual(ledger.history,
                         {op['key']: op for op in [rent, share, refund] + retry})
        self.assertEqual(sum(ledger.balances.values()), sum(supplied.values()))
        self.assertEqual(supplied, {'alice': 100, 'bob': 30, 'carol': 0})


if __name__ == '__main__':
    unittest.main()
