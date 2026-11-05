from copy import deepcopy
import unittest

from ledger import Ledger


def operation(source='a', target='b', amount=10, key='one'):
    return dict(source=source, target=target, amount=amount, key=key)


class LedgerTestCase(unittest.TestCase):
    def assert_rejected_unchanged(self, ledger, action):
        balances, history = ledger.balances, ledger.history
        before = deepcopy((balances, history))
        with self.assertRaises(ValueError):
            action()
        self.assertIs(ledger.balances, balances)
        self.assertIs(ledger.history, history)
        self.assertEqual((ledger.balances, ledger.history), before)


class ConstructorTests(LedgerTestCase):
    def test_copies_balances_in_both_directions(self):
        original = {'a': 100, 'b': 0}
        ledger = Ledger(original)
        ledger.transfer('a', 'b', 10, 'one')
        self.assertEqual(original, {'a': 100, 'b': 0})
        original['a'] = 1
        original['outside'] = 5
        self.assertEqual(ledger.balances, {'a': 90, 'b': 10})

    def test_empty_and_integer_boundaries(self):
        self.assertEqual(Ledger({}).balances, {})
        balances = {'': 0, 'large': 10 ** 100}
        ledger = Ledger(balances)
        self.assertEqual(ledger.balances, balances)
        self.assertEqual(ledger.history, {})

    def test_rejects_invalid_balances(self):
        for balance in [-1, True, False, 0.0, 1.5, '1', None, [], {}]:
            with self.subTest(balance=balance):
                original = {'valid': 10, 'invalid': balance}
                before = deepcopy(original)
                with self.assertRaises(ValueError):
                    Ledger(original)
                self.assertEqual(original, before)

    def test_rejects_invalid_container_and_account_names(self):
        for balances in [None, [], [('a', 1)], 'a', {1: 5}, {None: 5}]:
            with self.subTest(balances=balances), self.assertRaises(ValueError):
                Ledger(balances)


class TransferTests(LedgerTestCase):
    def setUp(self):
        self.ledger = Ledger({'a': 100, 'b': 0, 'c': 0, 'untouched': 17})
        self.ledger.transfer('a', 'b', 10, 'seed')

    def test_transfer_receipt_and_preserved_history(self):
        balances, history = self.ledger.balances, self.ledger.history
        seed = deepcopy(history['seed'])
        receipt = self.ledger.transfer('b', 'c', 7, 'next')
        self.assertEqual(receipt, operation('b', 'c', 7, 'next'))
        self.assertEqual(balances, {'a': 90, 'b': 3, 'c': 7, 'untouched': 17})
        self.assertEqual(history, {'seed': seed, 'next': receipt})
        self.assertIs(self.ledger.balances, balances)
        self.assertIs(self.ledger.history, history)

    def test_rejects_invalid_or_unavailable_accounts(self):
        pairs = [('missing', 'b'), ('a', 'missing'), ('a', 'a')]
        for invalid in [None, [], {}, 1, True]:
            pairs.extend([(invalid, 'b'), ('a', invalid)])
        for source, target in pairs:
            with self.subTest(source=source, target=target):
                self.assert_rejected_unchanged(
                    self.ledger, lambda: self.ledger.transfer(source, target, 1, 'bad'))

    def test_rejects_invalid_amounts_including_replay(self):
        for amount in [0, -1, True, False, 10.0, '10', None, [], {}]:
            for key in ['fresh', 'seed']:
                with self.subTest(amount=amount, key=key):
                    self.assert_rejected_unchanged(
                        self.ledger, lambda: self.ledger.transfer('a', 'b', amount, key))
        ledger = Ledger({'a': 1, 'b': 0})
        ledger.transfer('a', 'b', 1, 'one')
        self.assert_rejected_unchanged(ledger, lambda: ledger.transfer('a', 'b', True, 'one'))

    def test_rejects_invalid_keys(self):
        for key in ['', None, 0, True, [], {}]:
            with self.subTest(key=key):
                self.assert_rejected_unchanged(
                    self.ledger, lambda: self.ledger.transfer('a', 'b', 1, key))

    def test_overdraft_preserves_state_and_does_not_reserve_key(self):
        self.assert_rejected_unchanged(
            self.ledger, lambda: self.ledger.transfer('a', 'b', 91, 'retry'))
        receipt = self.ledger.transfer('a', 'b', 90, 'retry')
        self.assertEqual(receipt, operation('a', 'b', 90, 'retry'))
        self.assertEqual(self.ledger.balances['a'], 0)

    def test_replay_succeeds_without_funds_and_without_mutation(self):
        receipt = self.ledger.transfer('a', 'b', 90, 'drain')
        before = deepcopy((self.ledger.balances, self.ledger.history))
        replay = self.ledger.transfer('a', 'b', 90, 'drain')
        self.assertEqual(replay, receipt)
        self.assertIsNot(replay, receipt)
        self.assertEqual((self.ledger.balances, self.ledger.history), before)

    def test_conflicting_source_target_or_amount_preserves_state(self):
        for change in [{'source': 'untouched'}, {'target': 'c'}, {'amount': 11}]:
            with self.subTest(change=change):
                conflict = dict(operation(key='seed'), **change)
                self.assert_rejected_unchanged(
                    self.ledger, lambda: self.ledger.transfer(**conflict))

    def test_fresh_and_replayed_receipts_are_isolated(self):
        expected = operation(key='new')
        fresh = self.ledger.transfer(**expected)
        replay = self.ledger.transfer(**expected)
        before = deepcopy((self.ledger.balances, self.ledger.history))
        fresh.clear()
        replay.update(source='changed', target='changed', amount=-1, key='changed')
        self.assertEqual((self.ledger.balances, self.ledger.history), before)
        self.assertEqual(self.ledger.transfer(**expected), expected)

    def test_large_integer_empty_account_and_whitespace_key_are_valid(self):
        amount = 10 ** 100
        ledger = Ledger({'': amount, 'b': 0})
        expected = operation('', 'b', amount, ' ')
        self.assertEqual(ledger.transfer(**expected), expected)
        self.assertEqual(ledger.balances, {'': 0, 'b': amount})


