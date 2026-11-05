from copy import deepcopy
import unittest

from ledger import Ledger


def operation(source='a', target='b', amount=10, key='new'):
    return dict(source=source, target=target, amount=amount, key=key)


def snapshot(ledger):
    return deepcopy((ledger.balances, ledger.history))


class LedgerTests(unittest.TestCase):
    def seeded_ledger(self):
        ledger = Ledger({'a': 100, 'b': 0, 'c': 0, 'untouched': 7})
        ledger.transfer('a', 'c', 10, 'seed')
        return ledger

    def assert_rejected_without_change(self, ledger, action):
        before = snapshot(ledger)
        balances, history = ledger.balances, ledger.history
        with self.assertRaises(ValueError):
            action()
        self.assertEqual(snapshot(ledger), before)
        self.assertIs(ledger.balances, balances)
        self.assertIs(ledger.history, history)

    def test_constructor_copies_input_in_both_directions(self):
        balances = {'a': 20, 'b': 0}
        ledger = Ledger(balances)
        balances['a'] = 999
        balances['other'] = 5
        ledger.transfer('a', 'b', 5, 'one')
        self.assertEqual(ledger.balances, {'a': 15, 'b': 5})
        self.assertEqual(balances, {'a': 999, 'b': 0, 'other': 5})
        self.assertEqual(Ledger({}).balances, {})

    def test_constructor_rejects_invalid_balances(self):
        invalid = [True, False, -1, 0.0, 1.5, '10', None, [], {},
                   float('inf'), float('nan')]
        for value in invalid:
            with self.subTest(value=value), self.assertRaises(ValueError):
                Ledger({'a': value})
        for balances in [None, [], [('a', 10)], 'a', {1: 10}]:
            with self.subTest(balances=balances), self.assertRaises(ValueError):
                Ledger(balances)

    def test_invalid_transfer_inputs_preserve_all_state(self):
        cases = []
        for field in ('source', 'target'):
            for value in ('missing', None, True, 1, [], {}):
                cases.append({field: value})
        cases.append({'target': 'a'})
        for value in (True, False, 0, -1, 1.0, '1', None, [], {},
                      float('inf'), float('nan')):
            cases.append({'amount': value})
        for value in ('', None, True, 1, 1.0, [], {}):
            cases.append({'key': value})

        for changes in cases:
            with self.subTest(changes=changes):
                ledger = self.seeded_ledger()
                op = operation()
                op.update(changes)
                self.assert_rejected_without_change(ledger, lambda: ledger.transfer(**op))

    def test_insufficient_funds_does_not_consume_key(self):
        ledger = self.seeded_ledger()
        self.assert_rejected_without_change(
            ledger, lambda: ledger.transfer('a', 'b', 91, 'retry'))
        ledger.transfer('c', 'a', 1, 'fund')
        receipt = ledger.transfer('a', 'b', 91, 'retry')
        self.assertEqual(receipt, operation(amount=91, key='retry'))
        self.assertEqual(ledger.balances, {'a': 0, 'b': 91, 'c': 9, 'untouched': 7})

    def test_replay_after_source_is_empty_and_new_key_executes(self):
        ledger = Ledger({'a': 10, 'b': 0})
        receipt = ledger.transfer('a', 'b', 10, 'one')
        before = snapshot(ledger)
        self.assertEqual(ledger.transfer('a', 'b', 10, 'one'), receipt)
        self.assertEqual(snapshot(ledger), before)
        ledger.transfer('b', 'a', 10, 'refund')
        ledger.transfer('a', 'b', 10, 'two')
        self.assertEqual(ledger.balances, {'a': 0, 'b': 10})
        self.assertEqual(set(ledger.history), {'one', 'refund', 'two'})

    def test_changed_payload_and_invalid_replay_are_rejected(self):
        ledger = self.seeded_ledger()
        ledger.transfer('a', 'b', 1, 'one')
        for changes in ({'source': 'c'}, {'target': 'c'}, {'amount': 2},
                        {'amount': True}, {'amount': 1.0}):
            with self.subTest(changes=changes):
                op = operation(amount=1, key='one')
                op.update(changes)
                self.assert_rejected_without_change(ledger, lambda: ledger.transfer(**op))

    def test_success_and_replay_receipts_do_not_expose_history(self):
        ledger = self.seeded_ledger()
        expected = operation()
        receipt = ledger.transfer(**expected)
        self.assertEqual(receipt, expected)
        before = snapshot(ledger)
        receipt.clear()
        replay = ledger.transfer(**expected)
        self.assertEqual(replay, expected)
        replay['amount'] = 999
        self.assertEqual(snapshot(ledger), before)
        self.assertEqual(ledger.transfer(**expected), expected)

    def test_large_integers_and_nonempty_whitespace_keys_are_valid(self):
        amount = 10 ** 100
        ledger = Ledger({'': amount, 'b': 0})
        expected = operation(source='', amount=amount, key=' ')
        self.assertEqual(ledger.transfer(**expected), expected)
        self.assertEqual(ledger.balances, {'': 0, 'b': amount})
        self.assertEqual(ledger.transfer(**expected), expected)

    def test_batch_rejects_invalid_containers_without_change(self):
        ledger = self.seeded_ledger()
        for operations in (None, {}, (), 'operations', iter([])):
            with self.subTest(operations=operations):
                self.assert_rejected_without_change(ledger, lambda: ledger.batch(operations))

    def test_batch_rolls_back_validation_funding_and_key_failures(self):
        failures = [
            operation(amount=71, key='overdraw'),
            operation(target='missing', key='missing'),
            operation(target='a', key='same'),
            operation(source=[], key='invalid-source'),
            operation(amount=True, key='boolean'),
            operation(key=''),
            operation(amount=21, key='new'),
            operation(key='seed'),
            None, [], 'invalid', {},
            {'source': 'a', 'target': 'b', 'amount': 1},
            dict(operation(), extra=True),
            {1: 'invalid'},
        ]
        for failure in failures:
            with self.subTest(failure=failure):
                ledger = self.seeded_ledger()
                prefix = operation(amount=20)
                seed = operation(target='c', key='seed')
                operations = [prefix, seed, failure]
                original_operations = deepcopy(operations)
                self.assert_rejected_without_change(ledger, lambda: ledger.batch(operations))
                self.assertEqual(operations, original_operations)
                before = snapshot(ledger)
                self.assertEqual(ledger.transfer(**seed), seed)
                self.assertEqual(snapshot(ledger), before)
                self.assertEqual(ledger.transfer(**prefix), prefix)
                self.assertEqual(ledger.balances,
                                 {'a': 70, 'b': 20, 'c': 10, 'untouched': 7})

    def test_empty_batch_preserves_state(self):
        for ledger in (Ledger({}), self.seeded_ledger()):
            with self.subTest(balances=ledger.balances):
                before = snapshot(ledger)
                balances, history = ledger.balances, ledger.history
                self.assertEqual(ledger.batch([]), [])
                self.assertEqual(snapshot(ledger), before)
                self.assertIs(ledger.balances, balances)
                self.assertIs(ledger.history, history)

    def test_batch_receipts_are_independent_and_inputs_unchanged(self):
        ledger = self.seeded_ledger()
        op = operation()
        operations = [op, dict(op), operation(target='c', key='seed')]
        original_operations = deepcopy(operations)
        balances, history = ledger.balances, ledger.history
        receipts = ledger.batch(operations)
        self.assertEqual(receipts, original_operations)
        self.assertEqual(ledger.balances, {'a': 80, 'b': 10, 'c': 10, 'untouched': 7})
        self.assertIs(ledger.balances, balances)
        self.assertIs(ledger.history, history)
        self.assertEqual(operations, original_operations)
        before = snapshot(ledger)
        receipts[0].clear()
        self.assertEqual(receipts[1], original_operations[1])
        receipts[1]['target'] = 'c'
        receipts[2]['amount'] = 999
        op['amount'] = 500
        self.assertEqual(snapshot(ledger), before)

    def test_integrated_multi_transfer_replay_rollback_and_recovery(self):
        initial = {'payroll': 1000, 'alice': 0, 'bob': 0, 'shop': 0, 'reserve': 77}
        ledger = Ledger(initial)
        alice_pay = operation('payroll', 'alice', 600, 'pay-alice')
        self.assertEqual(ledger.transfer(**alice_pay), alice_pay)
        bob_pay = operation('payroll', 'bob', 400, 'pay-bob')
        purchase = operation('alice', 'shop', 150, 'purchase')
        gift = operation('bob', 'alice', 50, 'gift')
        operations = [bob_pay, purchase, gift, alice_pay, purchase]
        self.assertEqual(ledger.batch(operations), operations)
        self.assertEqual(ledger.balances,
                         {'payroll': 0, 'alice': 500, 'bob': 350, 'shop': 150, 'reserve': 77})
        self.assertEqual(ledger.history,
                         {op['key']: op for op in [alice_pay, bob_pay, purchase, gift]})
        before = snapshot(ledger)
        self.assertEqual(ledger.batch(operations), operations)
        self.assertEqual(snapshot(ledger), before)

        refund = operation('shop', 'alice', 100, 'refund')
        charge = operation('alice', 'bob', 601, 'charge')
        self.assert_rejected_without_change(ledger, lambda: ledger.batch([refund, charge]))
        charge['amount'] = 600
        self.assertEqual(ledger.batch([refund, charge]), [refund, charge])
        self.assertEqual(ledger.balances,
                         {'payroll': 0, 'alice': 0, 'bob': 950, 'shop': 50, 'reserve': 77})
        self.assertEqual(sum(ledger.balances.values()), sum(initial.values()))
        self.assertEqual(ledger.history, {op['key']: op for op in
                         [alice_pay, bob_pay, purchase, gift, refund, charge]})
        before = snapshot(ledger)
        for op in (alice_pay, bob_pay, purchase, gift, refund, charge):
            self.assertEqual(ledger.transfer(**op), op)
        self.assertEqual(snapshot(ledger), before)
        self.assertEqual(initial,
                         {'payroll': 1000, 'alice': 0, 'bob': 0, 'shop': 0, 'reserve': 77})


if __name__ == '__main__':
    unittest.main()
