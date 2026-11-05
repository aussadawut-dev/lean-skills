import unittest
from copy import deepcopy

from ledger import Ledger


class UntrustedDict(dict):
    """Copying or inspecting this subclass directly is not reliable."""

    def copy(self):
        return self

    def items(self):
        return {}.items()

    def keys(self):
        return {'source', 'target', 'amount', 'key'}

    def __eq__(self, other):
        return True

    def __missing__(self, key):
        return 0

    def update(self, *args, **kwargs):
        raise AssertionError('caller-owned dictionary must not be updated')


class UntrustedList(list):
    def copy(self):
        return self


def invalid_operations():
    cases = {
        'source': ['missing', None, 1, True, [], {}],
        'target': ['missing', None, 1, True, [], {}],
        'amount': [0, -1, True, False, 1.0, '1', None, [], {}],
        'key': ['', None, 1, True, [], {}],
    }
    for field, values in cases.items():
        for value in values:
            operation = {'source': 'a', 'target': 'b', 'amount': 1, 'key': 'candidate'}
            operation[field] = value
            yield field, value, operation
    yield 'same account', 'a', {
        'source': 'a', 'target': 'a', 'amount': 1, 'key': 'candidate'}
    yield 'insufficient funds', 101, {
        'source': 'a', 'target': 'b', 'amount': 101, 'key': 'candidate'}