class BatchTests(LedgerTestCase):
    def setUp(self):
        self.ledger = Ledger({'a': 100, 'b': 0, 'c': 0, 'untouched': 17})
        self.ledger.transfer('a', 'b', 10, 'seed')

    def test_success_funds_later_operations_and_preserves_dictionaries(self):
        balances, history = self.ledger.balances, self.ledger.history
        seed = deepcopy(history['seed'])
        operations = [operation(amount=50), operation('b', 'c', 60, 'two'),
                      operation('c', 'a', 15, 'three')]
        before_operations = deepcopy(operations)
        self.assertEqual(self.ledger.batch(operations), operations)
        self.assertEqual(balances, {'a': 55, 'b': 0, 'c': 45, 'untouched': 17})
        self.assertEqual(history, {'seed': seed, **{op['key']: op for op in operations}})
        self.assertEqual(operations, before_operations)
        self.assertIs(self.ledger.balances, balances)
        self.assertIs(self.ledger.history, history)

    def test_batch_matches_transfers_with_existing_and_new_replays(self):
        ordinary = Ledger(self.ledger.balances)
        ordinary_seed = ordinary.transfer('a', 'c', 1, 'existing')
        self.ledger.transfer(**ordinary_seed)
        operations = [ordinary_seed, operation(amount=89), operation(amount=89),
                      operation('b', 'c', 99, 'two'), ordinary_seed]
        expected = [ordinary.transfer(**op) for op in operations]
        receipts = self.ledger.batch(operations)
        self.assertEqual(receipts, expected)
        self.assertEqual(self.ledger.balances, ordinary.balances)
        self.assertEqual(self.ledger.history,
                         {'seed': operation(key='seed'), **ordinary.history})
        before = deepcopy((self.ledger.balances, self.ledger.history))
        self.assertEqual(self.ledger.batch(operations), expected)
        self.assertEqual((self.ledger.balances, self.ledger.history), before)

    def test_invalid_batch_containers(self):
        for operations in [None, {}, (), 'operations', 1, iter([])]:
            with self.subTest(operations=operations):
                self.assert_rejected_unchanged(
                    self.ledger, lambda: self.ledger.batch(operations))

    def test_malformed_operations_roll_back_earlier_success(self):
        missing = operation()
        del missing['key']
        extra = dict(operation(), extra=1)
        nonstring_field = dict(operation())
        nonstring_field[1] = 'unexpected'
        for bad in [None, [], 'operation', 1, {}, missing, extra, nonstring_field]:
            with self.subTest(operation=bad):
                operations = [operation(key='pending'), bad]
                self.assert_rejected_unchanged(
                    self.ledger, lambda: self.ledger.batch(operations))

    def test_invalid_values_roll_back_balances_and_seeded_history(self):
        bad_operations = [
            operation(amount=1000, key='overdraft'),
            operation(source='missing', key='source'),
            operation(target='missing', key='target'),
            operation(target='a', key='same'),
            operation(source=[], key='unhashable'),
            operation(amount=True, key='boolean'),
            operation(amount=0, key='zero'),
            operation(key=''),
            operation(key=[]),
            operation(amount=11, key='seed'),
            operation(target='c', key='pending'),
        ]
        for bad in bad_operations:
            with self.subTest(operation=bad):
                operations = [operation(key='seed'), operation(key='pending'),
                              operation('b', 'c', 5, 'forward'), bad]
                self.assert_rejected_unchanged(
                    self.ledger, lambda: self.ledger.batch(operations))
                self.assertEqual(self.ledger.transfer(**operation(key='seed')),
                                 operation(key='seed'))

    def test_failure_at_first_middle_or_last_operation(self):
        for position in range(3):
            with self.subTest(position=position):
                operations = [operation(amount=1, key=f'new-{index}') for index in range(3)]
                operations[position] = operation(amount=1000, key='overdraft')
                self.assert_rejected_unchanged(
                    self.ledger, lambda: self.ledger.batch(operations))

    def test_receipts_and_inputs_do_not_alias_history_or_each_other(self):
        new = operation(key='new')
        operations = [operation(key='seed'), new, new]
        receipts = self.ledger.batch(operations)
        before = deepcopy((self.ledger.balances, self.ledger.history))
        receipts[1].clear()
        self.assertEqual(receipts[2], new)
        receipts[0]['amount'] = 1000
        receipts[2]['key'] = 'changed'
        new['source'] = 'changed'
        self.assertEqual((self.ledger.balances, self.ledger.history), before)
        self.assertEqual(self.ledger.transfer(**operation(key='new')), operation(key='new'))

    def test_empty_batch_preserves_state(self):
        balances, history = self.ledger.balances, self.ledger.history
        before = deepcopy((balances, history))
        self.assertEqual(self.ledger.batch([]), [])
        self.assertEqual((self.ledger.balances, self.ledger.history), before)
        self.assertIs(self.ledger.balances, balances)
        self.assertIs(self.ledger.history, history)


