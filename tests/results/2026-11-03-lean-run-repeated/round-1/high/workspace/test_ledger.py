from copy import deepcopy
import unittest

from ledger import Ledger


def operation(source='a', target='b', amount=20, key='one'):
    return dict(source=source, target=target, amount=amount, key=key)


class LedgerTests(unittest.TestCase):
    def setUp(self):
        self.ledger = Ledger({'a': 100, 'b': 0, 'c': 50})

    def assert_rejected_without_change(self, ledger, action):
        balances, history = ledger.balances, ledger.history
        before = deepcopy((balances, history))
        with self.assertRaises(ValueError):
            action()
        self.assertEqual((ledger.balances, ledger.history), before)
        self.assertIs(ledger.balances, balances)
        self.assertIs(ledger.history, history)

    def test_constructor_copies_input(self):
        balances = {'a': 100, 'b': 0}
        ledger = Ledger(balances)
        ledger.transfer('a', 'b', 20, 'one')
        self.assertEqual(balances, {'a': 100, 'b': 0})
        balances['a'] = 999
        balances['new'] = 1
        self.assertEqual(ledger.balances, {'a': 80, 'b': 20})

    def test_constructor_rejects_invalid_values_without_changing_input(self):
        invalid = (-1, True, False, 1.0, 0.5, float('inf'),
                   '1', None, [], {}, 1 + 0j)
        for value in invalid:
            with self.subTest(value=value):
                balances = {'a': 100, 'b': value}
                before = deepcopy(balances)
                with self.assertRaises(ValueError):
                    Ledger(balances)
                self.assertEqual(balances, before)

    def test_constructor_rejects_invalid_containers_and_account_names(self):
        for balances in (None, [], [('a', 10)], 'a', 10,
                         {1: 10}, {None: 10}, {('a',): 10}):
            with self.subTest(balances=balances):
                with self.assertRaises(ValueError):
                    Ledger(balances)

    def test_empty_ledger_and_valid_integer_boundaries(self):
        ledger = Ledger({})
        self.assertEqual(ledger.balances, {})
        self.assertEqual(ledger.history, {})
        self.assertEqual(ledger.batch([]), [])
        self.assert_rejected_without_change(
            ledger, lambda: ledger.transfer('missing', 'other', 1, 'key'))
        amount = 10 ** 100
        ledger = Ledger({'': amount, 'target': 0})
        receipt = ledger.transfer('', 'target', amount, ' ')
        self.assertEqual(ledger.balances, {'': 0, 'target': amount})
        self.assertEqual(receipt, operation('', 'target', amount, ' '))

    def test_transfer_exact_funds_and_public_dictionary_identity(self):
        ledger = self.ledger
        balances, history = ledger.balances, ledger.history
        expected = operation(amount=100)
        self.assertEqual(ledger.transfer(**expected), expected)
        self.assertEqual(ledger.balances, {'a': 0, 'b': 100, 'c': 50})
        self.assertEqual(ledger.history, {'one': expected})
        self.assertIs(ledger.balances, balances)
        self.assertIs(ledger.history, history)

    def test_transfer_rejects_invalid_values_without_change(self):
        ledger = self.ledger
        ledger.transfer('a', 'b', 10, 'seed')
        invalid = {
            'source': ('missing', None, [], {}, True, 1),
            'target': ('missing', None, [], {}, False, 1),
            'amount': (0, -1, True, False, 1.0, 0.5, float('nan'),
                       float('inf'), '1', None, [], {}),
            'key': ('', None, True, 1, 1.0, [], {}),
        }
        for field, values in invalid.items():
            for value in values:
                with self.subTest(field=field, value=value):
                    op = operation()
                    op[field] = value
                    self.assert_rejected_without_change(
                        ledger, lambda: ledger.transfer(**op))
        self.assert_rejected_without_change(
            ledger, lambda: ledger.transfer('a', 'a', 1, 'same'))

    def test_insufficient_funds_does_not_consume_key(self):
        ledger = self.ledger
        self.assert_rejected_without_change(
            ledger, lambda: ledger.transfer('b', 'a', 1, 'retry'))
        ledger.transfer('a', 'b', 1, 'fund')
        expected = operation('b', 'a', 1, 'retry')
        self.assertEqual(ledger.transfer(**expected), expected)
        self.assertEqual(ledger.balances, {'a': 100, 'b': 0, 'c': 50})
        self.assertEqual(ledger.history, {
            'fund': operation('a', 'b', 1, 'fund'), 'retry': expected})

    def test_replay_succeeds_after_balances_change(self):
        ledger = self.ledger
        expected = operation(amount=100)
        ledger.transfer(**expected)
        ledger.transfer('b', 'c', 100, 'two')
        before = deepcopy((ledger.balances, ledger.history))
        self.assertEqual(ledger.transfer(**expected), expected)
        self.assertEqual((ledger.balances, ledger.history), before)

    def test_replay_rejects_each_changed_payload_field(self):
        ledger = self.ledger
        ledger.transfer('a', 'b', 20, 'one')
        for field, value in (('source', 'c'), ('target', 'c'), ('amount', 21)):
            with self.subTest(field=field):
                op = operation()
                op[field] = value
                self.assert_rejected_without_change(
                    ledger, lambda: ledger.transfer(**op))

    def test_replay_still_validates_amount_type(self):
        ledger = self.ledger
        ledger.transfer('a', 'b', 1, 'one')
        for amount in (True, 1.0):
            with self.subTest(amount=amount):
                self.assert_rejected_without_change(
                    ledger, lambda: ledger.transfer('a', 'b', amount, 'one'))

    def test_new_and_replayed_receipts_are_isolated(self):
        ledger = self.ledger
        expected = operation()
        first = ledger.transfer(**expected)
        first.clear()
        self.assertEqual(ledger.history, {'one': expected})
        replay = ledger.transfer(**expected)
        self.assertEqual(replay, expected)
        replay['amount'] = 999
        replay['extra'] = []
        self.assertEqual(ledger.history, {'one': expected})
        self.assertEqual(ledger.transfer(**expected), expected)
        self.assertEqual(ledger.balances, {'a': 80, 'b': 20, 'c': 50})

    def test_empty_batch_preserves_populated_state(self):
        ledger = self.ledger
        ledger.transfer('a', 'b', 20, 'one')
        balances, history = ledger.balances, ledger.history
        before = deepcopy((balances, history))
        self.assertEqual(ledger.batch([]), [])
        self.assertEqual((ledger.balances, ledger.history), before)
        self.assertIs(ledger.balances, balances)
        self.assertIs(ledger.history, history)

    def test_batch_rejects_non_lists_without_change(self):
        ledger = self.ledger
        ledger.transfer('a', 'b', 10, 'seed')
        for operations in (None, {}, 'operations', 1,
                           (operation(),), iter([operation()])):
            with self.subTest(operations=operations):
                self.assert_rejected_without_change(
                    ledger, lambda: ledger.batch(operations))

    def test_malformed_operations_roll_back_earlier_transfers(self):
        ledger = self.ledger
        ledger.transfer('a', 'b', 10, 'seed')
        malformed = [None, [], 'operation', 1, tuple(operation().items())]
        for field in operation():
            op = operation()
            del op[field]
            malformed.append(op)
        malformed.extend([dict(operation(), extra=1), {**operation(), 1: 'bad'}])
        for invalid in malformed:
            with self.subTest(invalid=invalid):
                operations = [operation(key='early'), invalid]
                before = deepcopy(operations)
                self.assert_rejected_without_change(
                    ledger, lambda: ledger.batch(operations))
                self.assertEqual(operations, before)

    def test_invalid_transfers_roll_back_earlier_batch_operations(self):
        ledger = self.ledger
        ledger.transfer('a', 'b', 10, 'seed')
        invalid = [operation(source='missing'), operation(target='missing'),
                   operation(target='a'), operation(source=[]),
                   operation(amount=True), operation(amount=0),
                   operation(amount=1.0), operation(key=''),
                   operation(key=[]), operation(amount=100)]
        for op in invalid:
            with self.subTest(operation=op):
                self.assert_rejected_without_change(
                    ledger, lambda: ledger.batch([operation(key='early'), op]))

    def test_batch_conflict_with_existing_key_rolls_back(self):
        ledger = self.ledger
        ledger.transfer('a', 'b', 20, 'one')
        self.assert_rejected_without_change(
            ledger, lambda: ledger.batch([
                operation('b', 'c', 5, 'early'), operation(amount=21)]))

    def test_batch_conflict_with_new_key_rolls_back(self):
        ledger = self.ledger
        self.assert_rejected_without_change(
            ledger, lambda: ledger.batch([operation(), operation(target='c')]))

    def test_batch_replays_are_ordered_and_receipts_are_isolated(self):
        ledger = self.ledger
        ledger.transfer('a', 'b', 20, 'one')
        balances, history = ledger.balances, ledger.history
        operations = [operation(), operation('b', 'c', 5, 'two'),
                      operation(), operation('b', 'c', 5, 'two')]
        expected = deepcopy(operations)
        receipts = ledger.batch(operations)
        self.assertEqual(receipts, expected)
        self.assertEqual(operations, expected)
        self.assertEqual(ledger.balances, {'a': 80, 'b': 15, 'c': 55})
        self.assertEqual(ledger.history, {'one': expected[0], 'two': expected[1]})
        self.assertIs(ledger.balances, balances)
        self.assertIs(ledger.history, history)
        receipts[0].clear()
        receipts[1]['amount'] = 999
        operations[0]['amount'] = 123
        self.assertEqual(receipts[2:], expected[2:])
        self.assertEqual(ledger.history, {'one': expected[0], 'two': expected[1]})

    def test_batch_failure_after_replay_preserves_prior_history(self):
        ledger = self.ledger
        ledger.transfer('a', 'b', 20, 'one')
        self.assert_rejected_without_change(
            ledger, lambda: ledger.batch([
                operation(), operation('b', 'c', 5, 'two'),
                operation('b', 'a', 16, 'three')]))

    def test_failed_batch_keys_can_be_retried_and_use_earlier_credits(self):
        ledger = self.ledger
        operations = [operation(amount=100), operation('b', 'c', 101, 'two')]
        self.assert_rejected_without_change(ledger, lambda: ledger.batch(operations))
        operations[1]['amount'] = 100
        self.assertEqual(ledger.batch(operations), operations)
        self.assertEqual(ledger.balances, {'a': 0, 'b': 0, 'c': 150})
        self.assertEqual(ledger.history, {'one': operations[0], 'two': operations[1]})
        before = deepcopy((ledger.balances, ledger.history))
        self.assertEqual(ledger.batch(operations), operations)
        self.assertEqual((ledger.balances, ledger.history), before)

    def test_integrated_funding_purchases_rollback_and_retry(self):
        ledger = Ledger({'treasury': 120, 'alice': 0, 'bob': 0, 'vendor': 0})
        balances, history = ledger.balances, ledger.history
        funding = operation('treasury', 'alice', 60, 'fund-alice')
        self.assertEqual(ledger.transfer(**funding), funding)
        purchases = [operation('treasury', 'bob', 40, 'fund-bob'),
                     operation('alice', 'vendor', 25, 'alice-order'),
                     operation('bob', 'vendor', 15, 'bob-order')]
        batch = purchases + [purchases[1].copy()]
        self.assertEqual(ledger.batch(batch), batch)
        self.assertEqual(ledger.balances,
                         {'treasury': 20, 'alice': 35, 'bob': 25, 'vendor': 40})
        before = deepcopy((ledger.balances, ledger.history))
        self.assertEqual(ledger.batch(batch), batch)
        self.assertEqual((ledger.balances, ledger.history), before)

        refund = operation('vendor', 'alice', 10, 'refund')
        settlement = operation('bob', 'treasury', 30, 'settlement')
        self.assert_rejected_without_change(
            ledger, lambda: ledger.batch([refund, settlement]))
        settlement['amount'] = 25
        self.assertEqual(ledger.batch([refund, settlement]), [refund, settlement])
        self.assert_rejected_without_change(
            ledger, lambda: ledger.transfer('alice', 'vendor', 24, 'alice-order'))
        self.assertEqual(ledger.transfer(**funding), funding)
        self.assertEqual(ledger.balances,
                         {'treasury': 45, 'alice': 45, 'bob': 0, 'vendor': 30})
        self.assertEqual(sum(ledger.balances.values()), 120)
        self.assertEqual(ledger.history, {
            op['key']: op for op in [funding, *purchases, refund, settlement]})
        self.assertIs(ledger.balances, balances)
        self.assertIs(ledger.history, history)


if __name__ == '__main__':
    unittest.main()
