import unittest
from copy import deepcopy

from ledger import Ledger


def operation(source='a', target='b', amount=1, key='new'):
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

    def test_constructor_owns_its_balances(self):
        original = {'a': 10, 'b': 0}
        ledger = Ledger(original)
        self.assertIsNot(ledger.balances, original)
        original['a'] = 100
        original['outside'] = 7
        self.assertEqual(ledger.balances, {'a': 10, 'b': 0})
        ledger.transfer('a', 'b', 3, 'one')
        self.assertEqual(original, {'a': 100, 'b': 0, 'outside': 7})

    def test_constructor_rejects_invalid_containers_keys_and_balances(self):
        invalid = [None, True, 10, 'a', [], [('a', 10)], (('a', 10),)]
        invalid += [{key: 10} for key in (1, False, None, ('a',), b'a')]
        invalid += [{'a': 10, 'b': value}
                    for value in (-1, True, False, 1.0, '1', None, [], {})]
        for value in invalid:
            with self.subTest(balances=value):
                before = deepcopy(value)
                with self.assertRaises(ValueError):
                    Ledger(value)
                self.assertEqual(value, before)

    def test_empty_ledger_and_valid_value_boundaries(self):
        empty = Ledger({})
        self.assertEqual(empty.balances, {})
        self.assertEqual(empty.history, {})
        self.assertEqual(empty.batch([]), [])
        for amount in (1, 10**100):
            with self.subTest(amount=amount):
                ledger = Ledger({'': amount, 'b': 0})
                receipt = ledger.transfer('', 'b', amount, ' ')
                self.assertEqual(receipt, operation('', 'b', amount, ' '))
                self.assertEqual(ledger.balances, {'': 0, 'b': amount})

    def test_transfer_receipt_balances_history_and_dictionary_identity(self):
        ledger = Ledger({'a': 10, 'b': 4})
        balances, history = ledger.balances, ledger.history
        expected = operation(amount=3, key='one')
        self.assertEqual(ledger.transfer(**expected), expected)
        self.assertEqual(ledger.balances, {'a': 7, 'b': 7})
        self.assertEqual(ledger.history, {'one': expected})
        self.assertIs(ledger.balances, balances)
        self.assertIs(ledger.history, history)

    def test_invalid_transfer_values_leave_existing_state_untouched(self):
        invalid_fields = {
            'source': [None, True, 1, [], {}, b'a', 'missing', 'b'],
            'target': [None, False, 0, [], {}, b'b', 'missing', 'a'],
            'amount': [0, -1, True, False, 1.0, '1', None, [], {}],
            'key': ['', None, True, 1, [], {}, b'key'],
        }
        for field, values in invalid_fields.items():
            for value in values:
                with self.subTest(field=field, value=value):
                    ledger = Ledger({'a': 10, 'b': 0})
                    ledger.transfer('a', 'b', 2, 'prior')
                    candidate = operation()
                    candidate[field] = value
                    self.assert_rejected_without_change(
                        ledger, lambda: ledger.transfer(**candidate))

    def test_insufficient_funds_does_not_consume_key(self):
        ledger = Ledger({'a': 10, 'b': 0})
        for candidate in (operation(amount=11), operation('b', 'a', 1)):
            with self.subTest(candidate=candidate):
                self.assert_rejected_without_change(
                    ledger, lambda: ledger.transfer(**candidate))
        ledger.transfer('a', 'b', 4, 'fund')
        receipt = ledger.transfer('b', 'a', 1, 'new')
        self.assertEqual(receipt, operation('b', 'a', 1, 'new'))
        self.assertEqual(ledger.balances, {'a': 7, 'b': 3})

    def test_replay_succeeds_after_source_is_empty(self):
        ledger = Ledger({'a': 10, 'b': 0})
        candidate = operation(amount=10, key='one')
        first = ledger.transfer(**candidate)
        before = deepcopy((ledger.balances, ledger.history))
        replay = ledger.transfer(**candidate)
        self.assertEqual(replay, first)
        self.assertIsNot(replay, first)
        self.assertEqual((ledger.balances, ledger.history), before)
        self.assert_rejected_without_change(
            ledger, lambda: ledger.transfer('a', 'b', 10, 'another'))

    def test_changed_replay_payload_is_rejected(self):
        ledger = Ledger({'a': 10, 'b': 10, 'c': 10})
        original = operation(amount=2, key='one')
        ledger.transfer(**original)
        for changes in ({'source': 'c'}, {'target': 'c'}, {'amount': 3},
                        {'source': 'b', 'target': 'a'}):
            with self.subTest(changes=changes):
                candidate = dict(original, **changes)
                self.assert_rejected_without_change(
                    ledger, lambda: ledger.transfer(**candidate))

    def test_replay_cannot_bypass_value_validation(self):
        ledger = Ledger({'a': 10, 'b': 0})
        ledger.transfer('a', 'b', 1, 'one')
        for amount in (True, 1.0):
            with self.subTest(amount=amount):
                self.assert_rejected_without_change(
                    ledger, lambda: ledger.transfer('a', 'b', amount, 'one'))

    def test_first_and_replayed_receipts_do_not_expose_history(self):
        ledger = Ledger({'a': 10, 'b': 0})
        expected = operation(amount=2, key='one')
        receipt = ledger.transfer(**expected)
        receipt['amount'] = 999
        receipt['extra'] = []
        del receipt['source']
        replay = ledger.transfer(**expected)
        self.assertEqual(replay, expected)
        replay.clear()
        self.assertEqual(ledger.history, {'one': expected})
        self.assertEqual(ledger.balances, {'a': 8, 'b': 2})
        self.assertEqual(ledger.transfer(**expected), expected)

    def test_successful_batch_uses_staged_funds_and_preserves_order(self):
        ledger = Ledger({'a': 10, 'b': 0, 'c': 0})
        balances, history = ledger.balances, ledger.history
        operations = [operation(amount=10, key='one'),
                      operation('b', 'c', 7, 'two'),
                      operation('c', 'a', 2, 'three')]
        before = deepcopy(operations)
        self.assertEqual(ledger.batch(operations), before)
        self.assertEqual(ledger.balances, {'a': 2, 'b': 3, 'c': 5})
        self.assertEqual(ledger.history, {op['key']: op for op in before})
        self.assertIs(ledger.balances, balances)
        self.assertIs(ledger.history, history)
        self.assertEqual(operations, before)
        operations[0]['amount'] = 999
        self.assertEqual(ledger.history['one'], before[0])

    def test_batch_replays_existing_and_new_keys_and_isolates_receipts(self):
        ledger = Ledger({'a': 10, 'b': 0, 'c': 0})
        first = operation(amount=10, key='one')
        second = operation('b', 'c', 10, 'two')
        ledger.transfer(**first)
        operations = [first, second, second, first]
        receipts = ledger.batch(operations)
        self.assertEqual(receipts, operations)
        self.assertEqual(ledger.balances, {'a': 0, 'b': 0, 'c': 10})
        expected_history = {'one': dict(first), 'two': dict(second)}
        self.assertEqual(ledger.history, expected_history)
        for index, receipt in enumerate(receipts):
            receipt.clear()
            self.assertEqual(receipts[index + 1:], operations[index + 1:])
            self.assertEqual(ledger.history, expected_history)
        before = deepcopy((ledger.balances, ledger.history))
        self.assertEqual(ledger.batch(operations), operations)
        self.assertEqual((ledger.balances, ledger.history), before)

    def test_identical_payloads_with_different_keys_both_apply(self):
        ledger = Ledger({'a': 10, 'b': 0})
        operations = [operation(amount=2, key='one'), operation(amount=2, key='two')]
        self.assertEqual(ledger.batch(operations), operations)
        self.assertEqual(ledger.balances, {'a': 6, 'b': 4})
        self.assertEqual(ledger.history, {op['key']: op for op in operations})

    def test_batch_requires_a_list(self):
        invalid = [None, True, 1, '', {}, (), (operation(),), iter([operation()])]
        for operations in invalid:
            with self.subTest(operations=operations):
                ledger = Ledger({'a': 10, 'b': 0})
                ledger.transfer('a', 'b', 1, 'prior')
                self.assert_rejected_without_change(
                    ledger, lambda: ledger.batch(operations))

    def test_malformed_batch_operation_rolls_back_earlier_work(self):
        valid = operation(amount=2, key='first')
        invalid = [None, True, 1, 'bad', [], (), {},
                   dict(operation(), extra=1), {1: 'bad'}]
        invalid += [{field: value for field, value in operation().items()
                     if field != missing} for missing in operation()]
        for malformed in invalid:
            with self.subTest(operation=malformed):
                ledger = Ledger({'a': 10, 'b': 0})
                ledger.transfer('a', 'b', 1, 'prior')
                operations = [valid, malformed]
                before = deepcopy(operations)
                self.assert_rejected_without_change(
                    ledger, lambda: ledger.batch(operations))
                self.assertEqual(operations, before)
                self.assertEqual(ledger.transfer(**valid), valid)
                self.assertEqual(ledger.balances, {'a': 7, 'b': 3})

    def test_invalid_batch_values_roll_back_earlier_work(self):
        invalid = [operation(source=[]), operation(target='missing'),
                   operation(target='a'), operation(amount=0),
                   operation(amount=True), operation(amount=1.0),
                   operation(amount=100), operation(key=[]), operation(key='')]
        for candidate in invalid:
            with self.subTest(operation=candidate):
                ledger = Ledger({'a': 10, 'b': 0})
                ledger.transfer('a', 'b', 1, 'prior')
                operations = [operation(amount=2, key='first'), candidate]
                self.assert_rejected_without_change(
                    ledger, lambda: ledger.batch(operations))

    def test_batch_conflicting_key_rolls_back_for_existing_and_new_keys(self):
        for existing_key in (False, True):
            with self.subTest(existing_key=existing_key):
                ledger = Ledger({'a': 10, 'b': 0, 'c': 0})
                first = operation(amount=2, key='one')
                if existing_key:
                    ledger.transfer(**first)
                operations = [first, operation('b', 'c', 1, 'two'),
                              operation(amount=3, key='one')]
                self.assert_rejected_without_change(
                    ledger, lambda: ledger.batch(operations))
                self.assertEqual(ledger.batch(operations[:2]), operations[:2])
                self.assertEqual(ledger.balances, {'a': 8, 'b': 1, 'c': 1})
                self.assertEqual(ledger.history, {'one': first, 'two': operations[1]})

    def test_empty_batch_preserves_populated_state(self):
        ledger = Ledger({'a': 10, 'b': 0})
        ledger.transfer('a', 'b', 1, 'prior')
        balances, history = ledger.balances, ledger.history
        before = deepcopy((balances, history))
        self.assertEqual(ledger.batch([]), [])
        self.assertEqual((ledger.balances, ledger.history), before)
        self.assertIs(ledger.balances, balances)
        self.assertIs(ledger.history, history)

    def test_integrated_transfers_replays_failure_and_recovery(self):
        original = {'treasury': 100, 'alice': 0, 'bob': 0}
        ledger = Ledger(original)
        balances, history = ledger.balances, ledger.history
        grant = operation('treasury', 'alice', 60, 'grant')
        pay = operation('alice', 'bob', 25, 'pay')
        refund = operation('bob', 'treasury', 5, 'refund')
        self.assertEqual(ledger.transfer(**grant), grant)
        self.assertEqual(ledger.batch([grant, pay, pay, refund]),
                         [grant, pay, pay, refund])
        self.assertEqual(ledger.balances, {'treasury': 45, 'alice': 35, 'bob': 20})
        before = deepcopy((ledger.balances, ledger.history))
        self.assertEqual(ledger.batch([grant, pay, pay, refund]),
                         [grant, pay, pay, refund])
        self.assertEqual((ledger.balances, ledger.history), before)

        topup = operation('treasury', 'alice', 10, 'topup')
        overdraft = operation('alice', 'bob', 46, 'purchase')
        self.assert_rejected_without_change(
            ledger, lambda: ledger.batch([grant, topup, overdraft]))
        purchase = operation('alice', 'bob', 45, 'purchase')
        self.assertEqual(ledger.batch([topup, purchase]), [topup, purchase])
        self.assertEqual(ledger.balances, {'treasury': 35, 'alice': 0, 'bob': 65})
        self.assertEqual(ledger.transfer(**purchase), purchase)

        conflict = operation('alice', 'bob', 44, 'purchase')
        self.assert_rejected_without_change(ledger, lambda: ledger.transfer(**conflict))
        giveback = operation('bob', 'treasury', 15, 'giveback')
        self.assertEqual(ledger.transfer(**giveback), giveback)
        self.assertEqual(ledger.balances, {'treasury': 50, 'alice': 0, 'bob': 50})
        expected = [grant, pay, refund, topup, purchase, giveback]
        self.assertEqual(ledger.history, {op['key']: op for op in expected})
        self.assertEqual(sum(ledger.balances.values()), 100)
        self.assertEqual(original, {'treasury': 100, 'alice': 0, 'bob': 0})
        self.assertIs(ledger.balances, balances)
        self.assertIs(ledger.history, history)


if __name__ == '__main__':
    unittest.main()