class IntegratedJourneyTests(LedgerTestCase):
    def test_pay_settle_refund_replay_fail_and_retry(self):
        original = {'payer': 120, 'shop': 0, 'supplier': 0, 'reserve': 30}
        original_snapshot = original.copy()
        ledger = Ledger(original)
        balances, history = ledger.balances, ledger.history
        order = operation('payer', 'shop', 100, 'order')
        checkout = [order, operation('shop', 'supplier', 60, 'stock'),
                    operation('shop', 'payer', 10, 'refund'), order]
        receipts = ledger.batch(checkout)
        self.assertEqual(receipts, checkout)
        self.assertEqual(balances, {'payer': 30, 'shop': 30, 'supplier': 60, 'reserve': 30})
        settled = deepcopy((balances, history))
        receipts[0].clear()
        self.assertEqual(ledger.batch(checkout), checkout)
        self.assertEqual((balances, history), settled)

        restock = [operation('supplier', 'payer', 10, 'return'),
                   operation('shop', 'supplier', 20, 'restock'),
                   operation('payer', 'shop', 101, 'payment')]
        self.assert_rejected_unchanged(ledger, lambda: ledger.batch(restock))
        self.assertEqual(ledger.transfer(**order), order)
        self.assertEqual((balances, history), settled)

        restock[-1]['amount'] = 25
        self.assertEqual(ledger.batch(restock), restock)
        self.assertEqual(balances, {'payer': 15, 'shop': 35, 'supplier': 70, 'reserve': 30})
        completed = deepcopy((balances, history))
        self.assertEqual(ledger.batch(restock), restock)
        self.assertEqual(ledger.transfer(**order), order)
        self.assertEqual((balances, history), completed)
        self.assertEqual(history, {op['key']: op for op in checkout + restock})
        self.assert_rejected_unchanged(
            ledger, lambda: ledger.transfer('payer', 'shop', 99, 'order'))
        self.assertEqual(sum(balances.values()), sum(original.values()))
        self.assertEqual(original, original_snapshot)
        self.assertIs(ledger.balances, balances)
        self.assertIs(ledger.history, history)


if __name__ == '__main__':
    unittest.main()