class LedgerTests(unittest.TestCase):
    def setUp(self):
        self.ledger = Ledger({'a': 100, 'b': 0, 'c': 20})

    def assert_rejected_without_change(self, action, ledger=None):
        ledger = self.ledger if ledger is None else ledger
        balances = ledger.balances
        history = ledger.history
        history_entries = dict(history)
        before = deepcopy((balances, history))
        with self.assertRaises(ValueError):
            action()
        self.assertEqual((ledger.balances, ledger.history), before)
        self.assertIs(ledger.balances, balances)
        self.assertIs(ledger.history, history)
        for key, receipt in history_entries.items():
            self.assertIs(ledger.history[key], receipt)

    def test_constructor_owns_balances(self):
        supplied = {'a': 100, 'b': 0}
        ledger = Ledger(supplied)
        supplied['a'] = 500
        ledger.transfer('a', 'b', 20, 'first')
        self.assertEqual(ledger.balances, {'a': 80, 'b': 20})
        self.assertEqual(supplied, {'a': 500, 'b': 0})

    def test_constructor_rejects_boolean_balance(self):
        with self.assertRaises(ValueError):
            Ledger({'a': True})

    def test_constructor_rejects_invalid_values(self):
        invalid = [None, [], [('a', 1)], 'a', 1]
        invalid.extend({'a': value} for value in [-1, False, 1.0, '1', None, [], {}])
        invalid.extend({key: 1} for key in [1, True, None, ('a',)])
        for balances in invalid:
            with self.subTest(balances=balances):
                before = deepcopy(balances)
                with self.assertRaises(ValueError):
                    Ledger(balances)
                self.assertEqual(balances, before)

    def test_constructor_accepts_empty_and_boundary_balances(self):
        self.assertEqual(Ledger({}).balances, {})
        supplied = {'': 0, ' ': 1, 'savings': 10 ** 100, '貯金': 0}
        ledger = Ledger(supplied)
        self.assertEqual(ledger.balances, supplied)
        self.assertEqual(ledger.history, {})
        self.assertIs(type(ledger.balances), dict)
        self.assertIs(type(ledger.history), dict)
        receipt = ledger.transfer('savings', '', 10 ** 100, ' ')
        self.assertEqual(receipt, {
            'source': 'savings', 'target': '', 'amount': 10 ** 100, 'key': ' '})
        self.assertEqual(ledger.balances, {'': 10 ** 100, ' ': 1, 'savings': 0, '貯金': 0})

    def test_constructor_normalizes_dictionary_subclasses(self):
        supplied = UntrustedDict({'a': 100, 'b': 0})
        ledger = Ledger(supplied)
        self.assertIs(type(ledger.balances), dict)
        self.assertEqual(ledger.balances, {'a': 100, 'b': 0})
        supplied['a'] = 500
        ledger.transfer('a', 'b', 20, 'first')
        self.assertEqual(ledger.balances, {'a': 80, 'b': 20})
        self.assertEqual(dict(supplied), {'a': 500, 'b': 0})
        self.assert_rejected_without_change(
            lambda: ledger.transfer('missing', 'a', 1, 'missing'), ledger)
        for invalid in [{'a': -1}, {'a': True}, {1: 10}]:
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                Ledger(UntrustedDict(invalid))

    def test_transfer_rejects_boolean_amount(self):
        self.assert_rejected_without_change(
            lambda: self.ledger.transfer('a', 'b', True, 'invalid'))

    def test_invalid_transfer_values_preserve_state(self):
        self.ledger.transfer('a', 'b', 1, 'existing')
        for field, value, operation in invalid_operations():
            with self.subTest(field=field, value=value):
                self.assert_rejected_without_change(
                    lambda: self.ledger.transfer(**operation))
                if field != 'key':
                    operation['key'] = 'existing'
                    self.assert_rejected_without_change(
                        lambda: self.ledger.transfer(**operation))

    def test_insufficient_funds_preserves_state(self):
        self.assert_rejected_without_change(
            lambda: self.ledger.transfer('a', 'b', 101, 'invalid'))

    def test_changed_replay_preserves_state(self):
        self.ledger.transfer('a', 'b', 20, 'first')
        for field, value in [('source', 'c'), ('target', 'c'), ('amount', 21)]:
            with self.subTest(field=field):
                operation = {'source': 'a', 'target': 'b', 'amount': 20, 'key': 'first'}
                operation[field] = value
                self.assert_rejected_without_change(
                    lambda: self.ledger.transfer(**operation))

    def test_replay_succeeds_without_available_funds(self):
        first = self.ledger.transfer('a', 'b', 100, 'drain')
        before = deepcopy((self.ledger.balances, self.ledger.history))
        replay = self.ledger.transfer('a', 'b', 100, 'drain')
        self.assertEqual(replay, first)
        self.assertIsNot(replay, first)
        self.assertEqual((self.ledger.balances, self.ledger.history), before)

    def test_new_key_applies_same_payload_again(self):
        self.ledger.transfer('a', 'b', 20, 'first')
        self.ledger.transfer('a', 'b', 20, 'second')
        self.assertEqual(self.ledger.balances, {'a': 60, 'b': 40, 'c': 20})
        self.assertEqual(set(self.ledger.history), {'first', 'second'})

    def test_rejected_transfer_does_not_reserve_key(self):
        self.assert_rejected_without_change(
            lambda: self.ledger.transfer('c', 'a', 21, 'retry'))
        receipt = self.ledger.transfer('c', 'a', 20, 'retry')
        self.assertEqual(receipt, {
            'source': 'c', 'target': 'a', 'amount': 20, 'key': 'retry'})
        self.assertEqual(self.ledger.balances, {'a': 120, 'b': 0, 'c': 0})

    def test_receipt_is_detached_from_history(self):
        receipt = self.ledger.transfer('a', 'b', 20, 'first')
        expected = {'source': 'a', 'target': 'b', 'amount': 20, 'key': 'first'}
        receipt['amount'] = 999
        receipt.clear()
        self.assertEqual(self.ledger.history['first'], expected)
        replay = self.ledger.transfer('a', 'b', 20, 'first')
        self.assertIs(type(replay), dict)
        self.assertEqual(replay, expected)
        replay['target'] = 'c'
        self.assertEqual(self.ledger.transfer('a', 'b', 20, 'first'), expected)
        self.assertEqual(self.ledger.balances, {'a': 80, 'b': 20, 'c': 20})

    def test_failed_batch_preserves_earlier_state(self):
        self.ledger.transfer('a', 'b', 10, 'existing')
        self.assert_rejected_without_change(lambda: self.ledger.batch([
            {'source': 'a', 'target': 'b', 'amount': 20, 'key': 'first'},
            {'source': 'c', 'target': 'a', 'amount': 21, 'key': 'second'},
        ]))

    def test_batch_rejects_invalid_container(self):
        self.ledger.transfer('a', 'b', 1, 'existing')
        for operations in [None, {}, (), 'operations', 1, iter([])]:
            with self.subTest(operations=operations):
                self.assert_rejected_without_change(lambda: self.ledger.batch(operations))

    def test_batch_rejects_malformed_operations_atomically(self):
        existing = self.ledger.transfer('a', 'b', 1, 'existing')
        valid = {'source': 'a', 'target': 'c', 'amount': 1, 'key': 'new'}
        malformed = [None, [], (), 'operation', 1, {}, dict(valid, extra=1)]
        malformed.append(dict(valid, **{'not-a-parameter': 1}))
        non_string_key = dict(valid)
        non_string_key[1] = 'invalid'
        malformed.append(non_string_key)
        malformed.extend({k: v for k, v in valid.items() if k != field} for field in valid)
        for operation in malformed:
            with self.subTest(operation=operation):
                self.assert_rejected_without_change(
                    lambda: self.ledger.batch([existing, valid, operation]))

    def test_batch_invalid_values_roll_back_new_operations(self):
        existing = self.ledger.transfer('a', 'b', 1, 'existing')
        valid = {'source': 'a', 'target': 'c', 'amount': 1, 'key': 'new'}
        for field, value, operation in invalid_operations():
            with self.subTest(field=field, value=value):
                self.assert_rejected_without_change(
                    lambda: self.ledger.batch([existing, valid, operation]))

    def test_batch_rolls_back_key_conflicts(self):
        existing = self.ledger.transfer('a', 'b', 20, 'existing')
        new = {'source': 'a', 'target': 'c', 'amount': 10, 'key': 'new'}
        for original in [existing, new]:
            alternate = 'c' if original['target'] == 'b' else 'b'
            changes = [('source', alternate), ('target', alternate),
                       ('amount', original['amount'] + 1)]
            for field, value in changes:
                changed = dict(original)
                changed[field] = value
                with self.subTest(key=original['key'], field=field):
                    self.assert_rejected_without_change(
                        lambda: self.ledger.batch([new, changed]))

    def test_batch_normalizes_container_subclasses(self):
        supplied = UntrustedDict(source='a', target='b', amount=20, key='first')
        operations = UntrustedList([supplied, supplied])
        expected = {'source': 'a', 'target': 'b', 'amount': 20, 'key': 'first'}
        receipts = self.ledger.batch(operations)
        self.assertIs(type(receipts), list)
        self.assertEqual(receipts, [expected, expected])
        self.assertEqual(self.ledger.balances, {'a': 80, 'b': 20, 'c': 20})
        self.assertEqual(dict(supplied), expected)
        self.assertIs(operations[0], supplied)
        self.assertIs(operations[1], supplied)
        supplied['amount'] = 999
        receipts[0].clear()
        self.assertEqual(receipts[1], expected)
        self.assertEqual(self.ledger.history, {'first': expected})
        self.assertIs(type(self.ledger.history['first']), dict)
        changed = UntrustedDict(source='a', target='b', amount=21, key='first')
        self.assert_rejected_without_change(lambda: self.ledger.batch([changed]))
        missing = UntrustedDict(source='a', target='b', key='missing')
        self.assert_rejected_without_change(lambda: self.ledger.batch([missing]))

    def test_empty_batch_preserves_state(self):
        self.ledger.transfer('a', 'b', 1, 'existing')
        balances, history = self.ledger.balances, self.ledger.history
        before = deepcopy((balances, history))
        self.assertEqual(self.ledger.batch([]), [])
        self.assertEqual((balances, history), before)
        self.assertIs(self.ledger.balances, balances)
        self.assertIs(self.ledger.history, history)
        self.assertEqual(Ledger({}).batch([]), [])

    def test_integrated_transfers_replay_rollback_and_retry(self):
        balances, history = self.ledger.balances, self.ledger.history
        initial = self.ledger.transfer('a', 'b', 10, 'initial')
        first = {'source': 'a', 'target': 'b', 'amount': 90, 'key': 'first'}
        second = {'source': 'b', 'target': 'c', 'amount': 100, 'key': 'second'}
        third = {'source': 'c', 'target': 'a', 'amount': 120, 'key': 'third'}
        operations = [first, first, initial, second, third]
        original_operations = deepcopy(operations)
        receipts = self.ledger.batch(operations)
        self.assertEqual(receipts, original_operations)
        self.assertEqual(operations, original_operations)
        self.assertEqual(balances, {'a': 120, 'b': 0, 'c': 0})
        self.assertEqual(history, {
            'initial': initial, 'first': first, 'second': second, 'third': third})
        self.assertEqual(sum(balances.values()), 120)
        self.assertIs(self.ledger.balances, balances)
        self.assertIs(self.ledger.history, history)

        before = deepcopy((balances, history))
        self.assertEqual(self.ledger.transfer(**second), second)
        replay = self.ledger.batch(operations)
        self.assertEqual(replay, original_operations)
        self.assertEqual((balances, history), before)
        for receipt in receipts + replay:
            receipt['amount'] = -1
        self.assertEqual((balances, history), before)

        retry = {'source': 'a', 'target': 'b', 'amount': 30, 'key': 'retry'}
        failed = {'source': 'c', 'target': 'a', 'amount': 1, 'key': 'failed'}
        self.assert_rejected_without_change(
            lambda: self.ledger.batch([initial, retry, failed]))
        self.assertEqual(self.ledger.batch([retry, retry]), [retry, retry])
        recovered = self.ledger.transfer('b', 'c', 30, 'failed')
        self.assertEqual(recovered, {
            'source': 'b', 'target': 'c', 'amount': 30, 'key': 'failed'})
        self.assertEqual(balances, {'a': 90, 'b': 0, 'c': 30})
        self.assertEqual(sum(balances.values()), 120)
        self.assertEqual(set(history), {'initial', 'first', 'second', 'third', 'retry', 'failed'})
        self.assertEqual(operations, original_operations)


if __name__ == '__main__':
    unittest.main()
