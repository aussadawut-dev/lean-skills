import copy
import unittest

from ledger import Ledger


def operation(source='a', target='b', amount=1, key='new'):
    return dict(source=source, target=target, amount=amount, key=key)


class LedgerTests(unittest.TestCase):
    def make_ledger(self):
        ledger = Ledger({'a': 100, 'b': 20, 'c': 0})
        ledger.transfer('a', 'b', 1, 'seed')
        return ledger

    def snapshot(self, ledger):
        return (ledger.balances, ledger.history,
                copy.deepcopy(ledger.balances), copy.deepcopy(ledger.history))

    def assert_unchanged(self, ledger, before):
        balances, history, balance_values, history_values = before
        self.assertIs(ledger.balances, balances)
        self.assertIs(ledger.history, history)
        self.assertEqual(ledger.balances, balance_values)
        self.assertEqual(ledger.history, history_values)

    def assert_rejected(self, ledger, action):
        before = self.snapshot(ledger)
        with self.assertRaises(ValueError):
            action()
        self.assert_unchanged(ledger, before)

    def test_constructor_copies_input_in_both_directions(self):
        balances = {'a': 10, 'b': 0}
        ledger = Ledger(balances)
        self.assertIsNot(ledger.balances, balances)
        balances['a'] = 999
        balances['extra'] = 0
        self.assertEqual(ledger.balances, {'a': 10, 'b': 0})
        ledger.transfer('a', 'b', 4, 'one')
        self.assertEqual(balances, {'a': 999, 'b': 0, 'extra': 0})
        self.assertEqual(ledger.balances, {'a': 6, 'b': 4})

    def test_constructor_rejects_invalid_containers_accounts_and_balances(self):
        invalid = [None, [], (), 'a', 1,
                   {1: 0}, {True: 0}, {None: 0}, {('a',): 0}]
        invalid.extend({'a': value} for value in
                       [-1, True, False, 1.0, '1', None, [], {}])
        for balances in invalid:
            with self.subTest(balances=balances):
                before = copy.deepcopy(balances)
                with self.assertRaises(ValueError):
                    Ledger(balances)
                self.assertEqual(balances, before)

    def test_empty_ledger_and_empty_batch(self):
        for ledger in [Ledger({}), self.make_ledger()]:
            with self.subTest(balances=ledger.balances):
                before = self.snapshot(ledger)
                self.assertEqual(ledger.batch([]), [])
                self.assert_unchanged(ledger, before)

    def test_exact_balance_transfer_and_replay_keep_dictionary_identity(self):
        ledger = Ledger({'a': 7, 'b': 0})
        balances, history = ledger.balances, ledger.history
        expected = operation(amount=7, key='drain')
        self.assertEqual(ledger.transfer(**expected), expected)
        self.assertEqual(ledger.balances, {'a': 0, 'b': 7})
        self.assertEqual(ledger.history, {'drain': expected})
        self.assertIs(ledger.balances, balances)
        self.assertIs(ledger.history, history)
        before = self.snapshot(ledger)
        self.assertEqual(ledger.transfer(**expected), expected)
        self.assert_unchanged(ledger, before)

    def test_string_and_integer_boundaries(self):
        amount = 10 ** 100
        ledger = Ledger({'': amount, ' ': 0})
        expected = operation(source='', target=' ', amount=amount, key=' ')
        self.assertEqual(ledger.transfer(**expected), expected)
        self.assertEqual(ledger.balances, {'': 0, ' ': amount})

    def test_transfer_rejects_invalid_values_without_any_writes(self):
        invalid = {
            'source': ['missing', None, [], {}, 1, True, b'a'],
            'target': ['missing', 'a', None, [], {}, 1, True, b'b'],
            'amount': [0, -1, True, False, 1.0, '1', None, [], {}, 100],
            'key': ['', None, 1, True, [], {}, b'key'],
        }
        for field, values in invalid.items():
            for value in values:
                with self.subTest(field=field, value=value):
                    ledger = self.make_ledger()
                    op = operation(**{field: value})
                    self.assert_rejected(ledger, lambda: ledger.transfer(**op))

    def test_replay_rejects_changed_or_invalid_payload(self):
        changes = [dict(source='c'), dict(target='c'), dict(amount=2),
                   dict(amount=True), dict(amount=1.0), dict(amount=0),
                   dict(source=[]), dict(target='missing')]
        for change in changes:
            with self.subTest(change=change):
                ledger = self.make_ledger()
                op = operation(key='seed', **change)
                self.assert_rejected(ledger, lambda: ledger.transfer(**op))

    def test_returned_transfer_and_replay_receipts_are_independent(self):
        ledger = self.make_ledger()
        expected = operation(key='owned')
        receipt = ledger.transfer(**expected)
        before = self.snapshot(ledger)
        self.assertIsNot(receipt, ledger.history['owned'])
        receipt.clear()
        self.assert_unchanged(ledger, before)
        replay = ledger.transfer(**expected)
        self.assertEqual(replay, expected)
        self.assertIsNot(replay, ledger.history['owned'])
        replay['amount'] = 999
        self.assert_unchanged(ledger, before)
        self.assertEqual(ledger.transfer(**expected), expected)

    def test_rejected_transfer_does_not_reserve_key(self):
        ledger = Ledger({'a': 0, 'b': 5})
        self.assert_rejected(ledger, lambda: ledger.transfer('a', 'b', 5, 'retry'))
        ledger.transfer('b', 'a', 5, 'fund')
        self.assertEqual(ledger.transfer('a', 'b', 5, 'retry'),
                         operation(amount=5, key='retry'))
        self.assertEqual(ledger.balances, {'a': 0, 'b': 5})

    def test_batch_rejects_invalid_containers(self):
        for operations in [None, {}, (), 'operations', 1, iter([])]:
            with self.subTest(operations=operations):
                ledger = self.make_ledger()
                self.assert_rejected(ledger, lambda: ledger.batch(operations))

    def test_batch_rejects_malformed_or_invalid_operations_atomically(self):
        invalid = [None, [], (), 'operation', 1, {},
                   dict(operation(), extra=1), dict(operation(), **{'': 1}),
                   {**operation(), 1: 'extra'},
                   operation(amount=True), operation(target='missing'),
                   operation(target='a'), operation(key='')]
        invalid.extend({key: value for key, value in operation().items()
                        if key != missing}
                       for missing in operation())
        for bad in invalid:
            with self.subTest(operation=bad):
                ledger = self.make_ledger()
                operations = [operation(amount=10, key='earlier'), bad]
                before = copy.deepcopy(operations)
                self.assert_rejected(ledger, lambda: ledger.batch(operations))
                self.assertEqual(operations, before)

    def test_batch_rolls_back_failure_at_every_position(self):
        for position in range(3):
            with self.subTest(position=position):
                ledger = self.make_ledger()
                operations = [operation(amount=10, key='first'),
                              operation(source='b', target='c', amount=5, key='second')]
                operations.insert(position, operation(amount=1000, key='overdraw'))
                self.assert_rejected(ledger, lambda: ledger.batch(operations))

    def test_batch_rolls_back_existing_and_new_key_conflicts(self):
        for conflicting in [operation(amount=2, key='seed'),
                            operation(amount=2, key='first')]:
            with self.subTest(conflicting=conflicting):
                ledger = self.make_ledger()
                operations = [operation(key='seed'), operation(key='first'), conflicting]
                self.assert_rejected(ledger, lambda: ledger.batch(operations))

    def test_batch_receipts_and_duplicate_receipts_are_independent(self):
        ledger = self.make_ledger()
        expected = operation(amount=3)
        operations = [expected.copy(), expected.copy()]
        receipts = ledger.batch(operations)
        self.assertEqual(receipts, operations)
        self.assertEqual(ledger.balances, {'a': 96, 'b': 24, 'c': 0})
        self.assertIsNot(receipts[0], receipts[1])
        before = self.snapshot(ledger)
        receipts[0].clear()
        self.assertEqual(receipts[1], expected)
        receipts[1]['amount'] = 999
        operations[0]['target'] = 'c'
        self.assert_unchanged(ledger, before)
        replays = ledger.batch([expected, expected])
        self.assertEqual(replays, [expected, expected])
        replays[0].clear()
        replays[1].clear()
        self.assert_unchanged(ledger, before)

    def test_integrated_multi_transfer_replay_rollback_and_retry(self):
        supplied = {'a': 100, 'b': 0, 'c': 0}
        ledger = Ledger(supplied)
        balances, history = ledger.balances, ledger.history
        seed = operation(amount=10, key='seed')
        ledger.transfer(**seed)
        forward = operation(source='b', target='c', amount=10, key='forward')
        operations = [seed, forward, operation(amount=90, key='drain'),
                      forward.copy(),
                      operation(source='b', target='c', amount=90, key='finish')]
        original_operations = copy.deepcopy(operations)
        self.assertEqual(ledger.batch(operations), operations)
        self.assertEqual(ledger.balances, {'a': 0, 'b': 0, 'c': 100})
        self.assertEqual(ledger.history, {op['key']: op for op in operations})
        self.assertIs(ledger.balances, balances)
        self.assertIs(ledger.history, history)
        before = self.snapshot(ledger)
        self.assertEqual(ledger.batch(operations), operations)
        self.assert_unchanged(ledger, before)

        refund = operation(source='c', target='a', amount=20, key='refund')
        ledger.transfer(**refund)
        adjustment = operation(source='c', target='b', amount=10, key='adjust')
        self.assert_rejected(ledger, lambda: ledger.batch([
            adjustment, operation(source='a', target='c', amount=21, key='fail')]))
        self.assertEqual(ledger.batch([adjustment]), [adjustment])
        self.assertEqual(ledger.balances, {'a': 20, 'b': 10, 'c': 70})
        expected_history = {op['key']: op for op in operations + [refund, adjustment]}
        self.assertEqual(ledger.history, expected_history)
        self.assertEqual(sum(ledger.balances.values()), 100)
        self.assertEqual(supplied, {'a': 100, 'b': 0, 'c': 0})
        self.assertEqual(operations, original_operations)


if __name__ == '__main__':
    unittest.main()
