from copy import deepcopy
import unittest

from ledger import Ledger


def operation(source='a', target='b', amount=20, key='one'):
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

    def test_constructor_copies_input_in_both_directions(self):
        original = {'a': 100, 'b': 0}
        ledger = Ledger(original)
        ledger.transfer('a', 'b', 20, 'one')
        self.assertEqual(original, {'a': 100, 'b': 0})
        original['a'] = 999
        original['new'] = 1
        self.assertEqual(ledger.balances, {'a': 80, 'b': 20})

    def test_constructor_rejects_invalid_balances(self):
        for balance in (-1, True, False, 1.0, float('nan'), None, '1', [], {}):
            with self.subTest(balance=balance):
                original = {'valid': 10, 'invalid': balance}
                with self.assertRaises(ValueError):
                    Ledger(original)
                self.assertEqual(set(original), {'valid', 'invalid'})
                self.assertEqual(original['valid'], 10)
                self.assertIs(original['invalid'], balance)

    def test_constructor_rejects_invalid_container_or_account(self):
        for balances in (None, [], [('a', 10)], 'a', 10, {1: 10}, {None: 10}):
            with self.subTest(balances=balances):
                with self.assertRaises(ValueError):
                    Ledger(balances)

    def test_empty_zero_and_large_balances_and_string_boundaries(self):
        empty = Ledger({})
        self.assertEqual(empty.batch([]), [])
        self.assertEqual((empty.balances, empty.history), ({}, {}))
        large = 10**100
        ledger = Ledger({'': large, '貯金': 0})
        receipt = ledger.transfer('', '貯金', large, ' ')
        self.assertEqual(receipt, operation('', '貯金', large, ' '))
        self.assertEqual(ledger.balances, {'': 0, '貯金': large})

    def test_transfer_moves_exact_amount_and_records_receipt(self):
        ledger = Ledger({'a': 100, 'b': 3, 'c': 7})
        balances, history = ledger.balances, ledger.history
        expected = operation()
        receipt = ledger.transfer(**expected)
        self.assertEqual(receipt, expected)
        self.assertEqual(ledger.balances, {'a': 80, 'b': 23, 'c': 7})
        self.assertEqual(ledger.history, {'one': expected})
        self.assertIs(ledger.balances, balances)
        self.assertIs(ledger.history, history)

    def test_transfer_rejects_invalid_values_without_changing_state(self):
        invalid_values = {
            'source': ['missing', None, [], {}, 1, True],
            'target': ['missing', None, [], {}, 1, True, 'a'],
            'amount': [0, -1, True, False, 20.0, float('inf'), None, '20', [], {}],
            'key': ['', None, True, 1, [], {}],
        }
        for field, values in invalid_values.items():
            for value in values:
                with self.subTest(field=field, value=value):
                    ledger = self.seeded_ledger()
                    invalid = operation()
                    invalid[field] = value
                    self.assert_rejected_unchanged(
                        ledger, lambda: ledger.transfer(**invalid)
                    )

    def test_insufficient_funds_preserves_state_and_does_not_reserve_key(self):
        ledger = Ledger({'a': 10, 'b': 0})
        self.assert_rejected_unchanged(
            ledger, lambda: ledger.transfer('a', 'b', 11, 'retry')
        )
        self.assertEqual(
            ledger.transfer('a', 'b', 10, 'retry'),
            operation('a', 'b', 10, 'retry'),
        )
        self.assertEqual(ledger.balances, {'a': 0, 'b': 10})

    def test_exact_replay_succeeds_even_when_source_is_empty(self):
        ledger = Ledger({'a': 20, 'b': 0})
        first = ledger.transfer(**operation())
        before = deepcopy((ledger.balances, ledger.history))
        replay = ledger.transfer(**operation())
        self.assertEqual(replay, first)
        self.assertIsNot(replay, first)
        self.assertEqual((ledger.balances, ledger.history), before)

    def test_conflicting_replay_rejects_each_changed_payload_field(self):
        for changes in ({'source': 'c'}, {'target': 'c'}, {'amount': 21}):
            with self.subTest(changes=changes):
                ledger = Ledger({'a': 100, 'b': 0, 'c': 100})
                first = ledger.transfer(**operation())
                conflicting = dict(first, **changes)
                self.assert_rejected_unchanged(
                    ledger, lambda: ledger.transfer(**conflicting)
                )
                self.assertEqual(ledger.transfer(**operation()), first)

    def test_replay_cannot_bypass_amount_type_validation(self):
        ledger = Ledger({'a': 1, 'b': 0})
        ledger.transfer('a', 'b', 1, 'one')
        for amount in (True, 1.0):
            with self.subTest(amount=amount):
                self.assert_rejected_unchanged(
                    ledger, lambda: ledger.transfer('a', 'b', amount, 'one')
                )

    def test_new_and_replayed_receipts_cannot_mutate_history(self):
        ledger = Ledger({'a': 100, 'b': 0})
        ledger.transfer(**operation()).clear()
        replay = ledger.transfer(**operation())
        replay['amount'] = 999
        replay['target'] = []
        self.assertEqual(ledger.history, {'one': operation()})
        self.assertEqual(ledger.transfer(**operation()), operation())
        self.assertEqual(ledger.balances, {'a': 80, 'b': 20})

    def test_empty_batch_preserves_existing_state_and_dictionaries(self):
        ledger = self.seeded_ledger()
        balances, history = ledger.balances, ledger.history
        before = deepcopy((balances, history))
        self.assertEqual(ledger.batch([]), [])
        self.assertEqual((ledger.balances, ledger.history), before)
        self.assertIs(ledger.balances, balances)
        self.assertIs(ledger.history, history)

    def test_batch_rejects_non_list_input(self):
        for operations in (None, {}, (), (operation(),), 'operations', iter([]), 1):
            with self.subTest(operations=operations):
                ledger = self.seeded_ledger()
                self.assert_rejected_unchanged(
                    ledger, lambda: ledger.batch(operations)
                )

    def test_malformed_operation_after_valid_operation_rolls_back(self):
        missing_fields = [
            {name: value for name, value in operation().items() if name != missing}
            for missing in operation()
        ]
        malformed = [None, [], 'operation', 1, {}, dict(operation(), extra=True)]
        malformed += missing_fields + [{**operation(), 1: 'unexpected'}]
        for invalid in malformed:
            with self.subTest(invalid=invalid):
                ledger = self.seeded_ledger()
                self.assert_rejected_unchanged(
                    ledger, lambda: ledger.batch([operation(), invalid])
                )

    def test_invalid_transfer_after_valid_operation_rolls_back(self):
        for changes in (
            {'source': 'missing'}, {'target': []}, {'target': 'a'},
            {'amount': True}, {'amount': 1.5}, {'amount': -1}, {'key': ''},
        ):
            with self.subTest(changes=changes):
                ledger = self.seeded_ledger()
                invalid = dict(operation(key='two'), **changes)
                self.assert_rejected_unchanged(
                    ledger, lambda: ledger.batch([operation(), invalid])
                )

    def test_late_insufficient_funds_rolls_back_all_operations_and_can_retry(self):
        ledger = self.seeded_ledger()
        operations = [
            operation(),
            operation('b', 'c', 15, 'two'),
            operation('b', 'c', 6, 'three'),
        ]
        self.assert_rejected_unchanged(ledger, lambda: ledger.batch(operations))
        operations[-1]['amount'] = 5
        self.assertEqual(ledger.batch(operations), operations)
        self.assertEqual(ledger.balances, {'a': 75, 'b': 0, 'c': 25, 'untouched': 7})
        self.assertEqual(ledger.history, {
            'seed': operation('a', 'c', 5, 'seed'),
            **{item['key']: item for item in operations},
        })

    def test_batch_replays_existing_and_new_keys_in_order(self):
        ledger = Ledger({'a': 100, 'b': 0, 'c': 0})
        seed = operation(key='seed')
        ledger.transfer(**seed)
        one = operation(amount=80)
        two = operation('b', 'c', 100, 'two')
        operations = [seed, one, one, two, seed, two]
        balances, history = ledger.balances, ledger.history
        self.assertEqual(ledger.batch(operations), operations)
        self.assertEqual(ledger.balances, {'a': 0, 'b': 0, 'c': 100})
        self.assertEqual(ledger.history, {'seed': seed, 'one': one, 'two': two})
        before = deepcopy((ledger.balances, ledger.history))
        self.assertEqual(ledger.batch(operations), operations)
        self.assertEqual((ledger.balances, ledger.history), before)
        self.assertIs(ledger.balances, balances)
        self.assertIs(ledger.history, history)

    def test_conflicting_existing_or_new_batch_key_rolls_back(self):
        for conflicting in (
            operation('a', 'c', 6, 'seed'),
            operation(amount=21),
        ):
            with self.subTest(conflicting=conflicting):
                ledger = self.seeded_ledger()
                self.assert_rejected_unchanged(
                    ledger, lambda: ledger.batch([operation(), conflicting])
                )

    def test_batch_input_and_receipts_do_not_alias_history_or_each_other(self):
        ledger = Ledger({'a': 100, 'b': 0})
        item = operation()
        receipts = ledger.batch([item, item])
        self.assertEqual(item, operation())
        self.assertEqual(receipts, [operation(), operation()])
        item['amount'] = 99
        receipts[0].clear()
        self.assertEqual(receipts[1], operation())
        receipts[1]['source'] = 'changed'
        self.assertEqual(ledger.history, {'one': operation()})
        self.assertEqual(ledger.transfer(**operation()), operation())

    def test_integrated_multi_transfer_replay_failure_and_recovery(self):
        original = {'payer': 120, 'merchant': 0, 'escrow': 0, 'reserve': 30, 'other': 9}
        ledger = Ledger(original)
        authorize = operation('payer', 'escrow', 70, 'authorize')
        self.assertEqual(ledger.transfer(**authorize), authorize)
        settlement = [
            authorize,
            operation('escrow', 'merchant', 50, 'settle'),
            operation('escrow', 'payer', 20, 'refund'),
        ]
        self.assertEqual(ledger.batch(settlement), settlement)
        self.assertEqual(ledger.balances, {
            'payer': 70, 'merchant': 50, 'escrow': 0, 'reserve': 30, 'other': 9,
        })

        payment = [
            operation('reserve', 'payer', 10, 'topup'),
            operation('payer', 'merchant', 81, 'payment'),
        ]
        self.assert_rejected_unchanged(ledger, lambda: ledger.batch(payment))
        payment[-1]['amount'] = 80
        self.assertEqual(ledger.batch(payment), payment)
        self.assertEqual(ledger.balances, {
            'payer': 0, 'merchant': 130, 'escrow': 0, 'reserve': 20, 'other': 9,
        })
        before = deepcopy((ledger.balances, ledger.history))
        self.assertEqual(ledger.transfer(**authorize), authorize)
        self.assertEqual(ledger.batch(settlement + payment), settlement + payment)
        self.assertEqual((ledger.balances, ledger.history), before)

        conflicting = [
            operation('reserve', 'merchant', 5, 'extra'),
            operation('escrow', 'merchant', 51, 'settle'),
        ]
        self.assert_rejected_unchanged(ledger, lambda: ledger.batch(conflicting))
        self.assertEqual(ledger.history, {
            item['key']: item for item in settlement + payment
        })
        self.assertEqual(sum(ledger.balances.values()), sum(original.values()))
        self.assertEqual(original, {
            'payer': 120, 'merchant': 0, 'escrow': 0, 'reserve': 30, 'other': 9,
        })


if __name__ == '__main__':
    unittest.main()
