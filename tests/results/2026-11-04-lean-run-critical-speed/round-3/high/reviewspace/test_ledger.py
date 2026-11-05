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

    def test_constructor_copies_input(self):
        supplied = {'a': 10, 'b': 0}
        ledger = Ledger(supplied)
        self.assertIsNot(ledger.balances, supplied)
        supplied['a'] = 999
        supplied['c'] = 5
        ledger.transfer('a', 'b', 10, 'all')
        self.assertEqual(ledger.balances, {'a': 0, 'b': 10})
        self.assertEqual(supplied, {'a': 999, 'b': 0, 'c': 5})

    def test_constructor_rejects_invalid_balances_without_changing_input(self):
        for value in (-1, True, False, 0.0, 1.5, '1', None, [], {}):
            with self.subTest(value=value):
                supplied = {'a': 10, 'b': value}
                before = deepcopy(supplied)
                with self.assertRaises(ValueError):
                    Ledger(supplied)
                self.assertEqual(supplied, before)

    def test_constructor_rejects_non_dictionary(self):
        for supplied in (None, [], [('a', 1)], 'a', 1):
            with self.subTest(supplied=supplied):
                with self.assertRaises(ValueError):
                    Ledger(supplied)

    def test_constructor_rejects_non_string_accounts_without_changing_input(self):
        for account in (1, None, True, 1.5, b'a', ('a',)):
            with self.subTest(account=account):
                supplied = {account: 10, 'a': 0}
                before = deepcopy(supplied)
                with self.assertRaises(ValueError):
                    Ledger(supplied)
                self.assertEqual(supplied, before)

    def test_opaque_unicode_accounts_support_transfer_batch_and_replay(self):
        # Canonically equivalent spellings remain distinct opaque identifiers.
        source = ' 账户/e\u0301\u200d💰\x00 '
        target = ' 账户/é\u200d💰\x00 '
        supplied = {source: 10, target: 0, 'merchant': 0}
        ledger = Ledger(supplied)
        balances, history = ledger.balances, ledger.history
        seed = operation(source, target, 4, 'seed')
        self.assertEqual(ledger.transfer(**seed), seed)
        purchase = operation(target, 'merchant', 2, 'purchase')
        refund = operation('merchant', source, 1, 'refund')
        operations = [seed, purchase, purchase, refund]
        self.assertEqual(ledger.batch(operations), operations)
        self.assertEqual(ledger.balances, {source: 7, target: 2, 'merchant': 1})
        self.assertEqual(ledger.history, {
            'seed': seed, 'purchase': purchase, 'refund': refund,
        })
        committed = deepcopy((ledger.balances, ledger.history))
        self.assertEqual(ledger.transfer(**seed), seed)
        self.assertEqual(ledger.batch(operations), operations)
        self.assertEqual((ledger.balances, ledger.history), committed)
        self.assert_rejected_without_change(
            ledger, lambda: ledger.batch([
                operation(source, target, 1, 'prefix'),
                operation(target, 'merchant', 4, 'overdraft'),
            ])
        )
        self.assertEqual(supplied, {source: 10, target: 0, 'merchant': 0})
        self.assertIs(ledger.balances, balances)
        self.assertIs(ledger.history, history)

    def test_exact_balance_and_large_integers(self):
        amount = 10 ** 100
        ledger = Ledger({'a': amount, 'b': 0})
        balances, history = ledger.balances, ledger.history
        expected = operation(amount=amount, key='all')
        self.assertEqual(ledger.transfer(**expected), expected)
        self.assertEqual(ledger.balances, {'a': 0, 'b': amount})
        self.assertEqual(ledger.history, {'all': expected})
        self.assertIs(ledger.balances, balances)
        self.assertIs(ledger.history, history)

    def test_invalid_transfers_preserve_existing_state(self):
        invalid_arguments = [
            ('source', 'missing'), ('target', 'missing'),
            ('source', None), ('target', None),
            ('source', []), ('target', {}),
            ('target', 'a'),
            ('amount', 0), ('amount', -1), ('amount', True),
            ('amount', False), ('amount', 1.0), ('amount', 1.5),
            ('amount', '1'), ('amount', None), ('amount', []),
            ('amount', 9),
            ('key', ''), ('key', 1), ('key', True),
            ('key', None), ('key', []), ('key', {}),
        ]
        for field, value in invalid_arguments:
            with self.subTest(field=field, value=value):
                ledger = Ledger({'a': 10, 'b': 0})
                ledger.transfer('a', 'b', 2, 'seed')
                candidate = operation()
                candidate[field] = value
                self.assert_rejected_without_change(
                    ledger, lambda: ledger.transfer(**candidate)
                )

    def test_replay_validates_amount_type_even_when_values_compare_equal(self):
        ledger = Ledger({'a': 10, 'b': 0})
        ledger.transfer('a', 'b', 1, 'one')
        for amount in (True, 1.0):
            with self.subTest(amount=amount):
                self.assert_rejected_without_change(
                    ledger, lambda: ledger.transfer('a', 'b', amount, 'one')
                )

    def test_replay_succeeds_without_funds_and_returns_an_independent_receipt(self):
        ledger = Ledger({'a': 5, 'b': 0})
        receipt = ledger.transfer('a', 'b', 5, 'all')
        before = deepcopy((ledger.balances, ledger.history))
        replay = ledger.transfer('a', 'b', 5, 'all')
        self.assertEqual(replay, receipt)
        self.assertIsNot(replay, receipt)
        self.assertIsNot(replay, ledger.history['all'])
        self.assertEqual((ledger.balances, ledger.history), before)

    def test_replay_rejects_each_changed_payload_field(self):
        ledger = Ledger({'a': 10, 'b': 10, 'c': 10})
        original = operation(amount=2, key='one')
        ledger.transfer(**original)
        for field, value in (('source', 'c'), ('target', 'c'), ('amount', 3)):
            with self.subTest(field=field):
                candidate = dict(original, **{field: value})
                self.assert_rejected_without_change(
                    ledger, lambda: ledger.transfer(**candidate)
                )

    def test_new_key_applies_an_equal_payload_again(self):
        ledger = Ledger({'a': 10, 'b': 0})
        ledger.transfer('a', 'b', 2, 'one')
        ledger.transfer('a', 'b', 2, 'two')
        self.assertEqual(ledger.balances, {'a': 6, 'b': 4})
        self.assertEqual(set(ledger.history), {'one', 'two'})

    def test_returned_receipts_cannot_change_history_or_later_replays(self):
        ledger = Ledger({'a': 10, 'b': 0})
        expected = operation(amount=3, key='one')
        receipt = ledger.transfer(**expected)
        receipt.clear()
        replay = ledger.transfer(**expected)
        self.assertEqual(replay, expected)
        replay['amount'] = 999
        replay['key'] = 'changed'
        self.assertEqual(ledger.history, {'one': expected})
        self.assertEqual(ledger.transfer(**expected), expected)
        self.assertEqual(ledger.balances, {'a': 7, 'b': 3})

    def test_failed_transfer_does_not_reserve_key(self):
        ledger = Ledger({'a': 5, 'b': 0})
        self.assert_rejected_without_change(
            ledger, lambda: ledger.transfer('a', 'b', 6, 'retry')
        )
        expected = operation(amount=3, key='retry')
        self.assertEqual(ledger.transfer(**expected), expected)
        self.assertEqual(ledger.balances, {'a': 2, 'b': 3})

    def test_empty_account_name_and_whitespace_key_are_valid(self):
        ledger = Ledger({'': 3, ' b ': 0})
        expected = operation(source='', target=' b ', amount=3, key=' ')
        self.assertEqual(ledger.transfer(**expected), expected)
        self.assertEqual(ledger.balances, {'': 0, ' b ': 3})

    def test_empty_batch_preserves_state(self):
        for ledger in (Ledger({}), Ledger({'a': 10, 'b': 0})):
            if ledger.balances:
                ledger.transfer('a', 'b', 1, 'seed')
            balances, history = ledger.balances, ledger.history
            before = deepcopy((balances, history))
            self.assertEqual(ledger.batch([]), [])
            self.assertEqual((ledger.balances, ledger.history), before)
            self.assertIs(ledger.balances, balances)
            self.assertIs(ledger.history, history)

    def test_batch_requires_list(self):
        ledger = Ledger({'a': 10, 'b': 0})
        for operations in (None, {}, (), 'operations', True, iter([operation()])):
            with self.subTest(operations=operations):
                self.assert_rejected_without_change(
                    ledger, lambda: ledger.batch(operations)
                )

    def test_malformed_batch_operations_roll_back_valid_prefix(self):
        invalid_operations = [None, 1, [], 'operation', {},
                              dict(operation(), extra=1),
                              {**operation(), 1: 'unexpected'}]
        for field in operation():
            missing_field = operation()
            del missing_field[field]
            invalid_operations.append(missing_field)
        invalid_operations.extend([
            operation(amount=True), operation(amount=0), operation(key=[]),
            operation(source=[]), operation(target='missing'), operation(target='a'),
        ])
        for invalid in invalid_operations:
            with self.subTest(invalid=invalid):
                ledger = Ledger({'a': 10, 'b': 0})
                ledger.transfer('a', 'b', 1, 'seed')
                self.assert_rejected_without_change(
                    ledger, lambda: ledger.batch([operation(key='prefix'), invalid])
                )

    def test_failed_batch_at_each_position_preserves_state(self):
        for position in range(3):
            with self.subTest(position=position):
                ledger = Ledger({'a': 10, 'b': 3, 'c': 0})
                ledger.transfer('a', 'c', 1, 'seed')
                operations = [operation(amount=2, key='first'),
                              operation(source='b', target='c', amount=2, key='last')]
                operations.insert(position, operation(amount=100, key='overdraw'))
                before = deepcopy(operations)
                self.assert_rejected_without_change(
                    ledger, lambda: ledger.batch(operations)
                )
                self.assertEqual(operations, before)

    def test_batch_conflicting_replay_rolls_back_for_old_and_new_keys(self):
        for key in ('seed', 'new'):
            with self.subTest(key=key):
                ledger = Ledger({'a': 10, 'b': 0})
                ledger.transfer('a', 'b', 1, 'seed')
                self.assert_rejected_without_change(
                    ledger, lambda: ledger.batch([
                        operation(amount=2), operation(amount=3, key=key)
                    ])
                )

    def test_batch_duplicate_receipts_and_inputs_are_independent(self):
        ledger = Ledger({'a': 5, 'b': 0})
        expected = operation(amount=5)
        operations = [expected.copy(), expected.copy()]
        receipts = ledger.batch(operations)
        self.assertEqual(receipts, [expected, expected])
        self.assertEqual(ledger.balances, {'a': 0, 'b': 5})
        self.assertEqual(ledger.history, {'new': expected})
        receipts[0].clear()
        operations[0]['amount'] = 999
        self.assertEqual(receipts[1], expected)
        self.assertEqual(ledger.history, {'new': expected})
        receipts[1]['source'] = 'changed'
        self.assertEqual(ledger.transfer(**expected), expected)

    def test_integrated_transfer_batch_replay_failure_and_recovery(self):
        ledger = Ledger({'checking': 120, 'savings': 0, 'merchant': 0})
        balances, history = ledger.balances, ledger.history
        seed = operation('checking', 'savings', 20, 'seed')
        self.assertEqual(ledger.transfer(**seed), seed)
        purchase = operation('checking', 'merchant', 70, 'purchase')
        refund = operation('merchant', 'savings', 15, 'refund')
        cashback = operation('savings', 'checking', 5, 'cashback')
        operations = [seed, purchase, refund, purchase, cashback]
        before_operations = deepcopy(operations)
        self.assertEqual(ledger.batch(operations), before_operations)
        self.assertEqual(operations, before_operations)
        self.assertEqual(balances, {'checking': 35, 'savings': 30, 'merchant': 55})
        self.assertEqual(history, {op['key']: op for op in before_operations})
        committed = deepcopy((balances, history))
        self.assertEqual(ledger.batch(operations), before_operations)
        self.assertEqual((balances, history), committed)

        later = operation('checking', 'merchant', 10, 'later')
        overdraft = operation('savings', 'merchant', 31, 'retry')
        self.assert_rejected_without_change(
            ledger, lambda: ledger.batch([later, overdraft])
        )
        recovered = operation('savings', 'merchant', 30, 'retry')
        self.assertEqual(ledger.batch([later, recovered]), [later, recovered])
        self.assertEqual(balances, {'checking': 25, 'savings': 0, 'merchant': 95})
        self.assertEqual(history, {
            **committed[1], 'later': later, 'retry': recovered,
        })
        self.assertEqual(sum(balances.values()), 120)
        self.assertIs(ledger.balances, balances)
        self.assertIs(ledger.history, history)


if __name__ == '__main__':
    unittest.main()
